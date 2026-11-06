import os
from decouple import config

environment = config('DJANGO_ENV', default=os.environ.get('ENVIRONMENT', 'development')).lower()

if environment in ['production', 'prod']:
    from .production import *
elif environment in ['testing', 'test']:
    from .testing import *
else:
    from .development import *

