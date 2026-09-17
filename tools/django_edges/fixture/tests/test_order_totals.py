from django.test import TestCase

from shop.models import Customer, Order


class TestOrderTotals(TestCase):
    def test_order_updates_customer_lifetime_value(self) -> None:
        customer = Customer.objects.create(name="Ada")
        Order.objects.create(customer=customer, quantity=2, unit_price=500)
        customer.refresh_from_db()
        assert customer.lifetime_value == 1000

    def test_bulk_order_gets_the_discount(self) -> None:
        customer = Customer.objects.create(name="Grace")
        Order.objects.create(customer=customer, quantity=10, unit_price=100)
        customer.refresh_from_db()
        assert customer.lifetime_value == 900
