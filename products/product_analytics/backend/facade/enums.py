"""Enumerations the product_analytics models use.

Consumers that only need a variable type read it from here and do not need the model class. The
model keeps it as a class attribute (``InsightVariable.Type``) so existing call sites are
unchanged. In an annotation the class attribute is not a valid type, so annotate with
``InsightVariableType`` directly.
"""

from posthog.enums import LabeledStrEnum


class InsightVariableType(LabeledStrEnum):
    STRING = "String", "String"
    NUMBER = "Number", "Number"
    BOOLEAN = "Boolean", "Boolean"
    LIST = "List", "List"
    DATE = "Date", "Date"
