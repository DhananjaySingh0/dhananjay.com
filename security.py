"""Auth, rate limiting and input validation helpers."""

import re
import secrets
import time
import threading
from functools import wraps
from urllib.parse import urlparse

from flask import jsonify, request, session

import config

# A deliberately permissive check - the goal is to reject obvious junk and
# typos, not to police the RFC. Deliverability is proven by replying, not by
# a regex.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")

_SAFE_URL_SCHEMES = {"http", "https", "mailto"}


def is_valid_email(value):
    return bool(value) and len(value) <= config.MAX_EMAIL_LEN and bool(_EMAIL_RE.match(value))


def clean_text(value, max_len):
    """Trim, collapse control characters, and hard-cap length."""
    text = (value or "").strip()
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return text[:max_len]


def safe_url(value):
    """Return `value` only if it is a link a browser can safely follow.

    Blocks javascript:, data:, vbscript: and friends. These fields are
    admin-only, so this is defence in depth rather than a live hole - but it
    costs one function and removes the footgun entirely.
    """
    url = (value or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme:
        # Bare "github.com/x" - assume https rather than silently producing a
        # relative link.
        return "https://" + url.lstrip("/")
    if parsed.scheme.lower() not in _SAFE_URL_SCHEMES:
        return ""
    return url


# ---------------------------------------------------------------------------
# Admin auth
# ---------------------------------------------------------------------------

def _token_matches(supplied):
    if not config.ADMIN_TOKEN or not supplied:
        return False
    return secrets.compare_digest(supplied, config.ADMIN_TOKEN)


def is_admin():
    """True if the caller is authenticated, by session cookie or by token.

    NOTE: the token is read from the request header and the form body only -
    never from the query string, because query strings end up in access logs,
    browser history and Referer headers.
    """
    if session.get("is_admin"):
        return True
    supplied = request.headers.get("X-Admin-Token") or request.form.get("admin_token")
    return _token_matches(supplied)


def login_admin(token):
    if not _token_matches(token):
        return False
    session.clear()
    session["is_admin"] = True
    session.permanent = True
    return True


def logout_admin():
    session.clear()


def require_admin(view):
    """Only let the request through if the caller is authenticated.

    Never leaves an endpoint open by accident: with no ADMIN_TOKEN configured
    the endpoint is disabled outright rather than public.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not config.ADMIN_TOKEN:
            return jsonify({
                "error": "This endpoint is disabled. Set ADMIN_TOKEN in your .env file to enable it."
            }), 503
        if not is_admin():
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class RateLimiter:
    """Fixed-window in-memory limiter, keyed by client IP.

    In-process only, so it resets on restart and is per-worker. That is fine
    for a portfolio contact form: the goal is to stop a bot hammering the
    endpoint and burning the Resend quota, not to survive a determined
    attacker. Swap in flask-limiter with Redis if this ever needs to be real.
    """

    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self._hits = {}
        self._lock = threading.Lock()

    def _prune(self, now):
        cutoff = now - self.window
        for key in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
            self._hits.pop(key, None)

    def check(self, key):
        """Record a hit. Returns (allowed, seconds_until_retry)."""
        now = time.time()
        with self._lock:
            if len(self._hits) > 5000:
                self._prune(now)
            stamps = [t for t in self._hits.get(key, []) if t > now - self.window]
            if len(stamps) >= self.limit:
                retry_after = int(self.window - (now - stamps[0])) + 1
                self._hits[key] = stamps
                return False, retry_after
            stamps.append(now)
            self._hits[key] = stamps
            return True, 0


def client_ip():
    """Best-effort client IP behind a reverse proxy (Render, Cloudflare...)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


contact_limiter = RateLimiter(config.CONTACT_RATE_LIMIT, config.CONTACT_RATE_WINDOW)
