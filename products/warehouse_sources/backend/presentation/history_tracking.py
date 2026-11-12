from typing import TYPE_CHECKING, Literal, Optional

from posthog.event_usage import report_user_action

from products.warehouse_sources.backend.facade.models import ExternalDataSchema

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser

    from rest_framework.request import Request

    from posthog.models.user import User

HISTORY_ENABLED_EVENT = "data warehouse history enabled"
HISTORY_DISABLED_EVENT = "data warehouse history disabled"
HISTORY_TABLE_DELETED_EVENT = "data warehouse history table deleted"


def report_history_toggled(
    user: "User | AnonymousUser",
    schema: ExternalDataSchema,
    *,
    enabled: bool,
    table_mode: str,
    request: Optional["Request"] = None,
) -> None:
    report_user_action(
        user,
        HISTORY_ENABLED_EVENT if enabled else HISTORY_DISABLED_EVENT,
        {
            "source_type": schema.source.source_type,
            "source_id": str(schema.source_id),
            "schema_id": str(schema.id),
            "table_mode": table_mode,
        },
        team=schema.team,
        request=request,
    )


def report_history_change(
    user: "User | AnonymousUser",
    schema: ExternalDataSchema,
    *,
    history_mode_before: str | None,
    request: Optional["Request"] = None,
) -> None:
    """`history_mode_before` is the table mode the schema kept history in, or None if it kept none."""
    if schema.keeps_history == (history_mode_before is not None):
        return
    if schema.keeps_history:
        report_history_toggled(user, schema, enabled=True, table_mode=schema.cdc_table_mode, request=request)
    else:
        assert history_mode_before is not None
        report_history_toggled(user, schema, enabled=False, table_mode=history_mode_before, request=request)


def report_history_table_deleted(
    user: "User | AnonymousUser",
    schema: ExternalDataSchema,
    *,
    trigger: Literal["mode_change", "delete_action", "mask"],
    request: Optional["Request"] = None,
) -> None:
    """`trigger` tells a drop chosen while switching history off from one made later on its own, and from a
    mask that empties the table."""
    report_user_action(
        user,
        HISTORY_TABLE_DELETED_EVENT,
        {
            "source_type": schema.source.source_type,
            "source_id": str(schema.source_id),
            "schema_id": str(schema.id),
            "trigger": trigger,
        },
        team=schema.team,
        request=request,
    )
