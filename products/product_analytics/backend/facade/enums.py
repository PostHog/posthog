"""Enumerations the product_analytics models use.

Consumers that only need a variable type read it from here and do not need the model class. The
model keeps it as a class attribute (``InsightVariable.Type``) so ``choices=`` and existing call
sites are unchanged. In an annotation the class attribute is not a valid type, so annotate with
``InsightVariableType`` directly.
"""

from django.db import models


class InsightVariableType(models.TextChoices):
    STRING = "String", "String"
    NUMBER = "Number", "Number"
    BOOLEAN = "Boolean", "Boolean"
    LIST = "List", "List"
    DATE = "Date", "Date"
