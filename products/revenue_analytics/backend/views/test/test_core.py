import pytest

from posthog.warehouse.models.external_data_source import ExternalDataSource

from products.revenue_analytics.backend.views.core import view_name_for_event, view_name_for_source


@pytest.mark.parametrize(
    "source_type,prefix,view_name,expected",
    [
        ("stripe", None, "charges", "stripe.charges"),
        ("stripe", "prod", "charges", "stripe.prod.charges"),
        ("stripe", "prod_", "charges", "stripe.prod.charges"),
        ("stripe", "_prod", "charges", "stripe.prod.charges"),
        ("stripe", "_prod_", "charges", "stripe.prod.charges"),
    ],
)
def test_get_view_name_for_source(source_type, prefix, view_name, expected):
    source = ExternalDataSource(source_type=source_type, prefix=prefix)
    result = view_name_for_source(source, view_name)
    assert result == expected


@pytest.mark.parametrize(
    "event,view_name,expected",
    [
        ("charge_succeeded", "charges", "revenue_analytics.events.charge_succeeded.charges"),
        ("charge.succeeded", "charges", "revenue_analytics.events.charge_succeeded.charges"),
        ("charge-succeeded", "charges", "revenue_analytics.events.charge_succeeded.charges"),
        ("charge$succeeded", "charges", "revenue_analytics.events.charge_succeeded.charges"),
        ("charge123succeeded", "charges", "revenue_analytics.events.charge123succeeded.charges"),
        ("charge*!@#%^#$succeeded", "charges", "revenue_analytics.events.charge________succeeded.charges"),
    ],
)
def test_get_view_name_for_event(event, view_name, expected):
    result = view_name_for_event(event, view_name)
    assert result == expected
