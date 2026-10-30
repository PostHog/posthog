from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.contracts import MonitoringUnresolvedSignalExtra
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.source_repository import _issue_repository
from products.signals.backend.signal_metadata import EMBEDDING_MODEL, _deduped_signals_subquery

if TYPE_CHECKING:
    from products.signals.backend.temporal.types import SignalData


@frozen
class MonitoringRepositorySources:
    repositories: frozenset[str]
    require_private_destination: bool


@frozen
class _MonitoringReferences:
    repositories: frozenset[str]
    parents: frozenset[str]
    origins: frozenset[str]
    row_count: int
    incomplete: bool


def _read_monitoring_source_references(team: Team, report_ids: set[str], remaining_rows: int) -> _MonitoringReferences:
    query = (
        """
        SELECT DISTINCT
            JSONExtractString(metadata, 'report_id'),
            JSONExtractString(metadata, 'source_product'),
            JSONExtractString(metadata, 'source_type'),
            JSONExtractString(metadata, 'extra', 'html_url'),
            JSONExtractString(metadata, 'extra', 'report_id')
        FROM ("""
        + _deduped_signals_subquery(
            include_content=False,
            candidate_document_filter="JSONExtractString(metadata, 'report_id') IN {report_ids}",
        )
        + """)
        WHERE JSONExtractString(metadata, 'report_id') IN {report_ids}
            AND NOT JSONExtractBool(metadata, 'deleted')
        LIMIT 501
    """
    )
    result = execute_hogql_query(
        query=query,
        query_type="MonitoringResearchRepositorySources",
        team=team,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "report_ids": ast.Tuple(exprs=[ast.Constant(value=report_id) for report_id in sorted(report_ids)]),
        },
        ch_user=ClickHouseUser.SIGNALS,
        workload=Workload.OFFLINE,
    )
    rows = result.results or []
    repositories: set[str] = set()
    parents: set[str] = set()
    origins: set[str] = set()
    incomplete = len(rows) > remaining_rows
    for source_report, product, source_type, url, report_id in rows[:remaining_rows]:
        origins.add(str(source_report))
        if product == SignalSourceProduct.GITHUB and source_type == SignalSourceType.ISSUE:
            ref = GitHubIntegrationBase.parse_issue_url(url)
            if ref is None:
                incomplete = True
            else:
                repositories.add(ref.repository.lower())
        elif product == SignalSourceProduct.SIGNALS_CHECK and source_type == SignalSourceType.MONITORING_UNRESOLVED:
            try:
                parents.add(str(UUID(report_id)))
            except (TypeError, ValueError, AttributeError):
                incomplete = True
    return _MonitoringReferences(
        repositories=frozenset(repositories),
        parents=frozenset(parents),
        origins=frozenset(origins),
        row_count=len(rows),
        incomplete=incomplete,
    )


def monitoring_repository_sources(team_id: int, signals: list[SignalData]) -> MonitoringRepositorySources | None:
    pending = {
        MonitoringUnresolvedSignalExtra.model_validate(signal.extra).report_id
        for signal in signals
        if signal.source_product == SignalSourceProduct.SIGNALS_CHECK
        and signal.source_type == SignalSourceType.MONITORING_UNRESOLVED
    }
    if not pending:
        return None
    repositories = {repository for signal in signals if (repository := _issue_repository(signal))}
    seen: set[str] = set()
    private_required = False
    team = Team.objects.get(id=team_id)
    remaining_rows = 500
    for _ in range(SignalReportArtefact.MAX_REPORT_LINK_GRAPH_LEVELS):
        frontier = pending - seen
        if not frontier:
            break
        seen.update(frontier)
        if len(seen) > SignalReportArtefact.MAX_REPORT_LINK_GRAPH_NODES:
            private_required = True
            break
        available = {
            str(report_id)
            for report_id in SignalReport.objects.using("default")
            .filter(team_id=team_id, id__in=frontier)
            .values_list("id", flat=True)
        }
        private_required = private_required or available != frontier
        if not available:
            break
        selections = (
            SignalReportArtefact.objects.using("default")
            .filter(team_id=team_id, report_id__in=available, type=SignalReportArtefact.ArtefactType.REPO_SELECTION)
            .order_by("report_id", "-created_at", "-id")
            .distinct("report_id")
            .values_list("content", flat=True)
        )
        for content in selections:
            try:
                repository = json.loads(content).get("repository")
            except (ValueError, AttributeError):
                private_required = True
                continue
            if isinstance(repository, str) and repository:
                repositories.add(repository.lower())
        references = _read_monitoring_source_references(team, available, remaining_rows)
        repositories.update(references.repositories)
        remaining_rows -= references.row_count
        private_required = private_required or references.incomplete or bool(available - references.origins)
        pending = set(references.parents)
        if references.incomplete:
            break
    else:
        private_required = bool(pending - seen) or private_required
    return MonitoringRepositorySources(
        repositories=frozenset(repositories), require_private_destination=private_required or not repositories
    )
