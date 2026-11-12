#!/bin/bash
set -e

cd /app

echo "Waiting for PostgreSQL database to be ready..."
until pg_isready -h "${POSTGRES_HOST:-db}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-postgres}"; do
  echo "PostgreSQL is unavailable at ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432} - sleeping 1s"
  sleep 1
done
echo "PostgreSQL is ready!"

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

# Idempotent superuser creation
if [ -n "$DJANGO_SUPERUSER_EMAIL" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "Checking / creating superuser..."
    python manage.py shell <<EOF
from django.contrib.auth import get_user_model
User = get_user_model()
email = "$DJANGO_SUPERUSER_EMAIL"
password = "$DJANGO_SUPERUSER_PASSWORD"
if not User.objects.filter(email=email).exists():
    User.objects.create_superuser(email=email, password=password, first_name='Admin', last_name='User')
    print(f"Superuser '{email}' created successfully.")
else:
    print(f"Superuser '{email}' already exists. Skipping.")
EOF
fi

echo "Starting application server..."
if [ "$DEBUG" = "True" ] || [ "$DEBUG" = "true" ] || [ "$DEBUG" = "1" ] || [ "$DJANGO_ENV" = "development" ]; then
    echo "Running Django Development Server with live reload 🚀"
    exec python manage.py runserver 0.0.0.0:8000
else
    echo "Running Production Gunicorn Server 🚀"
    exec gunicorn Event_Project.wsgi:application --bind 0.0.0.0:8000 --workers 3
fi
