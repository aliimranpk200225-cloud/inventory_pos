from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from inventory.models import Category, PostingStatus, Product, ProductUnit, Purchase, PurchaseItem, Supplier, Unit
from inventory.stock import current_stock

from pos.models import CashMovement, CashSession, Sale
from pos.services import CheckoutError, checkout, save_draft
from pos.sessions import (
    SessionError,
    add_cash_movement,
    close_session,
    compute_totals,
    get_open_session,
    open_session,
)

User = get_user_model()


class ProductSearchStockTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('cashier', password='pass-12345')
        category = Category.objects.create(name='Drinks')
        bottle = Unit.objects.create(name='Bottle', abbreviation='Btl')
        self.product = Product.objects.create(
            name='Cola',
            sku='COLA',
            category=category,
            base_unit=bottle,
            min_stock=10,
        )
        self.unit = ProductUnit.objects.create(
            product=self.product,
            unit=bottle,
            conversion_to_base=Decimal('1'),
            purchase_price=Decimal('10.00'),
            retail_price=Decimal('15.00'),
            wholesale_price=Decimal('12.00'),
        )
        self.client.force_login(self.user)

    def test_product_search_includes_out_of_stock_status(self):
        response = self.client.get('/pos/products/')
        self.assertEqual(response.status_code, 200)
        row = response.json()['results'][0]
        self.assertEqual(row['stock_status'], 'out')
        self.assertEqual(row['stock_on_hand'], '0')
        self.assertEqual(row['stock_in_unit'], '0')
        self.assertEqual(row['base_unit'], 'Btl')
        self.assertEqual(row['image_url'], '')
        self.assertFalse(self.product.image)

    def test_product_search_returns_image_url_when_uploaded(self):
        uploaded = SimpleUploadedFile(
            'cola.png',
            (
                b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
                b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f'
                b'\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
            ),
            content_type='image/png',
        )
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root, MEDIA_URL='/media/'):
                self.product.image.save('cola.png', uploaded, save=True)
                response = self.client.get('/pos/products/')
        row = response.json()['results'][0]
        self.assertTrue(row['image_url'])
        self.assertIn('cola', row['image_url'])

    def test_product_search_formats_converted_stock(self):
        carton = Unit.objects.create(name='Carton', abbreviation='crt')
        pack = ProductUnit.objects.create(
            product=self.product,
            unit=carton,
            conversion_to_base=Decimal('24'),
            purchase_price=Decimal('240.00'),
            retail_price=Decimal('1100.00'),
            wholesale_price=Decimal('1000.00'),
        )
        supplier = Supplier.objects.create(name='Bottler')
        purchase = Purchase.objects.create(
            supplier=supplier,
            invoice_number='PO-CONV',
            purchase_date=date.today(),
            created_by=self.user,
            status=PostingStatus.POSTED,
        )
        PurchaseItem.objects.create(
            purchase=purchase,
            product_unit=self.unit,
            quantity=Decimal('200'),
            unit_price=Decimal('10.00'),
        )
        from inventory.stock import sync_purchase_stock
        sync_purchase_stock(purchase, self.user)
        response = self.client.get('/pos/products/')
        rows = {row['id']: row for row in response.json()['results']}
        carton_row = rows[pack.pk]
        self.assertEqual(carton_row['unit'], 'crt')
        self.assertEqual(carton_row['retail_price'], '1100.00')
        self.assertEqual(carton_row['stock_on_hand'], '200')
        self.assertEqual(carton_row['stock_in_unit'], '8.33')
        self.assertNotIn('8.333333', carton_row['stock_in_unit'])
        self.assertEqual(carton_row['conversion_to_base'], '24.0000')
        bottle_row = rows[self.unit.pk]
        self.assertEqual(bottle_row['unit'], 'Btl')
        self.assertEqual(bottle_row['stock_on_hand'], '200')
        self.assertEqual(bottle_row['stock_in_unit'], '200')


class CashSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali', password='pass-12345', is_staff=True)
        self.other = User.objects.create_user('sara', password='pass-12345')
        category = Category.objects.create(name='Drinks')
        bottle = Unit.objects.create(name='Bottle', abbreviation='Btl')
        self.product = Product.objects.create(
            name='Cola',
            sku='COLA',
            category=category,
            base_unit=bottle,
            min_stock=0,
        )
        self.unit = ProductUnit.objects.create(
            product=self.product,
            unit=bottle,
            conversion_to_base=Decimal('1'),
            purchase_price=Decimal('10.00'),
            retail_price=Decimal('15.00'),
            wholesale_price=Decimal('12.00'),
        )
        supplier = Supplier.objects.create(name='Bottler')
        purchase = Purchase.objects.create(
            supplier=supplier,
            invoice_number='PO-CASH',
            purchase_date=date.today(),
            created_by=self.user,
            status=PostingStatus.POSTED,
        )
        PurchaseItem.objects.create(
            purchase=purchase,
            product_unit=self.unit,
            quantity=Decimal('100'),
            unit_price=Decimal('10.00'),
        )
        from inventory.stock import sync_purchase_stock
        sync_purchase_stock(purchase, self.user)
        self.client.force_login(self.user)

    def _sale(self, qty, payment='cash', as_draft=False, **extra):
        payload = {
            'items': [{
                'product_unit_id': self.unit.pk,
                'quantity': str(qty),
                'unit_price': '15.00',
            }],
            'payment_method': payment,
            'paid_amount': str(Decimal(qty) * Decimal('15')),
            **extra,
        }
        if as_draft:
            return save_draft(self.user, payload)
        return checkout(self.user, payload)

    def test_login_home_shows_pos_module(self):
        response = self.client.get('/pos/')
        self.assertContains(response, 'Select Module')
        self.assertContains(response, 'POS')

    def test_pos_requires_opening_cash(self):
        response = self.client.get('/pos/enter/', follow=True)
        self.assertContains(response, 'Opening cash')
        self.client.post('/pos/session/open/', {'amount': '10000'})
        session = get_open_session(self.user)
        self.assertEqual(session.opening_cash, Decimal('10000.00'))
        self.assertEqual(session.status, CashSession.Status.OPEN)
        self.assertEqual(session.cashier, self.user)
        self.assertIsNotNone(session.opened_at)
        response = self.client.get('/pos/day/')
        self.assertContains(response, '10,000.00')

    def test_day_draft_orders_badge_counts_open_session_drafts(self):
        open_session(self.user, Decimal('10000'))
        response = self.client.get('/pos/day/')
        self.assertContains(response, 'Draft orders')
        self.assertContains(response, reverse('pos:orders') + '?status=draft')
        self.assertNotContains(response, 'class="badge bg-danger"')

        draft = self._sale(1, as_draft=True)
        self._sale(1, payment='cash')
        response = self.client.get('/pos/day/')
        self.assertContains(response, 'class="badge bg-danger"')
        self.assertContains(response, 'aria-label="1 draft orders"')

        self._sale(1, as_draft=True)
        response = self.client.get('/pos/day/')
        self.assertContains(response, 'aria-label="2 draft orders"')

        checkout(self.user, {
            'sale_id': draft.pk,
            'items': [{
                'product_unit_id': self.unit.pk,
                'quantity': '1',
                'unit_price': '15.00',
            }],
            'payment_method': 'cash',
            'paid_amount': '15',
        })
        response = self.client.get('/pos/day/')
        self.assertContains(response, 'aria-label="1 draft orders"')

        open_session(self.other, Decimal('8000'))
        save_draft(self.other, {
            'items': [{
                'product_unit_id': self.unit.pk,
                'quantity': '1',
                'unit_price': '15.00',
            }],
            'payment_method': 'cash',
            'paid_amount': '0',
        })
        response = self.client.get('/pos/day/')
        self.assertContains(response, 'aria-label="1 draft orders"')

    def test_cannot_open_two_sessions(self):
        open_session(self.user, Decimal('10000'))
        with self.assertRaises(SessionError):
            open_session(self.user, Decimal('5000'))
        self.assertEqual(CashSession.objects.filter(cashier=self.user, status='open').count(), 1)

    def test_checkout_requires_open_session(self):
        with self.assertRaises(CheckoutError):
            checkout(self.user, {
                'items': [{'product_unit_id': self.unit.pk, 'quantity': '1', 'unit_price': '15'}],
                'payment_method': 'cash',
                'paid_amount': '15',
            })

    def test_sales_and_drafts_and_close(self):
        open_session(self.user, Decimal('10000'))
        cash_sale = self._sale(2, payment='cash')
        self.assertEqual(cash_sale.cash_session, get_open_session(self.user))
        self.assertEqual(cash_sale.status, PostingStatus.POSTED)
        draft = self._sale(1, as_draft=True)
        self.assertEqual(draft.status, PostingStatus.DRAFT)
        self.assertEqual(current_stock(self.product), Decimal('98.0000'))
        card_sale = self._sale(3, payment='card')
        session = get_open_session(self.user)
        totals = compute_totals(session)
        self.assertEqual(totals['opening_cash'], Decimal('10000.00'))
        self.assertEqual(totals['cash_sales'], Decimal('30.00'))
        self.assertEqual(totals['card_sales'], Decimal('45.00'))
        self.assertEqual(totals['total_sales'], Decimal('75.00'))
        self.assertEqual(totals['draft_orders'], 1)
        self.assertEqual(totals['completed_orders'], 2)
        self.assertEqual(totals['expected_closing_cash'], Decimal('10030.00'))
        add_cash_movement(
            session,
            movement_type=CashMovement.MovementType.CASH_IN,
            amount=Decimal('2000'),
            user=self.user,
            reason='Bank float',
        )
        add_cash_movement(
            session,
            movement_type=CashMovement.MovementType.CASH_OUT,
            amount=Decimal('3000'),
            user=self.user,
            reason='Change',
        )
        add_cash_movement(
            session,
            movement_type=CashMovement.MovementType.REFUND,
            amount=Decimal('1000'),
            user=self.user,
            payment_method=Sale.PaymentMethod.CASH,
            reason='Return',
        )
        totals = compute_totals(session)
        self.assertEqual(totals['expected_closing_cash'], Decimal('8030.00'))
        closed = close_session(session, Decimal('7530.00'))
        self.assertEqual(closed.status, CashSession.Status.CLOSED)
        self.assertEqual(closed.actual_closing_cash, Decimal('7530.00'))
        self.assertEqual(closed.expected_closing_cash, Decimal('8030.00'))
        self.assertEqual(closed.cash_difference, Decimal('-500.00'))
        self.assertIsNotNone(closed.closed_at)
        self.assertIsNone(get_open_session(self.user))
        response = self.client.get(reverse('pos:session_detail', args=[closed.pk]))
        self.assertContains(response, '8,030.00')
        self.assertContains(response, '-500.00')
        self.assertContains(response, draft.invoice_number)

    def test_draft_then_complete_posts_stock(self):
        open_session(self.user, Decimal('10000'))
        draft = self._sale(4, as_draft=True)
        self.assertEqual(current_stock(self.product), Decimal('100.0000'))
        completed = checkout(self.user, {
            'sale_id': draft.pk,
            'items': [{
                'product_unit_id': self.unit.pk,
                'quantity': '4',
                'unit_price': '15.00',
            }],
            'payment_method': 'cash',
            'paid_amount': '60',
        })
        self.assertEqual(completed.pk, draft.pk)
        self.assertEqual(completed.status, PostingStatus.POSTED)
        self.assertEqual(current_stock(self.product), Decimal('96.0000'))
        totals = compute_totals(completed.cash_session)
        self.assertEqual(totals['cash_sales'], Decimal('60.00'))
        self.assertEqual(totals['draft_orders'], 0)

    def test_cancelled_orders_are_not_sales(self):
        open_session(self.user, Decimal('10000'))
        sale = self._sale(2)
        from pos.services import cancel_sale
        cancel_sale(sale, self.user)
        totals = compute_totals(sale.cash_session)
        self.assertEqual(totals['cash_sales'], Decimal('0.00'))
        self.assertEqual(totals['cancelled_orders'], 1)
        self.assertEqual(totals['expected_closing_cash'], Decimal('10000.00'))
        self.assertEqual(current_stock(self.product), Decimal('100.0000'))

    def test_other_user_can_open_own_session(self):
        open_session(self.user, Decimal('10000'))
        other_session = open_session(self.other, Decimal('8000'))
        self.assertEqual(other_session.cashier, self.other)
        self.assertEqual(CashSession.objects.filter(status='open').count(), 2)

    def test_overpayment_saves_balance_and_zero_due(self):
        open_session(self.user, Decimal('10000'))
        sale = checkout(self.user, {
            'items': [{
                'product_unit_id': self.unit.pk,
                'quantity': '1',
                'unit_price': '500.00',
            }],
            'payment_method': 'cash',
            'paid_amount': '1000',
        })
        self.assertEqual(sale.total, Decimal('500.00'))
        self.assertEqual(sale.paid_amount, Decimal('1000.00'))
        self.assertEqual(sale.due_amount, Decimal('0.00'))
        self.assertEqual(sale.change_amount, Decimal('500.00'))
        self.assertEqual(sale.payment_status, Sale.PaymentStatus.PAID)
        response = self.client.get(reverse('pos:invoice', args=[sale.pk]))
        self.assertContains(response, 'Balance')
        self.assertContains(response, '500.00')

    def test_invoice_shows_sold_qty_and_unit_not_base_conversion(self):
        carton = Unit.objects.create(name='Carton', abbreviation='crt')
        pack = ProductUnit.objects.create(
            product=self.product,
            unit=carton,
            conversion_to_base=Decimal('24'),
            purchase_price=Decimal('240.00'),
            retail_price=Decimal('1100.00'),
            wholesale_price=Decimal('1000.00'),
        )
        open_session(self.user, Decimal('10000'))
        sale = checkout(self.user, {
            'items': [{
                'product_unit_id': pack.pk,
                'quantity': '1',
                'unit_price': '1100.00',
            }],
            'payment_method': 'cash',
            'paid_amount': '1100',
        })
        item = sale.items.get()
        self.assertEqual(item.quantity, Decimal('1.0000'))
        self.assertEqual(item.base_quantity, Decimal('24.0000'))
        self.assertEqual(item.unit_price, Decimal('1100.00'))
        self.assertEqual(current_stock(self.product), Decimal('76.0000'))
        response = self.client.get(reverse('pos:invoice', args=[sale.pk]))
        self.assertContains(response, 'Cola')
        self.assertContains(response, 'COLA · crt')
        self.assertContains(response, '1 crt')
        self.assertContains(response, 'Rs. 1,100.00')
        self.assertNotContains(response, '8.333333')
        self.assertNotContains(response, '1.0000')
        self.assertNotContains(response, '24.0000')

    def test_underpayment_saves_due(self):
        open_session(self.user, Decimal('10000'))
        sale = checkout(self.user, {
            'items': [{
                'product_unit_id': self.unit.pk,
                'quantity': '1',
                'unit_price': '1000.00',
            }],
            'payment_method': 'cash',
            'paid_amount': '700',
        })
        self.assertEqual(sale.total, Decimal('1000.00'))
        self.assertEqual(sale.paid_amount, Decimal('700.00'))
        self.assertEqual(sale.due_amount, Decimal('300.00'))
        self.assertEqual(sale.change_amount, Decimal('0.00'))
        self.assertEqual(sale.payment_status, Sale.PaymentStatus.PARTIAL)

    def test_invoice_percent_discount_reduces_saved_total(self):
        open_session(self.user, Decimal('10000'))
        sale = checkout(self.user, {
            'items': [{
                'product_unit_id': self.unit.pk,
                'quantity': '1',
                'unit_price': '1000.00',
            }],
            'discount_type': 'percent',
            'discount_value': '10',
            'payment_method': 'cash',
            'paid_amount': '1000',
        })
        self.assertEqual(sale.applied_discount, Decimal('100.00'))
        self.assertEqual(sale.total, Decimal('900.00'))
        self.assertEqual(sale.change_amount, Decimal('100.00'))

    def test_item_percent_discount_applies_to_line_subtotal(self):
        open_session(self.user, Decimal('10000'))
        sale = checkout(self.user, {
            'items': [{
                'product_unit_id': self.unit.pk,
                'quantity': '2',
                'unit_price': '550.00',
                'discount_type': 'percent',
                'discount_value': '10',
            }],
            'payment_method': 'cash',
            'paid_amount': '990',
        })
        item = sale.items.get()
        self.assertEqual(item.discount_type, 'percent')
        self.assertEqual(item.discount_value, Decimal('10.00'))
        self.assertEqual(item.applied_discount, Decimal('110.00'))
        self.assertEqual(item.total, Decimal('990.00'))
        self.assertEqual(sale.subtotal, Decimal('990.00'))
        self.assertEqual(sale.applied_discount, Decimal('0.00'))
        self.assertEqual(sale.total, Decimal('990.00'))

    def test_item_discounts_are_independent_per_line(self):
        open_session(self.user, Decimal('10000'))
        sale = checkout(self.user, {
            'items': [
                {
                    'product_unit_id': self.unit.pk,
                    'quantity': '1',
                    'unit_price': '550.00',
                    'discount_type': 'percent',
                    'discount_value': '10',
                },
                {
                    'product_unit_id': self.unit.pk,
                    'quantity': '1',
                    'unit_price': '550.00',
                    'discount_type': 'fixed',
                    'discount_value': '50',
                },
            ],
            'payment_method': 'cash',
            'paid_amount': '995',
        })
        totals = list(sale.items.order_by('id').values_list('total', flat=True))
        self.assertEqual(totals, [Decimal('495.00'), Decimal('500.00')])
        self.assertEqual(sale.subtotal, Decimal('995.00'))
        self.assertEqual(sale.total, Decimal('995.00'))

    def test_counter_has_bootstrap_discount_and_balance_ui(self):
        open_session(self.user, Decimal('10000'))
        response = self.client.get('/pos/counter/')
        self.assertContains(response, 'bootstrap@5.3.3')
        self.assertContains(response, 'Percentage')
        self.assertContains(response, 'Fixed Amount')
        self.assertContains(response, 'btn-group')
        self.assertContains(response, 'btn-outline-primary')
        self.assertContains(response, 'id="sum-due"')
        self.assertContains(response, 'id="sum-change"')
        self.assertContains(response, 'Balance')
        self.assertContains(response, 'name="payment_method"')
        self.assertContains(response, 'id="pay-cash"')
        self.assertContains(response, 'Bank Transfer')
        self.assertContains(response, 'btn-check')
        self.assertContains(response, 'static/js/pos.js')
        self.assertContains(response, 'id="customer-name"')
        self.assertContains(response, 'id="customer-phone"')
        self.assertNotContains(response, 'id="customer-email"')
        self.assertNotContains(response, 'id="customer-address"')
        self.assertContains(response, 'col-md-6')
        self.assertContains(response, 'Customer Name')
        self.assertContains(response, 'Phone Number')

    def test_card_sale_does_not_increase_expected_cash(self):
        open_session(self.user, Decimal('10000'))
        sale = checkout(self.user, {
            'items': [{
                'product_unit_id': self.unit.pk,
                'quantity': '1',
                'unit_price': '500.00',
            }],
            'payment_method': 'card',
            'paid_amount': '500',
        })
        totals = compute_totals(sale.cash_session)
        self.assertEqual(sale.payment_method, Sale.PaymentMethod.CARD)
        self.assertEqual(totals['total_sales'], Decimal('500.00'))
        self.assertEqual(totals['card_sales'], Decimal('500.00'))
        self.assertEqual(totals['cash_sales'], Decimal('0.00'))
        self.assertEqual(totals['expected_closing_cash'], Decimal('10000.00'))

    def test_bank_sale_does_not_increase_expected_cash(self):
        open_session(self.user, Decimal('10000'))
        sale = checkout(self.user, {
            'items': [{
                'product_unit_id': self.unit.pk,
                'quantity': '1',
                'unit_price': '500.00',
            }],
            'payment_method': 'bank',
            'paid_amount': '500',
        })
        totals = compute_totals(sale.cash_session)
        self.assertEqual(sale.payment_method, Sale.PaymentMethod.BANK)
        self.assertEqual(totals['bank_sales'], Decimal('500.00'))
        self.assertEqual(totals['expected_closing_cash'], Decimal('10000.00'))

    def test_cash_overpay_increases_expected_cash_by_sale_total(self):
        open_session(self.user, Decimal('10000'))
        sale = checkout(self.user, {
            'items': [{
                'product_unit_id': self.unit.pk,
                'quantity': '1',
                'unit_price': '500.00',
            }],
            'payment_method': 'cash',
            'paid_amount': '1000',
        })
        totals = compute_totals(sale.cash_session)
        self.assertEqual(sale.change_amount, Decimal('500.00'))
        self.assertEqual(totals['cash_sales'], Decimal('500.00'))
        self.assertEqual(totals['expected_closing_cash'], Decimal('10500.00'))


