from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from inventory.models import (
    Category,
    PostingStatus,
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
from inventory.stock import (
    current_stock,
    sync_adjustment_stock,
    sync_purchase_stock,
    sync_sale_stock,
)
from pos.models import Sale, SaleItem
from pos.services import CheckoutError, checkout


User = get_user_model()


class StockLedgerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('staff', password='pass-12345', is_staff=True)
        self.category = Category.objects.create(name='Drinks')
        self.bottle = Unit.objects.create(name='Bottle', abbreviation='Btl')
        self.crate = Unit.objects.create(name='Crate', abbreviation='Crt')
        self.product = Product.objects.create(
            name='Cola',
            sku='COLA',
            category=self.category,
            base_unit=self.bottle,
            min_stock=10,
        )
        self.unit_bottle = ProductUnit.objects.create(
            product=self.product,
            unit=self.bottle,
            conversion_to_base=Decimal('1'),
            purchase_price=Decimal('10.00'),
            retail_price=Decimal('15.00'),
            wholesale_price=Decimal('12.00'),
        )
        self.unit_crate = ProductUnit.objects.create(
            product=self.product,
            unit=self.crate,
            conversion_to_base=Decimal('12'),
            purchase_price=Decimal('120.00'),
            retail_price=Decimal('180.00'),
            wholesale_price=Decimal('150.00'),
        )
        self.supplier = Supplier.objects.create(name='Bottler')

    def _purchase(self, lines, invoice='PO-1', **extra):
        purchase = Purchase.objects.create(
            supplier=self.supplier,
            invoice_number=invoice,
            purchase_date=date.today(),
            created_by=self.user,
            status=PostingStatus.POSTED,
            discount_type=extra.get('discount_type', 'fixed'),
            discount_value=extra.get('discount_value', 0),
        )
        for line in lines:
            PurchaseItem.objects.create(
                purchase=purchase,
                product_unit=line['unit'],
                quantity=line['qty'],
                unit_price=line.get('price', line['unit'].purchase_price),
                discount_type=line.get('discount_type', 'fixed'),
                discount_value=line.get('discount_value', 0),
            )
        sync_purchase_stock(purchase, self.user)
        return purchase

    def _sale(self, lines, **extra):
        sale = Sale.objects.create(
            cashier=self.user,
            customer_name='Walk-in',
            status=PostingStatus.POSTED,
            discount_type=extra.get('discount_type', 'fixed'),
            discount_value=extra.get('discount_value', 0),
        )
        for line in lines:
            SaleItem.objects.create(
                sale=sale,
                product_unit=line['unit'],
                quantity=line['qty'],
                unit_price=line.get('price', line['unit'].retail_price),
                discount_type=line.get('discount_type', 'fixed'),
                discount_value=line.get('discount_value', 0),
            )
        sync_sale_stock(sale, self.user)
        return sale

    def test_purchase_crates_converts_to_base_units(self):
        self._purchase([{'unit': self.unit_crate, 'qty': 5}])
        self.assertEqual(current_stock(self.product), Decimal('60.0000'))
        movement = StockMovement.objects.get(reference_type='purchase')
        self.assertEqual(movement.movement_type, StockMovement.MovementType.IN)
        self.assertEqual(movement.quantity, Decimal('60.0000'))
        self.assertEqual(movement.unit_cost, Decimal('10.00'))

    def test_sale_bottles_decreases_base_units(self):
        self._purchase([{'unit': self.unit_crate, 'qty': 5}])
        self._sale([{'unit': self.unit_bottle, 'qty': 3}])
        self.assertEqual(current_stock(self.product), Decimal('57.0000'))
        movement = StockMovement.objects.get(reference_type='sale')
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUT)
        self.assertEqual(movement.quantity, Decimal('3.0000'))

    def test_sale_crates_decreases_converted_base_units(self):
        self._purchase([{'unit': self.unit_crate, 'qty': 5}])
        self._sale([{'unit': self.unit_crate, 'qty': 2}])
        self.assertEqual(current_stock(self.product), Decimal('36.0000'))

    def test_multiple_items_on_one_purchase(self):
        self._purchase([
            {'unit': self.unit_crate, 'qty': 1},
            {'unit': self.unit_bottle, 'qty': 4},
        ])
        self.assertEqual(current_stock(self.product), Decimal('16.0000'))
        self.assertEqual(StockMovement.objects.filter(reference_type='purchase').count(), 2)

    def test_line_discount_does_not_change_stock_quantity(self):
        self._purchase([{
            'unit': self.unit_crate,
            'qty': 5,
            'discount_type': 'percent',
            'discount_value': 10,
        }])
        self.assertEqual(current_stock(self.product), Decimal('60.0000'))
        item = PurchaseItem.objects.get()
        self.assertGreater(item.applied_discount, 0)

    def test_invoice_discount_does_not_change_stock_quantity(self):
        purchase = self._purchase(
            [{'unit': self.unit_crate, 'qty': 5}],
            discount_type='fixed',
            discount_value=Decimal('50'),
        )
        purchase.subtotal = Decimal('600.00')
        purchase.save()
        sync_purchase_stock(purchase, self.user)
        self.assertEqual(current_stock(self.product), Decimal('60.0000'))
        self.assertEqual(purchase.applied_discount, Decimal('50.00'))

    def test_sale_discounts_do_not_change_stock_quantity(self):
        self._purchase([{'unit': self.unit_crate, 'qty': 5}])
        self._sale(
            [{'unit': self.unit_bottle, 'qty': 3, 'discount_type': 'percent', 'discount_value': 5}],
            discount_type='fixed',
            discount_value=10,
        )
        self.assertEqual(current_stock(self.product), Decimal('57.0000'))

    def test_editing_purchase_updates_stock(self):
        purchase = self._purchase([{'unit': self.unit_crate, 'qty': 5}], invoice='PO-EDIT')
        item = purchase.items.get()
        item.quantity = Decimal('2')
        item.save()
        sync_purchase_stock(purchase, self.user)
        self.assertEqual(current_stock(self.product), Decimal('24.0000'))
        self.assertEqual(StockMovement.objects.filter(reference_type='purchase').count(), 1)

    def test_editing_sale_updates_stock(self):
        self._purchase([{'unit': self.unit_crate, 'qty': 5}])
        sale = self._sale([{'unit': self.unit_bottle, 'qty': 3}])
        item = sale.items.get()
        item.quantity = Decimal('1')
        item.save()
        sync_sale_stock(sale, self.user)
        self.assertEqual(current_stock(self.product), Decimal('59.0000'))
        self.assertEqual(StockMovement.objects.filter(reference_type='sale').count(), 1)

    def test_deleting_purchase_reverses_stock(self):
        purchase = self._purchase([{'unit': self.unit_crate, 'qty': 5}])
        purchase.delete()
        self.assertEqual(current_stock(self.product), Decimal('0.0000'))
        self.assertFalse(StockMovement.objects.filter(reference_type='purchase').exists())

    def test_deleting_sale_reverses_stock(self):
        self._purchase([{'unit': self.unit_crate, 'qty': 5}])
        sale = self._sale([{'unit': self.unit_bottle, 'qty': 3}])
        sale.delete()
        self.assertEqual(current_stock(self.product), Decimal('60.0000'))
        self.assertFalse(StockMovement.objects.filter(reference_type='sale').exists())

    def test_selling_more_than_available_is_blocked(self):
        self._purchase([{'unit': self.unit_bottle, 'qty': 2}])
        with self.assertRaises(ValidationError):
            self._sale([{'unit': self.unit_bottle, 'qty': 3}])
        self.assertEqual(current_stock(self.product), Decimal('2.0000'))
        self.assertFalse(StockMovement.objects.filter(reference_type='sale').exists())

    def test_resaving_purchase_does_not_duplicate_movements(self):
        purchase = self._purchase([{'unit': self.unit_crate, 'qty': 5}])
        sync_purchase_stock(purchase, self.user)
        sync_purchase_stock(purchase, self.user)
        self.assertEqual(StockMovement.objects.filter(reference_type='purchase').count(), 1)
        self.assertEqual(current_stock(self.product), Decimal('60.0000'))

    def test_resaving_sale_does_not_duplicate_movements(self):
        self._purchase([{'unit': self.unit_crate, 'qty': 5}])
        sale = self._sale([{'unit': self.unit_bottle, 'qty': 3}])
        sync_sale_stock(sale, self.user)
        self.assertEqual(StockMovement.objects.filter(reference_type='sale').count(), 1)
        self.assertEqual(current_stock(self.product), Decimal('57.0000'))

    def test_draft_purchase_does_not_change_stock(self):
        purchase = Purchase.objects.create(
            supplier=self.supplier,
            invoice_number='PO-DRAFT',
            purchase_date=date.today(),
            created_by=self.user,
            status=PostingStatus.DRAFT,
        )
        PurchaseItem.objects.create(
            purchase=purchase,
            product_unit=self.unit_crate,
            quantity=5,
            unit_price=self.unit_crate.purchase_price,
        )
        sync_purchase_stock(purchase, self.user)
        self.assertEqual(current_stock(self.product), Decimal('0.0000'))

    def test_cancelled_sale_reverses_stock(self):
        self._purchase([{'unit': self.unit_crate, 'qty': 5}])
        sale = self._sale([{'unit': self.unit_bottle, 'qty': 3}])
        sale.status = PostingStatus.CANCELLED
        sale.save()
        sync_sale_stock(sale, self.user)
        self.assertEqual(current_stock(self.product), Decimal('60.0000'))

    def test_adjustment_increase_and_decrease(self):
        self._purchase([{'unit': self.unit_bottle, 'qty': 10}])
        increase = StockAdjustment.objects.create(
            reason='Found stock',
            status=PostingStatus.POSTED,
            created_by=self.user,
        )
        StockAdjustmentItem.objects.create(
            adjustment=increase,
            product_unit=self.unit_bottle,
            quantity=5,
            direction=StockAdjustmentItem.Direction.INCREASE,
        )
        sync_adjustment_stock(increase, self.user)
        self.assertEqual(current_stock(self.product), Decimal('15.0000'))
        movement = StockMovement.objects.get(reference_type='adjustment')
        self.assertEqual(movement.quantity, Decimal('5.0000'))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.ADJUSTMENT)

        decrease = StockAdjustment.objects.create(
            reason='Breakage',
            status=PostingStatus.POSTED,
            created_by=self.user,
        )
        StockAdjustmentItem.objects.create(
            adjustment=decrease,
            product_unit=self.unit_bottle,
            quantity=4,
            direction=StockAdjustmentItem.Direction.DECREASE,
        )
        sync_adjustment_stock(decrease, self.user)
        self.assertEqual(current_stock(self.product), Decimal('11.0000'))
        down = StockMovement.objects.get(reference_id=decrease.pk, reference_type='adjustment')
        self.assertEqual(down.quantity, Decimal('-4.0000'))

    def test_adjustment_decrease_blocked_when_insufficient(self):
        adjustment = StockAdjustment.objects.create(
            reason='Bad count',
            status=PostingStatus.POSTED,
            created_by=self.user,
        )
        StockAdjustmentItem.objects.create(
            adjustment=adjustment,
            product_unit=self.unit_bottle,
            quantity=1,
            direction=StockAdjustmentItem.Direction.DECREASE,
        )
        with self.assertRaises(ValidationError):
            sync_adjustment_stock(adjustment, self.user)

    def test_pos_checkout_posts_stock_and_blocks_oversell(self):
        self._purchase([{'unit': self.unit_crate, 'qty': 1}], invoice='PO-POS')
        sale = checkout(self.user, {
            'items': [{
                'product_unit_id': self.unit_bottle.pk,
                'quantity': '2',
                'unit_price': '15.00',
                'discount_type': 'fixed',
                'discount_value': '0',
            }],
            'customer': {'name': 'Ali', 'phone': '03001111111'},
            'discount_type': 'fixed',
            'discount_value': '0',
            'tax': '0',
            'paid_amount': '30',
            'payment_method': 'cash',
        })
        self.assertEqual(sale.status, PostingStatus.POSTED)
        self.assertEqual(current_stock(self.product), Decimal('10.0000'))
        with self.assertRaises(CheckoutError):
            checkout(self.user, {
                'items': [{
                    'product_unit_id': self.unit_bottle.pk,
                    'quantity': '11',
                    'unit_price': '15.00',
                }],
                'payment_method': 'cash',
                'paid_amount': '0',
            })
        self.assertEqual(current_stock(self.product), Decimal('10.0000'))

    @override_settings(INVENTORY_ALLOW_NEGATIVE_STOCK=True)
    def test_negative_stock_can_be_allowed(self):
        self._sale([{'unit': self.unit_bottle, 'qty': 3}])
        self.assertEqual(current_stock(self.product), Decimal('-3.0000'))
