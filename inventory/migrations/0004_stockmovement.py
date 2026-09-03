import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0003_purchaseitem'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StockMovement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('movement_type', models.CharField(choices=[('in', 'In'), ('out', 'Out'), ('adjustment', 'Adjustment')], max_length=12)),
                ('quantity', models.DecimalField(decimal_places=4, max_digits=12)),
                ('reference_type', models.CharField(blank=True, choices=[('purchase', 'Purchase'), ('sale', 'Sale'), ('return', 'Return'), ('adjustment', 'Adjustment'), ('manual', 'Manual')], max_length=12)),
                ('reference_id', models.PositiveIntegerField(blank=True, null=True)),
                ('unit_cost', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('movement_date', models.DateTimeField()),
                ('notes', models.TextField(blank=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stock_movements', to=settings.AUTH_USER_MODEL)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stock_movements', to='inventory.product')),
            ],
            options={
                'ordering': ['-movement_date', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='stockmovement',
            index=models.Index(fields=['product', 'movement_date'], name='inventory_s_product_8a0c2e_idx'),
        ),
        migrations.AddIndex(
            model_name='stockmovement',
            index=models.Index(fields=['reference_type', 'reference_id'], name='inventory_s_referen_4f1c8a_idx'),
        ),
    ]
