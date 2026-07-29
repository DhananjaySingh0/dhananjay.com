"""GitHub Contents API backed persistence.

Push/pull JSON files to a GitHub repo so data (messages, projects, etc.)
survives an ephemeral container filesystem without needing a paid
persistent disk. This is a *backup/restore* layer, not a replacement for
storage.py's file locking: local disk stays the source of truth for a
running process, GitHub is what a fresh deploy restores from.

Env vars (add these to config.py / your .env):
    GITHUB_TOKEN      - fine-grained PAT with "Contents: Read and write"
                         on the target repo only
    GITHUB_REPO       - "owner/repo"
    GITHUB_BRANCH     - defaults to "main"
    GITHUB_DATA_PATH  - folder inside the repo to store JSON files,
                         defaults to "data"

If GITHUB_TOKEN or GITHUB_REPO isn't set, every function here is a no-op,
so the app works exactly as before with GitHub simply not configured.
"""
import base64
import json
import logging
import threading
import urllib.error
import urllib.request

from config import GITHUB_BRANCH, GITHUB_DATA_PATH, GITHUB_REPO, GITHUB_TOKEN

log = logging.getLogger(__name__)

def _log(msg, *args):
    """Log AND print. Render's log viewer doesn't always surface
    logging.warning() calls depending on how the platform captures stdout
    vs the logging handlers, so this guarantees the error is visible while
    debugging a GitHub sync issue. Safe to leave in permanently - it's only
    called on failures, which should be rare/zero in steady state.
    """
    formatted = msg % args if args else msg
    log.warning(formatted)
    print(f"[github_sync] {formatted}")


API_ROOT = "https://api.github.com"

# filename -> last-known blob sha. Avoids an extra GET before every PUT once
# we've pushed a file at least once in this process's lifetime.
_SHA_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _validate_repo_format():
    """Catch the single most common misconfiguration - GITHUB_REPO set to
    just a repo name ("dhananjay_com") instead of "owner/repo" - loudly and
    at import time, instead of failing silently on every push/fetch later.
    """
    if not GITHUB_REPO:
        return
    parts = GITHUB_REPO.strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        _log(
            'GITHUB_REPO=%r is not in "owner/repo" format - GitHub sync will '
            'be disabled until this is fixed. Example: GITHUB_REPO=%s/your-repo-name',
            GITHUB_REPO, "your-github-username",
        )


def enabled():
    return bool(GITHUB_TOKEN and GITHUB_REPO and len(GITHUB_REPO.strip("/").split("/")) == 2
                and all(GITHUB_REPO.strip("/").split("/")))


_validate_repo_format()


def diagnose():
    """Synchronous connectivity self-test, meant for an admin-only status
    endpoint so a misconfiguration shows up as a clear message in the
    browser instead of requiring a trawl through platform logs.

    Returns a dict describing exactly what's wrong (or that it's fine).
    """
    if not GITHUB_TOKEN:
        return {"ok": False, "reason": "GITHUB_TOKEN is not set."}
    if not GITHUB_REPO:
        return {"ok": False, "reason": "GITHUB_REPO is not set."}
    parts = GITHUB_REPO.strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        return {
            "ok": False,
            "reason": (
                f'GITHUB_REPO={GITHUB_REPO!r} is not in "owner/repo" format. '
                f'Example: DhananjaySingh0/dhananjay_com'
            ),
        }

    dir_path = (GITHUB_DATA_PATH or "").strip("/")
    url = f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{dir_path}?ref={GITHUB_BRANCH}"
    try:
        _request("GET", url)
        return {"ok": True, "reason": f"Connected to {GITHUB_REPO} ({GITHUB_BRANCH}) fine."}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Repo/branch reachable, just no data/ folder yet - that's fine,
            # the first push will create it.
            return {
                "ok": True,
                "reason": (
                    f"Connected to {GITHUB_REPO} ({GITHUB_BRANCH}); "
                    f"'{GITHUB_DATA_PATH}' folder doesn't exist yet - "
                    f"it will be created on the first write."
                ),
            }
        if e.code == 401:
            return {"ok": False, "reason": "401 Unauthorized - GITHUB_TOKEN is invalid or expired."}
        if e.code == 403:
            return {
                "ok": False,
                "reason": (
                    "403 Forbidden - the token doesn't have Contents: Read and "
                    "write permission on this repo (or rate-limited)."
                ),
            }
        return {"ok": False, "reason": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}


def _repo_path(filename):
    prefix = (GITHUB_DATA_PATH or "").strip("/")
    return f"{prefix}/{filename}" if prefix else filename


def _request(method, url, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def fetch_json(filename, default=None):
    """Pull a JSON file from the repo. Returns `default` if missing/disabled
    or on any error - a GitHub outage must never crash a read.
    """
    if not enabled():
        return default
    path = _repo_path(filename)
    url = f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{path}?ref={GITHUB_BRANCH}"
    try:
        info = _request("GET", url)
        content = base64.b64decode(info["content"]).decode("utf-8")
        with _CACHE_LOCK:
            _SHA_CACHE[filename] = info.get("sha")
        return json.loads(content)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            _log("GitHub fetch failed for %s: %s", filename, e)
        return default
    except Exception as e:  # noqa: BLE001 - never let a backup path raise
        _log("GitHub fetch failed for %s: %s", filename, e)
        return default


def push_json(filename, items, message=None):
    """Create or update a JSON file in the repo. Best-effort: returns False
    and logs on any failure instead of raising, so a GitHub outage never
    takes the app down.
    """
    if not enabled():
        return False
    path = _repo_path(filename)
    url = f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{path}"
    content = json.dumps(items, indent=2, ensure_ascii=False)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    with _CACHE_LOCK:
        sha = _SHA_CACHE.get(filename)

    if sha is None:
        # Unknown sha (first push this process, or cache miss) - look it up
        # so the PUT doesn't 409 against an existing file.
        try:
            info = _request(
                "GET", f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{path}?ref={GITHUB_BRANCH}"
            )
            sha = info.get("sha")
        except urllib.error.HTTPError as e:
            sha = None
            if e.code != 404:
                _log("GitHub sha lookup failed for %s: %s", filename, e)
        except Exception as e:  # noqa: BLE001
            _log("GitHub sha lookup failed for %s: %s", filename, e)
            sha = None

    payload = {
        "message": message or f"Update {filename}",
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    try:
        result = _request("PUT", url, payload)
        with _CACHE_LOCK:
            _SHA_CACHE[filename] = result.get("content", {}).get("sha")
        return True
    except Exception as e:  # noqa: BLE001
        _log("GitHub push failed for %s: %s", filename, e)
        return False


def push_json_async(filename, items, message=None):
    """Fire-and-forget push so a web request never waits on a GitHub round
    trip. Safe to call on every write - it's a no-op when disabled.
    """
    if not enabled():
        return
    threading.Thread(
        target=push_json, args=(filename, items, message), daemon=True
    ).start()


# ---------------------------------------------------------------------------
# Binary files (uploaded images, resume.pdf). Same idea as the JSON helpers
# above but for raw bytes, since Contents API always speaks base64 either
# way. Callers pass a full repo-relative path (see repo_data_path()) rather
# than a bare filename, since these live under uploads/ subfolders.
# ---------------------------------------------------------------------------

def repo_data_path(*parts):
    """Join path parts under GITHUB_DATA_PATH, e.g.
    repo_data_path("uploads", "abc.png") -> "data/uploads/abc.png".
    """
    prefix = (GITHUB_DATA_PATH or "").strip("/")
    joined = "/".join(p.strip("/") for p in parts if p)
    return f"{prefix}/{joined}" if prefix else joined


def fetch_bytes(repo_path, default=None):
    """Pull raw bytes of a file from the repo. Returns `default` if
    missing/disabled or on any error.
    """
    if not enabled():
        return default
    url = f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{repo_path}?ref={GITHUB_BRANCH}"
    try:
        info = _request("GET", url)
        with _CACHE_LOCK:
            _SHA_CACHE[repo_path] = info.get("sha")
        return base64.b64decode(info["content"])
    except urllib.error.HTTPError as e:
        if e.code != 404:
            _log("GitHub fetch failed for %s: %s", repo_path, e)
        return default
    except Exception as e:  # noqa: BLE001
        _log("GitHub fetch failed for %s: %s", repo_path, e)
        return default


def push_bytes(repo_path, data, message=None):
    """Create or update a binary file in the repo. Best-effort, never
    raises."""
    if not enabled():
        return False
    url = f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{repo_path}"
    encoded = base64.b64encode(data).decode("ascii")

    with _CACHE_LOCK:
        sha = _SHA_CACHE.get(repo_path)
    if sha is None:
        try:
            info = _request(
                "GET", f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{repo_path}?ref={GITHUB_BRANCH}"
            )
            sha = info.get("sha")
        except urllib.error.HTTPError as e:
            sha = None
            if e.code != 404:
                _log("GitHub sha lookup failed for %s: %s", repo_path, e)
        except Exception as e:  # noqa: BLE001
            _log("GitHub sha lookup failed for %s: %s", repo_path, e)
            sha = None

    payload = {
        "message": message or f"Update {repo_path}",
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    try:
        result = _request("PUT", url, payload)
        with _CACHE_LOCK:
            _SHA_CACHE[repo_path] = result.get("content", {}).get("sha")
        return True
    except Exception as e:  # noqa: BLE001
        _log("GitHub push failed for %s: %s", repo_path, e)
        return False


def push_bytes_async(repo_path, data, message=None):
    """Fire-and-forget binary push - use for uploaded images/resume so a
    request never waits on a GitHub round trip."""
    if not enabled():
        return
    threading.Thread(
        target=push_bytes, args=(repo_path, data, message), daemon=True
    ).start()


def delete_file(repo_path, message=None):
    """Delete a file from the repo. Best-effort: returns False (and logs)
    on any failure, including "we don't know its sha and a lookup failed" -
    a GitHub-side delete failing must never block a local delete.
    """
    if not enabled():
        return False
    with _CACHE_LOCK:
        sha = _SHA_CACHE.get(repo_path)
    if sha is None:
        try:
            info = _request(
                "GET", f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{repo_path}?ref={GITHUB_BRANCH}"
            )
            sha = info.get("sha")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Nothing on GitHub to delete - not an error, just a no-op.
                _log("GitHub delete skipped for %s: not found on GitHub (already gone, or never pushed)", repo_path)
            else:
                _log("GitHub delete sha-lookup failed for %s: HTTP %s %s", repo_path, e.code, e.reason)
            return False
        except Exception as e:  # noqa: BLE001
            _log("GitHub delete sha-lookup failed for %s: %s", repo_path, e)
            return False
    if not sha:
        _log("GitHub delete skipped for %s: no sha available (nothing to delete)", repo_path)
        return False
    url = f"{API_ROOT}/repos/{GITHUB_REPO}/contents/{repo_path}"
    payload = {"message": message or f"Delete {repo_path}", "sha": sha, "branch": GITHUB_BRANCH}
    try:
        _request("DELETE", url, payload)
        with _CACHE_LOCK:
            _SHA_CACHE.pop(repo_path, None)
        return True
    except Exception as e:  # noqa: BLE001
        _log("GitHub delete failed for %s: %s", repo_path, e)
        return False


def delete_file_async(repo_path, message=None):
    """Fire-and-forget delete - use when removing an image/resume locally."""
    if not enabled():
        return
    threading.Thread(target=delete_file, args=(repo_path, message), daemon=True).start()
