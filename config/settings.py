"""Réglages du site de l'AJC06.

L'infrastructure passe par des variables d'environnement (voir .env.example). Le courriel, la validation des comptes,
HelloAsso et l'hébergeur des mentions légales se règlent dans /gestion/reglages/ (app siteconfig) : les variables
correspondantes ci-dessous ne servent plus que de valeurs de départ, lues une seule fois à la création des réglages.
"""

import os
import sys
from pathlib import Path

from core.csp import NONCE, NONE, SELF
from core.embeds import FRAME_SOURCES

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path):
    """Hébergement mutualisé (Passenger) : les variables viennent d'un fichier .env à côté de manage.py.
    Les variables déjà définies dans l'environnement (Docker, shell) restent prioritaires."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


if not (len(sys.argv) > 1 and sys.argv[1] == "test"):
    load_env_file(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-secret" if DEBUG else "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY doit être défini en production.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/")
# Agenda de la région niçoise qui reprend les sorties des membres (case « publier aussi sur Nice-Event »).
NICE_EVENT_URL = os.environ.get("NICE_EVENT_URL", "https://nice-event.fr").rstrip("/")
# Derrière un reverse proxy de confiance (Caddy) : l'adresse du visiteur est dans X-Forwarded-For.
TRUST_X_FORWARDED_FOR = env_bool("TRUST_X_FORWARDED_FOR", False)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django.forms",
    "core",
    "events",
    "blog",
    "gestion",
    "community",
    "projets",
    "siteconfig",
    "social",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "core.security.BanMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.csp.ContentSecurityPolicyMiddleware",
    "core.middleware.LegacyRedirectMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "core.csp.nonce",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
                "community.context_processors.member",
            ],
        },
    },
]

FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", BASE_DIR / "db.sqlite3"),
        "OPTIONS": {"transaction_mode": "IMMEDIATE", "init_command": "PRAGMA journal_mode=WAL;"},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Français"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", BASE_DIR / "backups"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

# Cache partagé entre les processus (Passenger en lance plusieurs) : limites d'envoi, compteurs anti-abus.
if os.environ.get("CACHE_DIR"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                          "LOCATION": os.environ["CACHE_DIR"]}}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "community:login"
LOGIN_REDIRECT_URL = "community:me"
AUTHENTICATION_BACKENDS = ["community.auth.EmailBackend", "django.contrib.auth.backends.ModelBackend"]
LOGOUT_REDIRECT_URL = "core:home"

# Courriel : serveur lu dans les réglages du site à chaque envoi (siteconfig.mail) ; console tant qu'il n'est pas réglé.
EMAIL_BACKEND = "siteconfig.mail.ConfigEmailBackend"
EMAIL_TIMEOUT = 20
# Valeurs de départ des réglages (anciennes variables du .env, voir siteconfig.models.initial_values).
ENV_EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", not EMAIL_USE_SSL)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "AJC06 <no-reply@ajc06.com>")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "contact@ajc06.com")
ACCOUNT_EMAIL_CONFIRMATION = env_bool("ACCOUNT_EMAIL_CONFIRMATION", False)
ACCOUNT_VALIDATION = os.environ.get("ACCOUNT_VALIDATION", "")
HELLOASSO_CLIENT_ID = os.environ.get("HELLOASSO_CLIENT_ID", "")
HELLOASSO_CLIENT_SECRET = os.environ.get("HELLOASSO_CLIENT_SECRET", "")
HELLOASSO_ORGANIZATION = os.environ.get("HELLOASSO_ORGANIZATION", "association-des-jeunes-chercheurs-des-alpes-mariti")
# Chiffre les secrets des réglages (mot de passe SMTP, client_secret HelloAsso) ; à défaut, clé dérivée de SECRET_KEY.
CONFIG_ENCRYPTION_KEY = os.environ.get("CONFIG_ENCRYPTION_KEY", "")

# Hébergeur des mentions légales : valeur de départ, modifiable ensuite dans /gestion/reglages/.
LEGAL_HOST = os.environ.get(
    "LEGAL_HOST",
    "o2switch, 222 boulevard Gustave Flaubert, 63000 Clermont-Ferrand — SIRET 510 909 807 00024.",
)

# Sécurité
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CSP = {
    "default-src": [SELF],
    "script-src": [SELF, NONCE],
    "style-src": [SELF],
    "img-src": [SELF, "data:", "blob:"],
    "font-src": [SELF],
    "connect-src": [SELF],
    "form-action": [SELF],
    "frame-src": [SELF, *FRAME_SOURCES],  # lecteurs vidéo chargés au clic (core/embeds.py)
    "frame-ancestors": [NONE],
    "base-uri": [SELF],
    "object-src": [NONE],
}
if not DEBUG:
    if TRUST_X_FORWARDED_FOR:  # derrière un reverse proxy (Caddy) qui termine le TLS
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# Tests : hachage rapide des mots de passe (jamais utilisé hors de « manage.py test »).
if len(sys.argv) > 1 and sys.argv[1] == "test":
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
