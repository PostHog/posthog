import re
import json
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload

from products.signals.backend.enums import SignalSourceProduct
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


# Error tracking signals carry the issue id as their `source_id`. The bound signals behind a report
# that a scout or a team member writes directly carry an id the author chose, which can be the issue id.
_SOURCE_ID_PRODUCTS = (
    SignalSourceProduct.ERROR_TRACKING.value,
    SignalSourceProduct.SIGNALS_SCOUT.value,
    SignalSourceProduct.USER_AUTHORED.value,
)
_REFERENCE_FILTER = (
    "((JSONExtractString(metadata, 'source_product') IN ({source_id_products}) "
    "AND JSONExtractString(metadata, 'source_id') = {issue_id}) "
    "OR positionCaseInsensitive(JSONExtractRaw(metadata, 'extra', 'evidence'), {issue_id}) > 0 "
    "OR positionCaseInsensitive(content, {issue_id}) > 0)"
)


def _parse_json(raw: object) -> object:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def cites_error_tracking_issue(evidence: object, *, issue_id: UUID) -> bool:
    """Whether a scout finding's `extra.evidence` entries name the issue as error tracking evidence."""
    if not isinstance(evidence, list):
        return False
    for entry in evidence:
        if not isinstance(entry, dict) or entry.get("source_product") != SignalSourceProduct.ERROR_TRACKING.value:
            continue
        entity_id = entry.get("entity_id")
        if not isinstance(entity_id, str):
            continue
        try:
            if UUID(entity_id.strip()) == issue_id:
                return True
        except ValueError:
            continue
    return False


def _signal_report_ids(team: "Team", issue_id: UUID, *, max_execution_time: int | None) -> set[str]:
    # An evidence edit can remove a reference, so the filter only selects candidate documents. The
    # dedup then reads every version of each candidate, and the outer filter checks the latest one.
    query = f"""
        SELECT report_id, source_id, source_product, evidence, content
        FROM (
            SELECT
                JSONExtractString(metadata, 'report_id') as report_id,
                JSONExtractString(metadata, 'source_id') as source_id,
                JSONExtractString(metadata, 'source_product') as source_product,
                JSONExtractRaw(metadata, 'extra', 'evidence') as evidence,
                JSONExtractBool(metadata, 'deleted') as is_deleted,
                content,
                metadata,
                timestamp
            FROM ({_deduped_signals_subquery(candidate_document_filter=_REFERENCE_FILTER, candidate_document_limit=_REFERENCE_CANDIDATE_LIMIT)})
        )
        WHERE NOT is_deleted
          AND report_id != ''
          AND {_REFERENCE_FILTER}
        ORDER BY timestamp DESC, report_id, source_id
        LIMIT {{candidate_limit}}
    """
    tag_queries(product=Product.SIGNALS, feature=Feature.QUERY)
    result = execute_hogql_query(
        query_type="SignalsReportsReferencingErrorTrackingIssue",
        query=query,
        team=team,
        context=_signals_query_context(team),
        workload=Workload.ONLINE,
        placeholders={
            "model_name": ast.Constant(value=EMBEDDING_MODEL.value),
            "issue_id": ast.Constant(value=str(issue_id)),
            "source_id_products": ast.Tuple(exprs=[ast.Constant(value=product) for product in _SOURCE_ID_PRODUCTS]),
            "candidate_limit": ast.Constant(value=_REFERENCE_CANDIDATE_LIMIT),
        },
        settings=(
            HogQLGlobalSettings(max_execution_time=max_execution_time, timeout_overflow_mode="throw")
            if max_execution_time
            else None
        ),
    )
    report_ids: set[str] = set()
    for report_id, source_id, source_product, evidence, content in result.results or []:
        if not (
            (source_product in _SOURCE_ID_PRODUCTS and source_id == str(issue_id))
            or cites_error_tracking_issue(_parse_json(evidence), issue_id=issue_id)
            or references_error_tracking_issue(content, issue_id=issue_id, team_id=team.id)
        ):
            continue
        try:
            report_ids.add(str(UUID(report_id)))
        except ValueError:
            continue
    return report_ids


def reports_referencing_error_tracking_issue(
    *, team: "Team", issue_id: UUID, max_execution_time: int | None = None
) -> set[str]:
    """Report ids that reference the issue. The caller must check first that the issue belongs to the team."""
    report_ids = _signal_report_ids(team, issue_id, max_execution_time=max_execution_time)
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
