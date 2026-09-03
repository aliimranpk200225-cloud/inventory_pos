from django.db import migrations, models


def mark_existing_sales_posted(apps, schema_editor):
    Sale = apps.get_model('pos', 'Sale')
    Sale.objects.all().update(status='posted')


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0002_customer_saleitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='sale',
            name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('posted', 'Posted'), ('cancelled', 'Cancelled')], default='draft', max_length=10),
        ),
        migrations.RunPython(mark_existing_sales_posted, migrations.RunPython.noop),
    ]
