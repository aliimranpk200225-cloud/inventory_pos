import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('description', models.TextField(blank=True)),
            ],
            options={
                'verbose_name_plural': 'categories',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Unit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
                ('abbreviation', models.CharField(max_length=20, unique=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Product',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('sku', models.CharField(max_length=50, unique=True)),
                ('brand', models.CharField(blank=True, max_length=100)),
                ('description', models.TextField(blank=True)),
                ('min_stock', models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ('active', models.BooleanField(default=True)),
                ('base_unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='base_products', to='inventory.unit')),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='products', to='inventory.category')),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='ProductUnit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('conversion_to_base', models.DecimalField(decimal_places=4, help_text='How many base units equal one of this unit (e.g. 12 if a carton holds 12 pieces).', max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))])),
                ('purchase_price', models.DecimalField(decimal_places=2, max_digits=12)),
                ('retail_price', models.DecimalField(decimal_places=2, max_digits=12)),
                ('wholesale_price', models.DecimalField(decimal_places=2, max_digits=12)),
                ('barcode', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='product_units', to='inventory.product')),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='product_units', to='inventory.unit')),
            ],
            options={
                'ordering': ['product', 'conversion_to_base'],
                'constraints': [
                    models.UniqueConstraint(fields=('product', 'unit'), name='unique_product_unit'),
                ],
            },
        ),
    ]
