from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from inventory.models import PostingStatus, ProductUnit
from inventory.stock import InsufficientStock, sync_sale_stock

from .models import Customer, Sale, SaleItem


class CheckoutError(ValueError):
    pass


def _money(value, default='0'):
    if value in (None, ''):
        value = default
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError) as exc:
        raise CheckoutError('Invalid money value.') from exc


def _qty(value):
    try:
        qty = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise CheckoutError('Invalid quantity.') from exc
    if qty <= 0:
        raise CheckoutError('Quantity must be greater than zero.')
    return qty


def _discount_type(value):
    if value in ('fixed', 'percent', '', None):
        return value or 'fixed'
    raise CheckoutError('Discount must be fixed or percent.')


@transaction.atomic
def checkout(user, payload):
    items_data = payload.get('items') or []
    if not items_data:
        raise CheckoutError('Add at least one item.')

    customer_data = payload.get('customer') or {}
    customer = _get_or_create_customer(customer_data)

    sale = Sale(
        customer=customer,
        customer_name=(customer_data.get('name') or (customer.name if customer else '') or 'Walk-in').strip(),
        customer_phone=(customer_data.get('phone') or (customer.phone if customer else '')).strip(),
        cashier=user,
        payment_method=payload.get('payment_method') or Sale.PaymentMethod.CASH,
        discount_type=_discount_type(payload.get('discount_type')),
        discount_value=_money(payload.get('discount_value')),
        tax=_money(payload.get('tax')),
        paid_amount=_money(payload.get('paid_amount')),
        notes=(payload.get('notes') or '').strip(),
        status=PostingStatus.POSTED,
    )
    sale.save()

    subtotal = Decimal('0.00')
    for row in items_data:
        product_unit = ProductUnit.objects.select_related('product', 'unit').filter(
            pk=row.get('product_unit_id'),
            product__active=True,
        ).first()
        if product_unit is None:
            raise CheckoutError('One of the selected products was not found.')

        item = SaleItem(
            sale=sale,
            product_unit=product_unit,
            quantity=_qty(row.get('quantity')),
            unit_price=_money(row.get('unit_price'), default=str(product_unit.retail_price)),
            discount_type=_discount_type(row.get('discount_type')),
            discount_value=_money(row.get('discount_value')),
            tax=_money(row.get('tax')),
        )
        item.save()
        subtotal += item.total

    sale.subtotal = subtotal
    if payload.get('paid_amount') in (None, ''):
        sale.paid_amount = Decimal('0')
        sale.save()
        sale.paid_amount = sale.total
    sale.save()

    try:
        sync_sale_stock(sale, user, validate=True)
    except InsufficientStock as exc:
        raise CheckoutError('; '.join(exc.messages) if getattr(exc, 'messages', None) else str(exc)) from exc
    except ValidationError as exc:
        raise CheckoutError('; '.join(exc.messages) if getattr(exc, 'messages', None) else str(exc)) from exc
    return sale


def _get_or_create_customer(data):
    name = (data.get('name') or '').strip()
    phone = (data.get('phone') or '').strip()
    email = (data.get('email') or '').strip()
    address = (data.get('address') or '').strip()
    if not name and not phone:
        return None
    if phone:
        customer = Customer.objects.filter(phone=phone).first()
        if customer:
            if name:
                customer.name = name
            if email:
                customer.email = email
            if address:
                customer.address = address
            customer.save()
            return customer
    if not name:
        name = phone
    return Customer.objects.create(
        name=name,
        phone=phone,
        email=email,
        address=address,
    )
