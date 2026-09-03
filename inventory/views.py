from django.shortcuts import render

from .models import Category, Product


def home(request):
    active_products = Product.objects.filter(active=True)
    products = active_products.select_related('category', 'base_unit')[:20]
    return render(
        request,
        'home.html',
        {
            'products': products,
            'product_count': active_products.count(),
            'category_count': Category.objects.count(),
        },
    )
