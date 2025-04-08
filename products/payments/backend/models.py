from typing import TYPE_CHECKING
from django.db import models
from posthog.models.utils import UUIDModel, sane_repr

if TYPE_CHECKING:
    pass


class PaymentProduct(UUIDModel):
    class Meta:
        db_table = "posthog_payments_products"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    stripe_product_id = models.CharField(max_length=100)
    stripe_pricing_id = models.CharField(max_length=100)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)  # e.g. USD, EUR
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)
    deleted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name

    __repr__ = sane_repr("id", "name", "team_id", "stripe_product_id")


class PaymentTransaction(UUIDModel):
    class Meta:
        db_table = "posthog_payments_transactions"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    product = models.ForeignKey(PaymentProduct, on_delete=models.PROTECT)
    payload = models.JSONField()
    status = models.CharField(max_length=50)
    date_created = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.team_id} - {self.product.name} - {self.status}"

    __repr__ = sane_repr("id", "team_id", "product_id", "status")
