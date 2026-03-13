from django.apps import apps


def test_tracing_app_is_installed():
    assert apps.is_installed("products.tracing.backend")
