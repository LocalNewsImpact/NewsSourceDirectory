"""Settings for both front ends.

One image serves the admin and, later, the researcher portal. They differ by
ROOT_URLCONF and database role, not by codebase — see docs/auth.md.
"""

import os
from pathlib import Path

from config.db import database_config

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(int(default))).lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-a-real-secret")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]

# Cloud Run terminates TLS at the load balancer and forwards the scheme.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

# Which front end this process is. The portal never routes the admin at all,
# so a permissions bug cannot expose it.
SERVICE_ROLE = os.environ.get("SERVICE_ROLE", "admin")
ROOT_URLCONF = "config.urls_portal" if SERVICE_ROLE == "portal" else "config.urls"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "import_export",
    "simple_history",
    "directory",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "directory.views.auth_context",
            ]
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": database_config(os.environ)}

# One sign-in across the suite. When the directory runs against Datadesk's
# database, Datadesk owns identity and this application must not migrate
# those tables — see config/routers.py for what goes wrong if it does.
SHARED_IDENTITY = os.environ.get("SHARED_IDENTITY", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
if SHARED_IDENTITY:
    DATABASE_ROUTERS = ["config.routers.IdentityOwnedByDatadesk"]

# The session is Datadesk's, carried between the two subdomains by a
# cookie on the parent domain — no load balancer, no shared origin. The
# names must match Datadesk's exactly or each console reads past the
# other's cookie and signs the person in again.
SESSION_COOKIE_DOMAIN = os.environ.get("SESSION_COOKIE_DOMAIN", "") or None
CSRF_COOKIE_DOMAIN = SESSION_COOKIE_DOMAIN
SESSION_COOKIE_NAME = "lnic_session"
CSRF_COOKIE_NAME = "lnic_csrf"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{v}"}
    for v in (
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    )
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Chicago"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- authentication ---------------------------------------------------------

SITE_ID = 1
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
LOGIN_REDIRECT_URL = "/admin/"
# Anything requiring a login goes to allauth's page, not the admin form.
# Overridden below to the provider handshake when Google is configured.
LOGIN_URL = "/accounts/login/"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
SOCIALACCOUNT_ADAPTER = "directory.auth.DomainRestrictedAdapter"

# Let a Google identity attach to an account that already exists with the same
# address, so an editor can be added before they have ever signed in.
#
# allauth disables this by default because it is an account-takeover vector:
# anyone who can obtain a token for an address could claim the matching local
# account. That risk does not apply here — DomainRestrictedAdapter refuses any
# login whose email is unverified or outside the hosted domain, so the only
# identities that reach this point are ones Google has verified inside an
# organisation we control.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True

# Only this domain may reach the admin. `hd` below is a hint to Google's account
# chooser and is NOT enforcement — the claim is verified in the adapter.
ALLOWED_GOOGLE_DOMAIN = os.environ.get("ALLOWED_GOOGLE_DOMAIN", "localnewsimpact.org")

# .strip() matters: the secrets exist as blank placeholders until real
# credentials are issued, and whitespace would read as "configured".
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()


def build_socialaccount_providers(client_id: str, secret: str, hosted_domain: str) -> dict:
    """Describe the Google provider, and only describe an app when there is one.

    An APP entry with empty credentials is worse than none: allauth uses it, the
    token exchange fails, and the user sees "Third-Party Login Failure" with a
    bare 401 in the logs. Without it the provider is simply unconfigured, which
    says so plainly and lets a contributor run the project on the ordinary
    Django login.
    """
    config = {
        "google": {
            "SCOPE": ["profile", "email"],
            # A hint to Google's account chooser, not enforcement. The claim is
            # verified in directory/auth.py.
            "AUTH_PARAMS": {"hd": hosted_domain},
        }
    }
    if client_id and secret:
        config["google"]["APP"] = {"client_id": client_id, "secret": secret, "key": ""}
    return config


SOCIALACCOUNT_PROVIDERS = build_socialaccount_providers(
    GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, ALLOWED_GOOGLE_DOMAIN
)

GOOGLE_SIGN_IN_CONFIGURED = bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)

# Arriving from Datadesk's navigation should not stop at a sign-in page.
# Google already holds this person's session, so the handshake starts
# immediately and finishes as a redirect nobody has to act on.
#
# SOCIALACCOUNT_LOGIN_ON_GET is what lets a GET begin it. allauth leaves
# that off by default because a third party can then trigger a login; the
# consequence here is being signed in as yourself, to an admin the domain
# adapter gates anyway. The sign-in page stays at /accounts/login/ for
# choosing a different account, and remains the only route when Google is
# not configured — blanking the client secret still brings the ordinary
# form back, so a broken OAuth client cannot lock anybody out.
if GOOGLE_SIGN_IN_CONFIGURED:
    LOGIN_URL = "/accounts/google/login/"
    SOCIALACCOUNT_LOGIN_ON_GET = True

# --- publishing -------------------------------------------------------------

FEED_S3_BUCKET = os.environ.get("FEED_S3_BUCKET", "")
FEED_LOCAL_DIR = BASE_DIR / "dist" / "feed"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
