from django.apps import apps


def test_app_is_installed():
    assert apps.is_installed("products.platform_features.backend")
