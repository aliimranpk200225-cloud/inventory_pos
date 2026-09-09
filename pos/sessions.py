from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from inventory.models import PostingStatus

from .models import CashMovement, CashSession, Sale


class SessionError(ValueError):
    pass


def _money(value):
    return (value or Decimal('0')).quantize(Decimal('0.01'))


def get_open_session(user):
    return (
        CashSession.objects.filter(cashier=user, status=CashSession.Status.OPEN)
        .order_by('-opened_at')
        .first()
    )


def session_sales(session):
    return session.sales.all()


def compute_totals(session):
    """Live totals from posted sales and cash movements. Opening cash is not a sale."""
    posted = session.sales.filter(status=PostingStatus.POSTED)
    sales_by_method = {
        row['payment_method']: _money(row['total'])
        for row in posted.values('payment_method').annotate(total=Sum('total'))
    }
    cash_sales = sales_by_method.get(Sale.PaymentMethod.CASH, Decimal('0.00'))
    card_sales = sales_by_method.get(Sale.PaymentMethod.CARD, Decimal('0.00'))
    bank_sales = sales_by_method.get(Sale.PaymentMethod.BANK, Decimal('0.00'))
    other_sales = sales_by_method.get(Sale.PaymentMethod.OTHER, Decimal('0.00'))

    movements = session.movements.values('movement_type', 'payment_method').annotate(total=Sum('amount'))
    cash_in = Decimal('0.00')
    cash_out = Decimal('0.00')
    expenses = Decimal('0.00')
    refunds = Decimal('0.00')
    cash_refunds = Decimal('0.00')
    for row in movements:
        amount = _money(row['total'])
        mtype = row['movement_type']
        if mtype == CashMovement.MovementType.CASH_IN:
            cash_in += amount
        elif mtype == CashMovement.MovementType.CASH_OUT:
            cash_out += amount
        elif mtype == CashMovement.MovementType.EXPENSE:
            expenses += amount
        elif mtype == CashMovement.MovementType.REFUND:
            refunds += amount
            if row['payment_method'] == Sale.PaymentMethod.CASH:
                cash_refunds += amount

    counts = session.sales.aggregate(
        completed=Count('id', filter=Q(status=PostingStatus.POSTED)),
        cancelled=Count('id', filter=Q(status=PostingStatus.CANCELLED)),
        drafts=Count('id', filter=Q(status=PostingStatus.DRAFT)),
        orders=Count('id'),
    )
    opening = _money(session.opening_cash)
    expected = opening + cash_sales + cash_in - cash_refunds - cash_out - expenses
    return {
        'opening_cash': opening,
        'cash_sales': cash_sales,
        'card_sales': card_sales,
        'bank_sales': bank_sales,
        'other_sales': other_sales,
        'total_sales': cash_sales + card_sales + bank_sales + other_sales,
        'refunds': refunds,
        'cash_refunds': cash_refunds,
        'cash_in': cash_in,
        'cash_out': cash_out,
        'expenses': expenses,
        'expected_closing_cash': expected,
        'completed_orders': counts['completed'] or 0,
        'cancelled_orders': counts['cancelled'] or 0,
        'draft_orders': counts['drafts'] or 0,
        'order_count': counts['orders'] or 0,
        'actual_closing_cash': session.actual_closing_cash,
        'cash_difference': session.cash_difference,
    }


def apply_totals_snapshot(session, totals=None):
    totals = totals or compute_totals(session)
    session.cash_sales = totals['cash_sales']
    session.card_sales = totals['card_sales']
    session.bank_sales = totals['bank_sales']
    session.other_sales = totals['other_sales']
    session.refunds = totals['refunds']
    session.cash_in = totals['cash_in']
    session.cash_out = totals['cash_out']
    session.expenses = totals['expenses']
    session.expected_closing_cash = totals['expected_closing_cash']
    session.completed_orders = totals['completed_orders']
    session.cancelled_orders = totals['cancelled_orders']
    session.draft_orders = totals['draft_orders']
    return totals


def display_totals(session):
    """Open sessions stay live; closed sessions use the stored close snapshot."""
    if session.status == CashSession.Status.CLOSED:
        return {
            'opening_cash': _money(session.opening_cash),
            'cash_sales': _money(session.cash_sales),
            'card_sales': _money(session.card_sales),
            'bank_sales': _money(session.bank_sales),
            'other_sales': _money(session.other_sales),
            'total_sales': session.total_sales,
            'refunds': _money(session.refunds),
            'cash_in': _money(session.cash_in),
            'cash_out': _money(session.cash_out),
            'expenses': _money(session.expenses),
            'expected_closing_cash': _money(session.expected_closing_cash),
            'actual_closing_cash': session.actual_closing_cash,
            'cash_difference': session.cash_difference,
            'completed_orders': session.completed_orders,
            'cancelled_orders': session.cancelled_orders,
            'draft_orders': session.draft_orders,
            'order_count': session.completed_orders + session.cancelled_orders + session.draft_orders,
        }
    return compute_totals(session)


@transaction.atomic
def open_session(user, opening_cash):
    if get_open_session(user):
        raise SessionError('You already have an open POS session.')
    opening_cash = _money(opening_cash)
    if opening_cash < 0:
        raise SessionError('Opening cash cannot be negative.')
    session = CashSession(
        cashier=user,
        opened_at=timezone.now(),
        opening_cash=opening_cash,
        expected_closing_cash=opening_cash,
        status=CashSession.Status.OPEN,
    )
    try:
        session.save()
    except IntegrityError as exc:
        raise SessionError('You already have an open POS session.') from exc
    return session


@transaction.atomic
def close_session(session, actual_cash):
    if session.status != CashSession.Status.OPEN:
        raise SessionError('This POS session is already closed.')
    actual_cash = _money(actual_cash)
    if actual_cash < 0:
        raise SessionError('Actual cash cannot be negative.')
    totals = apply_totals_snapshot(session)
    session.status = CashSession.Status.CLOSED
    session.closed_at = timezone.now()
    session.actual_closing_cash = actual_cash
    session.cash_difference = actual_cash - totals['expected_closing_cash']
    session.save()
    return session


@transaction.atomic
def add_cash_movement(session, *, movement_type, amount, user, reason='', payment_method=None, sale=None):
    if session.status != CashSession.Status.OPEN:
        raise SessionError('Cash movements can only be recorded on an open session.')
    movement = CashMovement.objects.create(
        session=session,
        movement_type=movement_type,
        amount=_money(amount),
        payment_method=payment_method or Sale.PaymentMethod.CASH,
        reason=(reason or '').strip(),
        sale=sale,
        created_by=user,
    )
    apply_totals_snapshot(session)
    session.save()
    return movement
