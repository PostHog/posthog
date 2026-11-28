import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from itertools import batched
from typing import Any
from uuid import UUID

from django.db.models import Count, Q, Sum
from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.utils import generate_cache_key, get_safe_cache, safe_cache_add

from products.access_control.backend.facade import api as access
from products.error_tracking.backend.facade import alerts
from products.error_tracking.backend.facade.contracts import LifecycleFilterOutcome
from products.signals.backend.contracts import ISSUE_FILTER_SOURCES
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest, SignalSpend
from products.signals.backend.signal_metadata import EMBEDDING_MODEL, _deduped_signals_subquery, _signals_query_context
from products.signals.backend.source_filters import SourceFilterPreviewStatus as Status

logger = structlog.get_logger(__name__)
SAMPLE_SIZE = 5
PAGE_SIZE = 500
PREVIEW_CACHE_TTL_SECONDS = 60


@frozen
class PreviewSignal:
    timestamp: datetime
    signal_id: str
    source_type: str
    issue_id: str
    report_id: str


def recent_signals(team: Team, types: list[str], start: datetime, end: datetime) -> Iterator[PreviewSignal]:
    condition = """timestamp >= {start} AND timestamp < {end} AND rendering = 'plain'
        AND JSONExtractString(metadata, 'source_product') = 'error_tracking'
        AND JSONExtractString(metadata, 'source_type') IN {types}"""
    params: dict[str, ast.Expr] = {
        "start": ast.Constant(value=start),
        "end": ast.Constant(value=end),
        "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
        "types": ast.Tuple(exprs=[ast.Constant(value=value) for value in types]),
    }
    while True:
        cursor = " AND (timestamp, document_id) < ({last_time}, {last_id})" if "last_id" in params else ""
        deduped = _deduped_signals_subquery(include_content=False, extra_where=condition + cursor)
        page = (
            execute_hogql_query(
                query=f"""
                SELECT timestamp, document_id, JSONExtractString(metadata, 'source_type'),
                    JSONExtractString(metadata, 'source_id'), JSONExtractString(metadata, 'report_id')
                FROM ({deduped}) WHERE NOT JSONExtractBool(metadata, 'deleted')
                ORDER BY timestamp DESC, document_id DESC LIMIT {PAGE_SIZE}
            """,
                placeholders=params,
                team=team,
                context=_signals_query_context(team),
                ch_user=ClickHouseUser.SIGNALS,
                workload=Workload.ONLINE,
                query_type="SignalsIssueFilterPreview",
            ).results
            or []
        )
        for timestamp, signal_id, kind, issue_id, report_id in page:
            yield PreviewSignal(
                timestamp=timestamp, signal_id=signal_id, source_type=kind, issue_id=issue_id, report_id=report_id
            )
        if len(page) < PAGE_SIZE:
            break
        params.update(last_time=ast.Constant(value=page[-1][0]), last_id=ast.Constant(value=page[-1][1]))


def report_outcomes(team: Team, report_ids: set[UUID], start: datetime, end: datetime) -> dict:
    window = Q(created_at__gte=start, created_at__lt=end)
    reports = SignalReport.objects.filter(team=team, id__in=report_ids, created_at__lt=end).exclude(
        status=SignalReport.Status.DELETED
    )
    report_dates = dict(reports.values_list("id", "created_at"))
    if not report_dates:
        return {"count": 0, "spend_usd_cents": 0, "with_pr": 0, "with_merged_pr": 0}
    ids = list(report_dates)
    links = SignalReportArtefact.objects.filter(
        created_at__gte=min(report_dates.values()),
        created_at__lt=end,
        report__team=team,
        team=team,
        report_id__in=ids,
        type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
        pull_request__team=team,
    )
    # Grouping records describe the first assignment. Use the latest signal document, as
    # the report spend view does, so a moved signal is charged to its current report.
    deduped = _deduped_signals_subquery(
        include_content=False, extra_where="timestamp >= {start} AND timestamp < {end} AND rendering = 'plain'"
    )
    member_rows = execute_hogql_query(
        query=f"""SELECT groupUniqArray(document_id) FROM ({deduped})
            WHERE JSONExtractString(metadata, 'report_id') IN {{ids}} AND NOT JSONExtractBool(metadata, 'deleted')""",
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "ids": ast.Tuple(exprs=[ast.Constant(value=str(report_id)) for report_id in ids]),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
        },
        team=team,
        context=_signals_query_context(team),
        ch_user=ClickHouseUser.SIGNALS,
        workload=Workload.ONLINE,
        query_type="SignalsIssueFilterPreviewReportMembers",
    ).results
    members = member_rows[0][0] if member_rows else []
    spend = (
        SignalSpend.objects.for_team(team.pk)
        .filter(
            window,
            Q(report_id__in=ids) | Q(signal_id__in=members) | Q(signal_id__in=reports.values("triggering_signal_id")),
            finalized_at__lt=end,
            billing_exempt=False,
            accounting_failed=False,
        )
        .aggregate(total=Sum("spend", default=0))["total"]
    )
    pr_counts = links.aggregate(
        with_pr=Count("report_id", distinct=True),
        with_merged_pr=Count(
            "report_id", distinct=True, filter=Q(pull_request__state=SignalReportPullRequest.State.MERGED)
        ),
    )
    return {"count": len(ids), "spend_usd_cents": spend, **pr_counts}


def preview_issue_filters(team: Team, user: User, issue_filters: object, source_type: str | None = None) -> dict:
    try:
        if not isinstance(issue_filters, dict):
            raise alerts.AlertValidationError("Issue filters must be an object.")
        compiled = alerts.compile_signal_source_filters(team.pk, issue_filters)
    except alerts.AlertValidationError as exc:
        return {"status": Status.INVALID_EXPRESSION, "error": str(exc), "results": []}

    restricted = access.split_restricted_property_names(
        access.get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk)
    ).event
    keys = [prop["key"] for prop in compiled.get("properties", [])]
    if any(access.property_key_overlaps_restriction(key, restricted) for key in keys):
        return {"status": Status.ACCESS_DENIED, "error": "A filter property is restricted.", "results": []}

    types = [source_type] if source_type else sorted(kind for _, kind in ISSUE_FILTER_SOURCES)
    cache_key = generate_cache_key(
        team.pk,
        json.dumps(
            ["signals:issue-filter-preview:v1", user.pk, types, compiled], sort_keys=True, separators=(",", ":")
        ),
    )
    cached = get_safe_cache(cache_key)
    if isinstance(cached, dict):
        return cached
    try:
        preview = _replay_window(team, compiled, types)
    except Exception:
        logger.exception("signals.issue_filter_preview.query_failed", team_id=team.pk)
        return {"status": Status.QUERY_FAILED, "error": "Could not read the preview. Try again.", "results": []}
    if preview["status"] == Status.OK:
        safe_cache_add(cache_key, preview, timeout=PREVIEW_CACHE_TTL_SECONDS)
    return preview


def _replay_window(team: Team, compiled: dict, types: list[str]) -> dict:
    rows: dict[str, dict[str, Any]] = {
        kind: {
            "source_type": kind,
            "passing_count": 0,
            "excluded_count": 0,
            "unavailable_count": 0,
            "passing": [],
            "excluded": [],
        }
        for kind in types
    }
    excluded_reports: dict[str, set[UUID]] = {kind: set() for kind in types}
    end = timezone.now()
    start = end - timedelta(days=7)
    for batch in batched(recent_signals(team, types, start, end), 100, strict=False):
        verdicts = (
            alerts.replay_signal_filters(team, [signal.signal_id for signal in batch], compiled)
            if compiled["properties"]
            else {}
        )
        for signal in batch:
            row = rows[signal.source_type]
            verdict = verdicts.get(signal.signal_id) if compiled["properties"] else (LifecycleFilterOutcome.MATCH, {})
            if verdict is None:
                row["unavailable_count"] += 1
                continue
            outcome, fields = verdict
            if outcome == LifecycleFilterOutcome.FILTER_ERROR:
                return {
                    "status": Status.INVALID_EXPRESSION,
                    "error": "The filter could not be evaluated.",
                    "results": [],
                }
            group = "passing" if outcome == LifecycleFilterOutcome.MATCH else "excluded"
            row[f"{group}_count"] += 1
            if len(row[group]) < SAMPLE_SIZE:
                row[group].append({"issue_id": signal.issue_id, "timestamp": signal.timestamp, "field_values": fields})
            if group == "excluded" and signal.report_id:
                excluded_reports[signal.source_type].add(UUID(signal.report_id))
    for kind, row in rows.items():
        row["excluded_reports"] = report_outcomes(team, excluded_reports[kind], start, end)
    return {"status": Status.OK, "error": None, "results": list(rows.values())}
