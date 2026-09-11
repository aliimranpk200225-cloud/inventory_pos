from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
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
        BANK = 'bank', 'Bank Transfer'
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
    cash_session = models.ForeignKey(
        'CashSession',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='sales',
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

    @property
    def change_amount(self):
        extra = self.paid_amount - self.total
        if extra > 0:
            return extra.quantize(Decimal('0.01'))
        return Decimal('0.00')

    def refresh_totals_from_items(self):
        subtotal = Decimal('0.00')
        tax = Decimal('0.00')
        for item in self.items.all():
            subtotal += item.line_subtotal - item.applied_discount
            tax += item.tax
        self.subtotal = subtotal.quantize(Decimal('0.01'))
        self.tax = tax.quantize(Decimal('0.01'))

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
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(Decimal('100'))],
        help_text='Product tax percent stored at sale time.',
    )
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

    @property
    def taxable_amount(self):
        return self.line_subtotal - self.applied_discount

    def save(self, *args, **kwargs):
        if self.unit_price is None and self.product_unit_id:
            self.unit_price = self.product_unit.retail_price
        self.base_quantity = self.quantity * self.product_unit.conversion_to_base
        rate = Decimal(str(self.tax_rate or 0))
        taxable = self.taxable_amount
        if taxable <= 0 or rate <= 0:
            self.tax = Decimal('0.00')
        else:
            self.tax = (taxable * rate / Decimal('100')).quantize(Decimal('0.01'))
        self.total = taxable + self.tax
        super().save(*args, **kwargs)


class CashSession(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        CLOSED = 'closed', 'Closed'

    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='cash_sessions',
    )
    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    opening_cash = models.DecimalField(max_digits=12, decimal_places=2)
    cash_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    card_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bank_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    refunds = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_in = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_out = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expected_closing_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    actual_closing_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cash_difference = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    completed_orders = models.PositiveIntegerField(default=0)
    cancelled_orders = models.PositiveIntegerField(default=0)
    draft_orders = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )

    class Meta:
        ordering = ['-opened_at']
        constraints = [
            models.UniqueConstraint(
                fields=['cashier'],
                condition=models.Q(status='open'),
                name='unique_open_pos_session_per_cashier',
            ),
        ]
        indexes = [
            models.Index(fields=['cashier', 'status']),
        ]

    def __str__(self):
        when = timezone.localtime(self.opened_at).strftime('%d-%b-%Y %H:%M')
        return f'{self.cashier} {when} ({self.status})'

    @property
    def is_open(self):
        return self.status == self.Status.OPEN

    @property
    def total_sales(self):
        return self.cash_sales + self.card_sales + self.bank_sales + self.other_sales


class CashMovement(models.Model):
    class MovementType(models.TextChoices):
        CASH_IN = 'cash_in', 'Cash in'
        CASH_OUT = 'cash_out', 'Cash out'
        EXPENSE = 'expense', 'Expense'
        REFUND = 'refund', 'Refund'

    session = models.ForeignKey(
        CashSession,
        on_delete=models.PROTECT,
        related_name='movements',
    )
    movement_type = models.CharField(max_length=12, choices=MovementType.choices)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    payment_method = models.CharField(
        max_length=10,
        choices=Sale.PaymentMethod.choices,
        default=Sale.PaymentMethod.CASH,
    )
    reason = models.CharField(max_length=200, blank=True)
    sale = models.ForeignKey(
        Sale,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cash_movements',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='cash_movements',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.get_movement_type_display()} Rs. {self.amount}'
