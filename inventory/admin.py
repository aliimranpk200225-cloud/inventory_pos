from django.contrib import admin
from django.db import transaction
from django.forms.widgets import Script
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import path

from inventory.models import PostingStatus
from inventory.stock import annotate_current_stock, sync_adjustment_stock, sync_purchase_stock

from .forms import PurchaseItemForm

from .models import (
    Category,
    Product,
    ProductUnit,
    Purchase,
    PurchaseItem,
    StockAdjustment,
    StockAdjustmentItem,
    StockMovement,
    Supplier,
    Unit,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'abbreviation')
    search_fields = ('name', 'abbreviation')


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email')
    search_fields = ('name', 'phone', 'email')


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    form = PurchaseItemForm
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


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = (
        'invoice_number',
        'supplier',
        'purchase_date',
        'total',
        'paid_amount',
        'due_amount',
        'payment_status',
        'status',
        'created_by',
    )
    list_filter = ('status', 'payment_status', 'purchase_date', 'supplier')
    search_fields = ('invoice_number', 'supplier__name')
    autocomplete_fields = ('supplier',)
    exclude = ('created_by',)
    readonly_fields = (
        'applied_discount',
        'total',
        'due_amount',
        'payment_status',
        'created_at',
        'updated_at',
    )
    date_hierarchy = 'purchase_date'
    inlines = (PurchaseItemInline,)

    class Media:
        js = [
            'admin/js/jquery.init.js',
            Script('inventory/js/purchase_item_prefill.js', defer=True),
        ]

    def get_changeform_initial_data(self, request):
        return {'status': PostingStatus.POSTED}

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        with transaction.atomic():
            return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        purchase = form.instance
        purchase.refresh_from_db()
        sync_purchase_stock(purchase, request.user)


class ProductUnitInline(admin.TabularInline):
    model = ProductUnit
    extra = 1
    autocomplete_fields = ('unit',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'sku',
        'name',
        'category',
        'brand',
        'base_unit',
        'min_stock',
        'stock_on_hand',
        'active',
    )
    list_filter = ('active', 'category', 'brand')
    search_fields = ('sku', 'name', 'brand', 'product_units__barcode')
    list_editable = ('active',)
    autocomplete_fields = ('category', 'base_unit')
    inlines = (ProductUnitInline,)

    def get_queryset(self, request):
        return annotate_current_stock(super().get_queryset(request))

    @admin.display(description='On hand')
    def stock_on_hand(self, obj):
        value = getattr(obj, 'stock_on_hand', None)
        if value is None:
            return obj.current_stock()
        return value


@admin.register(ProductUnit)
class ProductUnitAdmin(admin.ModelAdmin):
    list_display = (
        'product',
        'unit',
        'conversion_to_base',
        'purchase_price',
        'retail_price',
        'wholesale_price',
        'barcode',
    )
    list_filter = ('unit',)
    search_fields = ('product__sku', 'product__name', 'barcode')
    autocomplete_fields = ('product', 'unit')

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path(
                '<int:object_id>/pricing/',
                self.admin_site.admin_view(self.pricing_view),
                name='inventory_productunit_pricing',
            ),
        ]
        return extra + urls

    def pricing_view(self, request, object_id):
        unit = get_object_or_404(
            ProductUnit.objects.select_related('product', 'unit'),
            pk=object_id,
        )
        return JsonResponse({
            'purchase_price': str(unit.purchase_price),
            'retail_price': str(unit.retail_price),
            'wholesale_price': str(unit.wholesale_price),
            'conversion_to_base': str(unit.conversion_to_base),
            'sku': unit.product.sku,
            'unit': unit.unit.abbreviation,
        })


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        'movement_date',
        'product',
        'movement_type',
        'quantity',
        'unit_cost',
        'reference_type',
        'reference_id',
        'line_id',
        'created_by',
    )
    list_filter = ('movement_type', 'reference_type', 'movement_date')
    search_fields = ('product__sku', 'product__name', 'notes')
    autocomplete_fields = ('product',)
    date_hierarchy = 'movement_date'
    readonly_fields = (
        'product',
        'movement_type',
        'quantity',
        'reference_type',
        'reference_id',
        'line_id',
        'unit_cost',
        'movement_date',
        'notes',
        'created_by',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class StockAdjustmentItemInline(admin.TabularInline):
    model = StockAdjustmentItem
    extra = 1
    autocomplete_fields = ('product_unit',)
    fields = ('product_unit', 'quantity', 'direction', 'unit_cost', 'base_quantity')
    readonly_fields = ('base_quantity',)


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'reason', 'status', 'created_by', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('reason', 'notes')
    exclude = ('created_by',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = (StockAdjustmentItemInline,)

    def get_changeform_initial_data(self, request):
        return {'status': PostingStatus.POSTED}

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        with transaction.atomic():
            return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        adjustment = form.instance
        adjustment.refresh_from_db()
        sync_adjustment_stock(adjustment, request.user)
