import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")      # backend/.env faylidan kalitlarni o'qiydi
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "rest_framework", "rest_framework_simplejwt.token_blacklist", "drf_spectacular", "corsheaders",
    "accounts", "content", "payments", "quizzes", "imports", "materials", "assistant", "stats", "notifications",
]
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages"]},
}]
WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("POSTGRES_DB"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"], "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""), "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432")}}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "accounts.User"
LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["accounts.authentication.SessionJWTAuthentication"],
    # Default: login + faol obuna. Ochiq endpointlar permission_classes ni o'zi belgilaydi.
    "DEFAULT_PERMISSION_CLASSES": ["accounts.permissions.HasActiveAccess"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"login": "10/min", "register": "5/min", "payment": "10/min", "ai": "60/hour", "import": "30/hour"},
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "config.errors.api_exception_handler",
}
SIMPLE_JWT = {"ACCESS_TOKEN_LIFETIME": timedelta(minutes=30), "REFRESH_TOKEN_LIFETIME": timedelta(days=7)}
SPECTACULAR_SETTINGS = {"TITLE": "Bilim Markazi Pro API", "VERSION": "1.1"}
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")

# Tariflar (so'm) va muddat (kun) — faqat serverda
PLANS = {"1m": {"name": "1 oylik", "price": 5000, "days": 30},
         "1y": {"name": "1 yillik", "price": 50000, "days": 365}}


# ---- To'lov shlyuzlari (kalitlar kabinetdan olinadi, .env orqali) ----
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
PAYME_MERCHANT_ID = os.environ.get("PAYME_MERCHANT_ID", "")
PAYME_KEY = os.environ.get("PAYME_KEY", "payme-test-key")      # sinov: TEST KEY, jangda: KEY
PAYME_TEST = os.environ.get("PAYME_TEST", "1") == "1"
CLICK_MERCHANT_ID = os.environ.get("CLICK_MERCHANT_ID", "")
CLICK_SERVICE_ID = os.environ.get("CLICK_SERVICE_ID", "")
CLICK_SECRET_KEY = os.environ.get("CLICK_SECRET_KEY", "click-secret")

# ---- PDF dan avtomatik import (Claude API) ----
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
MAX_PDF_PAGES = int(os.environ.get("MAX_PDF_PAGES", "200"))
PDF_CHUNK_PAGES = int(os.environ.get("PDF_CHUNK_PAGES", "6"))
MAX_PDF_BYTES = 50 * 1024 * 1024

# ---- Materiallar (yopiq saqlash), antivirus, fon vazifalari, monitoring ----
PRIVATE_ROOT = BASE_DIR / "private"                    # bu papka veb orqali OCHIQ berilmaydi
MAX_MATERIAL_BYTES = int(os.environ.get("MAX_MATERIAL_MB", "50")) * 1024 * 1024
CLAMAV_HOST = os.environ.get("CLAMAV_HOST", "")        # bo'sh = antivirus tekshiruvi o'chiq
CLAMAV_PORT = int(os.environ.get("CLAMAV_PORT", "3310"))
CLAMAV_REQUIRED = os.environ.get("CLAMAV_REQUIRED", "0") == "1"
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "")    # bo'sh = fon oqimi (Redis shart emas)
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.05, send_default_pii=False)

# ---- Jangda (DEBUG=0) xavfsizlik sozlamalari ----
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]
if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured
    if SECRET_KEY == "dev-only-change-me":
        raise ImproperlyConfigured("Jangda SECRET_KEY ni o'zgartiring (.env.prod)")
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "0") == "1"      # HTTPS yoqilgach 1 qiling
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
    SECURE_HSTS_SECONDS = 31536000 if SECURE_SSL_REDIRECT else 0
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
