import json
import asyncio
from collections.abc import Collection
from copy import deepcopy
from dataclasses import field
from typing import Any, Literal

from django.db.models import Model

from pydantic import BaseModel, ConfigDict

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.schema_migrations.upgrade import upgrade
from posthog.security.llm_prompt_sanitization import sanitize_user_text, strip_llm_framing_markers
from posthog.sync import database_sync_to_async

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.exports.backend.facade.auth import creator_can_query
from products.exports.backend.models.subscription import Subscription
from products.exports.backend.models.subscription_context import (
    MAX_CONTEXT_READ_BUDGET,
    MAX_SELECTED_CONTEXTS,
    ReportContextSelection,
)
from products.product_analytics.backend.facade.api import (
    insight_variables_for_team,
    insights_including_soft_deleted_for_team,
    map_stale_to_latest,
)
from products.product_analytics.backend.facade.models import Insight

from ee.hogai.context.insight.context import InsightContext
from ee.hogai.utils.query import validate_assistant_query

MAX_TOOL_ROUNDS = 8
MAX_CONCURRENT_CONTEXT_FETCHES = 5
REPORT_CONTEXT_SCHEMA_CHAR_BUDGET = 12_000
CONTEXT_RESULT_MAX_CHARS = 20_000
CONTEXT_NAME_MAX_LENGTH = 120
CONTEXT_DESCRIPTION_MAX_LENGTH = 300

ReportContextStatus = Literal["success", "failed", "truncated"]
# (dashboard_id, insight_id), with dashboard_id None for a standalone fetch. The same insight can be
# registered both standalone and as a dashboard tile, and each registration applies different
# dashboard filters/overrides, so a bare insight_id key would let a memoized standalone result stand
# in for the tile's filtered one (or vice versa).
_RegistrationKey = tuple[int | None, int]

_TRUNCATED_CONTEXT_MARKER = "\n\n…(context evidence truncated)"
_CONTEXT_UNAVAILABLE_ERROR = {"error": "context unavailable"}


@frozen
class ReportContextSchema:
    content: str = ""

    def __post_init__(self) -> None:
        if len(self.content) > REPORT_CONTEXT_SCHEMA_CHAR_BUDGET:
            raise ValueError("Report context schema exceeds its character budget")


class FetchInsightArgs(BaseModel):
    """Execute one attached saved insight's current query and return its formatted results."""

    # bind_tools() names the tool after the schema's title, not its class name; the title must
    # match the tool name dispatch() switches on, or a real model's tool call never reaches it.
    model_config = ConfigDict(title="fetch_insight")

    insight_id: int


class FetchDashboardArgs(BaseModel):
    """List an attached dashboard's query tiles; pass insight_ids to execute specific tiles."""

    model_config = ConfigDict(title="fetch_dashboard")

    dashboard_id: int
    insight_ids: list[int] | None = None


class ListSelectedContextsArgs(BaseModel):
    """List the dashboards and insights attached to this subscription, with the remaining read budget."""

    model_config = ConfigDict(title="list_selected_contexts")


def _safe_text(value: str | None, max_length: int, fallback: str) -> str:
    return sanitize_user_text(value or "", max_length) or fallback


@frozen
class ParsedContextRefs:
    dashboard_ids: list[int]
    insight_ids: list[int]


def dashboard_ref(dashboard_id: int) -> str:
    return f"dashboard:{dashboard_id}"


def insight_ref(insight_id: int) -> str:
    return f"insight:{insight_id}"


def parse_context_refs(context_refs: Collection[str]) -> ParsedContextRefs | None:
    dashboard_ids: list[int] = []
    insight_ids: list[int] = []
    targets = {"dashboard": dashboard_ids, "insight": insight_ids}
    for context_ref in context_refs:
        kind, separator, raw_id = context_ref.partition(":")
        try:
            context_id = int(raw_id)
        except ValueError:
            return None
        if separator != ":" or kind not in targets or context_id < 1:
            return None
        targets[kind].append(context_id)
    return ParsedContextRefs(dashboard_ids=dashboard_ids, insight_ids=insight_ids)


def _saved_query_events(insight: Insight) -> tuple[str, ...]:
    metadata = insight.query_metadata
    if not isinstance(metadata, dict) or not isinstance(metadata.get("events"), list):
        return ()
    return tuple(dict.fromkeys(event for event in metadata["events"] if isinstance(event, str) and event))


def _validated_saved_query(insight: Insight) -> BaseModel | None:
    raw_query = insight.query
    if not isinstance(raw_query, dict):
        return None
    try:
        upgraded_query = upgrade(deepcopy(raw_query))
        query = upgraded_query.get("source")
        if not isinstance(query, dict):
            query = upgraded_query
        return validate_assistant_query(query)
    except Exception as err:
        capture_exception(err)
        return None


def _can_view(access_control: UserAccessControl, resource: Model) -> bool:
    return access_control.check_access_level_for_object(resource, "viewer")


def creator_can_access_report_context(
    subscription: Subscription, *, dashboard_ids: Collection[int], insight_ids: Collection[int]
) -> bool:
    expected_dashboard_ids = set(dashboard_ids)
    expected_insight_ids = set(insight_ids)
    if not creator_can_query(user=subscription.created_by, team=subscription.team):
        return False
    assert subscription.created_by is not None
    access_control = UserAccessControl(user=subscription.created_by, team=subscription.team)
    if not expected_dashboard_ids and not expected_insight_ids:
        return True

    context_team_id = subscription.team.parent_team_id or subscription.team_id
    dashboards = list(
        Dashboard.objects_including_soft_deleted.filter(id__in=expected_dashboard_ids, team_id=context_team_id)
    )
    insights = list(
        insights_including_soft_deleted_for_team(
            team_id=context_team_id,
            insight_ids=expected_insight_ids,
        )
    )
    return (
        {dashboard.id for dashboard in dashboards if not dashboard.deleted} == expected_dashboard_ids
        and {insight.id for insight in insights if not insight.deleted} == expected_insight_ids
        and all(_can_view(access_control, dashboard) for dashboard in dashboards)
        and all(_can_view(access_control, insight) for insight in insights)
    )


def _truncate_content(content: str, remaining: int) -> tuple[str, bool]:
    if len(content) <= remaining:
        return content, False
    if remaining <= 0:
        return "", True
    if remaining <= len(_TRUNCATED_CONTEXT_MARKER):
        return _TRUNCATED_CONTEXT_MARKER[-remaining:], True
    return content[: remaining - len(_TRUNCATED_CONTEXT_MARKER)] + _TRUNCATED_CONTEXT_MARKER, True


@frozen
class AiReportInsightContext:
    id: int
    name: str
    status: ReportContextStatus

    def __post_init__(self) -> None:
        if self.status not in ("success", "failed", "truncated"):
            raise ValueError(f"Unknown AI report context status: {self.status}")
        if len(self.name) > CONTEXT_NAME_MAX_LENGTH:
            raise ValueError("AI report context name exceeds its bound")


@frozen
class AiReportDashboardContext:
    id: int
    name: str
    status: ReportContextStatus
    insights: tuple[AiReportInsightContext, ...]

    def __post_init__(self) -> None:
        if self.status not in ("success", "failed", "truncated"):
            raise ValueError(f"Unknown AI report context status: {self.status}")
        if len(self.name) > CONTEXT_NAME_MAX_LENGTH:
            raise ValueError("AI report dashboard name exceeds its bound")


@frozen
class AiReportContexts:
    dashboards: tuple[AiReportDashboardContext, ...] = ()
    insights: tuple[AiReportInsightContext, ...] = ()

    def __post_init__(self) -> None:
        if len(self.dashboards) + len(self.insights) > MAX_SELECTED_CONTEXTS:
            raise ValueError("AI report contexts exceed the selection bound")

    @property
    def has_selection(self) -> bool:
        return bool(self.dashboards or self.insights)


@frozen
class AiReportContext:
    contexts: AiReportContexts = field(default_factory=AiReportContexts)


@frozen
class _FetchOutcome:
    content: str | None = None
    error: str | None = None


class ContextToolRuntime:
    def __init__(
        self,
        *,
        subscription_id: int,
        team: Team,
        user: User,
        selection: ReportContextSelection,
        read_budget: int = MAX_CONTEXT_READ_BUDGET,
    ) -> None:
        self._subscription_id = subscription_id
        self._team = team
        self._user = user
        self._selection = selection
        self._remaining_budget = read_budget
        self._loaded = False
        self._load_lock = asyncio.Lock()
        self._load_error = False

        self._standalone_contexts: dict[int, InsightContext] = {}
        self._dashboard_tile_contexts: dict[int, dict[int, InsightContext]] = {}
        self._insight_meta: dict[int, tuple[str, str]] = {}
        self._insight_events: dict[int, tuple[str, ...]] = {}
        self._dashboard_meta: dict[int, tuple[str, str, tuple[int, ...]]] = {}
        self._load_failed_insight_ids: set[int] = set()
        self._load_failed_dashboard_ids: set[int] = set()

        self._memo: dict[_RegistrationKey, str] = {}
        self._insight_fetch_status: dict[_RegistrationKey, ReportContextStatus] = {}
        self._schema_parts: list[str] = []
        self._fallback_schema_parts: list[str] = []

    async def ensure_loaded(self) -> None:
        # Runs the lazy load exactly once with no fetches, so a selected ref that is already
        # unavailable (deleted, revoked access) surfaces in `statuses` even if the model never
        # calls a tool.
        if not self._loaded:
            async with self._load_lock:
                if not self._loaded:
                    await database_sync_to_async(self._load, thread_sensitive=False)()
                    await self._populate_fallback_schema_parts()
                    self._loaded = True

    async def _populate_fallback_schema_parts(self) -> None:
        # A frozen-plan run reconstructs its spec from the saved plan and never dispatches
        # fetch_insight/fetch_dashboard, so `_schema_parts` (only populated by a fetch) stays
        # empty and the HogQL repair loop loses its saved-query grounding. Precompute a
        # fetch-free schema for every registered context here; `schema_snapshot` only reaches
        # for it when no fetch-derived parts exist.
        contexts = list(self._standalone_contexts.values())
        for tile_contexts in self._dashboard_tile_contexts.values():
            contexts.extend(tile_contexts.values())
        if not contexts:
            return

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CONTEXT_FETCHES)

        async def format_one(context: InsightContext) -> str | None:
            async with semaphore:
                try:
                    schema_text = await context.format_schema()
                except Exception as err:
                    capture_exception(err)
                    return None
            return strip_llm_framing_markers(schema_text, max_len=len(schema_text))

        results = await asyncio.gather(*(format_one(context) for context in contexts))
        self._fallback_schema_parts = [part for part in results if part]

    async def dispatch(self, tool_name: str, args: dict[str, Any]) -> str:
        await self.ensure_loaded()

        if self._load_error:
            result = json.dumps(_CONTEXT_UNAVAILABLE_ERROR)
        elif tool_name == "list_selected_contexts":
            result = self._list_selected_contexts()
        elif tool_name == "fetch_insight":
            result = await self._fetch_insight(args["insight_id"])
        elif tool_name == "fetch_dashboard":
            result = await self._fetch_dashboard(args["dashboard_id"], args.get("insight_ids"))
        else:
            result = json.dumps({"error": f"unknown tool {tool_name}"})

        # The per-insight memo already caps each tile at CONTEXT_RESULT_MAX_CHARS, but
        # fetch_dashboard concatenates several tiles into one JSON payload with no aggregate bound,
        # so every dispatch return gets the same cap applied once more here.
        return _truncate_content(result, CONTEXT_RESULT_MAX_CHARS)[0]

    def tool_schemas(self) -> list[type[BaseModel]]:
        return [ListSelectedContextsArgs, FetchInsightArgs, FetchDashboardArgs]

    @property
    def fetched_refs(self) -> tuple[str, ...]:
        # An insight that is both a standalone selection and a tile of an attached dashboard
        # contributes one insight ref regardless of which registration(s) actually succeeded, so
        # refs are deduplicated through dict keys rather than a list.
        refs: dict[str, None] = {}
        for insight_id in self._selection.insight_ids:
            if self._insight_fetch_status.get((None, insight_id)) == "success":
                refs[insight_ref(insight_id)] = None
        for dashboard_id in self._selection.dashboard_ids:
            meta = self._dashboard_meta.get(dashboard_id)
            if meta is None:
                continue
            dashboard_succeeded = False
            for tile_id in meta[2]:
                if self._insight_fetch_status.get((dashboard_id, tile_id)) == "success":
                    refs[insight_ref(tile_id)] = None
                    dashboard_succeeded = True
            if dashboard_succeeded:
                refs[dashboard_ref(dashboard_id)] = None
        return tuple(refs.keys())

    @property
    def statuses(self) -> AiReportContexts:
        dashboards: list[AiReportDashboardContext] = []
        for dashboard_id in self._selection.dashboard_ids:
            if dashboard_id in self._load_failed_dashboard_ids:
                dashboards.append(
                    AiReportDashboardContext(
                        id=dashboard_id, name="Unavailable dashboard", status="failed", insights=()
                    )
                )
                continue
            meta = self._dashboard_meta.get(dashboard_id)
            if meta is None:
                continue
            name, _, tile_ids = meta
            tile_statuses = tuple(
                AiReportInsightContext(id=tile_id, name=self._insight_meta[tile_id][0], status=status)
                for tile_id in tile_ids
                if (status := self._insight_fetch_status.get((dashboard_id, tile_id))) is not None
            )
            if not tile_statuses:
                continue
            dashboard_status: ReportContextStatus = (
                "success" if any(tile.status == "success" for tile in tile_statuses) else "failed"
            )
            dashboards.append(
                AiReportDashboardContext(id=dashboard_id, name=name, status=dashboard_status, insights=tile_statuses)
            )

        insights: list[AiReportInsightContext] = []
        for insight_id in self._selection.insight_ids:
            if insight_id in self._load_failed_insight_ids:
                insights.append(AiReportInsightContext(id=insight_id, name="Unavailable insight", status="failed"))
                continue
            status = self._insight_fetch_status.get((None, insight_id))
            if status is None:
                continue
            insights.append(
                AiReportInsightContext(id=insight_id, name=self._insight_meta[insight_id][0], status=status)
            )

        return AiReportContexts(dashboards=tuple(dashboards), insights=tuple(insights))

    @property
    def has_usable_context(self) -> bool:
        return any(status == "success" for status in self._insight_fetch_status.values())

    @property
    def has_selection(self) -> bool:
        return bool(self._selection.dashboard_ids or self._selection.insight_ids)

    @property
    def selected_context_count(self) -> int:
        return len(self._selection.dashboard_ids) + len(self._selection.insight_ids)

    @property
    def schema_snapshot(self) -> ReportContextSchema:
        parts = self._schema_parts or self._fallback_schema_parts
        if not parts:
            return ReportContextSchema()
        per_part_budget = max(0, (REPORT_CONTEXT_SCHEMA_CHAR_BUDGET - 2 * (len(parts) - 1)) // len(parts))
        bounded_parts = [_truncate_content(part, per_part_budget)[0] for part in parts]
        content = "\n\n".join(part for part in bounded_parts if part)
        return ReportContextSchema(content=content[:REPORT_CONTEXT_SCHEMA_CHAR_BUDGET])

    @property
    def relevant_events(self) -> tuple[str, ...]:
        events: dict[str, None] = {}
        for (_, insight_id), status in self._insight_fetch_status.items():
            if status != "success":
                continue
            for event in self._insight_events.get(insight_id, ()):
                events[event] = None
        return tuple(events.keys())

    def _load(self) -> None:
        selection = self._selection
        if selection.over_limit or not creator_can_query(user=self._user, team=self._team):
            self._load_error = True
            self._load_failed_insight_ids = set(selection.insight_ids)
            self._load_failed_dashboard_ids = set(selection.dashboard_ids)
            return

        access_control = UserAccessControl(user=self._user, team=self._team)
        context_team_id = self._team.parent_team_id or self._team.id

        insights_by_id = {
            insight.id: insight
            for insight in insights_including_soft_deleted_for_team(
                team_id=context_team_id, insight_ids=selection.insight_ids
            )
        }
        for insight_id in selection.insight_ids:
            insight = insights_by_id.get(insight_id)
            if insight is None or insight.deleted or not _can_view(access_control, insight):
                self._load_failed_insight_ids.add(insight_id)
                continue
            query = _validated_saved_query(insight)
            if query is None:
                self._load_failed_insight_ids.add(insight_id)
                continue
            name = _safe_text(insight.name or insight.derived_name, CONTEXT_NAME_MAX_LENGTH, "Unnamed insight")
            description = _safe_text(insight.description, CONTEXT_DESCRIPTION_MAX_LENGTH, "")
            self._standalone_contexts[insight.id] = InsightContext(
                team=self._team,
                user=self._user,
                event_source=EventSource.SUBSCRIPTION,
                use_db_pool=True,
                query=query,
                name=name,
                description=description,
                insight_id=insight.short_id,
                insight_model_id=insight.id,
                insight_short_id=insight.short_id,
            )
            self._insight_meta[insight.id] = (name, description)
            self._insight_events[insight.id] = _saved_query_events(insight)

        dashboards_by_id = {
            dashboard.id: dashboard
            for dashboard in Dashboard.objects_including_soft_deleted.filter(
                id__in=selection.dashboard_ids, team_id=context_team_id
            )
        }
        for dashboard_id in selection.dashboard_ids:
            dashboard = dashboards_by_id.get(dashboard_id)
            if dashboard is None or dashboard.deleted or not _can_view(access_control, dashboard):
                self._load_failed_dashboard_ids.add(dashboard_id)
                continue
            self._load_dashboard(dashboard, access_control=access_control, context_team_id=context_team_id)

    def _load_dashboard(self, dashboard: Dashboard, *, access_control: UserAccessControl, context_team_id: int) -> None:
        tile_rows = list(
            DashboardTile.objects.filter(
                dashboard_id=dashboard.id,
                insight_id__isnull=False,
                insight__team_id=context_team_id,
                insight__deleted=False,
            )
            .select_related("insight", "insight__created_by")
            .order_by("id")
        )
        dashboard_variables = dashboard.variables if isinstance(dashboard.variables, dict) else {}
        current_variables = insight_variables_for_team(context_team_id) if dashboard_variables else []
        variables_override = (
            map_stale_to_latest(dashboard_variables, current_variables) if dashboard_variables else None
        )
        dashboard_filters = dashboard.filters if isinstance(dashboard.filters, dict) else None

        tile_ids: list[int] = []
        tile_contexts: dict[int, InsightContext] = {}
        for tile in tile_rows:
            insight = tile.insight
            if insight is None or insight.team_id != context_team_id or not _can_view(access_control, insight):
                continue
            query = _validated_saved_query(insight)
            if query is None:
                continue
            name = _safe_text(insight.name or insight.derived_name, CONTEXT_NAME_MAX_LENGTH, "Unnamed insight")
            description = _safe_text(insight.description, CONTEXT_DESCRIPTION_MAX_LENGTH, "")
            filters_override = tile.filters_overrides if isinstance(tile.filters_overrides, dict) else None
            tile_contexts[insight.id] = InsightContext(
                team=self._team,
                user=self._user,
                event_source=EventSource.SUBSCRIPTION,
                use_db_pool=True,
                query=query,
                name=name,
                description=description,
                insight_id=insight.short_id,
                insight_model_id=insight.id,
                insight_short_id=insight.short_id,
                dashboard_filters=dashboard_filters,
                filters_override=filters_override,
                variables_override=variables_override or None,
            )
            self._insight_meta[insight.id] = (name, description)
            self._insight_events[insight.id] = _saved_query_events(insight)
            tile_ids.append(insight.id)

        self._dashboard_tile_contexts[dashboard.id] = tile_contexts
        self._dashboard_meta[dashboard.id] = (
            _safe_text(dashboard.name, CONTEXT_NAME_MAX_LENGTH, "Unnamed dashboard"),
            _safe_text(dashboard.description, CONTEXT_DESCRIPTION_MAX_LENGTH, ""),
            tuple(tile_ids),
        )

    def _resolve_insight(self, insight_id: int) -> tuple[_RegistrationKey, InsightContext] | None:
        standalone_context = self._standalone_contexts.get(insight_id)
        if standalone_context is not None:
            return (None, insight_id), standalone_context
        for dashboard_id, tile_contexts in self._dashboard_tile_contexts.items():
            tile_context = tile_contexts.get(insight_id)
            if tile_context is not None:
                return (dashboard_id, insight_id), tile_context
        return None

    def _list_selected_contexts(self) -> str:
        dashboards = []
        for dashboard_id in self._selection.dashboard_ids:
            meta = self._dashboard_meta.get(dashboard_id)
            if meta is None:
                continue
            name, description, tile_ids = meta
            tiles = [
                {
                    "insight_id": tile_id,
                    "name": self._insight_meta[tile_id][0],
                    "description": self._insight_meta[tile_id][1],
                }
                for tile_id in tile_ids
            ]
            dashboards.append({"id": dashboard_id, "name": name, "description": description, "tiles": tiles})

        insights = []
        for insight_id in self._selection.insight_ids:
            if insight_id not in self._standalone_contexts:
                continue
            name, description = self._insight_meta[insight_id]
            insights.append({"id": insight_id, "name": name, "description": description})

        return json.dumps({"remaining_budget": self._remaining_budget, "dashboards": dashboards, "insights": insights})

    async def _fetch_insight(self, insight_id: int) -> str:
        resolved = self._resolve_insight(insight_id)
        if resolved is None:
            return json.dumps({"error": f"insight {insight_id} is not attached to this subscription"})
        key, context = resolved
        outcome = await self._fetch_one(key, context)
        if outcome.error is not None:
            return json.dumps({"error": outcome.error})
        assert outcome.content is not None
        return outcome.content

    async def _fetch_dashboard(self, dashboard_id: int, insight_ids: list[int] | None) -> str:
        tile_contexts = self._dashboard_tile_contexts.get(dashboard_id)
        meta = self._dashboard_meta.get(dashboard_id)
        if tile_contexts is None or meta is None:
            return json.dumps({"error": f"dashboard {dashboard_id} is not attached to this subscription"})
        _, _, tile_ids = meta

        if insight_ids is None:
            if len(tile_ids) > self._remaining_budget:
                tiles = [
                    {
                        "insight_id": tile_id,
                        "name": self._insight_meta[tile_id][0],
                        "description": self._insight_meta[tile_id][1],
                    }
                    for tile_id in tile_ids
                ]
                return json.dumps(
                    {
                        "dashboard_id": dashboard_id,
                        "tiles": tiles,
                        "remaining_budget": self._remaining_budget,
                        "note": "choose which tiles to fetch with fetch_insight or insight_ids",
                    }
                )
            targets = list(tile_ids)
        else:
            targets = insight_ids

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CONTEXT_FETCHES)

        async def fetch_tile(target_id: int) -> dict[str, Any]:
            context = tile_contexts.get(target_id)
            if context is None:
                return {"insight_id": target_id, "error": f"insight {target_id} is not attached to this subscription"}
            async with semaphore:
                outcome = await self._fetch_one((dashboard_id, target_id), context)
            if outcome.error is not None:
                return {"insight_id": target_id, "error": outcome.error}
            return {"insight_id": target_id, "content": outcome.content}

        results = await asyncio.gather(*(fetch_tile(target_id) for target_id in targets))
        return json.dumps({"dashboard_id": dashboard_id, "tiles": results})

    async def _fetch_one(self, key: _RegistrationKey, context: InsightContext) -> _FetchOutcome:
        memoized = self._memo.get(key)
        if memoized is not None:
            return _FetchOutcome(content=memoized)
        if self._remaining_budget <= 0:
            return _FetchOutcome(error="read budget exhausted")

        insight_id = key[1]
        self._remaining_budget -= 1
        try:
            raw = await context.execute_and_format(include_prompt_framing=False)
        except Exception as err:
            capture_exception(err)
            self._insight_fetch_status[key] = "failed"
            return _FetchOutcome(error=f"insight {insight_id} failed to execute")

        cleaned = strip_llm_framing_markers(raw, max_len=len(raw))
        bounded = cleaned[:CONTEXT_RESULT_MAX_CHARS]
        self._memo[key] = bounded
        self._insight_fetch_status[key] = "success"

        schema_text = await context.format_schema()
        self._schema_parts.append(strip_llm_framing_markers(schema_text, max_len=len(schema_text)))
        return _FetchOutcome(content=bounded)
