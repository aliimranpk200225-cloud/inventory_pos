from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from inventory.models import Category, Product, ProductUnit, Unit

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
