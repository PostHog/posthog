from django.test import Client, TestCase

from shop.models import Customer, Order


class TestOrderApi(TestCase):
    def test_summary_endpoint_returns_the_order_total(self) -> None:
        customer = Customer.objects.create(name="Ada")
        order = Order.objects.create(customer=customer, quantity=3, unit_price=200)
        response = Client().get(f"/orders/{order.pk}/summary/")
        assert response.status_code == 200
        assert response.json() == {"total": 600}
