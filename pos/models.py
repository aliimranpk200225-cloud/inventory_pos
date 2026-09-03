from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from inventory.models import DiscountMixin, PostingStatus, ProductUnit, StockMovement


class Customer(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        if self.phone:
            return f'{self.name} ({self.phone})'
        return self.name


class Sale(DiscountMixin, models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Cash'
        CARD = 'card', 'Card'
        OTHER = 'other', 'Other'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'unpaid', 'Unpaid'
        PARTIAL = 'partial', 'Partial'
        PAID = 'paid', 'Paid'

    invoice_number = models.CharField(max_length=32, unique=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales',
    )
    customer_name = models.CharField(max_length=200, blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='sales',
    )
    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(
        max_length=10,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
    )
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=PostingStatus.choices,
        default=PostingStatus.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.invoice_number

    @property
    def applied_discount(self):
        return self.discount_amount(self.subtotal)

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = f'TMP-{timezone.now().strftime("%Y%m%d%H%M%S%f")}'
        self.total = self.subtotal - self.applied_discount + self.tax
        self.due_amount = self.total - self.paid_amount
        if self.paid_amount <= 0:
            self.payment_status = self.PaymentStatus.UNPAID
        elif self.paid_amount >= self.total:
            self.payment_status = self.PaymentStatus.PAID
            self.due_amount = Decimal('0')
        else:
            self.payment_status = self.PaymentStatus.PARTIAL
        super().save(*args, **kwargs)
        if self.invoice_number.startswith('TMP-'):
            self.invoice_number = f'INV-{self.pk:05d}'
            super().save(update_fields=['invoice_number'])

    @transaction.atomic
    def delete(self, *args, **kwargs):
        from inventory.stock import reverse_document

        reverse_document(StockMovement.ReferenceType.SALE, self.pk)
        return super().delete(*args, **kwargs)


class SaleItem(DiscountMixin, models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    product_unit = models.ForeignKey(
        ProductUnit,
        on_delete=models.PROTECT,
        related_name='sale_items',
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))],
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    base_quantity = models.DecimalField(max_digits=12, decimal_places=4, default=0)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.product_unit} x {self.quantity}'

    @property
    def line_subtotal(self):
        return (self.quantity * self.unit_price).quantize(Decimal('0.01'))

    @property
    def applied_discount(self):
        return self.discount_amount(self.line_subtotal)

    def save(self, *args, **kwargs):
        if self.unit_price is None and self.product_unit_id:
            self.unit_price = self.product_unit.retail_price
        self.base_quantity = self.quantity * self.product_unit.conversion_to_base
        self.total = self.line_subtotal - self.applied_discount + self.tax
        super().save(*args, **kwargs)
