import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Supplier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True)),
                ('phone', models.CharField(blank=True, max_length=30)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('address', models.TextField(blank=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Purchase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('invoice_number', models.CharField(max_length=50)),
                ('purchase_date', models.DateField()),
                ('subtotal', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('discount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('tax', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('total', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('paid_amount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('due_amount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('payment_status', models.CharField(choices=[('unpaid', 'Unpaid'), ('partial', 'Partial'), ('paid', 'Paid')], default='unpaid', max_length=10)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='purchases', to=settings.AUTH_USER_MODEL)),
                ('supplier', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='purchases', to='inventory.supplier')),
            ],
            options={
                'ordering': ['-purchase_date', '-created_at'],
                'constraints': [
                    models.UniqueConstraint(fields=('supplier', 'invoice_number'), name='unique_supplier_invoice'),
                ],
            },
        ),
    ]
