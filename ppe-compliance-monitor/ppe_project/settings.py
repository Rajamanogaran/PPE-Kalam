"""
Django settings for PPE Compliance Monitoring — Industry Standard (12-factor, secure by default)
"""
from pathlib import Path
import os
import sys

BASE_DIR = Path(__file__).resolve().parent.parent

# --- 12-factor env ---
# Use django-environ if available, else fallback to os.environ
try:
    import environ  # type: ignore
    env = environ.Env(
        DJANGO_DEBUG=(bool, False),
        DJANGO_SECRET_KEY=(str, None),
        DJANGO_ALLOWED_HOSTS=(str, "*"),
        DJANGO_CSRF_TRUSTED_ORIGINS=(str, ""),
        DATABASE_URL=(str, ""),
        DJANGO_TIME_ZONE=(str, "Asia/Kolkata"),
    )
    # Read .env if present (local dev)
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        environ.Env.read_env(str(env_file))
    SECRET_KEY = env("DJANGO_SECRET_KEY") or os.environ.get("DJANGO_SECRET_KEY") or "django-insecure-ppe-kalam-dev-key-change-in-production-2026"
    DEBUG = env("DJANGO_DEBUG") if "DJANGO_DEBUG" in os.environ or env_file.exists() else (os.environ.get("DJANGO_DEBUG", "True") == "True")
    ALLOWED_HOSTS = [h.strip() for h in (env("DJANGO_ALLOWED_HOSTS") or os.environ.get("DJANGO_ALLOWED_HOSTS", "*")).split(",") if h.strip()]
    CSRF_TRUSTED_ORIGINS_ENV = env("DJANGO_CSRF_TRUSTED_ORIGINS") or os.environ.get("CSRF_TRUSTED_ORIGINS", "")
    TIME_ZONE = env("DJANGO_TIME_ZONE")
    DATABASE_URL = env("DATABASE_URL")
except ImportError:
    SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-ppe-kalam-dev-key-change-in-production-2026")
    DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"
    ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]
    CSRF_TRUSTED_ORIGINS_ENV = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
    TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Kolkata")
    DATABASE_URL = os.environ.get("DATABASE_URL", "")

# CSRF & Preview Hosts for Arena / Codespaces / E2B
CSRF_TRUSTED_ORIGINS = [o.strip() for o in CSRF_TRUSTED_ORIGINS_ENV.split(",") if o.strip()] if CSRF_TRUSTED_ORIGINS_ENV else []
if DEBUG:
    # Allow E2B preview hosts (https://{port}-{sandboxId}.e2b.app) and Codespaces
    CSRF_TRUSTED_ORIGINS += ["https://*.e2b.app", "http://*.e2b.app", "https://*.app.github.dev"]
CSRF_TRUSTED_ORIGINS = [o for o in CSRF_TRUSTED_ORIGINS if o]

# In production, enforce explicit hosts
if not DEBUG and ALLOWED_HOSTS == ["*"]:
    # Warn but allow for now; in real prod set DJANGO_ALLOWED_HOSTS
    print("WARNING: ALLOWED_HOSTS='*' in production is insecure - set DJANGO_ALLOWED_HOSTS", file=sys.stderr)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "monitor",
]

try:
    import whitenoise  # type: ignore  # noqa: F401
    HAS_WHITENOISE = True
except ImportError:
    HAS_WHITENOISE = False

_mw = [
    "django.middleware.security.SecurityMiddleware",
]
if HAS_WHITENOISE:
    _mw.append("whitenoise.middleware.WhiteNoiseMiddleware")
_mw += [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
MIDDLEWARE = _mw

ROOT_URLCONF = "ppe_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ppe_project.wsgi.application"
ASGI_APPLICATION = "ppe_project.asgi.application"

# --- Database: SQLite (dev) / Postgres via DATABASE_URL (prod) ---
# Example: DATABASE_URL=postgres://user:pass@host:5432/ppe_kalam
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
if DATABASE_URL:
    try:
        import dj_database_url  # type: ignore

        DATABASES["default"] = dj_database_url.parse(DATABASE_URL, conn_max_age=600, ssl_require=not DEBUG)
    except ImportError:
        # Fallback: try to parse postgres URL manually (basic)
        if DATABASE_URL.startswith("postgres"):
            print("INFO: dj_database_url not installed, using SQLite fallback. pip install dj-database_url for Postgres", file=sys.stderr)

# --- Auth ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
USE_I18N = True
USE_TZ = True

# --- Static / Media (WhiteNoise for industry) ---
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
if HAS_WHITENOISE:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- PPE Paths ---
PPE_ML_MODELS_DIR = Path(os.environ.get("PPE_ML_MODELS_DIR", BASE_DIR / "ml_models"))
PPE_LOGS_DIR = Path(os.environ.get("PPE_LOGS_DIR", BASE_DIR / "logs"))
PPE_ML_MODELS_DIR.mkdir(parents=True, exist_ok=True)
PPE_LOGS_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

# --- Security (industry standard) ---
# Allow iframe for preview only in DEBUG; in prod set to DENY/SAMEORIGIN
X_FRAME_OPTIONS = "ALLOWALL" if DEBUG else "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # needed for JS fetch with X-CSRFToken
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "False") == "True"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Referrer
    SECURE_REFERRER_POLICY = "same-origin"

# --- Upload limits ---
DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# --- Logging (12-factor: stdout) ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"},
        "simple": {"format": "[%(levelname)s] %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "monitor": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "ppe": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# --- Cache (locmem dev, redis prod if REDIS_URL) ---
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ppe-kalam",
    }
}
REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    try:
        CACHES["default"] = {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    except Exception:
        pass

# --- PPE / Camera ---
# Fernet key for encrypting camera passwords at rest (32 url-safe base64). Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
PPE_FERNET_KEY = os.environ.get("PPE_FERNET_KEY", "")
# If not set, passwords are stored plain with warning (dev only)
if not PPE_FERNET_KEY and not DEBUG:
    print("WARNING: PPE_FERNET_KEY not set - camera passwords stored in plain text. Set a Fernet key in production.", file=sys.stderr)

# Health check interval for cameras (seconds) - used by management command
PPE_CAMERA_HEALTH_INTERVAL = int(os.environ.get("PPE_CAMERA_HEALTH_INTERVAL", "60"))

# --- Pagination ---
PPE_API_PAGE_SIZE = int(os.environ.get("PPE_API_PAGE_SIZE", "20"))
