from .base import *

DEBUG = False

ALLOWED_HOSTS = ['*']

# Fast in-memory SQLite database for test runner
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Run Celery tasks synchronously in memory during tests
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# In-memory test email backend
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Disable throttling during automated test runs
REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES'] = []
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {}

# Relax cookie requirements for test client
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
REST_AUTH['JWT_AUTH_SECURE'] = False

