import json

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from inventory.models import ProductUnit

from .models import Customer, Sale
from .services import CheckoutError, checkout


@login_required
def counter(request):
    recent = (
        Sale.objects.select_related('customer')
        .prefetch_related('items')[:8]
    )
    return render(request, 'pos/counter.html', {'recent_sales': recent})


@login_required
@require_GET
def product_search(request):
    query = (request.GET.get('q') or '').strip()
    units = ProductUnit.objects.select_related('product', 'unit', 'product__category').filter(
        product__active=True,
    )
    if query:
        units = units.filter(
            Q(product__name__icontains=query)
            | Q(product__sku__icontains=query)
            | Q(product__brand__icontains=query)
            | Q(barcode__icontains=query)
        )
    results = []
    for unit in units[:30]:
        results.append({
            'id': unit.pk,
            'sku': unit.product.sku,
            'name': unit.product.name,
            'brand': unit.product.brand,
            'category': unit.product.category.name,
            'unit': unit.unit.abbreviation,
            'barcode': unit.barcode or '',
            'retail_price': str(unit.retail_price),
            'wholesale_price': str(unit.wholesale_price),
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


@login_required
@require_POST
def checkout_view(request):
    try:
        payload = json.loads(request.body.decode() or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid request.'}, status=400)
    try:
        sale = checkout(request.user, payload)
    except CheckoutError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({
        'invoice_number': sale.invoice_number,
        'invoice_url': reverse('pos:invoice', args=[sale.pk]),
        'total': str(sale.total),
    })


@login_required
def invoice(request, pk):
    sale = get_object_or_404(
        Sale.objects.select_related('customer', 'cashier').prefetch_related(
            'items__product_unit__product',
            'items__product_unit__unit',
        ),
        pk=pk,
    )
    return render(request, 'pos/invoice.html', {'sale': sale})
