from django.apps import AppConfig


class EnterpriseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.enterprise.backend"
    label = "ee"
    verbose_name = "Enterprise"
