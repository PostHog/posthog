from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=100)
    lifetime_value = models.IntegerField(default=0)


class Order(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="orders")
    quantity = models.IntegerField()
    unit_price = models.IntegerField()
