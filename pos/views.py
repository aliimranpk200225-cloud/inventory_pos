import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from inventory.models import Product, ProductUnit
from inventory.stock import (
    annotate_current_stock,
    classify_stock,
    format_quantity,
)

from .models import Customer, Sale
from .services import CheckoutError, checkout


@login_required
def counter(request):
    recent = (
        Sale.objects.select_related('customer')
        .prefetch_related('items')[:8]
    )
    return render(request, 'pos/counter.html', {
        'recent_sales': recent,
        'allow_negative_stock': getattr(settings, 'INVENTORY_ALLOW_NEGATIVE_STOCK', False),
    })


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
        conversion = unit.conversion_to_base or 1
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
