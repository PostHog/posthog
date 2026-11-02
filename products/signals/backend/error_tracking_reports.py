import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.error_tracking.backend.facade.api import issue_exists_by_id
from products.signals.backend.models import SignalReport
from products.signals.backend.report_merge import merge_survivor_ids
from products.signals.backend.signal_metadata import EMBEDDING_MODEL, _deduped_signals_subquery, _signals_query_context

if TYPE_CHECKING:
    from posthog.models.team.team import Team


_REFERENCE_CANDIDATE_LIMIT = 1000
_URL_PATTERN = re.compile(
    r"(?<![\w:+.-])https?://[^\s<>\[\]()\"'`]+|(?<![\w:/])/(?:project/\d+/)?error[-_]tracking/[^\s<>\[\]()\"'`]+"
)
_ISSUE_PATH_PATTERN = re.compile(r"/(?:project/(?P<team_id>\d+)/)?error[-_]tracking/(?P<issue_id>[0-9a-f-]+)/?", re.I)


def references_error_tracking_issue(text: str, *, issue_id: UUID, team_id: int) -> bool:
    site = urlsplit(settings.SITE_URL)
    allowed_hosts = {site.netloc.lower()}
    if site.netloc.lower() in {"us.posthog.com", "app.posthog.com"}:
        allowed_hosts.update({"us.posthog.com", "app.posthog.com"})
    for match in _URL_PATTERN.finditer(text):
        try:
            url = urlsplit(match.group().rstrip(".,;!"))
        except ValueError:
            continue
        if url.netloc and (url.netloc.lower() not in allowed_hosts or url.scheme != site.scheme):
            continue
        path = _ISSUE_PATH_PATTERN.fullmatch(url.path)
        if path is None or (path["team_id"] is not None and int(path["team_id"]) != team_id):
            continue
        try:
            if UUID(path["issue_id"]) == issue_id:
                return True
        except ValueError:
            continue
    return False


def _signal_report_ids(team: "Team", issue_id: UUID) -> set[str]:
    # A citation can be removed by an evidence edit, so select candidate documents first and
    # deduplicate all their versions before checking the current content.
    candidates = (
        "((JSONExtractString(metadata, 'source_product') IN ('error_tracking', 'signals_scout') "
        "AND JSONExtractString(metadata, 'source_id') = {issue_id}) "
        "OR positionCaseInsensitive(content, {issue_id}) > 0)"
    )
    query = f"""
        SELECT report_id, source_id, source_product, content
        FROM (
            SELECT
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractString(metadata, 'source_id') as source_id,
                JSONExtractString(metadata, 'source_product') as source_product,
                JSONExtractBool(metadata, 'deleted') as is_deleted,
                content,
                timestamp
            FROM ({_deduped_signals_subquery(candidate_document_filter=candidates, candidate_document_limit=_REFERENCE_CANDIDATE_LIMIT)})
        )
        WHERE NOT is_deleted
          AND report_id != ''
          AND ((source_product IN ('error_tracking', 'signals_scout') AND source_id = {{issue_id}})
            OR positionCaseInsensitive(content, {{issue_id}}) > 0)
        ORDER BY timestamp DESC, report_id, source_id
        LIMIT {{candidate_limit}}
    """
    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        query_type="SignalsReportsReferencingErrorTrackingIssue",
        query=query,
        team=team,
        context=_signals_query_context(team),
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "issue_id": ast.Constant(value=str(issue_id)),
            "candidate_limit": ast.Constant(value=_REFERENCE_CANDIDATE_LIMIT),
        },
    )
    report_ids: set[str] = set()
    for report_id, source_id, source_product, content in result.results or []:
        source_matches = source_product in {"error_tracking", "signals_scout"} and source_id == str(issue_id)
        if not source_matches and not references_error_tracking_issue(content, issue_id=issue_id, team_id=team.id):
            continue
        try:
            report_ids.add(str(UUID(report_id)))
        except ValueError:
            continue
    return report_ids


def reports_referencing_error_tracking_issue(*, team: "Team", issue_id: UUID) -> set[str]:
    if not issue_exists_by_id(team_id=team.id, issue_id=issue_id):
        return set()

    report_ids = _signal_report_ids(team, issue_id)
    summaries = (
        SignalReport.objects.filter(team_id=team.id, summary__icontains=str(issue_id))
        .exclude(status=SignalReport.Status.DELETED)
        .order_by("-updated_at", "id")
        .values_list("id", "summary")[:_REFERENCE_CANDIDATE_LIMIT]
    )
    report_ids.update(
        str(report_id)
        for report_id, summary in summaries
        if summary is not None and references_error_tracking_issue(summary, issue_id=issue_id, team_id=team.id)
    )
    return merge_survivor_ids(team_id=team.id, report_ids=report_ids)
