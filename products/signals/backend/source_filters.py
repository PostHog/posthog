from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
from pydantic import JsonValue

from posthog.hogql.database.models import DatabaseField

from posthog.dataclasses import frozen
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.filter_catalog_schema import CatalogBundle
from products.signals.backend.filter_expression import FilterExpression, FilterValidationError
from products.signals.backend.filter_recipes import FilterPredicate, WarehouseFilterBindings
from products.signals.backend.models import (
    SignalFilterCatalogVersion,
    SignalFilterSourceDefinition,
    SignalSourceFilterState,
)

logger = structlog.get_logger(__name__)

SOURCE_FILTERS_FLAG = "signals-source-filters"


@frozen
class SavedSourceFilter:
    expression: str
    catalog_version: int

    def to_config(self) -> dict[str, JsonValue]:
        return {"expression": self.expression, "catalog_version": self.catalog_version}

    @classmethod
    def from_config(cls, raw: object) -> "SavedSourceFilter":
        if (
            not isinstance(raw, dict)
            or set(raw) != {"expression", "catalog_version"}
            or not isinstance(raw["expression"], str)
            or isinstance(raw["catalog_version"], bool)
            or not isinstance(raw["catalog_version"], int)
        ):
            raise FilterValidationError("saved_filter_shape", "The saved filter is not in the stored format.")
        return cls(expression=raw["expression"], catalog_version=raw["catalog_version"])


def writes_open(
    rollout_state: SignalFilterSourceDefinition.RolloutState, *, eligible: bool, internal_flag_enabled: bool
) -> bool:
    if not eligible:
        return False
    if rollout_state == SignalFilterSourceDefinition.RolloutState.ENABLED:
        return True
    return rollout_state == SignalFilterSourceDefinition.RolloutState.INTERNAL and internal_flag_enabled


def _internal_flag_enabled(organization_id: str) -> bool:
    try:
        return feature_enabled_or_false(
            SOURCE_FILTERS_FLAG,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            send_feature_flag_events=False,
        )
    except Exception:
        logger.exception("signals.source_filters.flag_check_failed", organization_id=organization_id)
        return False


def compile_source_filter(
    *, organization_id: str, source_product: str, source_type: str, expression: str
) -> SavedSourceFilter:
    """Validate an expression a client wants to save and pin it to the active catalog version."""
    source = (
        SignalFilterSourceDefinition.objects.filter(source_product=source_product, source_type=source_type)
        .select_related("active_catalog_version")
        .first()
    )
    unavailable = FilterValidationError("not_available", "Filters are not available for this source.")
    if source is None or source.active_catalog_version is None:
        raise unavailable
    rollout_state = SignalFilterSourceDefinition.RolloutState(source.rollout_state)
    internal_flag_enabled = (
        rollout_state == SignalFilterSourceDefinition.RolloutState.INTERNAL and _internal_flag_enabled(organization_id)
    )
    if not writes_open(
        rollout_state, eligible=source.filter_query_eligible, internal_flag_enabled=internal_flag_enabled
    ):
        raise unavailable
    catalog_version = source.active_catalog_version
    bundle = CatalogBundle.model_validate(catalog_version.bundle)
    FilterExpression(expression, {field.name: field.type for field in bundle.fields})
    return SavedSourceFilter(expression=expression, catalog_version=catalog_version.version)


def saved_filter_predicate(
    *,
    source_product: str,
    source_type: str,
    saved: SavedSourceFilter,
    columns: Mapping[str, DatabaseField],
    source_alias: str,
) -> FilterPredicate | None:
    """Bind a saved filter to the catalog version it was saved against, not the active one."""
    catalog_version = SignalFilterCatalogVersion.objects.filter(
        source__source_product=source_product, source__source_type=source_type, version=saved.catalog_version
    ).first()
    if catalog_version is None:
        raise FilterValidationError("catalog_missing", "The filter's catalog version no longer exists.")
    bindings = WarehouseFilterBindings(
        CatalogBundle.model_validate(catalog_version.bundle), columns, source_alias=source_alias
    )
    return bindings.predicate(saved.expression)


@frozen
class FilterStateKey:
    team_id: int
    source_product: str
    source_type: str
    schema_id: UUID

    def rows(self) -> QuerySet[SignalSourceFilterState]:
        return SignalSourceFilterState.objects.for_team(self.team_id).filter(
            source_product=self.source_product, source_type=self.source_type, schema_id=self.schema_id
        )


@frozen
class PendingWindow:
    start: datetime
    # Empty when the window starts after `start` itself, not after one row at that timestamp.
    after_id: str


def pending_window(key: FilterStateKey) -> PendingWindow | None:
    row = key.rows().values_list("pending_window_start", "pending_window_id").first()
    if row is None or row[0] is None:
        return None
    return PendingWindow(start=row[0], after_id=row[1])


def record_fetch_failure(key: FilterStateKey, *, window_start: datetime, error: Exception) -> None:
    """Keep the earliest window that failed to fetch, so the next fetch reads it again."""
    if isinstance(error, FilterValidationError):
        code, message = error.code, str(error)
    else:
        code, message = "query_failed", type(error).__name__
    with transaction.atomic():
        state, _ = (
            key.rows()
            .select_for_update()
            .get_or_create(
                team_id=key.team_id,
                source_product=key.source_product,
                source_type=key.source_type,
                schema_id=key.schema_id,
            )
        )
        if state.pending_window_start is None or window_start < state.pending_window_start:
            state.pending_window_start = window_start
            state.pending_window_id = ""
        state.last_error_code = code[:64]
        state.last_error_message = message[:500]
        state.last_error_at = timezone.now()
        state.save()


def record_window_processed(
    key: FilterStateKey,
    *,
    window_start: datetime | None,
    malformed_count: int,
    resume_from: datetime | None,
    resume_after_id: str | None,
) -> None:
    """Record a processed window. Clear the stored one, or move it to `resume_from` after a capped batch.

    Another emission run can store an earlier failed window after this run read its bound, so the stored
    window changes only through a conditional update that requires this window to cover it.
    """
    now = timezone.now()
    state, created = key.rows().get_or_create(
        team_id=key.team_id,
        source_product=key.source_product,
        source_type=key.source_type,
        schema_id=key.schema_id,
        defaults={"last_malformed_count": malformed_count, "last_success_at": now},
    )
    rows = key.rows().filter(pk=state.pk)
    if not created:
        rows.update(last_malformed_count=malformed_count, last_success_at=now)
    covered = Q(pending_window_start__isnull=True)
    if window_start is not None:
        covered |= Q(pending_window_start__gte=window_start)
    rows.filter(covered).update(
        pending_window_start=resume_from,
        pending_window_id=(resume_after_id or "") if resume_from is not None else "",
        last_error_code="",
        last_error_message="",
    )
