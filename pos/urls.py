from django.urls import path

from . import views

app_name = 'pos'

urlpatterns = [
    path('', views.counter, name='counter'),
    path('products/', views.product_search, name='product_search'),
    path('customers/', views.customer_search, name='customer_search'),
    path('checkout/', views.checkout_view, name='checkout'),
    path('invoice/<int:pk>/', views.invoice, name='invoice'),
]
