"""Managed in code: refuse an API write to a field code owns, on an entity a stack manages.

Core runs `check_write` through `posthog/managed_writes.py` for every unsafe request that loads an object of
a model named here, and routes that write without loading the object call `enforce_managed_writes`. A project
with no managed entity pays one cache read, and one stacks query when that cached answer has expired.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.db.models import Count, F
from django.db.models.functions import Now

import structlog

from posthog.managed_writes import ObjectWrite, WriteRefusal
from posthog.models.scoping.manager import resolve_effective_team_id

from .. import engine_adapter
from ..db import WRITER_DB, database_ready
from ..facade.enums import BindingStatus, PushStatus
from ..models import StackBinding, StackDiff
from .credentials import STACKS_OAUTH_CLIENT_ID

# The model behind each definition kind's API, by Django label, or by `<product>.<Contract>` for a view that loads
# a facade contract.
KIND_BY_MODEL: dict[str, str] = {
    # The actions API reads through its facade, so its views load this contract instead of the model.
    "actions.ActionDetail": "action",
    "cdp.HogFunction": "destination",
    "cohorts.Cohort": "cohort",
    "dashboards.Dashboard": "dashboard",
    "data_catalog.Metric": "metric",
    "data_modeling.DataWarehouseSavedQuery": "model",
    "data_quality.DataQualityCheck": "check",
    "endpoints.Endpoint": "endpoint",
    "event_definitions.EventDefinition": "event",
    # The enterprise build serves event definitions through this subclass.
    "ee.EnterpriseEventDefinition": "event",
    "event_definitions.SchemaPropertyGroup": "property_group",
    "experiments.Experiment": "experiment",
    "feature_flags.FeatureFlag": "flag",
    "product_analytics.Insight": "insight",
    "surveys.Survey": "survey",
    "warehouse_sources.ExternalDataSource": "source",
}

# Kinds whose engine id may be the entity's name rather than its primary key.
NATURAL_ID_ATTRIBUTE: dict[str, str] = {
    "endpoint": "name",
    "event": "name",
    "metric": "name",
    "model": "name",
    "property_group": "name",
}

logger = structlog.get_logger(__name__)

# Custom actions that write an owned field the request body does not name.
# The tile actions change a dashboard's tiles, so they are refused only when the binding owns `tiles`.
_TILE_ACTIONS = (
    "move_tile",
    "copy_tile",
    "copy_group",
    "reorder_tiles",
    "create_text_tile",
    "update_text_tile",
    "delete_tile",
    "add_insight",
    "widgets_batch",
    "update_widgets_batch",
    "insight_dashboards",
)
ACTION_FIELDS: dict[tuple[str, str], frozenset[str]] = {
    ("dashboard", action): frozenset({"tiles"}) for action in _TILE_ACTIONS
}


# How long a project's answer, managed or not, stays cached. A project with no stack pays one stacks query per
# window; a binding change rewrites the answer as soon as it commits.
MARKER_TTL_SECONDS = 60
# Bumped when the shape of a cached `managed_kinds` row changes.
KINDS_SCHEMA = 2
MANAGED = [BindingStatus.PENDING.value, BindingStatus.BOUND.value]


def _team_key(team_id: int) -> str:
    return f"stacks:team_has_bindings:v2:{team_id}"


def _generation_key(team_id: int) -> str:
    return f"stacks:bindings_generation:{team_id}"


def _bound_now(team_id: int) -> bool:
    return StackBinding.objects.for_team(team_id, canonical=True).using(WRITER_DB).filter(status__in=MANAGED).exists()


def _cache_get(key: str) -> object | None:
    try:
        return cache.get(key)
    except Exception:
        logger.warning("stacks_marker_cache_unavailable", exc_info=True)
        return None


def _cache_set(key: str, value: object, timeout: int | None = MARKER_TTL_SECONDS) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.warning("stacks_marker_cache_unavailable", exc_info=True)


def _store_marker(team_id: int) -> None:
    # A new generation makes every cached `managed_kinds` of the project unreachable, even one a concurrent read
    # wrote from rows read before this change.
    _cache_set(_generation_key(team_id), str(uuid4()), timeout=None)
    _cache_set(_team_key(team_id), 1 if _bound_now(team_id) else 0)


def _kinds_key(team_id: int) -> str:
    generation = _cache_get(_generation_key(team_id)) or "0"
    return f"stacks:managed_kinds:v{KINDS_SCHEMA}:{team_id}:{generation}"


def managed_kinds(team_id: int) -> list[dict]:
    """For each kind a stack manages here: the stack, its repository and how many definitions."""
    key = _kinds_key(team_id)
    cached = _cache_get(key)
    if isinstance(cached, list):
        return cached
    rows = (
        StackBinding.objects.for_team(team_id, canonical=True)
        .using(WRITER_DB)
        .filter(status__in=MANAGED)
        .values("kind", "stack__name", "stack__repository")
        .annotate(definitions=Count("id"))
        .order_by("kind", "stack__name")
    )
    natural = engine_adapter.natural_key_kinds()
    value = [
        {
            "kind": row["kind"],
            "stack_name": row["stack__name"],
            "repository": row["stack__repository"],
            "definitions": row["definitions"],
            "redirect_creates": row["kind"] in natural,
        }
        for row in rows
    ]
    _cache_set(key, value)
    return value


def forget_team(team_id: int) -> None:
    """Rewrite the team's cached answers once a change to its bindings commits."""
    transaction.on_commit(lambda: _store_marker(team_id), using=WRITER_DB)


def team_has_bindings(team_id: int) -> bool:
    """Whether the team has any managed entity.

    A cached answer, managed or not, lasts `MARKER_TTL_SECONDS`. A missing or unreadable one is unknown, so the
    stacks database answers and the answer is cached. When this instance has no stacks database, nothing is
    managed.
    """
    cached = _cache_get(_team_key(team_id))
    if cached in (0, 1):
        return cached == 1
    if not database_ready() or not settings.STACKS_WRITE_LOCK_READS_DATABASE:
        return False
    try:
        bound = _bound_now(team_id)
    except DatabaseError:
        # The stacks database is down. Refusing every write of every project with it would take the product APIs
        # down too, so the lock opens for the outage. Known limit, logged for the alert.
        logger.exception("stacks_marker_database_unavailable", team_id=team_id)
        return False
    _cache_set(_team_key(team_id), 1 if bound else 0)
    return bound


def restore_markers() -> int:
    """Write the marker of every team that has a managed entity, so the first write after expiry is cheap."""
    team_ids = set(
        StackBinding.all_teams.using(WRITER_DB).filter(status__in=MANAGED).values_list("team_id", flat=True).distinct()
    )
    for team_id in team_ids:
        _cache_set(_team_key(team_id), 1)
    return len(team_ids)


def _live_push_stack_id(token_id: str | None) -> UUID | None:
    """The stack whose running push holds this token, while its attempt holds an unexpired lease."""
    if not token_id:
        return None
    diff = (
        StackDiff.all_teams.using(WRITER_DB)
        .filter(
            push_token_id=token_id,
            push_status=PushStatus.RUNNING.value,
            stack__lease_attempt_id=F("push_attempt_id"),
            stack__lease_generation=F("push_generation"),
            stack__lease_expires_at__gt=Now(),
        )
        .only("stack_id")
        .first()
    )
    return diff.stack_id if diff is not None else None


def check_write(write: ObjectWrite) -> WriteRefusal | None:
    kind = KIND_BY_MODEL.get(write.model_label)
    if kind is None:
        return None
    team_id = resolve_effective_team_id(write.team_id)
    if not team_has_bindings(team_id):
        return None
    entity_ids = {write.object_id}
    if natural := NATURAL_ID_ATTRIBUTE.get(kind):
        if (value := write.attribute(natural)) is not None:
            entity_ids.add(value)
    binding = (
        StackBinding.objects.for_team(team_id, canonical=True)
        .using(WRITER_DB)
        .filter(kind=kind, entity_id__in=sorted(entity_ids), status__in=MANAGED)
        .select_related("stack")
        .first()
    )
    if binding is None:
        return None
    if write.first_party_client_id == STACKS_OAUTH_CLIENT_ID and _live_push_stack_id(write.oauth_token_id) == (
        binding.stack_id
    ):
        # The running push of the stack that manages this entity. Any other token of the application is not.
        return None
    owned = frozenset(binding.owned_fields)
    if write.is_delete:
        # A managed entity is never deleted outside its stack, whatever fields code owns.
        fields = sorted(owned)
    elif (kind, write.action or "") in ACTION_FIELDS:
        fields = sorted(ACTION_FIELDS[(kind, write.action or "")] & owned)
        if not fields:
            return None
    else:
        fields = write.changed_fields(owned)
        if not fields:
            return None
    where = f" in {binding.stack.repository}" if binding.stack.repository else ""
    in_file = f" Edit {binding.source_file} instead." if binding.source_file else ""
    action = "deleted" if write.is_delete else "changed here"
    return WriteRefusal(
        code="managed_in_code",
        detail=f"This {kind} is managed in code by the stack {binding.stack.name}{where}, so it cannot be "
        f"{action}.{in_file} To manage it here again, detach it from the stack.",
        extra={
            "kind": kind,
            "binding_id": str(binding.id),
            "stack": binding.stack.name,
            "repository": binding.stack.repository,
            "source": {"file": binding.source_file, "export": binding.source_export},
            "fields": fields,
        },
    )
