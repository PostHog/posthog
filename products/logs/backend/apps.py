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
        #   wording, grandfathered webhooks the legacy logs body, alerts on the HogFunction path
        #   their `$logs_alert_*` events, and the platform API the logs `source_config` schema,
        #   through the functions registered below.
        from products.alerts_platform.backend.facade.contracts import SourceKind  # noqa: PLC0415
        from products.alerts_platform.backend.facade.delivery import (  # noqa: PLC0415
            register_legacy_event_emitter,
            register_legacy_webhook_body,
            register_source_alert_creator,
            register_source_describer,
        )
        from products.alerts_platform.backend.facade.source_access import register_source_alert_viewer  # noqa: PLC0415
        from products.alerts_platform.backend.facade.source_configs import register_source_config  # noqa: PLC0415
        from products.logs.backend import activity_logging  # noqa: F401, PLC0415
        from products.logs.backend.platform_alert_legacy_events import emit_logs_legacy_events  # noqa: PLC0415
        from products.logs.backend.platform_alert_wording import (  # noqa: PLC0415
            describe_logs_transition,
            legacy_logs_webhook_body,
        )
        from products.logs.backend.platform_hooks import logs_alert_creator, logs_alert_viewer  # noqa: PLC0415
        from products.logs.backend.platform_source_config import load_logs_source_config  # noqa: PLC0415

        register_source_describer(SourceKind.LOGS, describe_logs_transition)
        register_legacy_webhook_body(SourceKind.LOGS, legacy_logs_webhook_body)
        register_legacy_event_emitter(SourceKind.LOGS, emit_logs_legacy_events)
        register_source_config(SourceKind.LOGS, load_logs_source_config)
        register_source_alert_creator(SourceKind.LOGS, logs_alert_creator)
        register_source_alert_viewer(SourceKind.LOGS, logs_alert_viewer)

        from products.alerts_platform.backend.facade.appearance import register_occurrence_feed  # noqa: PLC0415
        from products.alerts_platform.backend.facade.delivery import register_appearance_describer  # noqa: PLC0415
        from products.alerts_platform.backend.facade.enums import PlatformAlertKind  # noqa: PLC0415
        from products.logs.backend.pattern_appearance import (  # noqa: PLC0415
            LOGS_PATTERN_FEED,
            describe_logs_pattern,
            load_logs_pattern_source_config,
        )

        # A new log pattern is an appearance alert on logs, which the platform evaluates and creates natively.
        register_occurrence_feed(SourceKind.LOGS, LOGS_PATTERN_FEED)
        register_appearance_describer(SourceKind.LOGS, describe_logs_pattern)
        register_source_config(SourceKind.LOGS, load_logs_pattern_source_config, PlatformAlertKind.APPEARANCE)
