from uuid import UUID

from posthog.ph_client import feature_enabled_or_false

from products.managed_warehouse.backend.facade.access import enable_customer_warehouse_access
from products.managed_warehouse.backend.facade.feature_flags import MANAGED_TRINO_QUERY_FLAG


def managed_warehouse_sql_editor_uses_trino(organization_id: UUID | str) -> bool:
    org_id = str(organization_id)
    enabled = feature_enabled_or_false(
        MANAGED_TRINO_QUERY_FLAG,
        org_id,
        groups={"organization": org_id},
        group_properties={"organization": {"id": org_id}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
    return enable_customer_warehouse_access(organization_id, trino_enabled=enabled)
