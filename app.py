"""Portfolio site - Flask application.

Run locally:   python app.py
Run for real:  gunicorn app:app --workers 1 --threads 8
               (app.run() is a development server and must not serve traffic)
"""

import logging
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

from flask import (
    Flask, abort, jsonify, make_response, redirect, render_template, request,
    send_from_directory, session, url_for,
)

import config
import github_sync
import notifications
import security
import storage

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
app.config["JSON_SORT_KEYS"] = False

# Sessions back the /admin sign-in. Without a SECRET_KEY the admin UI is
# disabled rather than insecure; API token auth still works.
if config.SECRET_KEY:
    app.secret_key = config.SECRET_KEY
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=not config.DEBUG,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )

storage.ensure_dirs(config.DATA_DIR, config.UPLOAD_FOLDER)

# Guards resume_path() so it only attempts a GitHub restore once per process
# lifetime, not on every page load's context_processor call. Reset happens
# naturally on the next deploy/restart, which is exactly when a restore is
# actually needed.
_resume_restore_attempted = False


DEFAULT_PROJECTS = [
    {
        "id": "chatbot-assistant",
        "title": "Chatbot Assistant",
        "description": "An AI-powered chatbot using Transformers and FastAPI.",
        "tags": ["Python", "FastAPI", "Transformers"],
        "code_url": "", "demo_url": "", "demo_text": "Live demo",
        "image": "", "initials": "CA", "order": 0,
    },
    {
        "id": "image-classifier",
        "title": "Image Classifier",
        "description": "CNN-based image classification model with high accuracy.",
        "tags": ["Python", "TensorFlow", "OpenCV"],
        "code_url": "", "demo_url": "", "demo_text": "Live demo",
        "image": "", "initials": "IC", "order": 1,
    },
    {
        "id": "sales-forecasting",
        "title": "Sales Forecasting",
        "description": "Time series forecasting model for sales prediction.",
        "tags": ["Python", "Scikit-learn", "Pandas"],
        "code_url": "", "demo_url": "", "demo_text": "Live demo",
        "image": "", "initials": "SF", "order": 2,
    },
    {
        "id": "portfolio-website",
        "title": "Portfolio Website",
        "description": "Responsive portfolio website built with modern technologies.",
        "tags": ["HTML", "CSS", "JavaScript", "Python"],
        "code_url": "", "demo_url": "", "demo_text": "Live demo",
        "image": "", "initials": "PW", "order": 3,
    },
]

# NOTE: the previous code claimed four certificates were hard-coded in
# index.html. They were not - #certGrid was an empty div, so the section
# always rendered "No certifications yet". Everything now comes from this
# store; add yours through /admin (or seed them here).
DEFAULT_CERTIFICATIONS = []

# Same story as certifications: the timeline used to be an empty <div> with
# no data behind it at all. Add entries through /admin (or seed them here).
DEFAULT_EXPERIENCES = []

# The Technical Skills section used to be plain, hand-edited HTML - changing
# a single tag meant a code deploy. It now comes from this store instead, and
# these are just the seed values so the first deploy looks unchanged. Add,
# edit, delete or reorder categories from /admin from now on.
#
# Each category is either a flat list of tags ("tags") or a set of labelled
# sub-groups ("subgroups": [{"label": ..., "tags": [...]}]), like the AI/ML
# card. "wide": true makes a category span the full row.
DEFAULT_SKILLS = [
    {
        "id": "skill-languages", "title": "Programming Languages",
        "subtitle": "Core languages I work in",
        "tags": ["Python", "C"], "subgroups": [], "wide": False, "order": 0,
    },
    {
        "id": "skill-web", "title": "Web Development",
        "subtitle": "Frontend & backend",
        "tags": ["HTML5", "CSS3", "Bootstrap", "Flask", "Django", "FastAPI", "REST APIs"],
        "subgroups": [], "wide": False, "order": 1,
    },
    {
        "id": "skill-databases", "title": "Databases",
        "subtitle": "Storage & queries",
        "tags": ["MySQL", "SQLite", "MongoDB"], "subgroups": [], "wide": False, "order": 2,
    },
    {
        "id": "skill-tools", "title": "Tools & Platforms",
        "subtitle": "Daily workflow",
        "tags": ["Git", "GitHub", "Docker", "VS Code", "Render"],
        "subgroups": [], "wide": False, "order": 3,
    },
    {
        "id": "skill-cloud", "title": "Cloud Platforms",
        "subtitle": "Deploying, managing & scaling AI apps",
        "tags": ["AWS", "Microsoft Azure", "Google Cloud Platform"],
        "subgroups": [], "wide": False, "order": 4,
    },
    {
        "id": "skill-ai", "title": "AI / Machine Learning",
        "subtitle": "Building intelligent applications using AI, Machine Learning, Deep Learning & Generative AI.",
        "tags": [],
        "subgroups": [
            {"label": "Frameworks", "tags": ["TensorFlow", "PyTorch", "Scikit-learn"]},
            {"label": "Libraries", "tags": ["Pandas", "NumPy", "OpenCV"]},
            {"label": "Domains", "tags": ["Computer Vision", "Natural Language Processing (NLP)", "Generative AI"]},
        ],
        "wide": True, "order": 5,
    },
]


# ---------------------------------------------------------------------------
# Template context
# ---------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    return {
        "site": config.SITE,
        "current_year": datetime.now(timezone.utc).year,
        "is_admin": security.is_admin(),
        "has_resume": resume_path() is not None,
        "asset_version": asset_version,
    }


def resume_path():
    """Path to whichever resume should be served, or None.

    An admin-uploaded resume (on DATA_DIR, so it survives deploys) takes
    priority; a resume bundled in the repo at static/resume.pdf is the
    fallback for a first deploy before anyone has uploaded one.

    If DATA_DIR was wiped (fresh deploy on an ephemeral disk) this tries a
    one-time restore from GitHub before falling back to the bundled copy -
    see github_sync.py.
    """
    global _resume_restore_attempted
    if not os.path.exists(config.RESUME_FILE) and not _resume_restore_attempted:
        _resume_restore_attempted = True
        data = github_sync.fetch_bytes(github_sync.repo_data_path("resume.pdf"))
        if data:
            _atomic_write_bytes(config.RESUME_FILE, data)

    if os.path.exists(config.RESUME_FILE):
        return config.RESUME_FILE
    bundled = os.path.join(app.static_folder, "resume.pdf")
    return bundled if os.path.exists(bundled) else None


def _atomic_write_bytes(path, data):
    """Write bytes to `path` via temp file + os.replace, same pattern as
    storage.py's JSON writer, so a crash mid-write never leaves a half
    file being served."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=os.path.splitext(path)[1])
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def asset_version(filename):
    """Mtime of a static file, used as a cache-busting query string (?v=...).

    Without this, browsers can keep serving a stale style.css/script.js from
    disk cache indefinitely after a deploy, since the URL never changes -
    that's exactly what caused the admin-only buttons to keep showing for
    logged-out visitors even after the fix landed.
    """
    try:
        return int(os.path.getmtime(os.path.join(app.static_folder, filename)))
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_projects():
    items = storage.load_list(config.PROJECTS_FILE, DEFAULT_PROJECTS)
    return sorted(items, key=lambda p: p.get("order", 0))


def load_certifications():
    items = storage.load_list(config.CERTIFICATIONS_FILE, DEFAULT_CERTIFICATIONS)
    return sorted(items, key=lambda c: c.get("order", 0))


def load_experiences():
    items = storage.load_list(config.EXPERIENCES_FILE, DEFAULT_EXPERIENCES)
    return sorted(items, key=lambda e: e.get("order", 0))


def load_skills():
    items = storage.load_list(config.SKILLS_FILE, DEFAULT_SKILLS)
    return sorted(items, key=lambda s: s.get("order", 0))


def parse_subgroups(raw):
    """Turn the admin form's textarea into [{"label", "tags"}, ...].

    One group per line, "Label: tag1, tag2, tag3". The label is optional -
    a line with no colon is just a set of tags with no label.
    """
    subgroups = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        label, _, rest = line.partition(":")
        if not rest:
            label, rest = "", label
        tags = [t.strip() for t in rest.split(",") if t.strip()][:20]
        if tags:
            subgroups.append({"label": security.clean_text(label, 60), "tags": tags})
    return subgroups[:6]


def remove_uploaded_image(image_path):
    """Delete an uploaded image from the data dir (and its GitHub backup).
    Never raises - a missing file or OS error is ignored so deletes always
    succeed cleanly.

    The GitHub side is deleted *synchronously* (not delete_file_async) on
    purpose: save_uploaded_image() below also pushes to GitHub in the
    background. If a project is created and then deleted quickly (as in
    testing, or a fast admin edit), the async upload thread and the async
    delete thread can race - the delete's GET-for-sha finds nothing yet
    (404, "not found"), returns early, and *then* the upload thread finishes
    and writes the image to GitHub, leaving it orphaned there forever even
    though the project is gone locally. Doing the delete inline (it's a
    single admin-triggered action, not a hot path) removes that race.
    """
    if not image_path or not image_path.startswith("uploads/"):
        return
    try:
        full_path = os.path.join(config.DATA_DIR, image_path)
        if os.path.exists(full_path):
            os.remove(full_path)
    except OSError as exc:
        app.logger.info("Could not remove image %s: %s", image_path, exc)
    filename = image_path.split("/", 1)[1]
    github_sync.delete_file(github_sync.repo_data_path("uploads", filename))


def save_uploaded_image():
    """Returns (image_path, error). image_path is '' when nothing was sent."""
    image_file = request.files.get("image")
    if not (image_file and image_file.filename):
        return "", None
    ext = image_file.filename.rsplit(".", 1)[-1].lower() if "." in image_file.filename else ""
    if ext not in config.ALLOWED_IMAGE_EXT:
        return "", "unsupported image type"
    # UUID + a whitelisted extension is already a safe filename, so there is
    # no need to also run it through secure_filename().
    filename = f"{uuid.uuid4().hex}.{ext}"
    data = image_file.read()
    with open(os.path.join(config.UPLOAD_FOLDER, filename), "wb") as f:
        f.write(data)
    # Pushed synchronously (not push_bytes_async) so the GitHub copy is
    # guaranteed to exist - or definitely not exist - by the time this
    # request returns. See the comment in remove_uploaded_image() for the
    # race this avoids with a follow-up delete.
    github_sync.push_bytes(github_sync.repo_data_path("uploads", filename), data)
    return f"uploads/{filename}", None


def _safe_upload_path(filename):
    """Resolve `filename` under UPLOAD_FOLDER, rejecting anything (like a
    '..' segment) that would escape it. Returns None if unsafe."""
    candidate = os.path.normpath(os.path.join(config.UPLOAD_FOLDER, filename))
    upload_root = os.path.normpath(config.UPLOAD_FOLDER)
    if candidate != upload_root and not candidate.startswith(upload_root + os.sep):
        return None
    return candidate


def next_order(items):
    return max((i.get("order", 0) for i in items), default=-1) + 1


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/contact")
def contact_page():
    return render_template("contact.html")


@app.route("/admin", methods=["GET", "POST"])
def admin():
    """Sign in once, then add/edit/delete without retyping the token."""
    if not config.ADMIN_TOKEN or not config.SECRET_KEY:
        return render_template("admin.html", disabled=True), 503
    error = None
    if request.method == "POST":
        if security.login_admin((request.form.get("admin_token") or "").strip()):
            return redirect(url_for("home"))
        error = "That token is not correct."
    return render_template("admin.html", error=error, disabled=False)


@app.route("/admin/logout", methods=["POST", "GET"])
def admin_logout():
    security.logout_admin()
    return redirect(url_for("home"))


@app.route("/resume")
def download_resume():
    """Serves the resume (admin-uploaded, or the one bundled in the repo)
    as a download with a clean filename."""
    path = resume_path()
    if not path:
        abort(404, description="Resume not uploaded yet. Upload one from /admin.")
    directory, filename = os.path.split(path)
    return send_from_directory(
        directory, filename,
        as_attachment=True, download_name="Dhananjay_Singh_Resume.pdf",
    )


def _looks_like_pdf(file_storage):
    """Cheap magic-byte check so a renamed .pdf can't smuggle in something
    else - the extension check alone only catches honest mistakes."""
    head = file_storage.stream.read(5)
    file_storage.stream.seek(0)
    return head == b"%PDF-"


@app.route("/api/resume", methods=["POST"])
@security.require_admin
def upload_resume():
    """Replace the live resume. Written atomically (temp file + os.replace)
    to DATA_DIR, same pattern as storage.py, so a request that dies midway
    never leaves a half-written PDF being served. Also backed up to GitHub
    in the background so it survives the next disk wipe."""
    global _resume_restore_attempted
    file = request.files.get("resume")
    if not (file and file.filename):
        return jsonify({"error": "Choose a PDF file first."}), 400
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in config.ALLOWED_RESUME_EXT:
        return jsonify({"error": "Only PDF files are accepted."}), 400
    if not _looks_like_pdf(file):
        return jsonify({"error": "That file doesn't look like a valid PDF."}), 400

    data = file.stream.read()
    _atomic_write_bytes(config.RESUME_FILE, data)
    _resume_restore_attempted = True  # we now have a fresh local copy
    # Synchronous, same reasoning as save_uploaded_image(): avoids the
    # upload/delete race if the resume is replaced or removed right after
    # being uploaded.
    github_sync.push_bytes(github_sync.repo_data_path("resume.pdf"), data)
    return jsonify({"status": "ok", "has_resume": True})


@app.route("/api/resume", methods=["DELETE"])
@security.require_admin
def delete_resume():
    """Removes the admin-uploaded resume (locally and from its GitHub
    backup) only. A repo-bundled static/resume.pdf, if present, is left
    alone and becomes the fallback again."""
    global _resume_restore_attempted
    if os.path.exists(config.RESUME_FILE):
        os.remove(config.RESUME_FILE)
    github_sync.delete_file(github_sync.repo_data_path("resume.pdf"))
    # Don't let the next has_resume check re-restore the copy we just deleted.
    _resume_restore_attempted = True
    return jsonify({"status": "ok", "has_resume": resume_path() is not None})


@app.route("/media/<path:filename>")
def media(filename):
    """Serve user-uploaded images out of DATA_DIR.

    They deliberately no longer live under static/: DATA_DIR is the directory
    you mount a persistent disk on, so uploads survive deploys. If the local
    copy is missing (fresh deploy on an ephemeral disk) this tries a
    one-shot restore from the GitHub backup before serving.
    """
    local_path = _safe_upload_path(filename)
    if local_path and not os.path.exists(local_path):
        data = github_sync.fetch_bytes(github_sync.repo_data_path("uploads", filename))
        if data is not None:
            try:
                _atomic_write_bytes(local_path, data)
            except OSError:
                pass
    return send_from_directory(config.UPLOAD_FOLDER, filename, max_age=86400)


@app.route("/robots.txt")
def robots():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /api/\n"
        f"Sitemap: {request.url_root.rstrip('/')}{url_for('sitemap')}\n"
    )
    response = make_response(body)
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response


@app.route("/sitemap.xml")
def sitemap():
    root = request.url_root.rstrip("/")
    today = datetime.now(timezone.utc).date().isoformat()
    urls = [url_for("home"), url_for("contact_page")]
    entries = "".join(
        f"<url><loc>{root}{u}</loc><lastmod>{today}</lastmod></url>" for u in urls
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}</urlset>"
    )
    response = make_response(body)
    response.headers["Content-Type"] = "application/xml; charset=utf-8"
    return response


# ---------------------------------------------------------------------------
# Contact API
# ---------------------------------------------------------------------------

@app.route("/api/contact", methods=["POST"])
def contact():
    data = request.get_json(silent=True) or {}

    # Honeypot: real users never see this field, so anything in it is a bot.
    # Return 200 so the bot thinks it worked and doesn't retry.
    if (data.get("website") or "").strip():
        app.logger.info("Contact honeypot triggered from %s", security.client_ip())
        return jsonify({"status": "ok", "message": "Thanks, your message was received!"})

    allowed, retry_after = security.contact_limiter.check(security.client_ip())
    if not allowed:
        response = jsonify({
            "error": "Too many messages from this address. Please try again later."
        })
        response.headers["Retry-After"] = str(retry_after)
        return response, 429

    name = security.clean_text(data.get("name"), config.MAX_NAME_LEN)
    email = security.clean_text(data.get("email"), config.MAX_EMAIL_LEN)
    phone = security.clean_text(data.get("phone"), config.MAX_PHONE_LEN)
    subject = security.clean_text(data.get("subject"), config.MAX_SUBJECT_LEN)
    message = security.clean_text(data.get("message"), config.MAX_MESSAGE_LEN)

    if not name or not email or not phone or not message:
        return jsonify({"error": "Name, phone, email and message are required."}), 400
    if not security.is_valid_email(email):
        return jsonify({"error": "That email address doesn't look right."}), 400

    entry = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "email": email,
        "phone": phone,
        "subject": subject,
        "message": message,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    def mutator(items):
        items.append(entry)
        return items, None

    storage.read_modify_write(config.MESSAGES_FILE, mutator, [])

    # Best-effort alert so you don't have to poll /api/messages.
    notifications.send_contact_notification(entry)

    return jsonify({
        "status": "ok",
        "message": f"Thanks {name}, your message was received!",
    })


@app.route("/api/messages", methods=["GET"])
@security.require_admin
def list_messages():
    messages = storage.load_list(config.MESSAGES_FILE, [])
    return jsonify(list(reversed(messages)))  # newest first


# ---------------------------------------------------------------------------
# Projects API
# ---------------------------------------------------------------------------

@app.route("/api/projects", methods=["GET"])
def list_projects():
    return jsonify(load_projects())


@app.route("/api/projects", methods=["POST"])
@security.require_admin
def add_project():
    title = security.clean_text(request.form.get("title"), 200)
    if not title:
        return jsonify({"error": "title is required"}), 400

    image_path, err = save_uploaded_image()
    if err:
        return jsonify({"error": err}), 400

    tags = [t.strip() for t in (request.form.get("tags") or "").split(",") if t.strip()]
    new_project = {
        "id": uuid.uuid4().hex[:8],
        "title": title,
        "description": security.clean_text(request.form.get("description"), 1000),
        "tags": tags[:12],
        "code_url": security.safe_url(request.form.get("code_url")),
        "demo_url": security.safe_url(request.form.get("demo_url")),
        "demo_text": security.clean_text(request.form.get("demo_text"), 40) or "Live demo",
        "image": image_path,
        "initials": ("".join(w[0] for w in title.split()[:2]).upper() or "PR"),
    }

    def mutator(items):
        new_project["order"] = next_order(items)
        items.append(new_project)
        return items, new_project

    created = storage.read_modify_write(config.PROJECTS_FILE, mutator, DEFAULT_PROJECTS)
    return jsonify({"status": "ok", "project": created}), 201


@app.route("/api/projects/<project_id>", methods=["PATCH", "POST"])
@security.require_admin
def update_project(project_id):
    """Edit an existing project. Only the fields you send are changed, so a
    typo no longer means delete-and-recreate."""
    if request.method == "POST" and request.form.get("_method") != "PATCH":
        abort(405)

    image_path, err = save_uploaded_image()
    if err:
        return jsonify({"error": err}), 400

    form = request.form

    def mutator(items):
        for item in items:
            if item.get("id") != project_id:
                continue
            if "title" in form:
                title = security.clean_text(form.get("title"), 200)
                if title:
                    item["title"] = title
                    item["initials"] = "".join(w[0] for w in title.split()[:2]).upper() or "PR"
            if "description" in form:
                item["description"] = security.clean_text(form.get("description"), 1000)
            if "tags" in form:
                item["tags"] = [t.strip() for t in form["tags"].split(",") if t.strip()][:12]
            if "code_url" in form:
                item["code_url"] = security.safe_url(form.get("code_url"))
            if "demo_url" in form:
                item["demo_url"] = security.safe_url(form.get("demo_url"))
            if "demo_text" in form:
                item["demo_text"] = security.clean_text(form.get("demo_text"), 40) or "Live demo"
            if image_path:
                remove_uploaded_image(item.get("image"))
                item["image"] = image_path
            return items, item
        return items, None

    updated = storage.read_modify_write(config.PROJECTS_FILE, mutator, DEFAULT_PROJECTS)
    if updated is None:
        return jsonify({"error": "project not found"}), 404
    return jsonify({"status": "ok", "project": updated})


@app.route("/api/projects/reorder", methods=["POST"])
@security.require_admin
def reorder_projects():
    """Body: {"ids": ["id1", "id2", ...]} - sets display order."""
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list):
        return jsonify({"error": "ids must be a list"}), 400

    def mutator(items):
        position = {pid: i for i, pid in enumerate(ids)}
        for item in items:
            item["order"] = position.get(item.get("id"), len(position))
        return items, sorted(items, key=lambda p: p.get("order", 0))

    ordered = storage.read_modify_write(config.PROJECTS_FILE, mutator, DEFAULT_PROJECTS)
    return jsonify({"status": "ok", "projects": ordered})


@app.route("/api/projects/<project_id>", methods=["DELETE"])
@security.require_admin
def delete_project(project_id):
    def mutator(items):
        remaining = [p for p in items if p.get("id") != project_id]
        if len(remaining) == len(items):
            return items, False
        for p in items:
            if p.get("id") == project_id:
                remove_uploaded_image(p.get("image"))
        return remaining, True

    deleted = storage.read_modify_write(config.PROJECTS_FILE, mutator, DEFAULT_PROJECTS)
    if not deleted:
        return jsonify({"error": "project not found"}), 404
    return jsonify({"status": "ok", "deleted": project_id})


# ---------------------------------------------------------------------------
# Certifications API
# ---------------------------------------------------------------------------

@app.route("/api/certifications", methods=["GET"])
def list_certifications():
    return jsonify(load_certifications())


@app.route("/api/certifications", methods=["POST"])
@security.require_admin
def add_certification():
    title = security.clean_text(request.form.get("title"), 200)
    if not title:
        return jsonify({"error": "title is required"}), 400

    image_path, err = save_uploaded_image()
    if err:
        return jsonify({"error": err}), 400

    new_cert = {
        "id": uuid.uuid4().hex[:8],
        "title": title,
        "issuer": security.clean_text(request.form.get("issuer"), 200),
        "meta": security.clean_text(request.form.get("meta"), 200),
        "image": image_path,
        "link": security.safe_url(request.form.get("link")),
    }

    def mutator(items):
        new_cert["order"] = next_order(items)
        items.append(new_cert)
        return items, new_cert

    created = storage.read_modify_write(config.CERTIFICATIONS_FILE, mutator, DEFAULT_CERTIFICATIONS)
    return jsonify({"status": "ok", "certification": created}), 201


@app.route("/api/certifications/<cert_id>", methods=["PATCH"])
@security.require_admin
def update_certification(cert_id):
    image_path, err = save_uploaded_image()
    if err:
        return jsonify({"error": err}), 400
    form = request.form

    def mutator(items):
        for item in items:
            if item.get("id") != cert_id:
                continue
            if "title" in form and security.clean_text(form.get("title"), 200):
                item["title"] = security.clean_text(form.get("title"), 200)
            if "issuer" in form:
                item["issuer"] = security.clean_text(form.get("issuer"), 200)
            if "meta" in form:
                item["meta"] = security.clean_text(form.get("meta"), 200)
            if "link" in form:
                item["link"] = security.safe_url(form.get("link"))
            if image_path:
                remove_uploaded_image(item.get("image"))
                item["image"] = image_path
            return items, item
        return items, None

    updated = storage.read_modify_write(config.CERTIFICATIONS_FILE, mutator, DEFAULT_CERTIFICATIONS)
    if updated is None:
        return jsonify({"error": "certification not found"}), 404
    return jsonify({"status": "ok", "certification": updated})


@app.route("/api/certifications/<cert_id>", methods=["DELETE"])
@security.require_admin
def delete_certification(cert_id):
    def mutator(items):
        remaining = [c for c in items if c.get("id") != cert_id]
        if len(remaining) == len(items):
            return items, False
        for c in items:
            if c.get("id") == cert_id:
                remove_uploaded_image(c.get("image"))
        return remaining, True

    deleted = storage.read_modify_write(config.CERTIFICATIONS_FILE, mutator, DEFAULT_CERTIFICATIONS)
    if not deleted:
        return jsonify({"error": "certification not found"}), 404
    return jsonify({"status": "ok", "deleted": cert_id})


# ---------------------------------------------------------------------------
# Experience API
# ---------------------------------------------------------------------------

@app.route("/api/experiences", methods=["GET"])
def list_experiences():
    return jsonify(load_experiences())


@app.route("/api/experiences", methods=["POST"])
@security.require_admin
def add_experience():
    role = security.clean_text(request.form.get("role"), 200)
    if not role:
        return jsonify({"error": "role is required"}), 400

    new_experience = {
        "id": uuid.uuid4().hex[:8],
        "role": role,
        "company": security.clean_text(request.form.get("company"), 200),
        "duration": security.clean_text(request.form.get("duration"), 100),
        "description": security.clean_text(request.form.get("description"), 1000),
    }

    def mutator(items):
        new_experience["order"] = next_order(items)
        items.append(new_experience)
        return items, new_experience

    created = storage.read_modify_write(config.EXPERIENCES_FILE, mutator, DEFAULT_EXPERIENCES)
    return jsonify({"status": "ok", "experience": created}), 201


@app.route("/api/experiences/<experience_id>", methods=["PATCH"])
@security.require_admin
def update_experience(experience_id):
    form = request.form

    def mutator(items):
        for item in items:
            if item.get("id") != experience_id:
                continue
            if "role" in form:
                role = security.clean_text(form.get("role"), 200)
                if role:
                    item["role"] = role
            if "company" in form:
                item["company"] = security.clean_text(form.get("company"), 200)
            if "duration" in form:
                item["duration"] = security.clean_text(form.get("duration"), 100)
            if "description" in form:
                item["description"] = security.clean_text(form.get("description"), 1000)
            return items, item
        return items, None

    updated = storage.read_modify_write(config.EXPERIENCES_FILE, mutator, DEFAULT_EXPERIENCES)
    if updated is None:
        return jsonify({"error": "experience not found"}), 404
    return jsonify({"status": "ok", "experience": updated})


@app.route("/api/experiences/reorder", methods=["POST"])
@security.require_admin
def reorder_experiences():
    """Body: {"ids": ["id1", "id2", ...]} - sets display order."""
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list):
        return jsonify({"error": "ids must be a list"}), 400

    def mutator(items):
        position = {eid: i for i, eid in enumerate(ids)}
        for item in items:
            item["order"] = position.get(item.get("id"), len(position))
        return items, sorted(items, key=lambda e: e.get("order", 0))

    ordered = storage.read_modify_write(config.EXPERIENCES_FILE, mutator, DEFAULT_EXPERIENCES)
    return jsonify({"status": "ok", "experiences": ordered})


@app.route("/api/experiences/<experience_id>", methods=["DELETE"])
@security.require_admin
def delete_experience(experience_id):
    def mutator(items):
        remaining = [e for e in items if e.get("id") != experience_id]
        if len(remaining) == len(items):
            return items, False
        return remaining, True

    deleted = storage.read_modify_write(config.EXPERIENCES_FILE, mutator, DEFAULT_EXPERIENCES)
    if not deleted:
        return jsonify({"error": "experience not found"}), 404
    return jsonify({"status": "ok", "deleted": experience_id})


# ---------------------------------------------------------------------------
# Skills API
# ---------------------------------------------------------------------------

@app.route("/api/skills", methods=["GET"])
def list_skills():
    return jsonify(load_skills())


@app.route("/api/skills", methods=["POST"])
@security.require_admin
def add_skill():
    title = security.clean_text(request.form.get("title"), 200)
    if not title:
        return jsonify({"error": "title is required"}), 400

    tags = [t.strip() for t in (request.form.get("tags") or "").split(",") if t.strip()][:20]
    new_skill = {
        "id": uuid.uuid4().hex[:8],
        "title": title,
        "subtitle": security.clean_text(request.form.get("subtitle"), 200),
        "tags": tags,
        "subgroups": parse_subgroups(request.form.get("subgroups")),
        "wide": (request.form.get("wide") or "").lower() in {"1", "true", "on", "yes"},
    }

    def mutator(items):
        new_skill["order"] = next_order(items)
        items.append(new_skill)
        return items, new_skill

    created = storage.read_modify_write(config.SKILLS_FILE, mutator, DEFAULT_SKILLS)
    return jsonify({"status": "ok", "skill": created}), 201


@app.route("/api/skills/<skill_id>", methods=["PATCH"])
@security.require_admin
def update_skill(skill_id):
    form = request.form

    def mutator(items):
        for item in items:
            if item.get("id") != skill_id:
                continue
            if "title" in form:
                title = security.clean_text(form.get("title"), 200)
                if title:
                    item["title"] = title
            if "subtitle" in form:
                item["subtitle"] = security.clean_text(form.get("subtitle"), 200)
            if "tags" in form:
                item["tags"] = [t.strip() for t in form["tags"].split(",") if t.strip()][:20]
            if "subgroups" in form:
                item["subgroups"] = parse_subgroups(form.get("subgroups"))
            if "wide" in form:
                item["wide"] = (form.get("wide") or "").lower() in {"1", "true", "on", "yes"}
            return items, item
        return items, None

    updated = storage.read_modify_write(config.SKILLS_FILE, mutator, DEFAULT_SKILLS)
    if updated is None:
        return jsonify({"error": "skill category not found"}), 404
    return jsonify({"status": "ok", "skill": updated})


@app.route("/api/skills/reorder", methods=["POST"])
@security.require_admin
def reorder_skills():
    """Body: {"ids": ["id1", "id2", ...]} - sets display order."""
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list):
        return jsonify({"error": "ids must be a list"}), 400

    def mutator(items):
        position = {sid: i for i, sid in enumerate(ids)}
        for item in items:
            item["order"] = position.get(item.get("id"), len(position))
        return items, sorted(items, key=lambda s: s.get("order", 0))

    ordered = storage.read_modify_write(config.SKILLS_FILE, mutator, DEFAULT_SKILLS)
    return jsonify({"status": "ok", "skills": ordered})


@app.route("/api/skills/<skill_id>", methods=["DELETE"])
@security.require_admin
def delete_skill(skill_id):
    def mutator(items):
        remaining = [s for s in items if s.get("id") != skill_id]
        if len(remaining) == len(items):
            return items, False
        return remaining, True

    deleted = storage.read_modify_write(config.SKILLS_FILE, mutator, DEFAULT_SKILLS)
    if not deleted:
        return jsonify({"error": "skill category not found"}), 404
    return jsonify({"status": "ok", "deleted": skill_id})


@app.route("/api/session", methods=["GET"])
def session_state():
    """Lets the front-end show or hide the owner-only controls."""
    return jsonify({"is_admin": security.is_admin()})


@app.route("/api/github-status", methods=["GET"])
@security.require_admin
def github_status():
    """Synchronous GitHub-sync connectivity check. Hit this from a browser
    (while signed in at /admin) instead of digging through platform logs -
    it returns the exact reason GitHub sync is or isn't working."""
    return jsonify(github_sync.diagnose())


# ---------------------------------------------------------------------------
# Errors - JSON for /api, HTML elsewhere
# ---------------------------------------------------------------------------

def _wants_json():
    return request.path.startswith("/api/")


@app.errorhandler(404)
def not_found(err):
    if _wants_json():
        return jsonify({"error": "not found"}), 404
    return render_template("error.html", code=404,
                           message=getattr(err, "description", "Page not found.")), 404


@app.errorhandler(413)
def too_large(err):
    return jsonify({"error": "That file is too large. Maximum size is 5 MB."}), 413


@app.errorhandler(500)
def server_error(err):
    app.logger.exception("Unhandled error")
    if _wants_json():
        return jsonify({"error": "internal server error"}), 500
    return render_template("error.html", code=500,
                           message="Something went wrong on my side."), 500


if __name__ == "__main__":
    # Development only. In production use:  gunicorn app:app
    app.run(host="0.0.0.0", debug=config.DEBUG, port=config.PORT)
