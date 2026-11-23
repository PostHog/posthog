"""Whether the rows a run writes to a history table count towards usage, for every kind of history table."""

from typing import TYPE_CHECKING

from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

HISTORY_BILLING_FLAG = "dwh-bill-history-tables"


def history_lane_billable(schema: "ExternalDataSchema", *, history_only: bool) -> bool:
    """A history-only run bills the history table, the one table it writes. Beside the main table, the history
    table bills as a table of its own once the organization has the flag; without it, only the main table bills."""
    if history_only:
        return True
    team = schema.team
    return feature_enabled_or_false(
        HISTORY_BILLING_FLAG,
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
    )
