from django.apps import AppConfig


class SyntheticMonitoringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.synthetic_monitoring.backend"
    label = "synthetic_monitoring"
    verbose_name = "Synthetic Monitoring"
