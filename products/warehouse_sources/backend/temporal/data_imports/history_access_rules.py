"""Give a table's history table the same access rules as the table.

A history table is a table of its own, so a rule set on its table does not reach it. With no rule of its
own it resolves from the rules on its source, which can leave the past versions of a restricted table
readable. A user who manages the access of both tables can copy the table's rules to its history table.

The history table only exists once its first snapshot loads. A copy asked for before then waits on the
schema, and runs when the history table is registered.
"""

from typing import Any
from uuid import UUID

from django.db import transaction

import structlog

from posthog.models import OrganizationMembership, User
from posthog.models.activity_logging.model_activity import ActingUserContext

from products.access_control.backend.facade.api import (
    can_write_access_rules,
    check_object_access_rules_copy,
    copy_object_access_rules,
    replace_object_access_rules,
)
from products.access_control.backend.facade.contracts import ObjectAccessRuleInput
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
from products.warehouse_sources.backend.self_managed_access import TABLE_RESOURCE
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import companion_resource_name
from products.warehouse_sources.backend.temporal.data_imports.cdc.history_table import (
    not_another_schemas_table,
    registered_history_naming,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import build_table_name

logger = structlog.get_logger(__name__)

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
    # A deferred copy runs later, so the user may have lost the project since asking.
    if not user_access_control.check_access_level_for_object(table.team, required_level="member"):
        return False
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


def copy_access_rules_now(user: User, table: DataWarehouseTable, history_table: DataWarehouseTable) -> None:
    """Copy the rules on request, and end a request that waits for a registration.

    A waiting request left behind would copy again at the next registration and overwrite rules edited since.
    """
    schema = ExternalDataSchema.objects.filter(team_id=table.team_id, table_id=table.id, deleted=False).first()
    with transaction.atomic():
        if schema is not None:
            lock_schema_for_history_registration(schema.id, schema.team_id)
        copy_access_rules(user, table, history_table)
        if schema is not None:
            update_sync_type_config_keys(schema.id, schema.team_id, removes=[PENDING_COPY_KEY])


def check_access_rules_copy(schema: ExternalDataSchema, user: User) -> None:
    """Raise when the copy would be refused, before the schema change saves.

    `HistoryAccessRulesNotAllowedError` when the user may not copy, `InvalidObjectAccessControlError`
    when the history table would pass the cap on objects with rules.
    """
    table = schema.table
    if table is None:
        return
    history_table = registered_history_table(table)
    if not can_copy_access_rules(user, table, history_table):
        raise HistoryAccessRulesNotAllowedError(HISTORY_ACCESS_RULES_NOT_ALLOWED_MESSAGE)
    check_object_access_rules_copy(
        team_id=table.team_id,
        resource=TABLE_RESOURCE,
        from_resource_id=str(table.id),
        to_resource_id=str(history_table.id) if history_table is not None else None,
    )


def request_access_rules_copy(schema: ExternalDataSchema, user: User) -> None:
    """Copy the access rules of the schema's table to its history table, now or once the history table exists.

    Does nothing when the schema keeps no history or has no table yet: a table that doesn't exist has no rules.
    """
    table = schema.table
    # In `cdc_only` mode the schema's table can already be its history table, which has nothing to copy from.
    if not schema.keeps_history or table is None or table.is_history_table:
        return
    with transaction.atomic():
        # Registration holds the same lock while it creates the history table and reads the request, so a
        # request either sees the registered table or is seen by the registration.
        lock_schema_for_history_registration(schema.id, schema.team_id)
        history_table = registered_history_table(table)
        if history_table is not None:
            copy_access_rules(user, table, history_table)
            drop_pending_access_rules_copy(schema)
            return
        if not can_copy_access_rules(user, table, None):
            raise HistoryAccessRulesNotAllowedError(HISTORY_ACCESS_RULES_NOT_ALLOWED_MESSAGE)
        schema.sync_type_config = update_sync_type_config_keys(
            schema.id, schema.team_id, updates={PENDING_COPY_KEY: {"table_id": str(table.id), "user_id": user.id}}
        )


def stage_access_rules_copy(schema: ExternalDataSchema, user: User | None, *, keeps_history: bool) -> None:
    """Set or clear the waiting copy on the schema's unsaved `sync_type_config`.

    The schema update saves it together with the mode change, before it starts any sync, so a registration
    that sync runs finds the request. With a user the copy is requested; without one, a request made before
    history was off or before the user declined is withdrawn.
    """
    config = schema.sync_type_config if schema.sync_type_config is not None else {}
    schema.sync_type_config = config
    table = schema.table
    if user is not None and keeps_history and table is not None and not table.is_history_table:
        config[PENDING_COPY_KEY] = {"table_id": str(table.id), "user_id": user.id}
    elif user is None:
        config.pop(PENDING_COPY_KEY, None)


def lock_schema_for_history_registration(schema_id: UUID, team_id: int) -> None:
    """Lock the schema row until the transaction ends. Call inside `transaction.atomic()`."""
    list(ExternalDataSchema.objects.select_for_update().filter(id=schema_id, team_id=team_id).values_list("id"))


def drop_pending_access_rules_copy(schema: ExternalDataSchema) -> None:
    """Forget a copy that waits, for a schema that stopped keeping history."""
    if PENDING_COPY_KEY in (schema.sync_type_config or {}):
        schema.sync_type_config = update_sync_type_config_keys(schema.id, schema.team_id, removes=[PENDING_COPY_KEY])


def _deny_history_table(team_id: int, history_table: DataWarehouseTable, keep_manager: User | None) -> None:
    """Deny the history table to everyone its rules don't name, instead of leaving it on its source's rules.

    `keep_manager` keeps a manager rule for the requester, whose access may come from rules the denial
    overrides, so the copy can still run when it is tried again.
    """
    rules = [ObjectAccessRuleInput(access_level="none")]
    if keep_manager is not None:
        membership = OrganizationMembership.objects.filter(
            user=keep_manager, organization_id=history_table.team.organization_id
        ).first()
        if membership is not None:
            rules.append(ObjectAccessRuleInput(access_level="manager", organization_member_id=membership.id))
    replace_object_access_rules(
        team_id=team_id, resource=TABLE_RESOURCE, resource_id=str(history_table.id), rules=rules
    )


def run_pending_access_rules_copy(schema_id: UUID, team_id: int, history_table: DataWarehouseTable) -> None:
    """Run a copy that waited for the schema's history table.

    The history table never falls back to its source's rules for want of the copy. When the requester can no
    longer set the rules, it is denied to everyone its rules don't name and the request ends. When the copy
    fails, it is denied the same way and the request stays pending: the next registration tries it again.
    Raises only when even that denial can't be written.
    """
    with transaction.atomic():
        lock_schema_for_history_registration(schema_id, team_id)
        _run_pending_copy(schema_id, team_id, history_table)


def _run_pending_copy(schema_id: UUID, team_id: int, history_table: DataWarehouseTable) -> None:
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
    user = User.objects.filter(id=pending.get("user_id"), is_active=True).first()
    table = DataWarehouseTable.objects.filter(team_id=team_id, id=pending.get("table_id"), deleted=False).first()
    if table is not None and table.id == history_table.id:
        log.info("history_access_rules_copy_skipped", reason="the request names the history table itself")
        update_sync_type_config_keys(schema_id, team_id, removes=[PENDING_COPY_KEY])
        return
    if table is None:
        # The rules to copy are gone with the table, so the history table must not fall back to its source's.
        log.info("history_access_rules_copy_denied", reason="table gone")
        _deny_history_table(team_id, history_table, keep_manager=None)
        update_sync_type_config_keys(schema_id, team_id, removes=[PENDING_COPY_KEY])
        return
    allowed = False
    try:
        with transaction.atomic():
            allowed = user is not None and can_copy_access_rules(user, table, history_table)
            if allowed and user is not None:
                copy_access_rules(user, table, history_table)
                log.info("history_access_rules_copied", table_id=str(table.id))
            else:
                log.info("history_access_rules_copy_denied", reason="user can no longer set the rules")
                _deny_history_table(team_id, history_table, keep_manager=None)
            update_sync_type_config_keys(schema_id, team_id, removes=[PENDING_COPY_KEY])
    except Exception:
        log.exception("history_access_rules_copy_failed")
        with ActingUserContext(user):
            _deny_history_table(team_id, history_table, keep_manager=user if allowed else None)
