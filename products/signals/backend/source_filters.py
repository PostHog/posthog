import json
import hashlib
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Q, QuerySet, TextChoices
from django.utils import timezone

import structlog
from pydantic import JsonValue

from posthog.hogql.database.models import DatabaseField

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.ph_client import feature_enabled_or_false

from products.signals.backend.filter_catalog_schema import CatalogBundle
from products.signals.backend.filter_expression import FilterExpression, FilterValidationError
from products.signals.backend.filter_recipes import FilterPredicate, WarehouseFilterBindings
from products.signals.backend.models import (
    SignalFilterCatalogVersion,
    SignalFilterSourceDefinition,
    SignalSourceFilterState,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

logger = structlog.get_logger(__name__)

SOURCE_FILTERS_FLAG = "signals-source-filters"


class SourceFilterPreviewStatus(TextChoices):
    OK = "ok", "ok"
    INVALID_EXPRESSION = "invalid_expression", "invalid_expression"
    NOT_CONNECTED = "not_connected", "not_connected"
    NOT_SYNCED = "not_synced", "not_synced"
    ACCESS_DENIED = "access_denied", "access_denied"
    INCOMPATIBLE_TABLE = "incompatible_table", "incompatible_table"
    QUERY_FAILED = "query_failed", "query_failed"


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


@frozen
class WritableSource:
    source_product: str
    source_type: str
    catalog_version: int
    bundle: CatalogBundle

    @property
    def field_types(self) -> dict[str, str]:
        return {field.name: field.type for field in self.bundle.fields}


def writable_sources(
    organization_id: str, *, source_product: str | None = None, source_type: str | None = None
) -> list[WritableSource]:
    """Sources whose filter this organization may write, each with its active catalog."""
    definitions = (
        SignalFilterSourceDefinition.objects.filter(filter_query_eligible=True, active_catalog_version__isnull=False)
        .exclude(rollout_state=SignalFilterSourceDefinition.RolloutState.DISABLED)
        .select_related("active_catalog_version")
        .order_by("source_product", "source_type")
    )
    if source_product is not None or source_type is not None:
        definitions = definitions.filter(source_product=source_product, source_type=source_type)
    sources = list(definitions)
    needs_flag = any(source.rollout_state == SignalFilterSourceDefinition.RolloutState.INTERNAL for source in sources)
    internal_flag_enabled = needs_flag and _internal_flag_enabled(organization_id)
    writable: list[WritableSource] = []
    for source in sources:
        catalog_version = source.active_catalog_version
        if catalog_version is None or not writes_open(
            SignalFilterSourceDefinition.RolloutState(source.rollout_state),
            eligible=source.filter_query_eligible,
            internal_flag_enabled=internal_flag_enabled,
        ):
            continue
        writable.append(
            WritableSource(
                source_product=source.source_product,
                source_type=source.source_type,
                catalog_version=catalog_version.version,
                bundle=CatalogBundle.model_validate(catalog_version.bundle),
            )
        )
    return writable


def writable_source(*, organization_id: str, source_product: str, source_type: str) -> WritableSource:
    """The source's active catalog, or `not_available` when this organization may not write its filter."""
    found = writable_sources(organization_id, source_product=source_product, source_type=source_type)
    if not found:
        raise FilterValidationError("not_available", "Filters are not available for this source.")
    return found[0]


@frozen
class SourceFilterValidation:
    catalog_version: int
    error: str | None = None
    error_code: str | None = None
    error_start: int | None = None
    error_end: int | None = None

    @property
    def valid(self) -> bool:
        return self.error_code is None


def validate_source_filter(
    *, organization_id: str, source_product: str, source_type: str, expression: str
) -> SourceFilterValidation:
    """Check an unsaved expression against the active catalog, without reading warehouse data.

    Raises `FilterValidationError("not_available")` when this organization cannot write the source's filter.
    """
    source = writable_source(organization_id=organization_id, source_product=source_product, source_type=source_type)
    try:
        FilterExpression(expression, source.field_types)
    except FilterValidationError as error:
        return SourceFilterValidation(
            catalog_version=source.catalog_version,
            error=str(error),
            error_code=error.code,
            error_start=error.start,
            error_end=error.end,
        )
    return SourceFilterValidation(catalog_version=source.catalog_version)


def compile_source_filter(
    *, organization_id: str, source_product: str, source_type: str, expression: str
) -> SavedSourceFilter:
    """Validate an expression a client wants to save and pin it to the active catalog version."""
    source = writable_source(organization_id=organization_id, source_product=source_product, source_type=source_type)
    FilterExpression(expression, source.field_types)
    return SavedSourceFilter(expression=expression, catalog_version=source.catalog_version)


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

    def canonical_team_id(self) -> int:
        # `rows()` scopes a child environment to its root team, and every row is saved under that team,
        # so a lookup by the child's own id would never find the row and the next create would hit the
        # unique constraint.
        return resolve_effective_team_id(self.team_id)


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


def saved_filter_fingerprint(raw: object) -> str:
    """A stable hash of the saved `hogql_filter` value, expression and catalog version included."""
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def record_fetch_failure(
    key: FilterStateKey, *, window_start: datetime, error: Exception, filter_fingerprint: str
) -> None:
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
                team_id=key.canonical_team_id(),
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
        # The success fields describe the filter that succeeded, so a failure under a new filter clears them.
        if state.filter_fingerprint != filter_fingerprint:
            state.last_success_at = None
            state.last_malformed_count = 0
        state.filter_fingerprint = filter_fingerprint
        state.save()


def record_window_processed(
    key: FilterStateKey,
    *,
    window_start: datetime | None,
    malformed_count: int,
    resume_from: datetime | None,
    resume_after_id: str | None,
    filter_fingerprint: str,
) -> None:
    """Record a processed window. Clear the stored one, or move it to `resume_from` after a capped batch.

    Another emission run can store an earlier failed window after this run read its bound, so the stored
    window changes only through a conditional update that requires this window to cover it.
    """
    now = timezone.now()
    state, created = key.rows().get_or_create(
        team_id=key.canonical_team_id(),
        source_product=key.source_product,
        source_type=key.source_type,
        schema_id=key.schema_id,
        defaults={
            "last_malformed_count": malformed_count,
            "last_success_at": now,
            "filter_fingerprint": filter_fingerprint,
        },
    )
    rows = key.rows().filter(pk=state.pk)
    if not created:
        rows.update(last_malformed_count=malformed_count, last_success_at=now, filter_fingerprint=filter_fingerprint)
    covered = Q(pending_window_start__isnull=True)
    if window_start is not None:
        covered |= Q(pending_window_start__gte=window_start)
    rows.filter(covered).update(
        pending_window_start=resume_from,
        pending_window_id=(resume_after_id or "") if resume_from is not None else "",
        last_error_code="",
        last_error_message="",
    )


class SourceFilterRunState(TextChoices):
    OK = "ok", "ok"
    FAILING = "failing", "failing"


@frozen
class SourceKey:
    source_product: str
    source_type: str


@frozen
class SourceFilterRunStatus:
    state: SourceFilterRunState
    error_code: str | None
    error_message: str | None
    failed_at: datetime | None
    unread_since: datetime | None
    last_success_at: datetime | None
    malformed_count: int


def filter_state_rows(team_id: int) -> dict[SourceKey, list[SignalSourceFilterState]]:
    """Filter state rows of a team's live warehouse schemas, grouped by source.

    State rows resolve to the root team, so a child environment would read its parent's rows. Matching on the
    schemas this exact team owns keeps each environment to its own results, and leaves out schemas or
    connections that were deleted, which can never run again to clear their last failure.
    """
    live_schema_ids = (
        ExternalDataSchema.objects.filter(team_id=team_id, deleted=False)
        .exclude(source__deleted=True)
        .values_list("id", flat=True)
    )
    rows_by_source: defaultdict[SourceKey, list[SignalSourceFilterState]] = defaultdict(list)
    for row in (
        SignalSourceFilterState.objects.for_team(team_id)
        .filter(schema_id__in=list(live_schema_ids))
        .only(
            "source_product",
            "source_type",
            "last_error_code",
            "last_error_message",
            "last_error_at",
            "pending_window_start",
            "last_success_at",
            "last_malformed_count",
            "filter_fingerprint",
        )
    ):
        rows_by_source[SourceKey(source_product=row.source_product, source_type=row.source_type)].append(row)
    return rows_by_source


def filter_run_status(rows: list[SignalSourceFilterState], *, filter_fingerprint: str) -> SourceFilterRunStatus | None:
    """How emission last went for one source's saved filter. None before the first fetch with that filter.

    A source can import several warehouse schemas, each with its own state row. One failing schema makes
    the source failing, so a broken import is never hidden behind its siblings.
    """
    rows = [row for row in rows if row.filter_fingerprint == filter_fingerprint]
    if not rows:
        return None
    failing = [row for row in rows if row.last_error_code]
    latest_failure = max(failing, key=lambda row: row.last_error_at or timezone.now()) if failing else None
    unread = [row.pending_window_start for row in failing if row.pending_window_start is not None]
    successes = [row.last_success_at for row in rows if row.last_success_at is not None]
    return SourceFilterRunStatus(
        state=SourceFilterRunState.FAILING if failing else SourceFilterRunState.OK,
        error_code=latest_failure.last_error_code if latest_failure else None,
        error_message=(latest_failure.last_error_message or None) if latest_failure else None,
        failed_at=latest_failure.last_error_at if latest_failure else None,
        unread_since=min(unread) if unread else None,
        last_success_at=max(successes) if successes else None,
        malformed_count=sum(row.last_malformed_count for row in rows),
    )
