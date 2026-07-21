"""
Django settings for rent_core_service project.
Hardened for Production - Padvault Core
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
_PRODUCTION = os.getenv("DJANGO_PRODUCTION", "false").lower() == "true"

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv(
        "ALLOWED_HOSTS",
        "rent-mgt-core-service.onrender.com,127.0.0.1,localhost"
    ).split(",")
    if h.strip()
]

# Security Headers
if _PRODUCTION:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_SSL_REDIRECT = _PRODUCTION
SECURE_HSTS_SECONDS = 31536000 if _PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = _PRODUCTION
SECURE_HSTS_PRELOAD = _PRODUCTION
X_FRAME_OPTIONS = 'DENY'

APPEND_SLASH = False

INSTALLED_APPS = [
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'django_apscheduler',
    'Users',
    'Admin',
    'Address',
    'Properties',
    'Rent',
    'Transactions',
    'Bookings',
    'Maintenance',
    'Invoices',
    'Notifications',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'utils.middleware.GlobalResponseMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# CORS
CORS_ALLOWED_ORIGINS = [
    "https://padvault.io",
    "https://www.padvault.io",
    "https://app.padvault.io",
]
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ['X-Access-Token']

# CSRF
CSRF_TRUSTED_ORIGINS = [
    "https://padvault.io",
    "https://www.padvault.io",
    "https://app.padvault.io",
    "http://localhost:3000",
    "http://localhost:5173",
]
CSRF_COOKIE_SAMESITE = 'None'
CSRF_COOKIE_SECURE = True

# Monnify
MONNIFY_API_KEY = os.getenv('MONNIFY_API_KEY')
MONNIFY_SECRET_KEY = os.getenv('MONNIFY_SECRET_KEY')
MONNIFY_BASE_URL = os.getenv('MONNIFY_BASE_URL', 'https://sandbox.monnify.com')
MONNIFY_CONTRACT_CODE = os.getenv('MONNIFY_CONTRACT_CODE')

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'utils.drf_auth.PadvaultJWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': ['utils.permissions.IsAuthenticated'],
    'UNAUTHENTICATED_USER': None,
    'UNAUTHENTICATED_TOKEN': None,
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
}

ROOT_URLCONF = 'rent_core_service.urls'
WSGI_APPLICATION = 'rent_core_service.wsgi.application'

# Cloudinary
import cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET'),
    secure=True
)

# Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# Database
import dj_database_url
DATABASES = {
    'default': dj_database_url.config(
        default=os.getenv('DATABASE_URL'),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    { 'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator' },
    { 'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': { 'min_length': 8 } },
    { 'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator' },
    { 'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator' },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Email Configuration (Brevo HTTP API)
# We use HTTP API because Render blocks standard SMTP ports (25, 587, 465)
BREVO_API_KEY = os.getenv('BREVO_API_KEY', '').strip()
BREVO_SENDER_EMAIL = os.getenv('BREVO_SENDER_EMAIL', 'padvault.ng@gmail.com').strip()
DEFAULT_FROM_EMAIL = f"Padvault <{BREVO_SENDER_EMAIL}>"

# Push Notifications (VAPID)
VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY')
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY')
VAPID_ADMIN_EMAIL = os.getenv('VAPID_ADMIN_EMAIL', 'mailto:padvault.ng@gmail.com')

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
