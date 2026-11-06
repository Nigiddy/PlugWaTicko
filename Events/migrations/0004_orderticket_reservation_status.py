# Generated for Phase 3 Migration M-02: OrderTicket reservation expiration and status

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Events', '0003_ticketprice_reservation_constraints'),
    ]

    operations = [
        migrations.AlterField(
            model_name='orderticket',
            name='status',
            field=models.CharField(
                choices=[
                    ('not completed', 'Pending'),
                    ('RESERVED', 'Inventory Reserved'),
                    ('completed', 'Completed'),
                    ('EXPIRED', 'Reservation Expired'),
                    ('CANCELLED', 'Order Cancelled')
                ],
                db_index=True,
                default='not completed',
                max_length=20
            ),
        ),
        migrations.AddField(
            model_name='orderticket',
            name='reservation_expires_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='orderticket',
            name='paystack_reference',
            field=models.CharField(blank=True, db_index=True, max_length=100, null=True, unique=True),
        ),
        migrations.AddIndex(
            model_name='orderticket',
            index=models.Index(fields=['status', 'reservation_expires_at'], name='ordertkt_stat_exp_idx'),
        ),
    ]

