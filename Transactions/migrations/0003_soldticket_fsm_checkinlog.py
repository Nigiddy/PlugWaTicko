# Generated for Phase 2 Migration M-04: SoldTicket FSM and CheckInLog

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


def populate_existing_sold_tickets(apps, schema_editor):
    SoldTicket = apps.get_model('Transactions', 'SoldTicket')
    for ticket in SoldTicket.objects.all():
        if ticket.used:
            ticket.status = 'CHECKED_IN'
        else:
            ticket.status = 'ISSUED'
        
        if not ticket.ticket_number:
            ticket.ticket_number = f"TKT-LEGACY-{ticket.id.hex[:8].upper()}"
        if not ticket.qr_code_token:
            ticket.qr_code_token = f"tkt_sec_{ticket.id.hex}"
        
        ticket.save(update_fields=['status', 'ticket_number', 'qr_code_token'])


def reverse_populate(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('Events', '0002_initial'),
        ('Transactions', '0002_initial'),
    ]

    operations = [
        # 1. Update Payment payment_id max_length to 100
        migrations.AlterField(
            model_name='payment',
            name='payment_id',
            field=models.CharField(max_length=100),
        ),
        # 2. Add new fields to SoldTicket as nullable first
        migrations.AddField(
            model_name='soldticket',
            name='status',
            field=models.CharField(choices=[('ISSUED', 'Issued'), ('CHECKED_IN', 'Checked In'), ('CANCELLED', 'Cancelled'), ('REFUNDED', 'Refunded'), ('EXPIRED', 'Expired')], db_index=True, default='ISSUED', max_length=20),
        ),
        migrations.AddField(
            model_name='soldticket',
            name='ticket_number',
            field=models.CharField(max_length=32, null=True),
        ),
        migrations.AddField(
            model_name='soldticket',
            name='qr_code_token',
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='soldticket',
            name='checked_in_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='soldticket',
            name='checked_in_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='scanned_tickets', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='soldticket',
            name='check_in_gate',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='soldticket',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='soldticket',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AlterField(
            model_name='soldticket',
            name='key',
            field=models.CharField(blank=True, db_index=True, max_length=32, null=True),
        ),
        migrations.AlterField(
            model_name='soldticket',
            name='payment',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sold_tickets', to='Transactions.payment'),
        ),
        # 3. Populate existing rows with unique identifiers and status
        migrations.RunPython(populate_existing_sold_tickets, reverse_populate),
        # 4. Enforce unique constraints on ticket_number and qr_code_token
        migrations.AlterField(
            model_name='soldticket',
            name='ticket_number',
            field=models.CharField(db_index=True, max_length=32, unique=True, null=True),
        ),
        migrations.AlterField(
            model_name='soldticket',
            name='qr_code_token',
            field=models.CharField(db_index=True, max_length=64, unique=True, null=True),
        ),
        # 5. Create CheckInLog model
        migrations.CreateModel(
            name='CheckInLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('scanned_token', models.CharField(max_length=64)),
                ('scanned_at', models.DateTimeField(auto_now_add=True)),
                ('gate', models.CharField(blank=True, default='Main Gate', max_length=100)),
                ('device_info', models.CharField(blank=True, default='', max_length=255)),
                ('result', models.CharField(choices=[('SUCCESS', 'Check-in Successful'), ('ALREADY_USED', 'Already Checked In'), ('INVALID_EVENT', 'Ticket Not Valid for This Event'), ('CANCELLED', 'Ticket Cancelled'), ('REFUNDED', 'Ticket Refunded'), ('INVALID_TOKEN', 'Token Unrecognized')], max_length=25)),
                ('notes', models.TextField(blank=True, default='')),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='check_in_logs', to='Events.event')),
                ('scanned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('ticket', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='check_in_logs', to='Transactions.soldticket')),
            ],
            options={
                'ordering': ['-scanned_at'],
            },
        ),
        # 6. Add indexes
        migrations.AddIndex(
            model_name='soldticket',
            index=models.Index(fields=['ticket', 'status'], name='soldtkt_tkt_status_idx'),
        ),
        migrations.AddIndex(
            model_name='soldticket',
            index=models.Index(fields=['qr_code_token', 'status'], name='soldtkt_qr_status_idx'),
        ),
        migrations.AddIndex(
            model_name='soldticket',
            index=models.Index(fields=['ticket_number'], name='soldtkt_number_idx'),
        ),
        migrations.AddIndex(
            model_name='checkinlog',
            index=models.Index(fields=['event', 'scanned_at'], name='checkin_evt_scan_idx'),
        ),
        migrations.AddIndex(
            model_name='checkinlog',
            index=models.Index(fields=['ticket', 'result'], name='checkin_tkt_res_idx'),
        ),
    ]

