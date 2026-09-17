from django.db.models.signals import post_save
from django.dispatch import receiver

from shop.models import Order
from shop.pricing import order_total


@receiver(post_save, sender=Order)
def update_lifetime_value(sender: type[Order], instance: Order, created: bool, **kwargs: object) -> None:
    if not created:
        return
    customer = instance.customer
    customer.lifetime_value += order_total(instance.quantity, instance.unit_price)
    customer.save(update_fields=["lifetime_value"])
