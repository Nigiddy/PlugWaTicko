#!/bin/bash
set -e

cd /app

echo "Waiting for Redis message broker..."
until python -c "import redis, os; url = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0'); r = redis.from_url(url); r.ping()" 2>/dev/null; do
  echo "Redis broker is unavailable - sleeping 1s"
  sleep 1
done
echo "Redis is ready!"

echo "Starting Celery worker..."
exec celery -A Event_Project worker -l info -c 2
