import math
import asyncio
import hashlib
from collections.abc import Collection, Iterator, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Literal, cast

from django.db.models import Model
from django.utils import timezone

from pydantic import BaseModel

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.exceptions_capture import capture_exception
from posthog.models import EventDefinition, Team, User
from posthog.security.llm_prompt_sanitization import sanitize_user_text, strip_llm_framing_markers
from posthog.sync import database_sync_to_async

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.models.subscription import Subscription
from products.exports.backend.models.subscription_context import SubscriptionContext
from products.product_analytics.backend.facade.api import recent_unique_viewer_counts_by_insight
from products.product_analytics.backend.facade.models import Insight

from ee.hogai.context.context import DASHBOARD_CONTEXT_CHAR_BUDGET
from ee.hogai.context.dashboard.context import DashboardContext, DashboardInsightContext
from ee.hogai.context.dashboard.prompts import DASHBOARD_RESULT_TEMPLATE
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.context.insight.format import TRUNCATED_MARKER
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.query import validate_assistant_query

MAX_REPORT_CONTEXTS = 3
MAX_DASHBOARD_INSIGHTS = 6
MAX_CONCURRENT_CONTEXT_QUERIES = 5
MAX_CONTEXT_EVENTS_PER_INSIGHT = 25
MAX_CONTEXT_EVENT_NAME_LENGTH = 400
CONTEXT_NAME_MAX_LENGTH = 120
CONTEXT_DESCRIPTION_MAX_LENGTH = 300

ReportContextStatus = Literal["success", "failed", "truncated"]
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

_UNAVAILABLE_INSIGHT_MARKER = "Insight context unavailable."
_UNAVAILABLE_DASHBOARD_MARKER = "Dashboard context unavailable."
_CONTEXT_LIMIT_EXCEEDED_MARKER = "Report context limit exceeded."
_TRUNCATED_CONTEXT_MARKER = "\n\n…(context evidence truncated)"


@frozen
class InsightReportProvenance:
    id: int
    name: str
    events: tuple[str, ...]
    status: ReportContextStatus

    def __post_init__(self) -> None:
        if self.status not in ("success", "failed", "truncated"):
            raise ValueError(f"Unknown report context status: {self.status}")
        if len(self.name) > CONTEXT_NAME_MAX_LENGTH:
            raise ValueError("Report context name exceeds its bound")
        if len(self.events) > MAX_CONTEXT_EVENTS_PER_INSIGHT:
            raise ValueError("Report context event provenance exceeds its bound")


@frozen
class InsightReportEvidence(InsightReportProvenance):
    content: str

    def __post_init__(self) -> None:
        InsightReportProvenance.__post_init__(self)
        if len(self.content) > DASHBOARD_CONTEXT_CHAR_BUDGET:
            raise ValueError("Insight report evidence exceeds its character budget")


@frozen
class DashboardReportEvidence:
    id: int
    name: str
    status: ReportContextStatus
    insights: tuple[InsightReportProvenance, ...]
    content: str

    def __post_init__(self) -> None:
        if self.status not in ("success", "failed", "truncated"):
            raise ValueError(f"Unknown report context status: {self.status}")
        if len(self.name) > CONTEXT_NAME_MAX_LENGTH:
            raise ValueError("Report context name exceeds its bound")
        if len(self.insights) > MAX_DASHBOARD_INSIGHTS:
            raise ValueError("Dashboard report provenance exceeds its insight bound")
        if len(self.content) > DASHBOARD_CONTEXT_CHAR_BUDGET:
            raise ValueError("Dashboard report evidence exceeds its character budget")


@frozen
class ReportContextEvidence:
    fingerprint: str
    dashboards: tuple[DashboardReportEvidence, ...]
    insights: tuple[InsightReportEvidence, ...]

    def __post_init__(self) -> None:
        if len(self.dashboards) + len(self.insights) > MAX_REPORT_CONTEXTS:
            raise ValueError("Report context evidence exceeds its durable context bound")
        if len(self.formatted_evidence) > DASHBOARD_CONTEXT_CHAR_BUDGET:
            raise ValueError("Combined report context evidence exceeds its character budget")

    @property
    def formatted_evidence(self) -> str:
        contents = [dashboard.content for dashboard in self.dashboards if dashboard.content]
        contents.extend(insight.content for insight in self.insights if insight.content)
        return "\n\n".join(contents)

    @property
    def event_names(self) -> tuple[str, ...]:
        names: list[str] = []
        seen: set[str] = set()
        for dashboard in self.dashboards:
            for insight in dashboard.insights:
                for event in insight.events:
                    if event not in seen:
                        seen.add(event)
                        names.append(event)
        for insight in self.insights:
            for event in insight.events:
                if event not in seen:
                    seen.add(event)
                    names.append(event)
        return tuple(names)


@frozen
class _SavedInsight:
    id: int
    short_id: str
    name: str
    description: str
    events: tuple[str, ...]
    query: BaseModel | None
    filters_override: JsonObject | None
    variables_override: JsonObject | None
    available: bool


@frozen
class _DashboardTile:
    insight: _SavedInsight
    layout_y: float
    layout_x: float


@frozen
class _SavedDashboard:
    id: int
    name: str
    description: str
    filters: JsonObject
    insights: tuple[_SavedInsight, ...]
    available: bool


@frozen
class _LoadedReportContext:
    team: Team
    user: User | None
    fingerprint: str
    dashboards: tuple[_SavedDashboard, ...]
    insights: tuple[_SavedInsight, ...]
    over_limit: bool


@frozen
class _PendingInsight:
    saved: _SavedInsight
    context: InsightContext | None


@frozen
class _ExecutedInsight:
    saved: _SavedInsight
    status: ReportContextStatus
    content: str


@frozen
class _UnboundedDashboardEvidence:
    id: int
    name: str
    description: str
    dashboard_url: str
    insights: tuple[_ExecutedInsight, ...]
    available: bool


def compute_report_context_fingerprint(*, dashboard_ids: Collection[int], insight_ids: Collection[int]) -> str:
    identifiers = {f"dashboard:{dashboard_id}" for dashboard_id in dashboard_ids}
    identifiers.update(f"insight:{insight_id}" for insight_id in insight_ids)
    return hashlib.sha256("\n".join(sorted(identifiers)).encode()).hexdigest()


def _walk_event_names(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        event = node.get("event")
        if isinstance(event, str) and 0 < len(event) <= MAX_CONTEXT_EVENT_NAME_LENGTH:
            yield event
        for value in node.values():
            yield from _walk_event_names(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_event_names(item)


def extract_context_event_names(node: object) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for name in _walk_event_names(node):
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
        if len(names) >= MAX_CONTEXT_EVENTS_PER_INSIGHT:
            break
    return tuple(names)


def _safe_text(value: str | None, max_length: int, fallback: str) -> str:
    return sanitize_user_text(value or "", max_length) or fallback


def _validated_saved_query(insight: Insight) -> tuple[BaseModel | None, tuple[str, ...]]:
    raw_query = insight.query or insight.query_from_filters
    if not isinstance(raw_query, dict):
        return None, ()
    event_names = extract_context_event_names(raw_query)
    query = raw_query.get("source")
    if not isinstance(query, dict):
        query = raw_query
    try:
        return validate_assistant_query(query), event_names
    except Exception:
        return None, event_names


def _can_view(access_control: UserAccessControl, resource: Model) -> bool:
    try:
        return access_control.check_access_level_for_object(resource, "viewer")
    except Exception as err:
        capture_exception(err)
        return False


def _layout_coordinate(layouts: object, coordinate: Literal["x", "y"]) -> float:
    if not isinstance(layouts, dict):
        return 100
    small_layout = layouts.get("sm")
    if not isinstance(small_layout, dict):
        return 100
    value = small_layout.get(coordinate)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return 100
    return float(value)


def _rank_dashboard_tiles(tiles: Sequence[_DashboardTile], viewer_counts: dict[int, int]) -> tuple[_DashboardTile, ...]:
    return tuple(
        sorted(
            tiles,
            key=lambda tile: (
                -viewer_counts.get(tile.insight.id, 0),
                tile.layout_y,
                tile.layout_x,
                tile.insight.id,
            ),
        )[:MAX_DASHBOARD_INSIGHTS]
    )


def _load_saved_insight(
    insight: Insight,
    *,
    filters_override: JsonObject | None = None,
    variables_override: JsonObject | None = None,
) -> _SavedInsight:
    query, events = _validated_saved_query(insight)
    return _SavedInsight(
        id=insight.id,
        short_id=insight.short_id,
        name=_safe_text(insight.name or insight.derived_name, CONTEXT_NAME_MAX_LENGTH, "Unnamed insight"),
        description=_safe_text(insight.description, CONTEXT_DESCRIPTION_MAX_LENGTH, ""),
        events=events,
        query=query,
        filters_override=filters_override,
        variables_override=variables_override,
        available=True,
    )


def _unavailable_insight(insight_id: int) -> _SavedInsight:
    return _SavedInsight(
        id=insight_id,
        short_id="",
        name="Unavailable insight",
        description="",
        events=(),
        query=None,
        filters_override=None,
        variables_override=None,
        available=False,
    )


def _unavailable_dashboard(dashboard_id: int) -> _SavedDashboard:
    return _SavedDashboard(
        id=dashboard_id,
        name="Unavailable dashboard",
        description="",
        filters={},
        insights=(),
        available=False,
    )


def _load_dashboard(
    dashboard: Dashboard,
    *,
    team: Team,
    access_control: UserAccessControl,
    popularity_since: datetime,
) -> _SavedDashboard:
    if dashboard.team_id != team.id or dashboard.deleted or not _can_view(access_control, dashboard):
        return _unavailable_dashboard(dashboard.id)

    tile_rows = list(
        DashboardTile.objects.filter(
            dashboard_id=dashboard.id,
            insight_id__isnull=False,
            insight__team_id=team.id,
            insight__deleted=False,
        ).select_related("insight")
    )
    candidates: list[_DashboardTile] = []
    for tile in tile_rows:
        insight = tile.insight
        if insight is None or insight.team_id != team.id or not _can_view(access_control, insight):
            continue
        candidates.append(
            _DashboardTile(
                insight=_load_saved_insight(
                    insight,
                    filters_override=cast(JsonObject, tile.filters_overrides) if tile.filters_overrides else None,
                    variables_override=cast(JsonObject, dashboard.variables) if dashboard.variables else None,
                ),
                layout_y=_layout_coordinate(tile.layouts, "y"),
                layout_x=_layout_coordinate(tile.layouts, "x"),
            )
        )

    viewer_counts: dict[int, int] = {}
    if candidates:
        try:
            viewer_counts = recent_unique_viewer_counts_by_insight(
                team_id=team.id,
                insight_ids=[tile.insight.id for tile in candidates],
                since=popularity_since,
            )
        except Exception as err:
            capture_exception(err)

    ranked = _rank_dashboard_tiles(candidates, viewer_counts)
    return _SavedDashboard(
        id=dashboard.id,
        name=_safe_text(dashboard.name, CONTEXT_NAME_MAX_LENGTH, "Unnamed dashboard"),
        description=_safe_text(dashboard.description, CONTEXT_DESCRIPTION_MAX_LENGTH, ""),
        filters=cast(JsonObject, dashboard.filters) if isinstance(dashboard.filters, dict) else {},
        insights=tuple(tile.insight for tile in ranked),
        available=True,
    )


def _validate_project_event_names(context: _LoadedReportContext) -> _LoadedReportContext:
    candidates = {event for insight in context.insights for event in insight.events}
    candidates.update(
        event for dashboard in context.dashboards for insight in dashboard.insights for event in insight.events
    )
    if not candidates:
        return context
    try:
        valid = set(
            EventDefinition.objects.filter(team_id=context.team.id, name__in=candidates).values_list("name", flat=True)
        )
    except Exception as err:
        capture_exception(err)
        valid = set()

    def validated(insight: _SavedInsight) -> _SavedInsight:
        return replace(insight, events=tuple(event for event in insight.events if event in valid))

    return replace(
        context,
        dashboards=tuple(
            replace(dashboard, insights=tuple(validated(insight) for insight in dashboard.insights))
            for dashboard in context.dashboards
        ),
        insights=tuple(validated(insight) for insight in context.insights),
    )


def _load_report_context(subscription_id: int, team_id: int) -> _LoadedReportContext:
    subscription = Subscription.objects.select_related("team", "created_by").get(id=subscription_id, team_id=team_id)
    context_rows = list(
        SubscriptionContext.objects.for_team(team_id)
        .filter(subscription_id=subscription.id)
        .only("id", "created_at", "dashboard_id", "insight_id")
        .order_by("created_at", "id")[: MAX_REPORT_CONTEXTS + 1]
    )
    selected_rows = sorted(
        context_rows[:MAX_REPORT_CONTEXTS],
        key=lambda row: (
            f"dashboard:{row.dashboard_id}" if row.dashboard_id is not None else f"insight:{row.insight_id}"
        ),
    )
    dashboard_ids = [row.dashboard_id for row in selected_rows if row.dashboard_id is not None]
    insight_ids = [row.insight_id for row in selected_rows if row.insight_id is not None]
    fingerprint = compute_report_context_fingerprint(dashboard_ids=dashboard_ids, insight_ids=insight_ids)
    over_limit = len(context_rows) > MAX_REPORT_CONTEXTS

    if over_limit:
        return _LoadedReportContext(
            team=subscription.team,
            user=subscription.created_by,
            fingerprint=fingerprint,
            dashboards=tuple(_unavailable_dashboard(dashboard_id) for dashboard_id in dashboard_ids),
            insights=tuple(_unavailable_insight(insight_id) for insight_id in insight_ids),
            over_limit=True,
        )

    user = subscription.created_by
    if user is None:
        query_access = False
        access_control = None
    else:
        try:
            access_control = UserAccessControl(user=user, team=subscription.team)
            query_access = access_control.check_access_level_for_resource("query", "viewer")
        except Exception as err:
            capture_exception(err)
            access_control = None
            query_access = False

    dashboards_by_id = (
        {
            dashboard.id: dashboard
            for dashboard in Dashboard.objects_including_soft_deleted.filter(
                id__in=dashboard_ids,
                team_id=team_id,
            )
        }
        if query_access
        else {}
    )
    insights_by_id = (
        {
            insight.id: insight
            for insight in Insight.objects_including_soft_deleted.filter(
                id__in=insight_ids,
                team_id=team_id,
            )
        }
        if query_access
        else {}
    )

    dashboards: list[_SavedDashboard] = []
    insights: list[_SavedInsight] = []
    popularity_since = timezone.now() - timedelta(days=7)
    for row in selected_rows:
        if row.dashboard_id is not None:
            dashboard = dashboards_by_id.get(row.dashboard_id)
            if not query_access or access_control is None or dashboard is None:
                dashboards.append(_unavailable_dashboard(row.dashboard_id))
            else:
                dashboards.append(
                    _load_dashboard(
                        dashboard,
                        team=subscription.team,
                        access_control=access_control,
                        popularity_since=popularity_since,
                    )
                )
        elif row.insight_id is not None:
            insight = insights_by_id.get(row.insight_id)
            if (
                not query_access
                or access_control is None
                or insight is None
                or insight.deleted
                or not _can_view(access_control, insight)
            ):
                insights.append(_unavailable_insight(row.insight_id))
            else:
                insights.append(_load_saved_insight(insight))

    loaded = _LoadedReportContext(
        team=subscription.team,
        user=user,
        fingerprint=fingerprint,
        dashboards=tuple(dashboards),
        insights=tuple(insights),
        over_limit=False,
    )
    return _validate_project_event_names(loaded)


async def _execute_insight(pending: _PendingInsight, semaphore: asyncio.Semaphore) -> _ExecutedInsight:
    if pending.context is None:
        return _ExecutedInsight(saved=pending.saved, status="failed", content=_UNAVAILABLE_INSIGHT_MARKER)
    try:
        async with semaphore:
            content = await pending.context.execute_and_format()
        safe_content = strip_llm_framing_markers(content, max_len=len(content))
        status: ReportContextStatus = "truncated" if TRUNCATED_MARKER in safe_content else "success"
        return _ExecutedInsight(saved=pending.saved, status=status, content=safe_content)
    except asyncio.CancelledError:
        raise
    except Exception as err:
        capture_exception(err)
        return _ExecutedInsight(saved=pending.saved, status="failed", content=_UNAVAILABLE_INSIGHT_MARKER)


def _to_insight_provenance(executed: _ExecutedInsight) -> InsightReportProvenance:
    return InsightReportProvenance(
        id=executed.saved.id,
        name=executed.saved.name,
        events=executed.saved.events,
        status=executed.status,
    )


def _dashboard_status(insights: Sequence[InsightReportProvenance]) -> ReportContextStatus:
    if any(insight.status == "truncated" for insight in insights):
        return "truncated"
    if insights and all(insight.status == "failed" for insight in insights):
        return "failed"
    return "success"


def _status_after_evidence_truncation(status: ReportContextStatus) -> ReportContextStatus:
    return "truncated" if status == "success" else status


def _truncate_content(content: str, remaining: int) -> tuple[str, bool]:
    if len(content) <= remaining:
        return content, False
    if remaining <= 0:
        return "", True
    if remaining <= len(_TRUNCATED_CONTEXT_MARKER):
        return _TRUNCATED_CONTEXT_MARKER[-remaining:], True
    return content[: remaining - len(_TRUNCATED_CONTEXT_MARKER)] + _TRUNCATED_CONTEXT_MARKER, True


def _format_dashboard_content(
    dashboard: _UnboundedDashboardEvidence,
    insight_contents: Sequence[str],
) -> str:
    return format_prompt_string(
        DASHBOARD_RESULT_TEMPLATE,
        dashboard_name=dashboard.name,
        dashboard_id=str(dashboard.id),
        dashboard_url=dashboard.dashboard_url,
        description=dashboard.description,
        insights="\n\n".join(insight_contents),
    )


def _bound_dashboard(
    dashboard: _UnboundedDashboardEvidence,
    remaining: int,
) -> DashboardReportEvidence:
    if not dashboard.available:
        content, truncated = _truncate_content(_UNAVAILABLE_DASHBOARD_MARKER, remaining)
        return DashboardReportEvidence(
            id=dashboard.id,
            name=dashboard.name,
            status="truncated" if truncated else "failed",
            insights=(),
            content=content,
        )

    provenance = tuple(_to_insight_provenance(insight) for insight in dashboard.insights)
    full_content = _format_dashboard_content(dashboard, [insight.content for insight in dashboard.insights])
    if len(full_content) <= remaining:
        return DashboardReportEvidence(
            id=dashboard.id,
            name=dashboard.name,
            status=_dashboard_status(provenance),
            insights=provenance,
            content=full_content,
        )

    truncation_item = _TRUNCATED_CONTEXT_MARKER.strip()
    for included_count in range(len(dashboard.insights) - 1, -1, -1):
        included_contents = [insight.content for insight in dashboard.insights[:included_count]]
        bounded_content = _format_dashboard_content(dashboard, [*included_contents, truncation_item])
        if len(bounded_content) > remaining:
            continue
        bounded_provenance = tuple(
            item if index < included_count else replace(item, status=_status_after_evidence_truncation(item.status))
            for index, item in enumerate(provenance)
        )
        return DashboardReportEvidence(
            id=dashboard.id,
            name=dashboard.name,
            status="truncated",
            insights=bounded_provenance,
            content=bounded_content,
        )

    marker_only_content = _format_dashboard_content(dashboard, [truncation_item])
    bounded_content, _ = _truncate_content(marker_only_content, remaining)
    return DashboardReportEvidence(
        id=dashboard.id,
        name=dashboard.name,
        status="truncated",
        insights=tuple(replace(item, status=_status_after_evidence_truncation(item.status)) for item in provenance),
        content=bounded_content,
    )


def _bound_evidence(
    dashboards: Sequence[_UnboundedDashboardEvidence], insights: Sequence[_ExecutedInsight]
) -> tuple[tuple[DashboardReportEvidence, ...], tuple[InsightReportEvidence, ...]]:
    remaining = DASHBOARD_CONTEXT_CHAR_BUDGET
    has_content = False
    bounded_dashboards: list[DashboardReportEvidence] = []
    bounded_insights: list[InsightReportEvidence] = []

    for dashboard in dashboards:
        separator_length = 2 if has_content else 0
        bounded_dashboard = _bound_dashboard(dashboard, max(0, remaining - separator_length))
        if bounded_dashboard.content:
            remaining -= separator_length + len(bounded_dashboard.content)
            has_content = True
        bounded_dashboards.append(bounded_dashboard)

    for executed_insight in insights:
        separator_length = 2 if has_content and executed_insight.content else 0
        bounded_content, truncated = _truncate_content(executed_insight.content, max(0, remaining - separator_length))
        if bounded_content:
            remaining -= separator_length + len(bounded_content)
            has_content = True
        bounded_insights.append(
            InsightReportEvidence(
                id=executed_insight.saved.id,
                name=executed_insight.saved.name,
                events=executed_insight.saved.events,
                status=(
                    _status_after_evidence_truncation(executed_insight.status) if truncated else executed_insight.status
                ),
                content=bounded_content,
            )
        )

    return tuple(bounded_dashboards), tuple(bounded_insights)


async def resolve_report_context(subscription: Subscription) -> ReportContextEvidence:
    """Execute the subscription's current durable contexts as bounded report evidence."""
    loaded = await database_sync_to_async(_load_report_context, thread_sensitive=True)(
        subscription.id, subscription.team_id
    )
    if loaded.over_limit:
        return ReportContextEvidence(
            fingerprint=loaded.fingerprint,
            dashboards=tuple(
                DashboardReportEvidence(
                    id=dashboard.id,
                    name=dashboard.name,
                    status="failed",
                    insights=(),
                    content=_CONTEXT_LIMIT_EXCEEDED_MARKER,
                )
                for dashboard in loaded.dashboards
            ),
            insights=tuple(
                InsightReportEvidence(
                    id=insight.id,
                    name=insight.name,
                    events=(),
                    status="failed",
                    content=_CONTEXT_LIMIT_EXCEEDED_MARKER,
                )
                for insight in loaded.insights
            ),
        )
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CONTEXT_QUERIES)

    dashboard_contexts: list[DashboardContext | None] = []
    pending_by_dashboard: list[list[_PendingInsight]] = []
    all_pending: list[_PendingInsight] = []
    for dashboard in loaded.dashboards:
        if not dashboard.available or loaded.user is None:
            dashboard_contexts.append(None)
            pending_by_dashboard.append([])
            continue
        valid_insights = [insight for insight in dashboard.insights if insight.query is not None]
        dashboard_context = DashboardContext(
            team=loaded.team,
            user=loaded.user,
            name=dashboard.name,
            description=dashboard.description,
            dashboard_id=str(dashboard.id),
            dashboard_filters=dashboard.filters,
            query_semaphore=semaphore,
            event_source=EventSource.SUBSCRIPTION,
            insights_data=[
                DashboardInsightContext(
                    query=insight.query,
                    name=insight.name,
                    description=insight.description,
                    short_id=insight.short_id,
                    db_id=insight.id,
                    filters_override=insight.filters_override,
                    variables_override=insight.variables_override,
                )
                for insight in valid_insights
                if insight.query is not None
            ],
        )
        contexts_by_id = {context.insight_model_id: context for context in dashboard_context.insights}
        dashboard_pending = [
            _PendingInsight(saved=insight, context=contexts_by_id.get(insight.id)) for insight in dashboard.insights
        ]
        dashboard_contexts.append(dashboard_context)
        pending_by_dashboard.append(dashboard_pending)
        all_pending.extend(dashboard_pending)

    standalone_pending: list[_PendingInsight] = []
    for insight in loaded.insights:
        context = (
            InsightContext(
                team=loaded.team,
                user=loaded.user,
                event_source=EventSource.SUBSCRIPTION,
                query=insight.query,
                name=insight.name,
                description=insight.description,
                insight_id=insight.short_id,
                insight_model_id=insight.id,
                insight_short_id=insight.short_id,
            )
            if insight.available and insight.query is not None and loaded.user is not None
            else None
        )
        standalone_item = _PendingInsight(saved=insight, context=context)
        standalone_pending.append(standalone_item)
        all_pending.append(standalone_item)

    executed = await asyncio.gather(*(_execute_insight(item, semaphore) for item in all_pending))
    executed_by_pending = {id(pending): result for pending, result in zip(all_pending, executed, strict=True)}

    dashboard_evidence: list[_UnboundedDashboardEvidence] = []
    for dashboard, maybe_dashboard_context, dashboard_pending in zip(
        loaded.dashboards, dashboard_contexts, pending_by_dashboard, strict=True
    ):
        if maybe_dashboard_context is None:
            dashboard_evidence.append(
                _UnboundedDashboardEvidence(
                    id=dashboard.id,
                    name=dashboard.name,
                    description="",
                    dashboard_url="",
                    insights=(),
                    available=False,
                )
            )
            continue
        executed_insights = tuple(executed_by_pending[id(item)] for item in dashboard_pending)
        dashboard_evidence.append(
            _UnboundedDashboardEvidence(
                id=dashboard.id,
                name=dashboard.name,
                description=dashboard.description,
                dashboard_url=maybe_dashboard_context.dashboard_url or "",
                insights=executed_insights,
                available=True,
            )
        )

    standalone_evidence = [executed_by_pending[id(pending)] for pending in standalone_pending]
    bounded_dashboards, bounded_insights = _bound_evidence(dashboard_evidence, standalone_evidence)
    return ReportContextEvidence(
        fingerprint=loaded.fingerprint,
        dashboards=bounded_dashboards,
        insights=bounded_insights,
    )
