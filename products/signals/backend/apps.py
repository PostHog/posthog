from django.apps import AppConfig


class SignalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.signals.backend"
    label = "signals"

    def ready(self) -> None:
        # activity_logging: consumes model_activity_signal to persist SignalScoutConfig audit-log
        #   entries (ModelActivityMixin only emits the signal; this is the consumer).
        # receivers: post_save receiver that closes a report's implementation PR on suppression/snooze.
        from . import (
            activity_logging,  # noqa: F401
            receivers,  # noqa: F401
        )

        self._register_signal_emission_gate()

    def _register_signal_emission_gate(self) -> None:
        """Let the data-import pipeline ask whether to emit signals for a source without
        importing this product (it depends on warehouse_sources). The gate impl is imported
        lazily so the registry/model stay off the django.setup() path.
        """
        from products.warehouse_sources.backend.facade.hooks import register_emit_signals_gate

        def _gate(team_id: int, source_type: str, schema_name: str, ai_data_processing_approved: bool) -> bool:
            from products.signals.backend.emission.gate import emit_signals_enabled  # noqa: PLC0415

            return emit_signals_enabled(team_id, source_type, schema_name, ai_data_processing_approved)

        register_emit_signals_gate(_gate)
