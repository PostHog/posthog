"""Plugs traces alerts into the alerts platform, which imports no source. Called from `ready()`."""

from products.alerts_platform.backend.facade.contracts import SourceConfigSpec, SourceKind
from products.alerts_platform.backend.facade.delivery import register_source_describer
from products.alerts_platform.backend.facade.source_configs import register_source_config
from products.tracing.backend.alerts.wording import describe_transition


def load_alert_config() -> SourceConfigSpec:
    from products.tracing.backend.alerts.source_config import (  # noqa: PLC0415 - keeps posthog.schema off the startup path
        TRACES_ALERT_CONFIG,
    )

    return TRACES_ALERT_CONFIG


def register() -> None:
    # Native delivery only, so no legacy event emitter and no legacy webhook body.
    register_source_describer(SourceKind.TRACES, describe_transition)
    register_source_config(SourceKind.TRACES, load_alert_config)
