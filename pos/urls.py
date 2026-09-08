from django.urls import path

from . import views

app_name = 'pos'

urlpatterns = [
    path('', views.home, name='home'),
    path('enter/', views.enter, name='enter'),
    path('session/open/', views.session_open, name='session_open'),
    path('session/close/', views.session_close, name='session_close'),
    path('day/', views.day, name='day'),
    path('counter/', views.counter, name='counter'),
    path('counter/<int:sale_id>/', views.counter, name='counter_edit'),
    path('orders/', views.orders, name='orders'),
    path('orders/<int:sale_id>/cancel/', views.order_cancel, name='order_cancel'),
    path('cash/in/', views.cash_in, name='cash_in'),
    path('cash/out/', views.cash_out, name='cash_out'),
    path('cash/refund/', views.refund, name='refund'),
    path('sessions/', views.session_list, name='session_list'),
    path('sessions/<int:pk>/', views.session_detail, name='session_detail'),
    path('products/', views.product_search, name='product_search'),
    path('customers/', views.customer_search, name='customer_search'),
    path('checkout/', views.checkout_view, name='checkout'),
    path('draft/', views.draft_view, name='draft'),
    path('invoice/<int:pk>/', views.invoice, name='invoice'),
]
