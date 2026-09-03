from django.db import migrations, models


def copy_discount_to_value(apps, schema_editor):
    Purchase = apps.get_model('inventory', 'Purchase')
    PurchaseItem = apps.get_model('inventory', 'PurchaseItem')
    Purchase.objects.all().update(discount_value=models.F('discount'), discount_type='fixed')
    PurchaseItem.objects.all().update(discount_value=models.F('discount'), discount_type='fixed')


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_stockmovement'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchase',
            name='discount_type',
            field=models.CharField(
                choices=[('fixed', 'Fixed (Rs.)'), ('percent', 'Percent (%)')],
                default='fixed',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='purchase',
            name='discount_value',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='purchaseitem',
            name='discount_type',
            field=models.CharField(
                choices=[('fixed', 'Fixed (Rs.)'), ('percent', 'Percent (%)')],
                default='fixed',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='purchaseitem',
            name='discount_value',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.RunPython(copy_discount_to_value, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='purchase',
            name='discount',
        ),
        migrations.RemoveField(
            model_name='purchaseitem',
            name='discount',
        ),
    ]
