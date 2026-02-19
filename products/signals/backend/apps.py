from django.apps import AppConfig
from django.db.models.signals import post_save


class SignalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.signals.backend"
    label = "signals"

    def ready(self):
        from .models import SignalReport
        from .signals import create_task_for_signal_report

        post_save.connect(create_task_for_signal_report, sender=SignalReport)
