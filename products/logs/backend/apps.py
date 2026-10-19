from django.apps import AppConfig


class LogsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.logs.backend"
    label = "logs"

    def ready(self) -> None:
        # Both imports happen at app-population, from dedicated light modules.
        # - activity_logging connects the logs alert / sampling-rule activity-log receivers. They must
        #   not live in the viewset modules: the lazy API router no longer pulls those, and alerts_api
        #   transitively imports the whole query-runner layer, which would drag posthog.schema and
        #   HogQL into django.setup() for every process type.
        # - The alerts platform cannot import this product, so native alert messages get the logs
        #   wording, grandfathered webhooks the legacy logs body, and alerts on the HogFunction path
        #   their `$logs_alert_*` events, through the functions registered below.
        from products.alerts_platform.backend.facade.contracts import SourceKind  # noqa: PLC0415
        from products.alerts_platform.backend.facade.delivery import (  # noqa: PLC0415
            register_legacy_event_emitter,
            register_legacy_webhook_body,
            register_source_describer,
        )
        from products.logs.backend import activity_logging  # noqa: F401, PLC0415
        from products.logs.backend.platform_alert_legacy_events import emit_logs_legacy_events  # noqa: PLC0415
        from products.logs.backend.platform_alert_wording import (  # noqa: PLC0415
            describe_logs_transition,
            legacy_logs_webhook_body,
        )

        register_source_describer(SourceKind.LOGS, describe_logs_transition)
        register_legacy_webhook_body(SourceKind.LOGS, legacy_logs_webhook_body)
        register_legacy_event_emitter(SourceKind.LOGS, emit_logs_legacy_events)
