"""Central configuration, read once at import time from the environment."""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # reads a ".env" file in the project root, if present
except ImportError:
    # python-dotenv not installed: fall back to real environment variables
    # only. Run "pip install python-dotenv" to enable the .env file.
    pass


def env_str(name, default=None):
    """Read an env var and strip surrounding whitespace/quotes.

    Dashboard UIs (Render included) very easily pick up a trailing space
    or a stray newline when you paste a value in, which silently breaks
    API keys and email addresses. Cleaning here saves a lot of debugging.
    """
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip().strip('"').strip("'").strip()
    return value or default


def env_int(name, default):
    try:
        return int(env_str(name, "") or default)
    except (TypeError, ValueError):
        return default


def env_bool(name, default=False):
    raw = (env_str(name, "") or "").lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Where mutable data lives.
#
# THIS IS THE IMPORTANT ONE. On Render/Heroku/Fly the container filesystem is
# ephemeral: every deploy or restart wipes it, taking your contact messages,
# projects and uploaded images with it.
#
# Attach a persistent disk (Render: Settings -> Disks, mount at /var/data) and
# set DATA_DIR=/var/data. Everything mutable then lives on that disk and
# survives deploys. Locally it defaults to ./data, which is gitignored.
#
# Alternatively (or in addition), configure GITHUB_TOKEN/GITHUB_REPO below -
# storage.py will then also back up every JSON write to a GitHub repo and
# restore from it on a fresh disk, without needing a paid persistent volume.
# ---------------------------------------------------------------------------
DATA_DIR = env_str("DATA_DIR") or os.path.join(BASE_DIR, "data")
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")

MESSAGES_FILE = os.path.join(DATA_DIR, "messages.json")
PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")
CERTIFICATIONS_FILE = os.path.join(DATA_DIR, "certifications.json")
EXPERIENCES_FILE = os.path.join(DATA_DIR, "experiences.json")
SKILLS_FILE = os.path.join(DATA_DIR, "skills.json")

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB cap on uploads

# Admin-uploaded resume. Lives on DATA_DIR (the persistent disk), not
# static/, so uploading a new resume from /admin survives the next deploy
# the same way projects/certifications/messages do. If nothing has been
# uploaded yet, app.py falls back to a resume bundled at static/resume.pdf.
ALLOWED_RESUME_EXT = {"pdf"}
RESUME_FILE = os.path.join(DATA_DIR, "resume.pdf")

# Field length caps for the public contact form. Enforced server-side; the
# HTML maxlength attributes are only a convenience.
MAX_NAME_LEN = 120
MAX_EMAIL_LEN = 200
MAX_PHONE_LEN = 40
MAX_SUBJECT_LEN = 200
MAX_MESSAGE_LEN = 5000

# Public contact form rate limit (per IP).
CONTACT_RATE_LIMIT = env_int("CONTACT_RATE_LIMIT", 5)
CONTACT_RATE_WINDOW = env_int("CONTACT_RATE_WINDOW", 3600)  # seconds

# Admin auth. ADMIN_TOKEN gates the API; signing in at /admin with it sets a
# session cookie so you don't retype it for every action.
ADMIN_TOKEN = env_str("ADMIN_TOKEN")
SECRET_KEY = env_str("SECRET_KEY") or env_str("FLASK_SECRET_KEY")

# Resend (HTTPS email API - see notifications.py for why not SMTP).
RESEND_API_KEY = env_str("RESEND_API_KEY")
NOTIFY_EMAIL = env_str("NOTIFY_EMAIL")
RESEND_FROM_EMAIL = env_str("RESEND_FROM_EMAIL", "onboarding@resend.dev")

# GitHub-backed backup/restore for storage.py (see github_sync.py). Optional:
# if GITHUB_TOKEN or GITHUB_REPO isn't set, github_sync.py is a no-op and
# storage.py behaves exactly as it did before.
#
# GITHUB_TOKEN: fine-grained PAT scoped to ONLY the backup repo, with
#               "Contents: Read and write" permission. Set it as an env
#               var on Render like ADMIN_TOKEN - never commit it.
# GITHUB_REPO:  "owner/repo", e.g. "DhananjaySingh0/portfolio-data". Can be
#               a small private repo used only for JSON backups.
GITHUB_TOKEN = env_str("GITHUB_TOKEN")
GITHUB_REPO = env_str("GITHUB_REPO")
GITHUB_BRANCH = env_str("GITHUB_BRANCH", "main")
GITHUB_DATA_PATH = env_str("GITHUB_DATA_PATH", "data")

DEBUG = env_bool("FLASK_DEBUG", False)
PORT = env_int("PORT", 5000)

# Used for canonical URLs, Open Graph tags and sitemap.xml.
SITE = {
    "name": "Dhananjay Kumar Singh",
    "description": (
        "AI/ML and Python developer building intelligent applications, "
        "scalable backends and production-ready APIs."
    ),
    "email": "dhananjaysingh90314@gmail.com",
    "github": "https://github.com/DhananjaySingh0",
    "linkedin": "https://www.linkedin.com/in/dhananjaysingh0",
    # Digits only, with country code, no "+" or spaces - this is what
    # wa.me/<number> expects.
    "whatsapp": "919905717181",
    "whatsapp_display": "+91 99057 17181",
}