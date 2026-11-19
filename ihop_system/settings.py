"""
Django settings for ihop_system project.
"""

from pathlib import Path
from django.contrib.messages import constants as messages
from decouple import config
import os
from dotenv import load_dotenv
load_dotenv()

# =========================
# BASE
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent

# Todo lo sensible se lee de variables de entorno (.env en local; NUNCA se sube a git).
DEBUG = config("DEBUG", default=False, cast=bool)

SECRET_KEY = config("SECRET_KEY", default="")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-solo-desarrollo-local"
    else:
        raise RuntimeError("Falta SECRET_KEY en el entorno (obligatorio con DEBUG=False).")

def _csv(name, default=""):
    return [x.strip() for x in config(name, default=default).split(",") if x.strip()]

ALLOWED_HOSTS = _csv("ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = _csv("CSRF_TRUSTED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")

# =========================
# APPS
# =========================
INSTALLED_APPS = [
    # Core Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_countries",
    # Tu app principal
    "reservas.apps.ReservasConfig",

    # Templates helpers
    "widget_tweaks",

    # Extras
    "django_extensions",
    "formtools",

    # Sites (para allauth)
    "django.contrib.sites",

    # Allauth
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",

    # Nuestra app de cuentas (OTP)
    "accounts.apps.AccountsConfig",

    # Seguridad
    "csp",
    "axes",

    # 2FA / OTP
    "django_otp",
    "django_otp.plugins.otp_static",
    "django_otp.plugins.otp_totp",
    "two_factor",
]
SITE_ID = 1

# =========================
# MIDDLEWARE
# =========================
MIDDLEWARE = [
    # Seguridad y sesión
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # sirve /static en producción
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",

    # Autenticación base
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "axes.middleware.AxesMiddleware",  # solo una vez (protege contra intentos)
    "allauth.account.middleware.AccountMiddleware",
    "reservas.middleware.SoporteMiddleware",
    "reservas.middleware.EmpresaMiddleware",
    "reservas.middleware.AreaMiddleware",

    # OTP / 2FA (después de Authentication)
    "django_otp.middleware.OTPMiddleware",
    "reservas.middleware.StaffOTPRequiredMiddleware",

    # Cache headers solo en páginas de auth
    "reservas.middleware.NoCacheForAuthPagesMiddleware",

    # Seguridad adicional
    "csp.middleware.CSPMiddleware",

    # Mensajes y protección de frames
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",

    # 🔁 Redirección: evita registro por Allauth (envía a OTP)
    "accounts.middleware.RedirectSignupMiddleware",
    'reservas.middleware.RedirectNonStaffFromStaffURLs',

]

# Axes (un solo bloque)
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hora(s)
AXES_LOCKOUT_CALLABLE = None

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ROOT_URLCONF = "ihop_system.urls"

# =========================
# TEMPLATES
# =========================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # carpeta global de plantillas
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                # Django
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # personalizados
                "reservas.context_processors.countries_context",
                "reservas.context_processors.google_maps",
                "reservas.context_processors.social_flags",
                "reservas.context_processors.branding",
                "reservas.context_processors.areas_trabajo",
            ],
        },
    },
]

WSGI_APPLICATION = "ihop_system.wsgi.application"

# =========================
# BASE DE DATOS
# =========================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="ihop_db"),
        "USER": config("DB_USER", default="ihop_user"),
        "PASSWORD": config("DB_PASSWORD", default="bd"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "OPTIONS": {"sslmode": config("DB_SSLMODE", default="disable" if DEBUG else "require")},
        "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
    }
}

# =========================
# PASSWORDS
# =========================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =========================
# LOCALIZACIÓN / I18N
# =========================
USE_I18N = True
USE_TZ = True
TIME_ZONE = "America/Mexico_City"

LANGUAGE_CODE = "es-mx"
LANGUAGES = [
    ("es", "Español"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

LANGUAGE_COOKIE_NAME = "django_language"
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365  # 1 año
LANGUAGE_COOKIE_SAMESITE = "Lax"
LANGUAGE_COOKIE_SECURE = not DEBUG

# =========================
# ESTÁTICOS / MEDIA
# =========================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # ← requerido para collectstatic
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
        else "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# =========================
# LOGIN / LOGOUT (coherente con /auth/)
# =========================
LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/staff/"
LOGOUT_REDIRECT_URL = "/auth/login/"

# Allauth mapea a lo anterior
ACCOUNT_AUTHENTICATED_LOGIN_REDIRECTS = True
ACCOUNT_LOGIN_REDIRECT_URL = LOGIN_REDIRECT_URL
ACCOUNT_LOGOUT_REDIRECT_URL = LOGOUT_REDIRECT_URL
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http" if DEBUG else "https"

# Two-Factor usa el mismo destino post-login
TWO_FACTOR_LOGIN_REDIRECT_URL = LOGIN_REDIRECT_URL

# =========================
# MENSAJES
# =========================
MESSAGE_TAGS = {
    messages.DEBUG: "secondary",
    messages.INFO: "info",
    messages.SUCCESS: "success",
    messages.WARNING: "warning",
    messages.ERROR: "danger",
}

# =========================
# ALLAUTH (formato nuevo)
# =========================
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]

# Email verification de allauth (staff/social). Público usa OTP.
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True

SOCIALACCOUNT_AUTO_SIGNUP = True


# Social
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
    }
}

# =========================
# TWO-FACTOR / OTP
# =========================
TWO_FACTOR_PATCH_ADMIN = True  # protege /admin con 2FA
TWO_FACTOR_REMEMBER_COOKIE_AGE = 60 * 60 * 24 * 7  # recordar 1 semana

# =========================
# EMAIL
# =========================
EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = config("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER or "no-reply@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Seguridad OTP (para nuestro flujo de clientes)
EMAIL_OTP_EXP_MINUTES = 15
EMAIL_OTP_MAX_ATTEMPTS = 5
EMAIL_OTP_RESEND_COOLDOWN_SECONDS = 60
EMAIL_OTP_MAX_PER_HOUR_PER_EMAIL = 5

# =========================
# REGLAS DE RESERVAS
# =========================
RESERVA_DURACION_MIN_NORM = 90
RESERVA_DURACION_MIN_PICO = 105
HORAS_PICO = [(7, 11), (12, 15), (18, 21)]
RESERVAS_MAX_DIAS_ADELANTE = 30
RESERVA_LEAD_MIN = 15
RESERVA_ANTICIPACION_MIN = 20
RESERVA_ANTICIPACION_MIN_PICO = 30
CHECKIN_TOLERANCIA_MIN = 5
RESERVA_MIN_SEPARACION_MIN = 120
RESERVA_SEPARACION_POR_SUCURSAL = True
HORARIO_APERTURA = 8
HORARIO_CIERRE = 22
RESERVA_INTERVALO_MIN = 15


# ---- Reserva / asignación automática ----
BIG_CAP = 8
PROTECCION_BIG = 90
WASTE_MAX = 3
CAP_MAX = 12

# =========================
# SEGURIDAD
# =========================
SESSION_COOKIE_SAMESITE = "Lax"

SECURE_SSL_REDIRECT = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

if DEBUG:
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
else:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- CSP (django-csp >= 4) ---
from csp.constants import NONCE, SELF  # noqa: E402

_CSP_DIRECTIVES = {
    "default-src": (SELF,),
    "script-src": (SELF, NONCE, "https://cdn.jsdelivr.net", "https://maps.googleapis.com"),
    "style-src": (SELF, "https://cdn.jsdelivr.net", "https://fonts.googleapis.com", "'unsafe-inline'"),
    "font-src": (SELF, "https://cdn.jsdelivr.net", "https://fonts.gstatic.com", "data:"),
    "img-src": (SELF, "data:", "blob:", "https://maps.gstatic.com", "https://maps.googleapis.com",
                "https://www.gstatic.com", "https://ui-avatars.com",
                "https://unsplash.com", "https://images.unsplash.com"),
    "connect-src": (SELF, "https://maps.googleapis.com"),
    "frame-src": (SELF, "https://www.google.com", "https://maps.google.com"),
}
if DEBUG:
    CONTENT_SECURITY_POLICY_REPORT_ONLY = {"DIRECTIVES": _CSP_DIRECTIVES}
else:
    CONTENT_SECURITY_POLICY = {"DIRECTIVES": _CSP_DIRECTIVES}

# =========================
# Sentry
# =========================
if not DEBUG and os.environ.get("SENTRY_DSN"):
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

# =========================
# CACHE
# =========================
REDIS_URL = config("REDIS_URL", default="")
if REDIS_URL:
    # Backend nativo de Django (requiere el paquete "redis")
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "reservas",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "reservas-local",
        }
    }

# =========================
# AJUSTES DINÁMICOS PARA DEV
# =========================
if DEBUG:
    # En local, desactiva SSL & CSP/AXES si estorban (puedes comentar si no lo necesitas)
    # OJO: Axes ya lo estás usando; si quieres mantenerlo en dev, quita "axes.middleware.AxesMiddleware" de este filtro.
    MIDDLEWARE = [
        m for m in MIDDLEWARE
        if m not in ( "csp.middleware.CSPMiddleware", )
    ]
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

# =========================
# GOOGLE MAPS
# =========================
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# =========================
# ADAPTER (cierra signup de allauth; clientes usan OTP)
# =========================
ACCOUNT_ADAPTER = "ihop_system.adapters.CustomAccountAdapter"


# Mantenemos 'mandatory' para que (si algún día usas Allauth con público)
# exija verificación a usuarios NO staff.
ACCOUNT_EMAIL_VERIFICATION = "mandatory"

# =========================
# RATE LIMIT (django-ratelimit)
# =========================
RATELIMIT_USE_CACHE = "default"
RATELIMIT_ENABLE = config("RATELIMIT_ENABLE", default=True, cast=bool)
SILENCED_SYSTEM_CHECKS = ["django_ratelimit.E003", "django_ratelimit.W001"]  # locmem en desarrollo

# =========================
# WHATSAPP (Meta WhatsApp Cloud API) — opcional
# Si no hay token configurado, los mensajes se registran en el log y no se envían.
# =========================
WHATSAPP_TOKEN = config("WHATSAPP_TOKEN", default="")
WHATSAPP_PHONE_NUMBER_ID = config("WHATSAPP_PHONE_NUMBER_ID", default="")
WHATSAPP_API_VERSION = config("WHATSAPP_API_VERSION", default="v21.0")
WHATSAPP_TEMPLATE_CONFIRMACION = config("WHATSAPP_TEMPLATE_CONFIRMACION", default="")
WHATSAPP_TEMPLATE_RECORDATORIO = config("WHATSAPP_TEMPLATE_RECORDATORIO", default="")
WHATSAPP_TEMPLATE_LANG = config("WHATSAPP_TEMPLATE_LANG", default="es_MX")

# Webhook de WhatsApp (mensajes entrantes para el asistente de IA)
WHATSAPP_VERIFY_TOKEN = config("WHATSAPP_VERIFY_TOKEN", default="")
WHATSAPP_APP_SECRET = config("WHATSAPP_APP_SECRET", default="")  # firma X-Hub-Signature-256
# Si todas las empresas comparten el número de la plataforma, a cuál se dirigen los mensajes
WHATSAPP_EMPRESA_POR_DEFECTO = config("WHATSAPP_EMPRESA_POR_DEFECTO", default="")

# =========================
# ASISTENTE DE IA (Claude)
# =========================
ANTHROPIC_API_KEY = config("ANTHROPIC_API_KEY", default="")
AGENTE_IA_MODELO = config("AGENTE_IA_MODELO", default="claude-haiku-5-5")
AGENTE_IA_MAX_TOKENS = config("AGENTE_IA_MAX_TOKENS", default=1024, cast=int)

# Sitio público (para armar enlaces absolutos en correos/WhatsApp)
SITE_URL = config("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")

# Marca por defecto de la plataforma (cada empresa puede sobrescribirla)
PLATFORM_NAME = config("PLATFORM_NAME", default="Mesaya")
VENTAS_EMAIL = config("VENTAS_EMAIL", default="")
VENTAS_WHATSAPP = config("VENTAS_WHATSAPP", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO" if not DEBUG else "INFO"},
}
