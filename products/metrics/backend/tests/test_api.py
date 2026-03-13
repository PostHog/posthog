from django.apps import apps


def test_metrics_app_is_installed():
    assert apps.is_installed("products.metrics.backend")
