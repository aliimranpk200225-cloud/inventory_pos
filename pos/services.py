from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from inventory.models import PostingStatus, ProductUnit
from inventory.stock import InsufficientStock, sync_sale_stock

from .models import Customer, Sale, SaleItem
from .sessions import SessionError, get_open_session


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


def _payment_method(value):
    method = value or Sale.PaymentMethod.CASH
    if method not in Sale.PaymentMethod.values:
        raise CheckoutError('Invalid payment method.')
    return method


def _discount_type(value):
    if value in ('fixed', 'percent', '', None):
        return value or 'fixed'
    raise CheckoutError('Discount must be fixed or percent.')


def _require_open_session(user):
    session = get_open_session(user)
    if session is None:
        raise CheckoutError('Open a POS session before making sales.')
    return session


def _get_draft_for_update(user, session, payload):
    sale_id = payload.get('sale_id')
    if not sale_id:
        return None
    sale = Sale.objects.filter(pk=sale_id, cashier=user, cash_session=session).first()
    if sale is None:
        raise CheckoutError('That draft order was not found.')
    if sale.status != PostingStatus.DRAFT:
        raise CheckoutError('Only draft orders can be edited.')
    if not session.is_open:
        raise CheckoutError('This POS session is closed.')
    return sale


def _replace_items(sale, items_data):
    sale.items.all().delete()
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
    return subtotal


def _apply_header(sale, user, session, payload, customer):
    customer_data = payload.get('customer') or {}
    sale.customer = customer
    sale.customer_name = (
        customer_data.get('name') or (customer.name if customer else '') or 'Walk-in'
    ).strip()
    sale.customer_phone = (
        customer_data.get('phone') or (customer.phone if customer else '')
    ).strip()
    sale.cashier = user
    sale.cash_session = session
    sale.payment_method = _payment_method(payload.get('payment_method'))
    sale.discount_type = _discount_type(payload.get('discount_type'))
    sale.discount_value = _money(payload.get('discount_value'))
    sale.tax = _money(payload.get('tax'))
    sale.notes = (payload.get('notes') or '').strip()


@transaction.atomic
def save_sale(user, payload, *, as_draft=False):
    items_data = payload.get('items') or []
    if not items_data:
        raise CheckoutError('Add at least one item.')

    session = _require_open_session(user)
    customer_data = payload.get('customer') or {}
    customer = _get_or_create_customer(customer_data)
    sale = _get_draft_for_update(user, session, payload) or Sale(cashier=user, cash_session=session)
    _apply_header(sale, user, session, payload, customer)
    sale.status = PostingStatus.DRAFT if as_draft else PostingStatus.POSTED
    if as_draft:
        sale.paid_amount = _money(payload.get('paid_amount'), default='0')
    else:
        paid = payload.get('paid_amount')
        sale.paid_amount = _money('0' if paid in (None, '') else paid)
    sale.save()

    subtotal = _replace_items(sale, items_data)
    sale.subtotal = subtotal
    if not as_draft and payload.get('paid_amount') in (None, ''):
        sale.paid_amount = Decimal('0')
        sale.save()
        sale.paid_amount = sale.total
    sale.save()

    if as_draft:
        return sale

    try:
        sync_sale_stock(sale, user, validate=True)
    except InsufficientStock as exc:
        raise CheckoutError('; '.join(exc.messages) if getattr(exc, 'messages', None) else str(exc)) from exc
    except ValidationError as exc:
        raise CheckoutError('; '.join(exc.messages) if getattr(exc, 'messages', None) else str(exc)) from exc
    return sale


def checkout(user, payload):
    return save_sale(user, payload, as_draft=False)


def save_draft(user, payload):
    return save_sale(user, payload, as_draft=True)


@transaction.atomic
def cancel_sale(sale, user):
    if sale.cashier_id != user.id:
        raise CheckoutError('You can only cancel your own orders.')
    session = sale.cash_session
    if session is None or not session.is_open:
        raise CheckoutError('Orders on a closed session cannot be cancelled here.')
    if sale.status == PostingStatus.CANCELLED:
        raise CheckoutError('This order is already cancelled.')
    sale.status = PostingStatus.CANCELLED
    sale.save(update_fields=['status', 'updated_at'])
    try:
        sync_sale_stock(sale, user, validate=False)
    except (InsufficientStock, ValidationError, SessionError) as exc:
        raise CheckoutError(str(exc)) from exc
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
