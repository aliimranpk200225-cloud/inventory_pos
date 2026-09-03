import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0001_initial'),
        ('pos', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.DeleteModel(
            name='SaleLine',
        ),
        migrations.CreateModel(
            name='Customer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('phone', models.CharField(blank=True, db_index=True, max_length=30)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('address', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.RenameField(
            model_name='sale',
            old_name='receipt_number',
            new_name='invoice_number',
        ),
        migrations.AlterField(
            model_name='sale',
            name='invoice_number',
            field=models.CharField(max_length=32, unique=True),
        ),
        migrations.AddField(
            model_name='sale',
            name='customer_name',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='sale',
            name='customer_phone',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name='sale',
            name='discount_type',
            field=models.CharField(choices=[('fixed', 'Fixed (Rs.)'), ('percent', 'Percent (%)')], default='fixed', max_length=10),
        ),
        migrations.AddField(
            model_name='sale',
            name='discount_value',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='sale',
            name='paid_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='sale',
            name='due_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='sale',
            name='payment_status',
            field=models.CharField(choices=[('unpaid', 'Unpaid'), ('partial', 'Partial'), ('paid', 'Paid')], default='unpaid', max_length=10),
        ),
        migrations.AddField(
            model_name='sale',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name='sale',
            name='customer',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sales', to='pos.customer'),
        ),
        migrations.CreateModel(
            name='SaleItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(decimal_places=4, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))])),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=12)),
                ('tax', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('total', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('base_quantity', models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ('discount_type', models.CharField(choices=[('fixed', 'Fixed (Rs.)'), ('percent', 'Percent (%)')], default='fixed', max_length=10)),
                ('discount_value', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('product_unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='sale_items', to='inventory.productunit')),
                ('sale', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='pos.sale')),
            ],
            options={
                'ordering': ['id'],
            },
        ),
    ]
