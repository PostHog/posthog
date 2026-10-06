from django.apps import apps
from django.test import SimpleTestCase

from products.access_control.backend.facade.user_access_control import ACCESS_CONTROL_RESOURCES


def test_metrics_app_is_installed():
    assert apps.is_installed("products.metrics.backend")


class TestMetricsResourceRegistration(SimpleTestCase):
    def test_metrics_is_a_controllable_resource(self) -> None:
        assert "metrics" in ACCESS_CONTROL_RESOURCES
