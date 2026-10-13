from typing import TYPE_CHECKING, Optional

from posthog.event_usage import report_user_action

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser

    from rest_framework.request import Request

    from posthog.models.user import User

HISTORY_ENABLED_EVENT = "data warehouse history enabled"
HISTORY_DISABLED_EVENT = "data warehouse history disabled"

_HISTORY_TABLE_MODES = frozenset({"cdc_only", "both"})


def schema_keeps_history(schema: ExternalDataSchema) -> bool:
    return schema.sync_type == ExternalDataSchema.SyncType.CDC and schema.cdc_table_mode in _HISTORY_TABLE_MODES


def report_history_toggled(
    user: "User | AnonymousUser",
    schema: ExternalDataSchema,
    *,
    enabled: bool,
    request: Optional["Request"] = None,
) -> None:
    report_user_action(
        user,
        HISTORY_ENABLED_EVENT if enabled else HISTORY_DISABLED_EVENT,
        {
            "source_type": schema.source.source_type,
            "source_id": str(schema.source_id),
            "schema_id": str(schema.id),
            "table_mode": schema.cdc_table_mode if enabled else None,
        },
        team=schema.team,
        request=request,
    )


def report_history_change(
    user: "User | AnonymousUser",
    schema: ExternalDataSchema,
    *,
    kept_history_before: bool,
    request: Optional["Request"] = None,
) -> None:
    keeps_history = schema_keeps_history(schema)
    if keeps_history != kept_history_before:
        report_history_toggled(user, schema, enabled=keeps_history, request=request)
