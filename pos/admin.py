from django.contrib import admin
from django.db import transaction

from inventory.models import PostingStatus
from inventory.stock import sync_sale_stock

from .models import Customer, Sale, SaleItem


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email')
    search_fields = ('name', 'phone', 'email')


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1
    autocomplete_fields = ('product_unit',)
    fields = (
        'product_unit',
        'quantity',
        'unit_price',
        'discount_type',
        'discount_value',
        'tax',
        'total',
        'base_quantity',
    )
    readonly_fields = ('total', 'base_quantity')


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = (
        'invoice_number',
        'customer_name',
        'payment_method',
        'total',
        'payment_status',
        'status',
        'cashier',
        'created_at',
    )
    list_filter = ('status', 'payment_status', 'payment_method', 'created_at')
    search_fields = ('invoice_number', 'customer_name', 'customer_phone')
    autocomplete_fields = ('customer',)
    exclude = ('cashier',)
    readonly_fields = (
        'invoice_number',
        'applied_discount',
        'total',
        'due_amount',
        'payment_status',
        'created_at',
        'updated_at',
    )
    inlines = (SaleItemInline,)
    date_hierarchy = 'created_at'

    def get_changeform_initial_data(self, request):
        return {'status': PostingStatus.POSTED}

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        with transaction.atomic():
            return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.cashier = request.user
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        sale = form.instance
        sale.refresh_from_db()
        sync_sale_stock(sale, request.user)
