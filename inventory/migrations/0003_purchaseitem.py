import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_supplier_purchase'),
    ]

    operations = [
        migrations.CreateModel(
            name='PurchaseItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(decimal_places=4, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))])),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=12)),
                ('discount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('tax', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('total', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('base_quantity', models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ('product_unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='purchase_items', to='inventory.productunit')),
                ('purchase', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='inventory.purchase')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
    ]
