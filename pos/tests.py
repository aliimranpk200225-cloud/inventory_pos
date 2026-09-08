from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
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
