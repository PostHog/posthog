from django.conf import settings


def order_total(quantity: int, unit_price: int) -> int:
    total = quantity * unit_price
    if quantity >= settings.SHOP_BULK_DISCOUNT_THRESHOLD:
        total = total * 9 // 10
    return total
