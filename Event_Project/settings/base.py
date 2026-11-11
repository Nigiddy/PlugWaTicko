import os
from pathlib import Path
from datetime import timedelta
from decouple import config
import cloudinary

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# settings/base.py -> settings/ -> Event_Project/ -> root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-ticketplug-default-secret-key-change-in-production')
SIGNING_KEY = config('SIGNING_KEY', default=SECRET_KEY)

SITE_ID = 1
AUTH_USER_MODEL = 'Users.User'
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_VERIFICATION = 'mandatory'
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_ADAPTER = 'Event_Project.adapter.CustomAdapter'
DEFAULT_FROM_EMAIL = 'TicketPlug@gmail.com'
FRONTEND_URL = config('FRONTEND_URL', default='http://localhost:3000')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'django.contrib.postgres',
    'rest_framework',
    'corsheaders',
    'dj_rest_auth',
    'allauth',
    'allauth.account',
    'rest_framework_simplejwt',
    'django_filters',
    'drf_yasg',
    'cloudinary',
    'Users.apps.UsersConfig',
    'Events.apps.EventsConfig',
    'ADMIN.apps.AdminConfig',
    'Transactions.apps.TransactionsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'Event_Project.urls'

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

WSGI_APPLICATION = 'Event_Project.wsgi.application'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
MEDIA_URL = 'media/'
STATIC_ROOT = os.path.join(BASE_DIR, 'static')
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework Configuration
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        'rest_framework.authentication.SessionAuthentication',
        "dj_rest_auth.jwt_auth.JWTCookieAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        'rest_framework.permissions.IsAuthenticated',
    ],
    "DEFAULT_PAGINATION_CLASS": 'rest_framework.pagination.LimitOffsetPagination',
    "PAGE_SIZE": 10,
    'DEFAULT_SCHEMA_CLASS': 'rest_framework.schemas.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/minute',
        'user': '300/minute',
        'auth_endpoints': '10/minute',
        'payment_init': '15/minute',
        'ticket_checkin': '120/minute',
    },
}

REST_AUTH_TOKEN_MODEL = None
REST_AUTH = {
    "USER_DETAILS_SERIALIZER": 'Users.serializers.UserDetailSerializer',
    "REGISTER_SERIALIZER": 'Users.serializers.RegisterSerializer',
    "TOKEN_MODEL": None,
    "JWT_AUTH_COOKIE": 'ticket-plug-access',
    "JWT_AUTH_REFRESH_COOKIE": 'ticket-plug-refresh',
    "USE_JWT": True,
    'PASSWORD_RESET_USE_SITES_DOMAIN': True,
    'OLD_PASSWORD_FIELD_ENABLED': True,
    "LOGIN_SERIALIZER": 'Users.serializers.LoginSerializer',
    "JWT_AUTH_HTTPONLY": True,
    "JWT_AUTH_SAMESITE": "Lax",
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=14),
    'SIGNING_KEY': SIGNING_KEY,
}

SWAGGER_SETTINGS = {
    'LOGIN_URL': 'rest_login',
    'LOGOUT_URL': 'rest_logout',
}

# Celery Base Configuration
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default=CELERY_BROKER_URL)

# Paystack
PAYSTACK_SECRET_KEY = config('PAYSTACK_SECRET_KEY', default='sk_test_placeholder_key')

# Cloudinary
cloudinary.config(
    cloud_name=config('CLOUD_NAME', default='mock_cloud'),
    api_key=config('CLOUD_API_KEY', default='mock_key'),
    api_secret=config('CLOUD_API_SECRET', default='mock_secret')
)

