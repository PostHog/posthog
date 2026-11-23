"""Plugs error tracking alerts into the alerts platform, which imports no source. Called from `ready()`."""

from products.alerts_platform.backend.facade.contracts import SourceConfigSpec, SourceKind
from products.alerts_platform.backend.facade.delivery import register_source_describer
from products.alerts_platform.backend.facade.source_configs import register_source_config
from products.error_tracking.backend.platform_alerts.wording import describe_transition


def load_alert_config() -> SourceConfigSpec:
    from products.error_tracking.backend.platform_alerts.source_config import (  # noqa: PLC0415 - keeps pydantic models off the startup path
        ERROR_TRACKING_ALERT_CONFIG,
    )

    return ERROR_TRACKING_ALERT_CONFIG


def register() -> None:
    # Native delivery only, so no legacy event emitter and no legacy webhook body.
    register_source_describer(SourceKind.ERROR_TRACKING, describe_transition)
    register_source_config(SourceKind.ERROR_TRACKING, load_alert_config)
