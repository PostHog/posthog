from django.apps import AppConfig


class ErrorTrackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.error_tracking.backend"
    label = "error_tracking"

    def ready(self) -> None:
        # The alerts platform cannot import this product, so it words error tracking's appearance alerts and
        # checks their settings through the functions registered here. Lifecycle workflows record the issues.
        from products.alerts_platform.backend.facade.contracts import SourceKind  # noqa: PLC0415
        from products.alerts_platform.backend.facade.delivery import register_appearance_describer  # noqa: PLC0415
        from products.alerts_platform.backend.facade.enums import PlatformAlertKind  # noqa: PLC0415
        from products.alerts_platform.backend.facade.source_configs import register_source_config  # noqa: PLC0415
        from products.error_tracking.backend.logic.issue_appearance import (  # noqa: PLC0415
            describe_issue_appearance,
            load_issue_appearance_source_config,
        )

        register_appearance_describer(SourceKind.ERROR_TRACKING, describe_issue_appearance)
        register_source_config(
            SourceKind.ERROR_TRACKING, load_issue_appearance_source_config, PlatformAlertKind.APPEARANCE
        )
