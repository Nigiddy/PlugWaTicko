# Generated for Phase 3 Migration M-03: Modernize JSON fields in BuyTicket and Event

import json
import ast
from django.db import migrations, models


def migrate_stringified_lists(apps, schema_editor):
    BuyTicket = apps.get_model('Events', 'BuyTicket')
    Event = apps.get_model('Events', 'Event')

    for bt in BuyTicket.objects.all():
        if bt.emails and isinstance(bt.emails, str):
            val = bt.emails.strip()
            parsed = None
            try:
                parsed = json.loads(val)
            except Exception:
                try:
                    parsed = ast.literal_eval(val)
                except Exception:
                    parsed = [val] if val else []
            bt.emails = parsed if isinstance(parsed, list) else ([parsed] if parsed else [])
            bt.save(update_fields=['emails'])

    for ev in Event.objects.all():
        if ev.tags and isinstance(ev.tags, str):
            val = ev.tags.strip()
            parsed = None
            try:
                parsed = json.loads(val)
            except Exception:
                try:
                    parsed = ast.literal_eval(val)
                except Exception:
                    parsed = [val] if val else []
            ev.tags = parsed if isinstance(parsed, list) else ([parsed] if parsed else [])
            ev.save(update_fields=['tags'])


def reverse_migration(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('Events', '0004_orderticket_reservation_status'),
    ]

    operations = [
        # Data migration to ensure values are valid JSON-serializable structures first
        migrations.RunPython(migrate_stringified_lists, reverse_migration),
        migrations.AlterField(
            model_name='buyticket',
            name='emails',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name='event',
            name='tags',
            field=models.JSONField(blank=True, default=list),
        ),
    ]

