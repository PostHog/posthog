from collections import Counter
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationReference

from products.warehouse_sources.backend.facade.contracts import (
    DEAD_CREDENTIALS_CLEARED_KEY,
    UnreadableSourceInputsError,
)
from products.warehouse_sources.backend.logic.source_credentials_rollout import is_stripped
from products.warehouse_sources.backend.logic.source_credentials_strip import OutcomeCounts
from products.warehouse_sources.backend.logic.source_credentials_sync import next_source_batch
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.source_inputs_backup import ExternalDataSourceInputsBackup
from products.warehouse_sources.backend.temporal.data_imports.sources.common.legacy_oauth import (
    LegacyOAuthGrantUnusable,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.oauth_pointers import (
    OAuthPointerShapeError,
    PointerPath,
    pointer_at,
    with_pointer_at,
)
from products.warehouse_sources.backend.types import source_key

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import AnySource

CLEANED = "cleaned"
FAILED = "failed"


@frozen
class _CleanupPlan:
    inputs: dict[str, Any] = field(repr=False)
    source_class: "AnySource" = field(repr=False)
    legacy_tokens: bool
    dangling_column: bool
    dangling_paths: frozenset[PointerPath]


def _plan(source: ExternalDataSource, cutoff: datetime) -> _CleanupPlan | str:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (  # noqa: PLC0415 - heavy registry import
        SourceRegistry,
    )

    inputs = SourceInputsStore.load_stored(source)
    if is_stripped(inputs):
        return "skipped_stripped"
    try:
        source_class = SourceRegistry.get_source(source_key(source.source_type))
    except ValueError:
        return "skipped_unknown_type"
    if not source_class.integration_id_fields_point_at_integrations:
        return "skipped_no_integration_references"

    slot = source_class.in_use_oauth_slot(inputs)
    in_use = pointer_at(inputs, slot)
    pointers = [
        pointer for path in source_class.oauth_pointer_paths if (pointer := pointer_at(inputs, path)) is not None
    ]
    existing = IntegrationManager.any.get_many(source.team_id, {pointer.integration_id for pointer in pointers})
    dangling_paths = frozenset(pointer.path for pointer in pointers if pointer.integration_id not in existing)
    dangling_column = False
    if source.credentials_integration_id is not None:
        try:
            column_id = IntegrationReference.parse(source.credentials_integration_id).legacy_id
        except ValueError:
            dangling_column = True
        else:
            rows = IntegrationManager.any if slot is not None else IntegrationManager.any.with_source_rows()
            dangling_column = column_id is None or column_id not in rows.get_many(source.team_id, [column_id])

    legacy_tokens = source_class.has_legacy_oauth_tokens(inputs)
    dead_pointer = in_use is not None and in_use.path in dangling_paths
    if not legacy_tokens and not dangling_column and not dead_pointer:
        if DEAD_CREDENTIALS_CLEARED_KEY in inputs and not dangling_paths:
            return "already_cleaned"
        return "skipped_no_dead_credentials"

    # A surviving active reference can still supply credentials, even when the other reference is stale.
    if (source.credentials_integration_id is not None and not dangling_column) or (
        in_use is not None and in_use.integration_id in existing
    ):
        return "skipped_existing_credentials"

    schemas = ExternalDataSchema.objects.filter(team_id=source.team_id, source_id=source.id)
    if schemas.filter(status=ExternalDataSchema.Status.RUNNING).exists():
        return "skipped_running"
    if schemas.filter(should_sync=True, last_synced_at__gte=cutoff).exists():
        return "skipped_recent_sync"
    return _CleanupPlan(
        inputs=inputs,
        source_class=source_class,
        legacy_tokens=legacy_tokens,
        dangling_column=dangling_column,
        dangling_paths=dangling_paths,
    )


def _lock(source_id: UUID, team_id: int) -> ExternalDataSource | None:
    return (
        ExternalDataSource.objects.select_for_update(of=("self",))
        .select_related(None)
        .exclude(deleted=True)
        .only("id", "team_id", "source_type", "job_inputs", "credentials_integration_id")
        .filter(team_id=team_id, id=source_id)
        .first()
    )


def _cleanup_one(source: ExternalDataSource, *, execute: bool, cutoff: datetime) -> str:
    plan = _plan(source, cutoff)
    if isinstance(plan, str):
        return plan
    if not execute:
        return "would_check_legacy_tokens" if plan.legacy_tokens else "would_clean"

    if plan.legacy_tokens:
        try:
            grant = plan.source_class.adopt_legacy_oauth(deepcopy(plan.inputs))
        except LegacyOAuthGrantUnusable:
            pass
        except Exception:
            return "skipped_transient"
        else:
            return "skipped_legacy_usable" if grant is not None else "skipped_no_legacy_grant"

    with transaction.atomic():
        locked = _lock(source.id, source.team_id)
        if locked is None:
            return "skipped_gone"
        # The token check ran without a lock. Never apply its result to changed inputs.
        if (
            locked.source_type != source.source_type
            or locked.credentials_integration_id != source.credentials_integration_id
            or SourceInputsStore.load_stored(locked) != plan.inputs
        ):
            return "skipped_changed"
        fresh_plan = _plan(locked, cutoff)
        if isinstance(fresh_plan, str):
            return fresh_plan
        legacy_keys = fresh_plan.source_class.legacy_oauth_keys()
        inputs = {key: value for key, value in fresh_plan.inputs.items() if key not in legacy_keys}
        for path in fresh_plan.dangling_paths:
            inputs = with_pointer_at(inputs, path, None)
        now = timezone.now()
        ExternalDataSourceInputsBackup.objects.for_team(locked.team_id).update_or_create(
            source_id=locked.id,
            defaults={
                "team_id": locked.team_id,
                "source_type": str(locked.source_type),
                "inputs": fresh_plan.inputs,
                "created_at": now,
            },
        )
        SourceInputsStore.write_cleaned(
            locked, inputs, cleared_at=now.isoformat(), clear_column=fresh_plan.dangling_column
        )
    return CLEANED


def cleanup_dead_credentials(
    *,
    execute: bool,
    batch_size: int = 200,
    team_ids: Sequence[int] = (),
    source_type: str | None = None,
    limit: int | None = None,
    idle_days: int = 30,
    on_batch: Callable[[int], None] | None = None,
) -> OutcomeCounts:
    if idle_days < 1 or batch_size < 1 or (limit is not None and limit < 0):
        raise ValueError("Use positive idle days and batch size, and a nonnegative limit")
    counts: OutcomeCounts = Counter()
    last_id: UUID | None = None
    remaining = limit
    cutoff = timezone.now() - timedelta(days=idle_days)
    while remaining is None or remaining > 0:
        page_size = batch_size if remaining is None else min(batch_size, remaining)
        batch = next_source_batch(last_id, page_size, team_ids, source_type)
        if not batch:
            break
        last_id = batch[-1].id
        for source in batch:
            try:
                outcome = _cleanup_one(source, execute=execute, cutoff=cutoff)
            except UnreadableSourceInputsError:
                outcome = "skipped_unreadable_inputs"
            except OAuthPointerShapeError:
                outcome = "skipped_unreadable_shape"
            except Exception:
                # Exception messages can contain credentials. Report only the failure count.
                outcome = FAILED
            counts[(str(source.source_type), outcome)] += 1
        if on_batch:
            on_batch(len(batch))
        if remaining is not None:
            remaining -= len(batch)
    return counts
