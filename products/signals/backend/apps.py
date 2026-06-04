from django.apps import AppConfig


class SignalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.signals.backend"
    label = "signals"

    def ready(self) -> None:
        # Registers the model_activity_signal receiver that persists SignalScoutConfig
        # audit-log entries. ModelActivityMixin only emits the signal; this is the consumer.
        from . import activity_logging  # noqa: F401
