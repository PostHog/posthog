"""Plugs warehouse alerts into the alerts platform, which imports no source. Called from `ready()`."""

from collections.abc import Collection
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import SourceConfigSpec, SourceKind
from products.alerts_platform.backend.facade.delivery import (
    register_source_describer,
    register_source_recipients,
    register_subscriber_access,
)
from products.alerts_platform.backend.facade.source_configs import register_source_config
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


def project_member_emails(*, team_id: int, configuration_id: UUID) -> list[str]:
    from products.warehouse_sources.backend.sync_alerts.email_recipients import (  # noqa: PLC0415 - keeps the platform API and the email tasks off the startup path
        project_member_emails as resolve,
    )

    return resolve(team_id=team_id, configuration_id=configuration_id)


def subscribers_with_warehouse_access(*, team_id: int, configuration_id: UUID, user_ids: Collection[int]) -> list[int]:
    from products.warehouse_sources.backend.sync_alerts.email_recipients import (  # noqa: PLC0415 - keeps the platform API and the email tasks off the startup path
        subscribers_with_warehouse_access as resolve,
    )

    return resolve(team_id=team_id, configuration_id=configuration_id, user_ids=user_ids)


def register() -> None:
    # Native delivery only, so no legacy event emitter and no legacy webhook body.
    register_source_describer(SourceKind.WAREHOUSE_SOURCE, describe_source_transition)
    register_source_describer(SourceKind.WAREHOUSE_DESTINATION, describe_destination_transition)
    register_source_config(SourceKind.WAREHOUSE_SOURCE, load_source_alert_config)
    register_source_config(SourceKind.WAREHOUSE_DESTINATION, load_destination_alert_config)
    register_source_recipients(SourceKind.WAREHOUSE_SOURCE, project_member_emails)
    register_source_recipients(SourceKind.WAREHOUSE_DESTINATION, project_member_emails)
    register_subscriber_access(SourceKind.WAREHOUSE_SOURCE, subscribers_with_warehouse_access)
    register_subscriber_access(SourceKind.WAREHOUSE_DESTINATION, subscribers_with_warehouse_access)
