# Generated for Phase 3 Migration M-01: TicketPrice reservation fields and check constraints

from django.db import migrations, models


def precheck_and_normalize_sold_counts(apps, schema_editor):
    TicketPrice = apps.get_model('Events', 'TicketPrice')
    for tp in TicketPrice.objects.all():
        if tp.sold > tp.qty:
            tp.sold = tp.qty
            tp.save(update_fields=['sold'])


def reverse_precheck(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('Events', '0002_initial'),
    ]

    operations = [
        # 1. Add reserved field to TicketPrice
        migrations.AddField(
            model_name='ticketprice',
            name='reserved',
            field=models.PositiveIntegerField(default=0),
        ),
        # 2. Ensure sold <= qty on existing rows before applying constraint
        migrations.RunPython(precheck_and_normalize_sold_counts, reverse_precheck),
        # 3. Apply DB CheckConstraints
        migrations.AddConstraint(
            model_name='ticketprice',
            constraint=models.CheckConstraint(
                check=models.Q(sold__lte=models.F('qty')),
                name='ticketprice_sold_lte_qty'
            ),
        ),
        migrations.AddConstraint(
            model_name='ticketprice',
            constraint=models.CheckConstraint(
                check=models.Q(sold + models.F('reserved') <= models.F('qty')),
                name='ticketprice_sold_plus_reserved_lte_qty'
            ),
        ),
        migrations.AddConstraint(
            model_name='ticketprice',
            constraint=models.CheckConstraint(
                check=models.Q(reserved__gte=0),
                name='ticketprice_reserved_gte_zero'
            ),
        ),
    ]

