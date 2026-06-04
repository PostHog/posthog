from django.apps import apps


def test_app_is_installed():
    assert apps.is_installed("products.engineering_analytics.backend")
