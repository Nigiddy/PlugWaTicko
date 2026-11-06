from .base import *

DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = ['*']

CORS_ALLOW_ALL_ORIGINS = True

# Development Cookie Security (allow HTTP on localhost)
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
REST_AUTH['JWT_AUTH_SECURE'] = False

# Database configuration: PostgreSQL with automatic localhost/db detection and SQLite fallback
postgres_name = config('POSTGRES_NAME', default='')
if postgres_name:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'USER': config('POSTGRES_USER', default='postgres'),
            'NAME': postgres_name,
            'PASSWORD': config('POSTGRES_PASSWORD', default=''),
            'HOST': config('POSTGRES_HOST', default='db' if os.path.exists('/.dockerenv') else 'localhost'),
            'PORT': config('POSTGRES_PORT', default=5432, cast=int),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Email Backend: Use SMTP if credentials provided, else console for local inspection
email_user = config('EMAIL_HOST_USER', default='')
if email_user:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_USE_SSL = False
    EMAIL_HOST_USER = email_user
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

