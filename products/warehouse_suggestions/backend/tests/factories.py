from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from products.data_modeling.backend.facade.contracts import SavedQueryDefinition
from products.warehouse_suggestions.backend.facade.enums import WarehouseSuggestionSubjectKind
from products.warehouse_suggestions.backend.logic.candidates.base import CandidateContext
from products.warehouse_suggestions.backend.logic.inventory import TeamInventory
from products.warehouse_suggestions.backend.logic.reads import (
    ReadWindow,
    Subject,
    SubjectReads,
    SubjectRefreshes,
    TeamReads,
)
from products.warehouse_suggestions.backend.logic.rules import RULES, Rules, Surface

TODAY = date(2026, 10, 7)
CREATED_AT = datetime(2026, 8, 1, tzinfo=UTC)


def view_subject(view_id: UUID) -> Subject:
    return Subject(kind=WarehouseSuggestionSubjectKind.SAVED_QUERY, id=view_id)


def table_subject(table_id: UUID) -> Subject:
    return Subject(kind=WarehouseSuggestionSubjectKind.TABLE, id=table_id)


def busy_reads(**overrides: Any) -> SubjectReads:
    reads = SubjectReads(
        human_requests=200,
        human_users=6,
        human_days=25,
        background_requests=0,
        human_reads=200,
        human_duration_ms=200 * 20_000,
        human_read_bytes=200 * 10**9,
        alone_reads=10,
        alone_duration_ms_median=10_000.0,
        alone_read_bytes_median=float(10**9),
        last_read_at=datetime(2026, 10, 6, tzinfo=UTC),
        requests_by_surface={Surface.SQL_EDITOR: 120, Surface.DASHBOARD: 80},
    )
    return replace(reads, **overrides)


def view(view_id: UUID, name: str = "orders", **overrides: Any) -> SavedQueryDefinition:
    definition = SavedQueryDefinition(
        id=view_id,
        name=name,
        hogql="SELECT timestamp, event FROM events",
        is_materialized=False,
        sync_frequency_interval=None,
        is_test=False,
        is_managed=False,
        origin=None,
        created_at=CREATED_AT,
    )
    return replace(definition, **overrides)


def team_reads(
    subjects: Mapping[Subject, SubjectReads],
    *,
    days_with_data: int = 30,
    recent_days_with_data: int = 7,
    refreshes: Mapping[UUID, SubjectRefreshes] | None = None,
) -> TeamReads:
    return TeamReads(
        window=ReadWindow.ending(TODAY, RULES),
        days_with_data=days_with_data,
        recent_days_with_data=recent_days_with_data,
        view_readers=10,
        view_reads=1000,
        subjects=subjects,
        refreshes=refreshes or {},
    )


def context(
    reads: TeamReads,
    *,
    views: Sequence[SavedQueryDefinition] = (),
    table_names: Mapping[UUID, str] | None = None,
    certified: frozenset[Subject] = frozenset(),
    direct_table_ids: frozenset[UUID] = frozenset(),
    team_id: int = 1,
    rules: Rules = RULES,
) -> CandidateContext:
    return CandidateContext(
        team_id=team_id,
        reads=reads,
        inventory=TeamInventory(
            saved_queries={saved_query.id: saved_query for saved_query in views},
            table_names=table_names or {},
            certified=certified,
            direct_table_ids=direct_table_ids,
        ),
        rules=rules,
        run_id="run-1",
    )


def days_ago(count: int) -> datetime:
    return datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC) - timedelta(days=count)
