import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0005_discount_type_value'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='purchase',
            name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('posted', 'Posted'), ('cancelled', 'Cancelled')], default='draft', max_length=10),
        ),
        migrations.AddField(
            model_name='stockmovement',
            name='line_id',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='stockmovement',
            constraint=models.UniqueConstraint(condition=models.Q(('line_id__isnull', False)), fields=('reference_type', 'line_id'), name='unique_stock_movement_per_line'),
        ),
        migrations.CreateModel(
            name='StockAdjustment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reason', models.CharField(max_length=200)),
                ('notes', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('posted', 'Posted'), ('cancelled', 'Cancelled')], default='draft', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stock_adjustments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='StockAdjustmentItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(decimal_places=4, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))])),
                ('direction', models.CharField(choices=[('increase', 'Increase'), ('decrease', 'Decrease')], max_length=10)),
                ('base_quantity', models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ('unit_cost', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('adjustment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='inventory.stockadjustment')),
                ('product_unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='adjustment_items', to='inventory.productunit')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
    ]
