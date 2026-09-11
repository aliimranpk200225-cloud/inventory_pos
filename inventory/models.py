from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction


class DiscountType(models.TextChoices):
    FIXED = 'fixed', 'Fixed (Rs.)'
    PERCENT = 'percent', 'Percent (%)'


class DiscountMixin(models.Model):
    discount_type = models.CharField(
        max_length=10,
        choices=DiscountType.choices,
        default=DiscountType.FIXED,
    )
    discount_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        abstract = True

    def discount_amount(self, base):
        value = Decimal(str(self.discount_value or 0))
        base = Decimal(str(base or 0))
        if value <= 0 or base <= 0:
            return Decimal('0.00')
        if self.discount_type == DiscountType.PERCENT:
            amount = base * value / Decimal('100')
        else:
            amount = value
        amount = amount.quantize(Decimal('0.01'))
        return min(amount, base)

    def clean(self):
        super().clean()
        if self.discount_type == DiscountType.PERCENT and self.discount_value > 100:
            raise ValidationError({'discount_value': 'Percentage cannot exceed 100.'})
        if self.discount_value < 0:
            raise ValidationError({'discount_value': 'Discount cannot be negative.'})


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = 'categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Unit(models.Model):
    name = models.CharField(max_length=50, unique=True)
    abbreviation = models.CharField(max_length=20, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.abbreviation


class Supplier(models.Model):
    name = models.CharField(max_length=200, unique=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, unique=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='products',
    )
    base_unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name='base_products',
    )
    brand = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(
        upload_to='products/',
        blank=True,
        null=True,
        help_text='Optional. Shown as the POS product card background when uploaded.',
    )
    min_stock = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.sku} — {self.name}'

    def current_stock(self):
        from inventory.stock import current_stock

        return current_stock(self)


class ProductUnit(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='product_units',
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name='product_units',
    )
    conversion_to_base = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))],
        help_text='How many base units equal one of this unit (e.g. 12 if a carton holds 12 pieces).',
    )
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2)
    retail_price = models.DecimalField(max_digits=12, decimal_places=2)
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2)
    barcode = models.CharField(max_length=64, blank=True, null=True, unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'unit'],
                name='unique_product_unit',
            ),
        ]
        ordering = ['product', 'conversion_to_base']

    def __str__(self):
        return f'{self.product.sku} ({self.unit.abbreviation})'


class PostingStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    POSTED = 'posted', 'Posted'
    CANCELLED = 'cancelled', 'Cancelled'


class Purchase(DiscountMixin, models.Model):
    class PaymentStatus(models.TextChoices):
        UNPAID = 'unpaid', 'Unpaid'
        PARTIAL = 'partial', 'Partial'
        PAID = 'paid', 'Paid'

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name='purchases',
    )
    invoice_number = models.CharField(max_length=50)
    purchase_date = models.DateField()
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
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='purchases',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-purchase_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['supplier', 'invoice_number'],
                name='unique_supplier_invoice',
            ),
        ]

    def __str__(self):
        return f'{self.invoice_number} — {self.supplier}'

    @property
    def applied_discount(self):
        return self.discount_amount(self.subtotal)

    def save(self, *args, **kwargs):
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

    @transaction.atomic
    def delete(self, *args, **kwargs):
        from inventory.stock import reverse_document

        reverse_document(StockMovement.ReferenceType.PURCHASE, self.pk)
        return super().delete(*args, **kwargs)


class PurchaseItem(DiscountMixin, models.Model):
    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name='items',
    )
    product_unit = models.ForeignKey(
        ProductUnit,
        on_delete=models.PROTECT,
        related_name='purchase_items',
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
        self.base_quantity = self.quantity * self.product_unit.conversion_to_base
        self.total = self.line_subtotal - self.applied_discount + self.tax
        super().save(*args, **kwargs)


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        IN = 'in', 'In'
        OUT = 'out', 'Out'
        ADJUSTMENT = 'adjustment', 'Adjustment'

    class ReferenceType(models.TextChoices):
        PURCHASE = 'purchase', 'Purchase'
        SALE = 'sale', 'Sale'
        RETURN = 'return', 'Return'
        ADJUSTMENT = 'adjustment', 'Adjustment'
        MANUAL = 'manual', 'Manual'

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='stock_movements',
    )
    movement_type = models.CharField(max_length=12, choices=MovementType.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    reference_type = models.CharField(
        max_length=12,
        choices=ReferenceType.choices,
        blank=True,
    )
    reference_id = models.PositiveIntegerField(null=True, blank=True)
    line_id = models.PositiveIntegerField(null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    movement_date = models.DateTimeField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='stock_movements',
    )

    class Meta:
        ordering = ['-movement_date', '-id']
        indexes = [
            models.Index(fields=['product', 'movement_date']),
            models.Index(fields=['reference_type', 'reference_id']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['reference_type', 'line_id'],
                condition=models.Q(line_id__isnull=False),
                name='unique_stock_movement_per_line',
            ),
        ]

    def __str__(self):
        sign = '+' if self.movement_type == self.MovementType.IN else (
            '-' if self.movement_type == self.MovementType.OUT else ''
        )
        return f'{self.product.sku} {sign}{self.quantity}'


class StockAdjustment(models.Model):
    reason = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=PostingStatus.choices,
        default=PostingStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='stock_adjustments',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'ADJ-{self.pk or "new"} {self.reason}'

    @transaction.atomic
    def delete(self, *args, **kwargs):
        from inventory.stock import reverse_document

        reverse_document(StockMovement.ReferenceType.ADJUSTMENT, self.pk)
        return super().delete(*args, **kwargs)


class StockAdjustmentItem(models.Model):
    class Direction(models.TextChoices):
        INCREASE = 'increase', 'Increase'
        DECREASE = 'decrease', 'Decrease'

    adjustment = models.ForeignKey(
        StockAdjustment,
        on_delete=models.CASCADE,
        related_name='items',
    )
    product_unit = models.ForeignKey(
        ProductUnit,
        on_delete=models.PROTECT,
        related_name='adjustment_items',
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))],
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)
    base_quantity = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.product_unit} {self.direction} {self.quantity}'

    def save(self, *args, **kwargs):
        self.base_quantity = self.quantity * self.product_unit.conversion_to_base
        if not self.unit_cost:
            conversion = self.product_unit.conversion_to_base
            self.unit_cost = (
                self.product_unit.purchase_price / conversion
            ).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)
