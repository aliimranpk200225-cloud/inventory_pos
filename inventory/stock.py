from collections import defaultdict
from datetime import datetime, time
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import (
    Case,
    DecimalField,
    F,
    OuterRef,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from inventory.models import PostingStatus, Product, StockMovement


class InsufficientStock(ValidationError):
    """Raised when a sale or decrease would take stock below zero."""


def allow_negative_stock():
    return getattr(settings, 'INVENTORY_ALLOW_NEGATIVE_STOCK', False)


def cost_per_base_unit(pack_price, conversion):
    conversion = conversion or Decimal('1')
    if conversion <= 0:
        return Decimal('0.00')
    return (Decimal(str(pack_price)) / conversion).quantize(Decimal('0.01'))


def _signed_quantity_expression():
    decimal = DecimalField(max_digits=12, decimal_places=4)
    return Case(
        When(movement_type=StockMovement.MovementType.IN, then=F('quantity')),
        When(movement_type=StockMovement.MovementType.OUT, then=-F('quantity')),
        When(movement_type=StockMovement.MovementType.ADJUSTMENT, then=F('quantity')),
        default=Value(0),
        output_field=decimal,
    )


def current_stock(product, *, exclude_reference=None):
    """On-hand quantity in the product's base unit."""
    product_id = product.pk if hasattr(product, 'pk') else product
    qs = StockMovement.objects.filter(product_id=product_id)
    if exclude_reference:
        reference_type, reference_id = exclude_reference
        qs = qs.exclude(reference_type=reference_type, reference_id=reference_id)
    total = qs.aggregate(stock=Sum(_signed_quantity_expression()))['stock']
    return total or Decimal('0.0000')


STOCK_OK = 'ok'
STOCK_LOW = 'low'
STOCK_OUT = 'out'


def format_quantity(value):
    text = format(Decimal(str(value or 0)), 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text or '0'


def classify_stock(on_hand, min_stock=0):
    """Return ok / low / out from base-unit on-hand and the product min_stock."""
    on_hand = Decimal(str(on_hand or 0))
    min_stock = Decimal(str(min_stock or 0))
    if on_hand <= 0:
        return STOCK_OUT
    if min_stock > 0 and on_hand <= min_stock:
        return STOCK_LOW
    return STOCK_OK


def stock_status_label(status):
    return {
        STOCK_OUT: 'Out of stock',
        STOCK_LOW: 'Low stock',
        STOCK_OK: 'In stock',
    }.get(status, 'In stock')


def annotate_current_stock(queryset):
    """Annotate a Product queryset with stock_on_hand for reports."""
    decimal = DecimalField(max_digits=12, decimal_places=4)
    stock_subquery = (
        StockMovement.objects.filter(product_id=OuterRef('pk'))
        .values('product_id')
        .annotate(_stock=Sum(_signed_quantity_expression()))
        .values('_stock')[:1]
    )
    return queryset.annotate(
        stock_on_hand=Coalesce(Subquery(stock_subquery, output_field=decimal), Value(Decimal('0.0000'))),
    )


def _active_stock_qs(active_only=True):
    qs = Product.objects.all()
    if active_only:
        qs = qs.filter(active=True)
    return annotate_current_stock(qs)


def out_of_stock_products(active_only=True):
    return _active_stock_qs(active_only).filter(stock_on_hand__lte=0)


def low_stock_products(active_only=True):
    """On hand is above zero but at or below the product's minimum."""
    return _active_stock_qs(active_only).filter(
        min_stock__gt=0,
        stock_on_hand__gt=0,
        stock_on_hand__lte=F('min_stock'),
    )


def movements_between(start, end, **filters):
    """Reusable ledger query for daily/monthly purchase, sale, and stock reports."""
    return StockMovement.objects.filter(
        movement_date__gte=start,
        movement_date__lt=end,
        **filters,
    )


def inventory_valuation(products=None):
    """
    On-hand quantity times the latest movement unit_cost per product.
    Intended as a starting point for valuation/profit reports.
    """
    qs = products if products is not None else Product.objects.filter(active=True)
    total = Decimal('0.00')
    for product in qs:
        qty = current_stock(product)
        if qty <= 0:
            continue
        latest = (
            StockMovement.objects.filter(product=product, unit_cost__gt=0)
            .order_by('-movement_date', '-id')
            .first()
        )
        cost = latest.unit_cost if latest else Decimal('0.00')
        total += (qty * cost).quantize(Decimal('0.01'))
    return total


@transaction.atomic
def reverse_document(reference_type, reference_id):
    if reference_id is None:
        return 0
    deleted, _ = StockMovement.objects.filter(
        reference_type=reference_type,
        reference_id=reference_id,
    ).delete()
    return deleted


def _aware_datetime(value):
    if value is None:
        return timezone.now()
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value
    combined = datetime.combine(value, time.min)
    return timezone.make_aware(combined, timezone.get_current_timezone())


def _create_movement(*, product, movement_type, quantity, reference_type, reference_id,
                     line_id, unit_cost, movement_date, notes, created_by):
    return StockMovement.objects.create(
        product=product,
        movement_type=movement_type,
        quantity=quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        line_id=line_id,
        unit_cost=unit_cost or Decimal('0.00'),
        movement_date=_aware_datetime(movement_date),
        notes=notes,
        created_by=created_by,
    )


def _is_posted(document):
    return getattr(document, 'status', None) == PostingStatus.POSTED


def _required_base_by_product(items):
    required = defaultdict(lambda: Decimal('0.0000'))
    products = {}
    for item in items:
        product = item.product_unit.product
        required[product.pk] += item.base_quantity
        products[product.pk] = product
    return required, products


def assert_sale_stock_available(sale):
    if allow_negative_stock():
        return
    items = sale.items.select_related('product_unit__product')
    required, products = _required_base_by_product(items)
    shortages = []
    for product_id, need in required.items():
        available = current_stock(
            product_id,
            exclude_reference=(StockMovement.ReferenceType.SALE, sale.pk),
        )
        if need > available:
            product = products[product_id]
            shortages.append(
                f'{product.sku}: need {need} {product.base_unit}, available {available}'
            )
    if shortages:
        raise InsufficientStock('Not enough stock. ' + '; '.join(shortages))


@transaction.atomic
def sync_purchase_stock(purchase, user=None):
    """Replace purchase IN movements so re-saving never duplicates."""
    reverse_document(StockMovement.ReferenceType.PURCHASE, purchase.pk)
    if not _is_posted(purchase):
        return []
    user = user or purchase.created_by
    created = []
    items = purchase.items.select_related('product_unit__product', 'product_unit')
    for item in items:
        conversion = item.product_unit.conversion_to_base
        created.append(_create_movement(
            product=item.product_unit.product,
            movement_type=StockMovement.MovementType.IN,
            quantity=item.base_quantity,
            reference_type=StockMovement.ReferenceType.PURCHASE,
            reference_id=purchase.pk,
            line_id=item.pk,
            unit_cost=cost_per_base_unit(item.unit_price, conversion),
            movement_date=purchase.purchase_date,
            notes=f'Purchase {purchase.invoice_number} line {item.pk}',
            created_by=user,
        ))
    return created


@transaction.atomic
def sync_sale_stock(sale, user=None, *, validate=True):
    """Replace sale OUT movements. POS and admin both use this."""
    if _is_posted(sale) and validate:
        assert_sale_stock_available(sale)
    reverse_document(StockMovement.ReferenceType.SALE, sale.pk)
    if not _is_posted(sale):
        return []
    user = user or sale.cashier
    created = []
    items = sale.items.select_related('product_unit__product', 'product_unit')
    for item in items:
        conversion = item.product_unit.conversion_to_base
        created.append(_create_movement(
            product=item.product_unit.product,
            movement_type=StockMovement.MovementType.OUT,
            quantity=item.base_quantity,
            reference_type=StockMovement.ReferenceType.SALE,
            reference_id=sale.pk,
            line_id=item.pk,
            unit_cost=cost_per_base_unit(item.product_unit.purchase_price, conversion),
            movement_date=sale.created_at,
            notes=f'Sale {sale.invoice_number} line {item.pk}',
            created_by=user,
        ))
    return created


@transaction.atomic
def sync_adjustment_stock(adjustment, user=None):
    reverse_document(StockMovement.ReferenceType.ADJUSTMENT, adjustment.pk)
    if not _is_posted(adjustment):
        return []
    if not allow_negative_stock():
        items = adjustment.items.select_related('product_unit__product', 'product_unit')
        required, products = defaultdict(lambda: Decimal('0.0000')), {}
        for item in items:
            if item.direction != item.Direction.DECREASE:
                continue
            product = item.product_unit.product
            required[product.pk] += item.base_quantity
            products[product.pk] = product
        shortages = []
        for product_id, need in required.items():
            available = current_stock(
                product_id,
                exclude_reference=(StockMovement.ReferenceType.ADJUSTMENT, adjustment.pk),
            )
            if need > available:
                product = products[product_id]
                shortages.append(
                    f'{product.sku}: need to remove {need}, available {available}'
                )
        if shortages:
            raise InsufficientStock('Not enough stock to decrease. ' + '; '.join(shortages))

    user = user or adjustment.created_by
    created = []
    items = adjustment.items.select_related('product_unit__product', 'product_unit')
    for item in items:
        signed_qty = item.base_quantity
        if item.direction == item.Direction.DECREASE:
            signed_qty = -item.base_quantity
        created.append(_create_movement(
            product=item.product_unit.product,
            movement_type=StockMovement.MovementType.ADJUSTMENT,
            quantity=signed_qty,
            reference_type=StockMovement.ReferenceType.ADJUSTMENT,
            reference_id=adjustment.pk,
            line_id=item.pk,
            unit_cost=item.unit_cost,
            movement_date=adjustment.created_at,
            notes=f'Adjustment {adjustment.pk} {item.direction} line {item.pk}',
            created_by=user,
        ))
    return created
