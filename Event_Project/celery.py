import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Event_Project.settings')

app = Celery('Event_Project')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Periodic task schedule
app.conf.beat_schedule = {
    'release-expired-ticket-reservations-every-minute': {
        'task': 'Transactions.tasks.release_expired_ticket_reservations',
        'schedule': 60.0,
    },
}