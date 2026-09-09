import json
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from inventory.models import PostingStatus, Product, ProductUnit
from inventory.stock import (
    annotate_current_stock,
    classify_stock,
    format_quantity,
)

from .forms import CashMovementForm, ClosingCashForm, OpeningCashForm
from .models import CashMovement, CashSession, Customer, Sale
from .services import CheckoutError, cancel_sale, checkout, save_draft
from .sessions import (
    SessionError,
    add_cash_movement,
    close_session,
    compute_totals,
    display_totals,
    get_open_session,
    open_session,
)


def _wants_json(request):
    content_type = request.headers.get('Content-Type', '')
    accept = request.headers.get('Accept', '')
    return 'application/json' in content_type or 'application/json' in accept


def require_open_session(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        session = get_open_session(request.user)
        if session is None:
            if _wants_json(request):
                return JsonResponse({'error': 'Open a POS session first.'}, status=400)
            messages.info(request, 'Enter opening cash to start today\'s POS session.')
            return redirect('pos:session_open')
        request.cash_session = session
        return view(request, *args, **kwargs)
    return wrapped


def _previous_sessions(user, limit=10):
    return (
        CashSession.objects.filter(cashier=user, status=CashSession.Status.CLOSED)
        .select_related('cashier')[:limit]
    )


def _draft_payload(sale):
    items = []
    units = [item.product_unit for item in sale.items.select_related(
        'product_unit__product__base_unit',
        'product_unit__unit',
        'product_unit__product__category',
    )]
    stock_by_product = {
        product.pk: product.stock_on_hand
        for product in annotate_current_stock(
            Product.objects.filter(pk__in={unit.product_id for unit in units})
        )
    } if units else {}
    for item in sale.items.all():
        unit = item.product_unit
        on_hand = stock_by_product.get(unit.product_id) or 0
        items.append({
            'product_unit_id': unit.pk,
            'sku': unit.product.sku,
            'name': unit.product.name,
            'unit': unit.unit.abbreviation,
            'base_unit': unit.product.base_unit.abbreviation,
            'quantity': format_quantity(item.quantity),
            'unit_price': str(item.unit_price),
            'discount_type': item.discount_type,
            'discount_value': str(item.discount_value),
            'conversion_to_base': str(unit.conversion_to_base),
            'stock_on_hand': format_quantity(on_hand),
            'stock_in_unit': format_quantity(on_hand / (unit.conversion_to_base or Decimal('1'))),
            'stock_status': classify_stock(on_hand, unit.product.min_stock),
        })
    return {
        'sale_id': sale.pk,
        'invoice_number': sale.invoice_number,
        'customer_name': sale.customer_name,
        'customer_phone': sale.customer_phone,
        'customer_email': sale.customer.email if sale.customer else '',
        'customer_address': sale.customer.address if sale.customer else '',
        'discount_type': sale.discount_type,
        'discount_value': str(sale.discount_value),
        'tax': str(sale.tax),
        'payment_method': sale.payment_method,
        'paid_amount': str(sale.paid_amount),
        'items': items,
    }


@login_required
def home(request):
    session = get_open_session(request.user)
    return render(request, 'pos/home.html', {
        'open_session': session,
        'previous_sessions': _previous_sessions(request.user),
    })


@login_required
def enter(request):
    if get_open_session(request.user):
        return redirect('pos:day')
    return redirect('pos:session_open')


@login_required
@require_http_methods(['GET', 'POST'])
def session_open(request):
    existing = get_open_session(request.user)
    if existing:
        return redirect('pos:day')
    form = OpeningCashForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            open_session(request.user, form.cleaned_data['amount'])
        except SessionError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, 'POS session opened.')
            return redirect('pos:day')
    return render(request, 'pos/session_open.html', {'form': form})


@login_required
@require_open_session
def day(request):
    session = request.cash_session
    totals = compute_totals(session)
    recent_completed = session.sales.filter(status=PostingStatus.POSTED)[:8]
    drafts = session.sales.filter(status=PostingStatus.DRAFT)[:8]
    return render(request, 'pos/day.html', {
        'session': session,
        'totals': totals,
        'recent_completed': recent_completed,
        'drafts': drafts,
        'previous_sessions': _previous_sessions(request.user, limit=5),
    })


@login_required
@require_open_session
def counter(request, sale_id=None):
    session = request.cash_session
    totals = compute_totals(session)
    draft = None
    if sale_id is not None:
        sale = get_object_or_404(Sale, pk=sale_id, cashier=request.user, cash_session=session)
        if sale.status != PostingStatus.DRAFT:
            messages.error(request, 'Only draft orders can be reopened.')
            return redirect('pos:orders')
        draft = _draft_payload(sale)
    recent = session.sales.filter(status=PostingStatus.POSTED).select_related('customer')[:8]
    return render(request, 'pos/counter.html', {
        'recent_sales': recent,
        'allow_negative_stock': getattr(settings, 'INVENTORY_ALLOW_NEGATIVE_STOCK', False),
        'session': session,
        'totals': totals,
        'draft': draft,
    })


@login_required
@require_open_session
def orders(request):
    session = request.cash_session
    status = (request.GET.get('status') or '').strip()
    sales = session.sales.select_related('customer').prefetch_related('items')
    if status in {PostingStatus.DRAFT, PostingStatus.POSTED, PostingStatus.CANCELLED}:
        sales = sales.filter(status=status)
    return render(request, 'pos/orders.html', {
        'session': session,
        'sales': sales[:100],
        'status': status,
        'totals': compute_totals(session),
    })


@login_required
@require_open_session
@require_POST
def order_cancel(request, sale_id):
    sale = get_object_or_404(Sale, pk=sale_id, cashier=request.user, cash_session=request.cash_session)
    try:
        cancel_sale(sale, request.user)
    except CheckoutError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'{sale.invoice_number} cancelled.')
    return redirect(request.POST.get('next') or reverse('pos:orders'))


@login_required
@require_GET
def product_search(request):
    query = (request.GET.get('q') or '').strip()
    units = ProductUnit.objects.select_related(
        'product',
        'unit',
        'product__category',
        'product__base_unit',
    ).filter(
        product__active=True,
    )
    if query:
        units = units.filter(
            Q(product__name__icontains=query)
            | Q(product__sku__icontains=query)
            | Q(product__brand__icontains=query)
            | Q(barcode__icontains=query)
        )
    units = list(units[:30])
    stock_by_product = {
        product.pk: product.stock_on_hand
        for product in annotate_current_stock(
            Product.objects.filter(pk__in={unit.product_id for unit in units})
        )
    }
    results = []
    for unit in units:
        on_hand = stock_by_product.get(unit.product_id) or 0
        conversion = unit.conversion_to_base or Decimal('1')
        if conversion <= 0:
            conversion = Decimal('1')
        status = classify_stock(on_hand, unit.product.min_stock)
        results.append({
            'id': unit.pk,
            'sku': unit.product.sku,
            'name': unit.product.name,
            'brand': unit.product.brand,
            'category': unit.product.category.name,
            'unit': unit.unit.abbreviation,
            'base_unit': unit.product.base_unit.abbreviation,
            'barcode': unit.barcode or '',
            'retail_price': str(unit.retail_price),
            'wholesale_price': str(unit.wholesale_price),
            'conversion_to_base': str(conversion),
            'stock_on_hand': format_quantity(on_hand),
            'stock_in_unit': format_quantity(on_hand / conversion),
            'min_stock': format_quantity(unit.product.min_stock),
            'stock_status': status,
        })
    return JsonResponse({'results': results})


@login_required
@require_GET
def customer_search(request):
    phone = (request.GET.get('phone') or '').strip()
    if not phone:
        return JsonResponse({'customer': None})
    customer = Customer.objects.filter(phone=phone).first()
    if customer is None:
        return JsonResponse({'customer': None})
    return JsonResponse({
        'customer': {
            'id': customer.pk,
            'name': customer.name,
            'phone': customer.phone,
            'email': customer.email,
            'address': customer.address,
        },
    })


def _json_payload(request):
    try:
        return json.loads(request.body.decode() or '{}')
    except json.JSONDecodeError as exc:
        raise CheckoutError('Invalid request.') from exc


@login_required
@require_open_session
@require_POST
def checkout_view(request):
    try:
        sale = checkout(request.user, _json_payload(request))
    except CheckoutError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({
        'invoice_number': sale.invoice_number,
        'invoice_url': reverse('pos:invoice', args=[sale.pk]),
        'total': str(sale.total),
    })


@login_required
@require_open_session
@require_POST
def draft_view(request):
    try:
        sale = save_draft(request.user, _json_payload(request))
    except CheckoutError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({
        'invoice_number': sale.invoice_number,
        'sale_id': sale.pk,
        'status': sale.status,
        'day_url': reverse('pos:day'),
        'edit_url': reverse('pos:counter_edit', args=[sale.pk]),
    })


@login_required
def invoice(request, pk):
    sale = get_object_or_404(
        Sale.objects.select_related('customer', 'cashier', 'cash_session').prefetch_related(
            'items__product_unit__product',
            'items__product_unit__unit',
        ),
        pk=pk,
    )
    if sale.cashier_id != request.user.id and not request.user.is_staff:
        messages.error(request, 'You cannot view that invoice.')
        return redirect('pos:home')
    return render(request, 'pos/invoice.html', {'sale': sale})


@login_required
@require_open_session
@require_http_methods(['GET', 'POST'])
def cash_in(request):
    return _cash_movement_page(
        request,
        title='Cash in',
        default_type=CashMovement.MovementType.CASH_IN,
        show_type=False,
        show_payment_method=False,
    )


@login_required
@require_open_session
@require_http_methods(['GET', 'POST'])
def cash_out(request):
    return _cash_movement_page(
        request,
        title='Cash out / expense',
        default_type=CashMovement.MovementType.CASH_OUT,
        show_type=True,
        show_payment_method=False,
    )


@login_required
@require_open_session
@require_http_methods(['GET', 'POST'])
def refund(request):
    return _cash_movement_page(
        request,
        title='Record refund',
        default_type=CashMovement.MovementType.REFUND,
        show_type=False,
        show_payment_method=True,
    )


def _cash_movement_page(request, *, title, default_type, show_type, show_payment_method):
    session = request.cash_session
    form = CashMovementForm(request.POST or None, initial={'movement_type': default_type})
    if request.method == 'POST' and form.is_valid():
        movement_type = default_type
        if show_type and form.cleaned_data.get('movement_type'):
            movement_type = form.cleaned_data['movement_type']
        payment_method = Sale.PaymentMethod.CASH
        if show_payment_method and form.cleaned_data.get('payment_method'):
            payment_method = form.cleaned_data['payment_method']
        try:
            add_cash_movement(
                session,
                movement_type=movement_type,
                amount=form.cleaned_data['amount'],
                user=request.user,
                reason=form.cleaned_data.get('reason') or '',
                payment_method=payment_method,
            )
        except SessionError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f'{title} recorded.')
            return redirect('pos:day')
    return render(request, 'pos/cash_movement.html', {
        'form': form,
        'title': title,
        'session': session,
        'show_type': show_type,
        'show_payment_method': show_payment_method,
        'totals': compute_totals(session),
    })


@login_required
@require_open_session
@require_http_methods(['GET', 'POST'])
def session_close(request):
    session = request.cash_session
    totals = compute_totals(session)
    form = ClosingCashForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            close_session(session, form.cleaned_data['amount'])
        except SessionError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, 'POS session closed.')
            return redirect('pos:session_detail', pk=session.pk)
    return render(request, 'pos/session_close.html', {
        'session': session,
        'totals': totals,
        'form': form,
    })


@login_required
def session_list(request):
    sessions = CashSession.objects.filter(cashier=request.user).select_related('cashier')
    return render(request, 'pos/session_list.html', {'sessions': sessions[:60]})


@login_required
def session_detail(request, pk):
    session = get_object_or_404(CashSession.objects.select_related('cashier'), pk=pk)
    if session.cashier_id != request.user.id and not request.user.is_staff:
        messages.error(request, 'You cannot view that POS day.')
        return redirect('pos:home')
    totals = display_totals(session)
    sales = session.sales.select_related('customer').order_by('created_at')
    movements = session.movements.select_related('created_by', 'sale')
    return render(request, 'pos/session_detail.html', {
        'session': session,
        'totals': totals,
        'sales': sales,
        'movements': movements,
    })
