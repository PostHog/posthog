"""Give a table's history table the same access rules as the table.

A history table is a table of its own, so a rule set on its table does not reach it. With no rule of its
own it resolves from the rules on its source, which can leave the past versions of a restricted table
readable. A user who manages the access of both tables can copy the table's rules to its history table.

The history table only exists once its first snapshot loads. A copy asked for before then waits on the
schema, and runs when the history table is registered.
"""

from typing import Any
from uuid import UUID

import structlog

from posthog.models import User
from posthog.models.activity_logging.model_activity import ActingUserContext

from products.access_control.backend.facade.api import can_write_access_rules, copy_object_access_rules
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.warehouse_sources.backend.facade.contracts import (
    HISTORY_ACCESS_RULES_NOT_ALLOWED_MESSAGE,
    HistoryAccessRulesNotAllowedError,
)
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import companion_resource_name
from products.warehouse_sources.backend.temporal.data_imports.cdc.history_table import (
    not_another_schemas_table,
    registered_history_naming,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import build_table_name

logger = structlog.get_logger(__name__)

TABLE_RESOURCE = "warehouse_table"

# The `sync_type_config` key of a copy that waits for the history table: the table to copy from and the
# user who asked, whose rights are checked again when the copy runs.
PENDING_COPY_KEY = "history_access_rules_copy"


def registered_history_table(table: DataWarehouseTable) -> DataWarehouseTable | None:
    """The registered history table of a table, or None when it has none.

    The history table stays after its schema stops writing it, and still holds the past versions.
    """
    schema = (
        ExternalDataSchema.objects.filter(team_id=table.team_id, table_id=table.id, deleted=False)
        .select_related("source")
        .first()
    )
    if schema is None:
        return None
    naming = registered_history_naming(schema)
    if naming is None:
        return None
    history = not_another_schemas_table(
        DataWarehouseTable.objects.filter(
            team_id=schema.team_id,
            external_data_source_id=schema.source_id,
            deleted=False,
            name=build_table_name(schema.source, companion_resource_name(schema.name, naming)),
        ),
        schema.id,
    ).first()
    # In `cdc_only` mode the schema's own table is its history table.
    if history is None or history.id == table.id:
        return None
    return history


def can_copy_access_rules(user: User, table: DataWarehouseTable, history_table: DataWarehouseTable | None) -> bool:
    """Whether the user may set the access rules of both tables, so the copy grants nothing they couldn't set.

    With no history table yet, only the table is checked. The copy checks the history table once it exists.
    """
    if not can_write_access_rules(team_id=table.team_id, user_id=user.id):
        return False
    user_access_control = UserAccessControl(user=user, team=table.team)
    return all(
        user_access_control.check_can_modify_access_levels_for_object(target)
        for target in (table, history_table)
        if target is not None
    )


def copy_access_rules(user: User, table: DataWarehouseTable, history_table: DataWarehouseTable) -> None:
    """Replace the history table's own rules with the table's, logged as the user's changes."""
    if not can_copy_access_rules(user, table, history_table):
        raise HistoryAccessRulesNotAllowedError(HISTORY_ACCESS_RULES_NOT_ALLOWED_MESSAGE)
    with ActingUserContext(user):
        copy_object_access_rules(
            team_id=table.team_id,
            resource=TABLE_RESOURCE,
            from_resource_id=str(table.id),
            to_resource_id=str(history_table.id),
        )


def check_access_rules_copy(schema: ExternalDataSchema, user: User) -> None:
    """Raise `HistoryAccessRulesNotAllowedError` when the user may not copy the schema's table rules."""
    table = schema.table
    if table is not None and not can_copy_access_rules(user, table, registered_history_table(table)):
        raise HistoryAccessRulesNotAllowedError(HISTORY_ACCESS_RULES_NOT_ALLOWED_MESSAGE)


def request_access_rules_copy(schema: ExternalDataSchema, user: User) -> None:
    """Copy the access rules of the schema's table to its history table, now or once the history table exists.

    Does nothing when the schema keeps no history or has no table yet: a table that doesn't exist has no rules.
    """
    table = schema.table
    if not schema.keeps_history or table is None:
        return
    history_table = registered_history_table(table)
    if history_table is not None:
        copy_access_rules(user, table, history_table)
        return
    if not can_copy_access_rules(user, table, None):
        raise HistoryAccessRulesNotAllowedError(HISTORY_ACCESS_RULES_NOT_ALLOWED_MESSAGE)
    schema.sync_type_config = update_sync_type_config_keys(
        schema.id, schema.team_id, updates={PENDING_COPY_KEY: {"table_id": str(table.id), "user_id": user.id}}
    )


def run_pending_access_rules_copy(schema_id: UUID, team_id: int, history_table: DataWarehouseTable) -> None:
    """Run a copy that waited for the schema's history table.

    Never fails the sync. A copy that raises stays pending, and the next registration of the history
    table, which every sync does, tries it again.
    """
    config: dict[str, Any] = (
        ExternalDataSchema.objects.filter(id=schema_id, team_id=team_id)
        .values_list("sync_type_config", flat=True)
        .first()
        or {}
    )
    pending = config.get(PENDING_COPY_KEY)
    if not pending:
        return
    log = logger.bind(team_id=team_id, schema_id=str(schema_id), history_table_id=str(history_table.id))
    try:
        user = User.objects.filter(id=pending.get("user_id"), is_active=True).first()
        table = DataWarehouseTable.objects.filter(team_id=team_id, id=pending.get("table_id"), deleted=False).first()
        if user is None or table is None or table.id == history_table.id:
            log.info("history_access_rules_copy_skipped", reason="user or table gone")
        else:
            copy_access_rules(user, table, history_table)
            log.info("history_access_rules_copied", table_id=str(table.id))
    except HistoryAccessRulesNotAllowedError:
        log.info("history_access_rules_copy_skipped", reason="user can no longer set the rules")
    except Exception:
        log.exception("history_access_rules_copy_failed")
        return
    update_sync_type_config_keys(schema_id, team_id, removes=[PENDING_COPY_KEY])
