from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from django.utils import timezone

from products.data_catalog.backend.facade.enums import CertificationStatus
from products.data_modeling.backend.facade.contracts import SavedQueryDefinition
from products.warehouse_suggestions.backend.facade.contracts import (
    PAYLOAD_VERSION,
    MaterializePayload,
    SuggestionDraft,
    SuggestionPayload,
)
from products.warehouse_suggestions.backend.facade.enums import (
    WarehouseSuggestionKind,
    WarehouseSuggestionMainSaving,
    WarehouseSuggestionSubjectKind,
)
from products.warehouse_suggestions.backend.logic.candidates.base import CandidateContext
from products.warehouse_suggestions.backend.logic.inventory import TeamInventory
from products.warehouse_suggestions.backend.logic.reads import (
    ReadWindow,
    RefreshRun,
    Subject,
    SubjectReads,
    SubjectRefreshes,
    TeamReads,
)
from products.warehouse_suggestions.backend.logic.rules import RULES, Rules, Surface
from products.warehouse_suggestions.backend.logic.suggestions import upsert_suggestions
from products.warehouse_suggestions.backend.models import WarehouseSuggestion

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
        background_reads=0,
        background_duration_ms=0,
        background_read_bytes=0,
        human_reads=200,
        human_duration_ms=200 * 20_000,
        human_read_bytes=200 * 10**9,
        alone_reads=10,
        alone_duration_ms_median=10_000.0,
        alone_read_bytes_median=float(10**9),
        alone_duration_ms_p90=10_000.0,
        alone_read_bytes_p90=float(10**9),
        last_read_at=datetime(2026, 10, 6, tzinfo=UTC),
        requests_by_surface={Surface.SQL_EDITOR: 120, Surface.DASHBOARD: 80},
    )
    return replace(reads, **overrides)


def view(view_id: UUID, name: str = "orders", **overrides: Any) -> SavedQueryDefinition:
    definition = SavedQueryDefinition(
        id=view_id,
        name=name,
        hogql="SELECT timestamp, event FROM events",
        materializes=False,
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
    refresh_runs: Mapping[UUID, tuple[RefreshRun, ...]] | None = None,
    readers: int = 10,
) -> TeamReads:
    return TeamReads(
        window=ReadWindow.ending(TODAY, RULES),
        days_with_data=days_with_data,
        recent_days_with_data=recent_days_with_data,
        readers=readers,
        view_readers=10,
        view_reads=1000,
        subjects=subjects,
        refreshes=refreshes or {},
        refresh_runs=refresh_runs or {},
    )


def context(
    reads: TeamReads,
    *,
    views: Sequence[SavedQueryDefinition] = (),
    table_names: Mapping[UUID, str] | None = None,
    certifications: Mapping[Subject, CertificationStatus] | None = None,
    direct_table_ids: frozenset[UUID] = frozenset(),
    team_id: int = 1,
    rules: Rules = RULES,
    recent_accepts: Mapping[WarehouseSuggestionKind, frozenset[UUID]] | None = None,
) -> CandidateContext:
    return CandidateContext(
        team_id=team_id,
        reads=reads,
        inventory=TeamInventory(
            saved_queries={saved_query.id: saved_query for saved_query in views},
            table_names=table_names or {},
            certifications=certifications or {},
            direct_table_ids=direct_table_ids,
        ),
        rules=rules,
        run_id="run-1",
        recent_accepts=recent_accepts or {},
    )


def days_ago(count: int) -> datetime:
    return datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC) - timedelta(days=count)


def materialize_payload(**overrides: Any) -> MaterializePayload:
    payload = MaterializePayload(
        subject_name="orders",
        refresh_interval_seconds=3600,
        saves_seconds_per_month=2400.0,
        saves_bytes_per_month=0.0,
        freshness_today_seconds=None,
        freshness_after_seconds=3600,
        waiting_seconds_saved_per_month=2400.0,
        background_seconds_saved_per_month=0.0,
        main_saving=WarehouseSuggestionMainSaving.WAITING,
        read_seconds=20.0,
        live_sources=(),
        unknown_sources=(),
    )
    return replace(payload, **overrides)


def make_surfaced_suggestion(
    team_id: int,
    view_id: UUID,
    *,
    kind: WarehouseSuggestionKind = WarehouseSuggestionKind.MATERIALIZE,
    payload: SuggestionPayload | None = None,
    surfaced: bool = True,
) -> WarehouseSuggestion:
    fingerprint = f"{kind}:{view_id}"
    upsert_suggestions(
        team_id,
        [
            SuggestionDraft(
                kind=kind,
                fingerprint=fingerprint,
                subject_kind=WarehouseSuggestionSubjectKind.SAVED_QUERY,
                subject_id=view_id,
                payload=payload or materialize_payload(),
                payload_version=PAYLOAD_VERSION,
                rules_version="test",
                evidence={},
                evidence_window_start=days_ago(30),
                evidence_window_end=days_ago(0),
                score=1.0,
                score_inputs={},
                run_id="run-1",
            )
        ],
    )
    suggestions = WarehouseSuggestion.objects.for_team(team_id).filter(fingerprint=fingerprint)
    if surfaced:
        suggestions.update(surfaced_at=timezone.now())
    return suggestions.get()
