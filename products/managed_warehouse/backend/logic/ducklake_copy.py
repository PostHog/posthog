from uuid import UUID

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import feature_enabled_or_false

from products.managed_warehouse.backend.facade.feature_flags import DUCKLAKE_DATA_IMPORTS_COPY_FLAG

LOGGER = structlog.get_logger(__name__)


def data_imports_ducklake_copy_enabled(*, team_id: int, team_uuid: UUID | str, organization_id: UUID | str) -> bool:
    # Callers run inside Temporal activities that must not fail on a flag lookup, so any error means off.
    try:
        return feature_enabled_or_false(
            DUCKLAKE_DATA_IMPORTS_COPY_FLAG,
            str(team_uuid),
            groups={"organization": str(organization_id), "project": str(team_id)},
            group_properties={
                "organization": {"id": str(organization_id)},
                "project": {"id": str(team_id)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception as error:
        LOGGER.warning("Failed to evaluate the DuckLake data imports copy feature flag", error=str(error))
        capture_exception(error)
        return False
