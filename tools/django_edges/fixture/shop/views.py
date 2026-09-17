from django.http import HttpRequest, JsonResponse

from shop.models import Order
from shop.pricing import order_total


def order_summary(request: HttpRequest, pk: int) -> JsonResponse:
    order = Order.objects.get(pk=pk)
    return JsonResponse({"total": order_total(order.quantity, order.unit_price)})
