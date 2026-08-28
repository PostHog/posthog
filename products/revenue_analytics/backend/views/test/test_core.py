from uuid import uuid4

import pytest

from products.revenue_analytics.backend.views.core import view_prefix_for_event, view_prefix_for_source
from products.warehouse_sources.backend.facade.contracts import RevenueSource


@pytest.mark.parametrize(
    "source_type,prefix,expected",
    [
        ("stripe", None, "stripe"),
        ("stripe", "prod", "stripe.prod"),
        ("stripe", "prod_", "stripe.prod"),
        ("stripe", "_prod", "stripe.prod"),
        ("stripe", "_prod_", "stripe.prod"),
    ],
)
def test_get_view_name_for_source(source_type, prefix, expected):
    source = RevenueSource(
        id=uuid4(),
        source_type=source_type,
        prefix=prefix,
        enabled=True,
        include_invoiceless_charges=True,
        schemas=(),
    )
    result = view_prefix_for_source(source)
    assert result == expected


@pytest.mark.parametrize(
    "event,expected",
    [
        ("charge_succeeded", "revenue_analytics.events.charge_succeeded"),
        ("charge.succeeded", "revenue_analytics.events.charge_succeeded"),
        ("charge-succeeded", "revenue_analytics.events.charge_succeeded"),
        ("charge$succeeded", "revenue_analytics.events.charge_succeeded"),
        ("charge123succeeded", "revenue_analytics.events.charge123succeeded"),
        ("charge*!@#%^#$succeeded", "revenue_analytics.events.charge________succeeded"),
    ],
)
def test_get_view_prefix_for_event(event, expected):
    result = view_prefix_for_event(event)
    assert result == expected
