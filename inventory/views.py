from django.shortcuts import render

from .models import Category, Product
from .stock import (
    annotate_current_stock,
    classify_stock,
    format_quantity,
    low_stock_products,
    out_of_stock_products,
)


def _with_status(products):
    for product in products:
        on_hand = getattr(product, 'stock_on_hand', 0)
        product.stock_status = classify_stock(on_hand, product.min_stock)
        product.stock_display = format_quantity(on_hand)
        product.min_display = format_quantity(product.min_stock)
    return products


def home(request):
    active_products = Product.objects.filter(active=True)
    products = _with_status(
        annotate_current_stock(
            active_products.select_related('category', 'base_unit')
        ).order_by('name')[:20]
    )
    alerts_out = _with_status(
        out_of_stock_products().select_related('category', 'base_unit').order_by('name')[:50]
    )
    alerts_low = _with_status(
        low_stock_products().select_related('category', 'base_unit').order_by('name')[:50]
    )
    return render(
        request,
        'home.html',
        {
            'products': products,
            'product_count': active_products.count(),
            'category_count': Category.objects.count(),
            'out_of_stock_count': out_of_stock_products().count(),
            'low_stock_count': low_stock_products().count(),
            'out_of_stock_products': alerts_out,
            'low_stock_products': alerts_low,
        },
    )
