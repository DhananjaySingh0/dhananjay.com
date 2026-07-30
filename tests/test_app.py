"""Tests for the portfolio API.

Run with:  pytest -q
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TOKEN = "test-token-please-ignore"


@pytest.fixture()
def client(monkeypatch):
    """A fresh app with an isolated temp data dir for every test."""
    tmp = tempfile.mkdtemp()
    os.environ["DATA_DIR"] = tmp
    os.environ["ADMIN_TOKEN"] = TOKEN
    os.environ["SECRET_KEY"] = "test-secret"
    os.environ["CONTACT_RATE_LIMIT"] = "3"

    for mod in ["config", "storage", "security", "notifications", "app"]:
        sys.modules.pop(mod, None)

    import notifications
    import app as app_module

    # Never hit the network in tests.
    monkeypatch.setattr(notifications, "send_contact_notification", lambda entry: False)
    monkeypatch.setattr(app_module.notifications, "send_contact_notification", lambda entry: False)

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def admin(client):
    return {"X-Admin-Token": TOKEN}


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def test_home_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"og:title" in res.data


def test_contact_page_renders(client):
    assert client.get("/contact").status_code == 200


def test_sitemap_and_robots(client):
    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert b"<urlset" in sitemap.data

    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert b"Disallow: /admin" in robots.data


def test_missing_resume_is_404_not_500(client):
    assert client.get("/resume").status_code == 404


# --------------------------------------------------------------------------
# Contact form validation
# --------------------------------------------------------------------------

def post_contact(client, **fields):
    payload = {"name": "Ada", "email": "ada@example.com", "phone": "+91 98765 43210", "message": "Hello there"}
    payload.update(fields)
    return client.post("/api/contact", json=payload)


def test_contact_happy_path(client):
    res = post_contact(client)
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_contact_requires_fields(client):
    assert post_contact(client, name="").status_code == 400
    assert post_contact(client, message="  ").status_code == 400
    assert post_contact(client, phone="").status_code == 400


def test_contact_rejects_bad_email(client):
    res = post_contact(client, email="not-an-email")
    assert res.status_code == 400
    assert "email" in res.get_json()["error"].lower()


def test_contact_truncates_overlong_message(client):
    res = post_contact(client, message="x" * 99999)
    assert res.status_code == 200
    stored = json.loads(open(os.path.join(os.environ["DATA_DIR"], "messages.json")).read())
    assert len(stored[-1]["message"]) == 5000


def test_honeypot_is_silently_accepted_but_not_stored(client):
    res = client.post("/api/contact", json={
        "name": "Bot", "email": "bot@example.com",
        "message": "spam", "website": "http://spam.example",
    })
    assert res.status_code == 200
    path = os.path.join(os.environ["DATA_DIR"], "messages.json")
    stored = json.loads(open(path).read()) if os.path.exists(path) else []
    assert all(m["name"] != "Bot" for m in stored)


def test_contact_is_rate_limited(client):
    for _ in range(3):
        assert post_contact(client).status_code == 200
    res = post_contact(client)
    assert res.status_code == 429
    assert res.headers.get("Retry-After")


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

def test_messages_require_auth(client):
    assert client.get("/api/messages").status_code == 401
    assert client.get("/api/messages", headers=admin(client)).status_code == 200


def test_token_in_query_string_is_rejected(client):
    """Query strings leak into logs, so the token must not be accepted there."""
    assert client.get(f"/api/messages?admin_token={TOKEN}").status_code == 401


def test_write_endpoints_require_auth(client):
    assert client.post("/api/projects", data={"title": "X"}).status_code == 401
    assert client.delete("/api/projects/chatbot-assistant").status_code == 401


def test_admin_login_sets_session(client):
    assert client.post("/admin", data={"admin_token": "wrong"}).status_code == 200
    res = client.post("/admin", data={"admin_token": TOKEN})
    assert res.status_code == 302
    assert client.get("/api/session").get_json()["is_admin"] is True
    assert client.get("/api/messages").status_code == 200


# --------------------------------------------------------------------------
# Projects CRUD
# --------------------------------------------------------------------------

def test_projects_seeded_and_sorted(client):
    items = client.get("/api/projects").get_json()
    assert len(items) == 4
    assert [p["order"] for p in items] == sorted(p["order"] for p in items)


def test_add_edit_delete_project(client):
    created = client.post("/api/projects", headers=admin(client), data={
        "title": "New Thing", "description": "desc", "tags": "Python, Flask",
    })
    assert created.status_code == 201
    pid = created.get_json()["project"]["id"]
    assert created.get_json()["project"]["initials"] == "NT"

    edited = client.patch(f"/api/projects/{pid}", headers=admin(client),
                          data={"title": "Renamed Thing"})
    assert edited.status_code == 200
    assert edited.get_json()["project"]["title"] == "Renamed Thing"
    # Untouched fields survive a partial update.
    assert edited.get_json()["project"]["description"] == "desc"

    assert client.delete(f"/api/projects/{pid}", headers=admin(client)).status_code == 200
    assert client.delete(f"/api/projects/{pid}", headers=admin(client)).status_code == 404


def test_dangerous_urls_are_stripped(client):
    res = client.post("/api/projects", headers=admin(client), data={
        "title": "Sketchy", "demo_url": "javascript:alert(1)", "code_url": "github.com/me/x",
    })
    project = res.get_json()["project"]
    assert project["demo_url"] == ""
    assert project["code_url"] == "https://github.com/me/x"


def test_reorder_projects(client):
    ids = [p["id"] for p in client.get("/api/projects").get_json()]
    reversed_ids = list(reversed(ids))
    res = client.post("/api/projects/reorder", headers=admin(client),
                      json={"ids": reversed_ids})
    assert res.status_code == 200
    assert [p["id"] for p in client.get("/api/projects").get_json()] == reversed_ids


def test_rejects_bad_image_extension(client):
    import io
    res = client.post("/api/projects", headers=admin(client), data={
        "title": "Evil", "image": (io.BytesIO(b"x"), "payload.svg"),
    }, content_type="multipart/form-data")
    assert res.status_code == 400


# --------------------------------------------------------------------------
# Experience CRUD
# --------------------------------------------------------------------------

def test_experience_starts_empty(client):
    assert client.get("/api/experiences").get_json() == []


def test_experience_write_endpoints_require_auth(client):
    assert client.post("/api/experiences", data={"role": "X"}).status_code == 401
    assert client.delete("/api/experiences/whatever").status_code == 401


def test_add_edit_delete_experience(client):
    created = client.post("/api/experiences", headers=admin(client), data={
        "role": "ML Intern", "company": "Acme Corp",
        "duration": "Jan 2024 - Present", "description": "Built models.",
    })
    assert created.status_code == 201
    exp = created.get_json()["experience"]
    assert exp["role"] == "ML Intern"
    eid = exp["id"]

    listed = client.get("/api/experiences").get_json()
    assert len(listed) == 1

    edited = client.patch(f"/api/experiences/{eid}", headers=admin(client),
                          data={"role": "Senior ML Intern"})
    assert edited.status_code == 200
    assert edited.get_json()["experience"]["role"] == "Senior ML Intern"
    # Untouched fields survive a partial update.
    assert edited.get_json()["experience"]["company"] == "Acme Corp"

    assert client.delete(f"/api/experiences/{eid}", headers=admin(client)).status_code == 200
    assert client.delete(f"/api/experiences/{eid}", headers=admin(client)).status_code == 404


def test_experience_requires_role(client):
    res = client.post("/api/experiences", headers=admin(client), data={"company": "Acme"})
    assert res.status_code == 400


def test_reorder_experiences(client):
    for role in ["First", "Second"]:
        client.post("/api/experiences", headers=admin(client), data={"role": role})
    ids = [e["id"] for e in client.get("/api/experiences").get_json()]
    reversed_ids = list(reversed(ids))
    res = client.post("/api/experiences/reorder", headers=admin(client),
                      json={"ids": reversed_ids})
    assert res.status_code == 200
    assert [e["id"] for e in client.get("/api/experiences").get_json()] == reversed_ids


# --------------------------------------------------------------------------
# Skills CRUD
# --------------------------------------------------------------------------

def test_skills_seeded(client):
    items = client.get("/api/skills").get_json()
    assert len(items) == 6
    assert [s["order"] for s in items] == sorted(s["order"] for s in items)
    # The AI/ML category is the seeded "wide" one with sub-groups.
    ai = next(s for s in items if s["id"] == "skill-ai")
    assert ai["wide"] is True
    assert {g["label"] for g in ai["subgroups"]} == {"Frameworks", "Libraries", "Domains"}


def test_skills_write_endpoints_require_auth(client):
    assert client.post("/api/skills", data={"title": "X"}).status_code == 401
    assert client.delete("/api/skills/skill-ai").status_code == 401


def test_add_edit_delete_skill(client):
    created = client.post("/api/skills", headers=admin(client), data={
        "title": "New Category", "subtitle": "desc", "tags": "Go, Rust",
    })
    assert created.status_code == 201
    skill = created.get_json()["skill"]
    assert skill["tags"] == ["Go", "Rust"]
    assert skill["wide"] is False
    sid = skill["id"]

    edited = client.patch(f"/api/skills/{sid}", headers=admin(client),
                          data={"title": "Renamed Category"})
    assert edited.status_code == 200
    assert edited.get_json()["skill"]["title"] == "Renamed Category"
    # Untouched fields survive a partial update.
    assert edited.get_json()["skill"]["subtitle"] == "desc"

    assert client.delete(f"/api/skills/{sid}", headers=admin(client)).status_code == 200
    assert client.delete(f"/api/skills/{sid}", headers=admin(client)).status_code == 404


def test_skill_requires_title(client):
    res = client.post("/api/skills", headers=admin(client), data={"subtitle": "no title"})
    assert res.status_code == 400


def test_skill_with_subgroups_and_wide_flag(client):
    created = client.post("/api/skills", headers=admin(client), data={
        "title": "Data Science",
        "subgroups": "Frameworks: TensorFlow, PyTorch\nLibraries: Pandas, NumPy",
        "wide": "on",
    })
    assert created.status_code == 201
    skill = created.get_json()["skill"]
    assert skill["wide"] is True
    assert skill["subgroups"] == [
        {"label": "Frameworks", "tags": ["TensorFlow", "PyTorch"]},
        {"label": "Libraries", "tags": ["Pandas", "NumPy"]},
    ]


def test_reorder_skills(client):
    ids = [s["id"] for s in client.get("/api/skills").get_json()]
    reversed_ids = list(reversed(ids))
    res = client.post("/api/skills/reorder", headers=admin(client),
                      json={"ids": reversed_ids})
    assert res.status_code == 200
    assert [s["id"] for s in client.get("/api/skills").get_json()] == reversed_ids


# --------------------------------------------------------------------------
# Storage safety
# --------------------------------------------------------------------------

def test_corrupt_store_falls_back_without_data_loss(client):
    path = os.path.join(os.environ["DATA_DIR"], "certifications.json")
    with open(path, "w") as f:
        f.write("{ this is not json")
    assert client.get("/api/certifications").status_code == 200
    # The bad file is preserved for inspection rather than silently discarded.
    assert os.path.exists(path + ".corrupt")


def test_concurrent_writes_do_not_lose_records():
    """Hammer the storage layer directly.

    Flask's test_client is not thread-safe (it uses context vars), so driving
    this through HTTP would test Werkzeug, not us. read_modify_write is the
    only mutation path in the app, so exercising it here covers every endpoint.
    """
    import threading
    import storage

    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "records.json")

    def append(i):
        def mutator(items):
            items.append({"i": i})
            return items, None
        storage.read_modify_write(path, mutator, [])

    threads = [threading.Thread(target=append, args=(i,)) for i in range(50)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    stored = json.loads(open(path).read())
    assert len(stored) == 50
    assert sorted(r["i"] for r in stored) == list(range(50))


def test_writes_are_atomic():
    """A reader must never observe a half-written file."""
    import storage
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "atomic.json")
    storage.save_list(path, [{"a": 1}])
    # No stray temp files left behind after a successful write.
    assert [f for f in os.listdir(tmp) if f.startswith(".tmp-")] == []
    assert json.loads(open(path).read()) == [{"a": 1}]
