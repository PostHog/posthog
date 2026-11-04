from django.apps import AppConfig


class ErrorTrackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.error_tracking.backend"
    label = "error_tracking"

    def ready(self) -> None:
        # The alerts platform cannot import this product, so it reads new and reopened issues, and
        # words their messages, through the functions registered here.
        from products.alerts_platform.backend.facade.appearance import register_occurrence_store  # noqa: PLC0415
        from products.alerts_platform.backend.facade.contracts import SourceKind  # noqa: PLC0415
        from products.alerts_platform.backend.facade.delivery import register_appearance_describer  # noqa: PLC0415
        from products.alerts_platform.backend.facade.enums import PlatformAlertKind  # noqa: PLC0415
        from products.alerts_platform.backend.facade.source_configs import register_source_config  # noqa: PLC0415
        from products.error_tracking.backend.logic.issue_appearance import (  # noqa: PLC0415
            ISSUE_OCCURRENCE_STORE,
            describe_issue_appearance,
            load_issue_appearance_source_config,
        )

        register_occurrence_store(SourceKind.ERROR_TRACKING, ISSUE_OCCURRENCE_STORE)
        register_appearance_describer(SourceKind.ERROR_TRACKING, describe_issue_appearance)
        register_source_config(
            SourceKind.ERROR_TRACKING, load_issue_appearance_source_config, PlatformAlertKind.APPEARANCE
        )
