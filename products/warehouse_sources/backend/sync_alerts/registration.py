"""Plugs warehouse alerts into the alerts platform, which imports no source. Called from `ready()`."""

from products.alerts.backend.facade.destinations import register_email_recipient_resolver
from products.alerts_platform.backend.facade.contracts import SourceConfigSpec, SourceKind
from products.alerts_platform.backend.facade.delivery import register_source_describer
from products.alerts_platform.backend.facade.source_configs import register_source_config
from products.warehouse_sources.backend.sync_alerts.destinations import EVENT_IDS_BY_KIND
from products.warehouse_sources.backend.sync_alerts.wording import (
    describe_destination_transition,
    describe_source_transition,
)


def load_source_alert_config() -> SourceConfigSpec:
    from products.warehouse_sources.backend.sync_alerts.source_config import (  # noqa: PLC0415 - keeps the platform API and the destinations layer off the startup path
        WAREHOUSE_SOURCE_ALERT_CONFIG,
    )

    return WAREHOUSE_SOURCE_ALERT_CONFIG


def load_destination_alert_config() -> SourceConfigSpec:
    from products.warehouse_sources.backend.sync_alerts.source_config import (  # noqa: PLC0415 - keeps the platform API and the destinations layer off the startup path
        WAREHOUSE_DESTINATION_ALERT_CONFIG,
    )

    return WAREHOUSE_DESTINATION_ALERT_CONFIG


def project_member_emails(*, team_id: int, alert_id: str) -> list[str]:
    from products.warehouse_sources.backend.sync_alerts.email_recipients import (  # noqa: PLC0415 - keeps the platform API and the email tasks off the startup path
        project_member_emails as resolve,
    )

    return resolve(team_id=team_id, alert_id=alert_id)


def register() -> None:
    # Native delivery only, so no legacy event emitter and no legacy webhook body.
    register_source_describer(SourceKind.WAREHOUSE_SOURCE, describe_source_transition)
    register_source_describer(SourceKind.WAREHOUSE_DESTINATION, describe_destination_transition)
    register_source_config(SourceKind.WAREHOUSE_SOURCE, load_source_alert_config)
    register_source_config(SourceKind.WAREHOUSE_DESTINATION, load_destination_alert_config)
    # Firing and resolved only. The incident events reach an incident manager, and an email for
    # them would send each person a second copy of the same transition.
    register_email_recipient_resolver(
        event_ids=[event_id for by_kind in EVENT_IDS_BY_KIND.values() for event_id in by_kind.values()],
        resolver=project_member_emails,
    )
