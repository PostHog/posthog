import json
import asyncio
import logging
from datetime import date
from typing import Any, Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import PropertyType, PropertyValuesQuery, WebAnalyticsAssistantFilters

from posthog.hogql import ast
from posthog.hogql.ast import Constant
from posthog.hogql.constants import LimitContext
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.dags.common.owners import JobOwners
from posthog.hogql_queries.property_values_query_runner import PropertyValuesQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User
from posthog.models.health_issue import HealthIssue
from posthog.queries.property_values import get_person_property_values_for_key
from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject
from posthog.sync import database_sync_to_async, database_sync_to_async_pool
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from posthog.temporal.health_checks.processing import _process_batch_detection
from posthog.temporal.health_checks.registry import HEALTH_CHECKS, ensure_registry_loaded, get_detect_fn

from products.replay_vision.backend.facade.api import fetch_page_session_observations
from products.web_analytics.backend.api.heatmaps_api import (
    DEFAULT_QUERY,
    FOLD_SUMMARY_QUERY,
    SCROLL_DEPTH_QUERY,
    HeatmapsRequestSerializer,
    HeatmapViewSet,
    parse_fold_summary_row,
)
from products.web_analytics.backend.heatmap_screenshot_grounding import GroundingResult, ground_heatmap_hotspots

from ee.hogai.chat_agent.taxonomy.agent import TaxonomyAgent
from ee.hogai.chat_agent.taxonomy.format import enrich_props_with_descriptions, format_properties_xml
from ee.hogai.chat_agent.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.chat_agent.taxonomy.toolkit import TaxonomyAgentToolkit, TaxonomyErrorMessages
from ee.hogai.chat_agent.taxonomy.tools import TaxonomyTool, ask_user_for_help, base_final_answer
from ee.hogai.chat_agent.taxonomy.types import TaxonomyAgentState
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName
from ee.hogai.utils.untrusted import as_untrusted_data

from .prompts import (
    COMPARE_FILTER_PROMPT,
    DATE_FIELDS_PROMPT,
    FILTER_EXAMPLES_PROMPT,
    FILTER_FIELDS_TAXONOMY_PROMPT,
    PATH_CLEANING_PROMPT,
    PRODUCT_DESCRIPTION_PROMPT,
    USER_FILTER_OPTIONS_PROMPT,
)


class final_answer(base_final_answer[WebAnalyticsAssistantFilters]):
    __doc__ = base_final_answer.__doc__


class retrieve_web_analytics_property_values(BaseModel):
    """
    Use this tool to lookup values for a web analytics property (event, session, or person properties).
    """

    property_key: str = Field(
        description="The key of the property to look up values for (e.g., $host, $browser, $entry_utm_source)",
    )
    property_type: Literal["event", "session", "person"] = Field(
        description="The type of property: 'event' for web event properties, 'session' for session properties, 'person' for person properties",
    )


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class WebAnalyticsFilterOptionsToolkit(TaxonomyAgentToolkit):
    def __init__(self, team: Team, user: User) -> None:
        super().__init__(team, user)

    async def handle_tools(self, tool_metadata: dict[str, list[tuple[TaxonomyTool, str]]]) -> dict[str, str]:
        results = {}
        unhandled_tools = {}
        for tool_name, tool_inputs in tool_metadata.items():
            if tool_name == "retrieve_web_analytics_property_values":
                if tool_inputs:
                    for tool_input, tool_call_id in tool_inputs:
                        result = await self._retrieve_web_analytics_property_values(
                            tool_input.arguments.property_key,  # type: ignore
                            tool_input.arguments.property_type,  # type: ignore
                        )
                        results[tool_call_id] = result
            else:
                unhandled_tools[tool_name] = tool_inputs

        if unhandled_tools:
            results.update(await super().handle_tools(unhandled_tools))
        return results

    def _get_custom_tools(self) -> list:
        return [final_answer, retrieve_web_analytics_property_values]

    def get_tools(self) -> list:
        return [*self._get_custom_tools(), ask_user_for_help]

    async def _retrieve_web_analytics_property_values(
        self, property_name: str, property_type: Literal["event", "session", "person"]
    ) -> str:
        if property_type == "person":
            with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
                values = await database_sync_to_async(get_person_property_values_for_key)(
                    property_name, self._team, value=None
                )
        elif property_type in ("event", "session"):
            with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
                values = await database_sync_to_async(self._retrieve_event_property_values)(property_name)
        else:
            return TaxonomyErrorMessages.property_not_found(property_name, property_type)

        return self._format_property_values(property_name, values, sample_count=len(values))

    def _retrieve_event_property_values(self, property_name: str) -> list:
        # Web analytics event and session property values both live on events.properties, so they
        # share the EVENT path of PropertyValuesQueryRunner (there is no SESSION property type).
        runner = PropertyValuesQueryRunner(
            team=self._team,
            query=PropertyValuesQuery(property_type=PropertyType.EVENT, property_key=property_name),
            user=self._user,
        )
        response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        return [item.name for item in getattr(response, "results", []) or []]


class WebAnalyticsFilterNode(TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[WebAnalyticsAssistantFilters]]):
    def __init__(
        self,
        team: Team,
        user: User,
        toolkit_class: type[WebAnalyticsFilterOptionsToolkit],
    ) -> None:
        super().__init__(team, user, toolkit_class=toolkit_class)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.WEB_ANALYTICS_FILTER

    def _filter_properties_by_type(self, property_group: str) -> list[tuple[str, str]]:
        """Extract properties from CORE_FILTER_DEFINITIONS_BY_GROUP for a given property group."""
        return [
            (prop_name, prop["type"])
            for prop_name, prop in CORE_FILTER_DEFINITIONS_BY_GROUP.get(property_group, {}).items()
            if prop.get("type") is not None
        ]

    def _get_system_prompt(self) -> ChatPromptTemplate:
        event_properties = self._filter_properties_by_type("event_properties")
        session_properties = self._filter_properties_by_type("session_properties")
        person_properties = self._filter_properties_by_type("person_properties")

        all_messages = [
            PRODUCT_DESCRIPTION_PROMPT,
            FILTER_EXAMPLES_PROMPT,
            FILTER_FIELDS_TAXONOMY_PROMPT,
            f"<event_properties>\n{format_properties_xml(enrich_props_with_descriptions('event', event_properties))}\n</event_properties>",
            f"<session_properties>\n{format_properties_xml(enrich_props_with_descriptions('session', session_properties))}\n</session_properties>",
            f"<person_properties>\n{format_properties_xml(enrich_props_with_descriptions('person', person_properties))}\n</person_properties>",
            PATH_CLEANING_PROMPT,
            COMPARE_FILTER_PROMPT,
            DATE_FIELDS_PROMPT,
            *super()._get_default_system_prompts(),
        ]
        system_messages = [("system", message) for message in all_messages]
        return ChatPromptTemplate(system_messages, template_format="mustache")


class WebAnalyticsFilterOptionsToolsNode(
    TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[WebAnalyticsAssistantFilters]]
):
    def __init__(
        self,
        team: Team,
        user: User,
        toolkit_class: type[WebAnalyticsFilterOptionsToolkit],
    ) -> None:
        super().__init__(team, user, toolkit_class=toolkit_class)

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.WEB_ANALYTICS_FILTER_OPTIONS_TOOLS


class WebAnalyticsFilterOptionsGraph(
    TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[WebAnalyticsAssistantFilters]]
):
    def __init__(self, team: Team, user: User) -> None:
        super().__init__(
            team,
            user,
            loop_node_class=WebAnalyticsFilterNode,
            tools_node_class=WebAnalyticsFilterOptionsToolsNode,
            toolkit_class=WebAnalyticsFilterOptionsToolkit,
        )


class FilterWebAnalyticsArgs(BaseModel):
    change: str = Field(
        description=(
            "The specific change to be made to the web analytics filters, briefly described. "
            "Include ALL relevant details that may or may not be needed, as the tool won't receive the history of this conversation."
        )
    )


class FilterWebAnalyticsTool(MaxTool):
    name: str = "filter_web_analytics"
    description: str = """
    - Update web analytics filters on this page, in order to better analyze web traffic and user behavior.
    - When to use the tool:
      * When the user asks to update web analytics filters
        - "update" synonyms: "change", "modify", "adjust", and similar
        - "web analytics" synonyms: "traffic", "visitors", "pageviews", and similar
      * When the user asks to search for web analytics or traffic data
        - "search for" synonyms: "find", "look up", "show me", and similar
      * When the user asks to enable/disable path cleaning or comparison
    """
    context_prompt_template: str = "Current web analytics filters are: {current_filters}"
    args_schema: type[BaseModel] = FilterWebAnalyticsArgs

    def get_required_resource_access(
        self,
    ) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("web_analytics", "viewer")]

    async def _invoke_graph(self, change: str) -> dict[str, Any] | Any:
        graph = WebAnalyticsFilterOptionsGraph(team=self._team, user=self._user)
        pretty_filters = json.dumps(self.context.get("current_filters", {}), indent=2)
        user_prompt = USER_FILTER_OPTIONS_PROMPT.format(change=change, current_filters=pretty_filters)
        graph_context = {
            "change": user_prompt,
            "output": None,
            "tool_progress_messages": [],
            **self.context,
        }
        result = await graph.compile_full_graph().ainvoke(graph_context)
        return result

    async def _arun_impl(self, change: str) -> tuple[str, WebAnalyticsAssistantFilters]:
        result = await self._invoke_graph(change)
        if type(result["output"]) is not WebAnalyticsAssistantFilters:
            content = result["intermediate_steps"][-1][0].tool_input
            filters = WebAnalyticsAssistantFilters.model_validate(self.context.get("current_filters", {}))
        else:
            try:
                content = "✅ Updated web analytics filters."
                filters = WebAnalyticsAssistantFilters.model_validate(result["output"])
            except Exception as e:
                raise ValueError(f"Failed to generate WebAnalyticsAssistantFilters: {e}")
        return content, filters


WEB_ANALYTICS_DOCTOR_DESCRIPTION = """
- Diagnose problems with the current team's Web Analytics setup and explain how to fix them.
- When to use the tool:
  * When the user asks why their web analytics looks wrong, low, missing, or off
    - "wrong" synonyms: "broken", "weird", "off", "not right", "messed up"
    - "low" synonyms: "missing", "no", "few", "zero"
    - data shape synonyms: "pageviews", "visitors", "sessions", "bounce rate", "traffic"
  * When the user asks to debug / troubleshoot / diagnose / fix / check their web analytics setup
  * When the user mentions reverse proxy coverage, host or domain not appearing, missing referrers, scroll depth, or Web Vitals not showing up
  * When the user asks "is my web analytics set up correctly?" or similar
- Do NOT use the tool:
  * When the user is asking about a specific managed reverse proxy record by name or id (use `diagnose_proxy` instead)
  * When the user just wants to change filters on the page (use `filter_web_analytics` instead)
""".strip()


class WebAnalyticsDoctorArgs(BaseModel):
    pass


class WebAnalyticsDoctorTool(MaxTool):
    name: str = "web_analytics_doctor"
    description: str = WEB_ANALYTICS_DOCTOR_DESCRIPTION
    args_schema: type[BaseModel] = WebAnalyticsDoctorArgs

    def get_required_resource_access(
        self,
    ) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("web_analytics", "viewer")]

    async def _arun_impl(self) -> tuple[str, dict[str, Any]]:
        await database_sync_to_async(ensure_registry_loaded)()
        web_kinds = sorted(kind for kind, reg in HEALTH_CHECKS.items() if reg.owner == JobOwners.TEAM_WEB_ANALYTICS)

        reevaluate_async = database_sync_to_async_pool(_reevaluate_one_check)

        async def reevaluate(kind: str) -> str | None:
            try:
                await reevaluate_async(self._team.id, kind)
                return None
            except Exception:
                logger.exception(
                    "web_analytics_doctor re-evaluation failed",
                    extra={"kind": kind, "team_id": self._team.id},
                )
                return kind

        results = await asyncio.gather(*(reevaluate(kind) for kind in web_kinds))
        failed_kinds = [k for k in results if k is not None]

        issues = await database_sync_to_async(_load_active_web_issues)(self._team.id, web_kinds)

        content = _format_doctor_content(issues, ran_kinds=web_kinds, failed_kinds=failed_kinds)
        artifact = {
            "issues": [_serialize_issue(i) for i in issues],
            "ran_kinds": web_kinds,
            "failed_kinds": failed_kinds,
        }
        return content, artifact


def _reevaluate_one_check(team_id: int, kind: str) -> None:
    detect_fn = get_detect_fn(kind)
    _process_batch_detection(team_ids=[team_id], kind=kind, detect_fn=detect_fn)


def _load_active_web_issues(team_id: int, kinds: list[str]) -> list[HealthIssue]:
    return list(
        HealthIssue.objects.filter(
            team_id=team_id,
            kind__in=kinds,
            status=HealthIssue.Status.ACTIVE,
            dismissed=False,
        ).order_by("kind")
    )


def _serialize_issue(issue: HealthIssue) -> dict[str, Any]:
    return {"kind": issue.kind, "severity": issue.severity, "payload": issue.payload}


_SEVERITY_ORDER: dict[str, int] = {
    HealthIssue.Severity.CRITICAL: 0,
    HealthIssue.Severity.WARNING: 1,
    HealthIssue.Severity.INFO: 2,
}

_SEVERITY_MARKER: dict[str, str] = {
    HealthIssue.Severity.CRITICAL: "×",
    HealthIssue.Severity.WARNING: "!",
    HealthIssue.Severity.INFO: "i",
}


def _format_doctor_content(issues: list[HealthIssue], *, ran_kinds: list[str], failed_kinds: list[str]) -> str:
    if not issues:
        kinds_summary = ", ".join(ran_kinds) if ran_kinds else "(no checks registered)"
        msg = f"Your Web Analytics setup looks healthy — no active issues detected. Checks evaluated: {kinds_summary}."
        if failed_kinds:
            msg += f"\n\nNote: {len(failed_kinds)} check(s) could not be re-evaluated: {', '.join(failed_kinds)}."
        return msg

    sorted_issues = sorted(issues, key=lambda i: (_SEVERITY_ORDER.get(i.severity, 99), i.kind))
    lines = [f"Found **{len(sorted_issues)}** active Web Analytics issue(s):", ""]
    for issue in sorted_issues:
        lines.extend(_format_doctor_issue(issue))
    if failed_kinds:
        lines.append("")
        lines.append(f"Note: {len(failed_kinds)} check(s) could not be re-evaluated: {', '.join(failed_kinds)}.")
    return "\n".join(lines)


def _format_doctor_issue(issue: HealthIssue) -> list[str]:
    marker = _SEVERITY_MARKER.get(issue.severity, "?")
    payload = issue.payload or {}
    reason = payload.get("reason", "(no description provided)")
    lines = [f"- [{marker}] **{issue.kind}** ({issue.severity}): {reason}"]
    proxied = payload.get("proxied_hosts")
    if proxied:
        lines.append(f"    - proxied hosts: {', '.join(proxied)}")
    unproxied = payload.get("unproxied_hosts")
    if unproxied:
        lines.append(f"    - unproxied hosts: {', '.join(unproxied)}")
    return lines


ASSESS_HEATMAP_DESCRIPTION = """
- Assess what a page's heatmap is telling you and recommend concrete changes. Pulls click, rageclick, and
  scroll-depth data for a URL, reads the above/below-the-fold split, and names the elements under the hot
  spots by cross-referencing autocapture clicks on the same page.
- When to use the tool:
  * When the user asks what a heatmap shows, or to "analyze" / "assess" / "review" the heatmap for a page
  * When the user asks why people aren't clicking something, where users rage-click, how far they scroll, or
    what to change on a page based on heatmap or click data
- Do NOT use the tool:
  * When the user only wants to create a saved heatmap screenshot with no analysis
  * When the user is asking about session replay in general (use the replay tools instead)
- You must pass an exact `page_url` (full URL including scheme and host). Confirm it with the user if ambiguous.
""".strip()


class AssessHeatmapArgs(BaseModel):
    page_url: str = Field(
        description="The exact page URL to assess, including scheme and host "
        "(e.g. 'https://posthog.com/pricing'). The trailing slash is ignored.",
    )
    date_from: str = Field(
        default="-7d",
        description="Start of the window. Relative (e.g. '-7d', '-30d') or absolute 'YYYY-MM-DD'. "
        "Defaults to the last 7 days; widen to '-30d' if volume is low. Heatmap data is retained for 90 days.",
    )
    date_to: str | None = Field(
        default=None,
        description="End of the window, inclusive. Relative or absolute 'YYYY-MM-DD'. Defaults to today.",
    )
    viewport_width_min: int | None = Field(
        default=None,
        description="Only include interactions captured at a viewport at least this wide, in CSS pixels. "
        "Use with viewport_width_max to isolate a device class (e.g. 360-768 for mobile); desktop and mobile "
        "have very different folds, so prefer assessing one band at a time.",
    )
    viewport_width_max: int | None = Field(
        default=None,
        description="Only include interactions captured at a viewport at most this wide, in CSS pixels.",
    )


class AssessHeatmapTool(MaxTool):
    name: str = "assess_heatmap"
    description: str = ASSESS_HEATMAP_DESCRIPTION
    args_schema: type[BaseModel] = AssessHeatmapArgs

    def get_required_resource_access(
        self,
    ) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("web_analytics", "viewer")]

    async def _arun_impl(
        self,
        page_url: str,
        date_from: str = "-7d",
        date_to: str | None = None,
        viewport_width_min: int | None = None,
        viewport_width_max: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        data = await database_sync_to_async(_gather_heatmap_data)(
            self._team,
            self._user,
            page_url=page_url,
            date_from=date_from,
            date_to=date_to,
            viewport_width_min=viewport_width_min,
            viewport_width_max=viewport_width_max,
        )
        content = _format_heatmap_report(page_url, data)
        return content, data


SUMMARIZE_WEBSITE_INTERACTIONS_DESCRIPTION = """
- Summarize how users interact with a page by fusing two signals: the aggregate heatmap (where and how much
  people click, rage-click, and scroll) with Replay Vision observations (per-session narratives of what users
  were trying to do and where they struggled). Heatmaps tell you what and where; Replay Vision tells you why.
- When to use the tool:
  * When the user asks how users are interacting with / behaving on / experiencing a page or their website
  * When the user wants both the numbers and the story behind them for a page — "what are users doing on X and
    why", "summarize engagement on my pricing page", "how do visitors use my homepage"
- Do NOT use the tool:
  * When the user only wants the heatmap numbers and layout recommendations (use `assess_heatmap` instead)
  * When the user is searching session recordings by meaning (use the replay tools instead)
- For a whole-site summary, call this once per top page and synthesize across the results.
- You must pass an exact `page_url` (full URL including scheme and host). Confirm it with the user if ambiguous.
""".strip()


class SummarizeWebsiteInteractionsTool(MaxTool):
    name: str = "summarize_website_interactions"
    description: str = SUMMARIZE_WEBSITE_INTERACTIONS_DESCRIPTION
    args_schema: type[BaseModel] = AssessHeatmapArgs

    def get_required_resource_access(
        self,
    ) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("web_analytics", "viewer"), ("session_recording", "viewer")]

    async def _arun_impl(
        self,
        page_url: str,
        date_from: str = "-7d",
        date_to: str | None = None,
        viewport_width_min: int | None = None,
        viewport_width_max: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        heatmap_data = await database_sync_to_async(_gather_heatmap_data)(
            self._team,
            self._user,
            page_url=page_url,
            date_from=date_from,
            date_to=date_to,
            viewport_width_min=viewport_width_min,
            viewport_width_max=viewport_width_max,
        )
        heatmap_block = _format_heatmap_report(page_url, heatmap_data)

        async def _ground() -> GroundingResult | None:
            if not heatmap_data.get("opted_in"):
                return None
            return await ground_heatmap_hotspots(self._team, self._user, page_url=page_url, heatmap_data=heatmap_data)

        async def _vision() -> tuple[list[str], str | None]:
            try:
                session_ids = await database_sync_to_async(_resolve_page_session_ids)(
                    self._team,
                    self._user,
                    page_url=page_url,
                    date_from=date_from,
                    date_to=date_to,
                    viewport_width_min=viewport_width_min,
                    viewport_width_max=viewport_width_max,
                )
                if not session_ids:
                    return [], None
                observations = await database_sync_to_async(fetch_page_session_observations)(
                    team=self._team, user=self._user, session_ids=session_ids
                )
                return session_ids, observations
            except Exception:
                logger.warning("summarize_website_interactions.vision_half_failed", exc_info=True)
                return [], None

        grounding, (session_ids, vision_block) = await asyncio.gather(_ground(), _vision())

        content = _format_website_interactions_report(
            page_url,
            heatmap_block,
            vision_block,
            session_count=len(session_ids),
            grounding=grounding,
        )
        artifact: dict[str, Any] = {
            "heatmap": heatmap_data,
            "session_count": len(session_ids),
            "has_vision_observations": vision_block is not None,
            "has_screenshot_grounding": grounding is not None,
        }
        if grounding is not None:
            artifact["screenshot"] = {
                "image_b64": grounding.annotated_image_b64,
                "markers": grounding.markers,
            }
        return content, artifact


def _format_website_interactions_report(
    page_url: str,
    heatmap_block: str,
    vision_block: str | None,
    *,
    session_count: int,
    grounding: GroundingResult | None = None,
) -> str:
    """Assemble the two evidence blocks into one report. This is a formatter, not a synthesizer — it labels
    the heatmap (page-level, quantitative) and Vision (whole-session, qualitative) evidence and lets Max's
    outer model do the fusion, mirroring `assess_heatmap` / the Replay Vision tools."""
    sections = [
        f"# How users interact with {page_url}",
        "",
        "## Aggregate heatmap signal — page-level",
        "",
        as_untrusted_data(
            "heatmap_signal",
            [heatmap_block],
            source="derived from captured website interactions and page text",
        ),
        "",
    ]

    if grounding:
        sections.extend(
            [
                f"**What's actually under the hot spots** — a vision model read a page screenshot (captured "
                f"{grounding.screenshot_captured_at}) with the top rage-click spots marked first, then the top "
                "click hot spots, in the order the report lists them; each marker's interaction count ties it "
                "back to a spot above. Hot-spot positions aggregate across visitor viewport widths while the "
                "screenshot has one fixed width, so a marker can sit slightly off vertically.",
                "",
                as_untrusted_data(
                    "screenshot_grounding",
                    [grounding.grounded_text],
                    source="derived from a screenshot of the user's web page",
                ),
                "",
            ]
        )

    sections.extend(
        [
            "## Replay Vision — whole-session color",
            "",
        ]
    )

    if vision_block is not None:
        sections.append(
            f"Replay Vision observations for {session_count} session(s) that interacted on this page. Each "
            "observation summarizes the visitor's **whole session** — which may span several pages — so read "
            "it as qualitative color for people who touched this page, not as page-specific ground truth."
        )
        sections.append("")
        sections.append(vision_block)
    else:
        sections.append(
            "No Replay Vision observations are available for this page's sessions yet. Replay Vision turns "
            "session recordings into per-session narratives of what users were trying to do and where they "
            "struggled. Configure a **summarizer** scanner over your recordings to enrich this report with "
            "the *why* behind the heatmap numbers."
        )

    sections.extend(
        [
            "",
            "---",
            "",
            "Treat the heatmap block as page-level ground truth (where and how much users click, rage-click, "
            "and scroll on this exact page). Treat the Replay Vision block as whole-session color for visitors "
            "who touched this page — never claim a Vision observation describes only this page. Lead with the "
            "quantitative signal and use the session narratives to explain the *why*.",
        ]
    )
    return "\n".join(sections)


# Heatmaps store coordinates as pure geometry — they don't know what was clicked. Cross-referencing
# autocapture clicks on the same URL is what turns "lots of clicks at (0.5, 220)" into "lots of clicks on
# the Pricing link". Grouping by visible text collapses repeats; `any(elements_chain)` keeps one
# representative DOM path for reference (it does not split same-text elements apart). The viewport
# filter mirrors the band applied to the heatmap signals so element identity lines up with the hotspots.
AUTOCAPTURE_ELEMENTS_QUERY = """
SELECT
    properties.$el_text AS el_text,
    any(elements_chain) AS chain,
    count() AS clicks
FROM events
WHERE event = '$autocapture'
  AND trimRight(properties.$current_url, '/') = trimRight({url}, '/')
  AND timestamp >= {date_from}
  AND timestamp <= {date_to} + interval 1 day
  AND notEmpty(properties.$el_text)
  AND {viewport_filter}
GROUP BY el_text
ORDER BY clicks DESC
LIMIT 25
"""

_TOP_POINTS = 15
_TOP_ELEMENTS = 15


def _gather_heatmap_data(
    team: Team,
    user: User,
    *,
    page_url: str,
    date_from: str,
    date_to: str | None,
    viewport_width_min: int | None,
    viewport_width_max: int | None,
) -> dict[str, Any]:
    if not team.heatmaps_opt_in:
        return {"opted_in": False}

    def predicates(heatmap_type: str) -> tuple[dict[str, Any], list[ast.Expr]]:
        return _heatmap_predicates(
            team,
            type=heatmap_type,
            page_url=page_url,
            date_from=date_from,
            date_to=date_to,
            vmin=viewport_width_min,
            vmax=viewport_width_max,
        )

    click_validated, click_exprs = predicates("click")
    # Drop (0, 0) origin noise the same way the heatmaps endpoint does for positional types.
    click_exprs.append(parse_expr("NOT (x = 0 AND y = 0)"))

    _rage_validated, rage_exprs = predicates("rageclick")
    rage_exprs.append(parse_expr("NOT (x = 0 AND y = 0)"))

    _scroll_validated, scroll_exprs = predicates("scrolldepth")

    resolved_from: date = click_validated["date_from"]
    resolved_to: date = click_validated.get("date_to") or date.today()

    return {
        "opted_in": True,
        "page_url": page_url,
        "date_from": resolved_from.isoformat(),
        "date_to": resolved_to.isoformat(),
        "viewport_width_min": viewport_width_min,
        "viewport_width_max": viewport_width_max,
        "clicks": _coordinate_points(team, user, click_exprs),
        "fold": _fold_summary(team, user, click_exprs),
        "rageclicks": _coordinate_points(team, user, rage_exprs),
        "scrolldepth": _scroll_buckets(team, user, scroll_exprs),
        "elements": _autocapture_elements(
            team, user, page_url, resolved_from, resolved_to, viewport_width_min, viewport_width_max
        ),
    }


def _heatmap_predicates(
    team: Team,
    *,
    type: str,
    page_url: str,
    date_from: str,
    date_to: str | None,
    vmin: int | None,
    vmax: int | None,
) -> tuple[dict[str, Any], list[ast.Expr]]:
    """Validate request params the same way the heatmaps endpoint does, then build its filter expressions.

    Reuses `HeatmapsRequestSerializer` (date parsing, url handling) and the endpoint's static placeholder /
    predicate builders so this tool and the API stay in lockstep on what "the heatmap for a page" means.
    """
    request_data: dict[str, Any] = {"type": type, "url_exact": page_url, "date_from": date_from}
    if date_to is not None:
        request_data["date_to"] = date_to
    if vmin is not None:
        request_data["viewport_width_min"] = vmin
    if vmax is not None:
        request_data["viewport_width_max"] = vmax

    serializer = HeatmapsRequestSerializer(data=request_data, context={"team": team})
    serializer.is_valid(raise_exception=True)
    validated = dict(serializer.validated_data)
    # Strip the non-predicate fields the serializer always includes — only the
    # remaining keys map to heatmap filter predicates.
    validated.pop("aggregation", None)
    validated.pop("hide_zero_coordinates", None)
    validated.pop("filter_test_accounts", None)

    placeholders = HeatmapViewSet._build_placeholders(validated)
    exprs = HeatmapViewSet._predicate_expressions(placeholders)
    return validated, exprs


SESSION_IDS_QUERY = """
SELECT DISTINCT session_id
FROM heatmaps
WHERE {predicates} AND notEmpty(session_id)
LIMIT {limit}
"""

_MAX_RESOLVED_SESSIONS = 300


def _resolve_page_session_ids(
    team: Team,
    user: User,
    *,
    page_url: str,
    date_from: str,
    date_to: str | None,
    viewport_width_min: int | None,
    viewport_width_max: int | None,
) -> list[str]:
    """Distinct session ids that clicked on `page_url` in the window, drawn from the heatmaps table.

    Reuses `_heatmap_predicates` so the URL/date/viewport match exactly mirrors the quantitative half; capped
    at `_MAX_RESOLVED_SESSIONS`. Returns `[]` when heatmaps aren't captured or nothing matched.
    """
    if not team.heatmaps_opt_in:
        return []

    _validated, exprs = _heatmap_predicates(
        team,
        type="click",
        page_url=page_url,
        date_from=date_from,
        date_to=date_to,
        vmin=viewport_width_min,
        vmax=viewport_width_max,
    )
    stmt = parse_select(
        SESSION_IDS_QUERY,
        {"predicates": ast.And(exprs=exprs), "limit": ast.Constant(value=_MAX_RESOLVED_SESSIONS)},
    )
    result = _execute(team, user, stmt)
    return [str(row[0]) for row in (result.results or []) if row[0]]


def _execute(team: Team, user: User, stmt: ast.SelectQuery | ast.SelectSetQuery) -> Any:
    context = HogQLContext(team_id=team.pk, limit_top_select=False)
    with tags_context(product=Product.MAX_AI, team_id=team.pk, org_id=team.organization_id):
        return execute_hogql_query(
            query=stmt, team=team, user=user, limit_context=LimitContext.HEATMAPS, context=context
        )


def _coordinate_points(team: Team, user: User, exprs: list[ast.Expr]) -> list[dict[str, Any]]:
    stmt = parse_select(
        DEFAULT_QUERY,
        {
            "aggregation_count": parse_expr("count(*) as cnt"),
            "predicates": ast.And(exprs=exprs),
            "limit": ast.Constant(value=_TOP_POINTS),
            "offset": ast.Constant(value=0),
        },
    )
    result = _execute(team, user, stmt)
    return [
        {
            "pointer_target_fixed": bool(item[0]),
            "pointer_relative_x": item[1],
            "pointer_y": item[2],
            "count": item[3],
        }
        for item in result.results or []
    ]


def _fold_summary(team: Team, user: User, exprs: list[ast.Expr]) -> dict[str, Any]:
    stmt = parse_select(FOLD_SUMMARY_QUERY, {"predicates": ast.And(exprs=exprs)})
    result = _execute(team, user, stmt)
    row = result.results[0] if result.results else None
    return parse_fold_summary_row(row)


def _scroll_buckets(team: Team, user: User, exprs: list[ast.Expr]) -> list[dict[str, Any]]:
    stmt = parse_select(
        SCROLL_DEPTH_QUERY,
        {"aggregation_count": parse_expr("count(*)"), "predicates": ast.And(exprs=exprs)},
    )
    result = _execute(team, user, stmt)
    return [
        {"scroll_depth_bucket": int(item[0]), "bucket_count": int(item[1]), "cumulative_count": int(item[2])}
        for item in result.results or []
    ]


def _autocapture_elements(
    team: Team,
    user: User,
    page_url: str,
    date_from: date,
    date_to: date,
    vmin: int | None,
    vmax: int | None,
) -> list[dict[str, Any]]:
    # Apply the same viewport band as the heatmap signals. $viewport_width is raw CSS pixels (not the
    # /16-scaled heatmap column), coerced like elsewhere in web analytics. A no-op `1 = 1` when unbounded.
    viewport_exprs: list[ast.Expr] = []
    if vmin is not None:
        viewport_exprs.append(
            parse_expr("toIntOrZero(toString(properties.$viewport_width)) >= {v}", {"v": Constant(value=vmin)})
        )
    if vmax is not None:
        viewport_exprs.append(
            parse_expr("toIntOrZero(toString(properties.$viewport_width)) <= {v}", {"v": Constant(value=vmax)})
        )
    viewport_filter: ast.Expr = ast.And(exprs=viewport_exprs) if viewport_exprs else parse_expr("1 = 1")

    stmt = parse_select(
        AUTOCAPTURE_ELEMENTS_QUERY,
        {
            "url": Constant(value=page_url),
            "date_from": Constant(value=date_from),
            "date_to": Constant(value=date_to),
            "viewport_filter": viewport_filter,
        },
    )
    result = _execute(team, user, stmt)
    return [{"text": item[0], "elements_chain": item[1], "clicks": int(item[2])} for item in result.results or []]


def _scroll_reach(buckets: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not buckets:
        return None
    total = max((b["cumulative_count"] for b in buckets), default=0)
    if not total:
        return None
    ascending = sorted(buckets, key=lambda b: b["scroll_depth_bucket"])
    # The deepest bucket still reached by at least `pct` of the population. `None` (not 0,
    # a real depth) when no bucket clears the threshold, so the report can say so honestly.
    reach: dict[int, int | None] = {}
    for pct in (75, 50, 25):
        deepest: int | None = None
        for b in ascending:
            if b["cumulative_count"] / total * 100 >= pct:
                deepest = b["scroll_depth_bucket"]
        reach[pct] = deepest
    return {"total": total, "reach": reach, "max_depth": ascending[-1]["scroll_depth_bucket"]}


def _format_heatmap_report(page_url: str, data: dict[str, Any]) -> str:
    if not data.get("opted_in"):
        return (
            f"Heatmaps aren't enabled for this project, so there's no data to assess for {page_url}. "
            "Turn on heatmap capture in the project's web analytics / autocapture settings "
            "(`Team.heatmaps_opt_in`), then check back once interactions have been recorded."
        )

    clicks = data["clicks"]
    rageclicks = data["rageclicks"]
    fold = data["fold"]
    elements = data["elements"]

    lines = [f"Heatmap assessment for **{page_url}** ({data['date_from']} → {data['date_to']}):", ""]

    band = _viewport_band(data.get("viewport_width_min"), data.get("viewport_width_max"))
    if band:
        lines.append(band)
        lines.append("")

    if not clicks and not rageclicks and fold["total_count"] == 0 and not data["scrolldepth"]:
        lines.append(
            "No heatmap interactions matched this page in the window. Either the URL is off, the page gets "
            "little traffic, or capture isn't recording it — verify the exact URL and that the page is being "
            "visited before concluding there's no engagement. You can widen the window with date_from='-30d'."
        )
        return "\n".join(lines)

    # Fold / scroll reach — the highest-value layout signal.
    lines.append("**Scroll & fold**")
    if fold["median_viewport_height"]:
        lines.append(f"- Typical fold (median viewport height): ~{fold['median_viewport_height']}px")
    if fold["total_count"]:
        lines.append(
            f"- {fold['pct_below_fold']}% of clicks landed below the fold "
            f"({fold['below_fold_count']} of {fold['total_count']} non-fixed clicks) — content people actively "
            "click that sits below the initial viewport is a candidate to move up."
        )
    reach = _scroll_reach(data["scrolldepth"])
    if reach:
        r = reach["reach"]

        def _depth(px: int | None) -> str:
            return f"≥{px}px" if px is not None else "n/a"

        lines.append(
            f"- Scroll reach: 75% of visitors reached {_depth(r[75])}, 50% reached {_depth(r[50])}, "
            f"25% reached {_depth(r[25])} (deepest bucket {reach['max_depth']}px)."
        )
    lines.append("")

    # Rage clicks — the strongest "something is broken or misleading" signal.
    lines.append("**Rage clicks**")
    if rageclicks:
        total_rage = sum(p["count"] for p in rageclicks)
        lines.append(
            f"- {total_rage} rage-click interaction(s) across {len(rageclicks)} spot(s) — repeated frustrated "
            "clicking. Treat any meaningful cluster as broken, slow, or looks-clickable-but-isn't."
        )
        for p in rageclicks[:5]:
            lines.append(f"    - {p['count']}× at x≈{p['pointer_relative_x']}, y≈{p['pointer_y']}px")
    else:
        lines.append("- None detected. 👍")
    lines.append("")

    # Click hotspots.
    lines.append("**Top click hotspots** (relative x is 0–1 across the viewport; y is pixels down the page)")
    if clicks:
        for p in clicks[:_TOP_POINTS]:
            fixed = " (fixed-position)" if p["pointer_target_fixed"] else ""
            lines.append(f"- {p['count']}× at x≈{p['pointer_relative_x']}, y≈{p['pointer_y']}px{fixed}")
    else:
        lines.append("- No click data for this page in the window.")
    lines.append("")

    # Autocapture identity — what actually sits under the clicks.
    lines.append("**What's under the clicks** (top autocapture elements on this page, by click count)")
    if elements:
        for el in elements[:_TOP_ELEMENTS]:
            text = (el["text"] or "").strip().replace("\n", " ")
            label = f'"{text}"' if text else "(no text)"
            lines.append(f"- {el['clicks']}× {label}")
        lines.append("")
        lines.append(
            "Match these elements to the hot coordinates above. Clicks concentrated on something that is NOT a "
            "link or button (plain text, an image, a disabled control) is a classic 'users expect this to be "
            "clickable' finding."
        )
    else:
        lines.append(
            "- No autocapture clicks on this page in the window, so element identity is unavailable. The "
            "coordinates above show where people interact, but not what they hit."
        )
    lines.append("")

    lines.append(
        "Use this to recommend concrete changes, ranked by signal strength: rage-click clusters first, then "
        "clicks on non-interactive elements, then important CTAs sitting below the scroll cliff, then ignored "
        "primary actions. Tie every recommendation to the signal it came from. You're reasoning from "
        "coordinates plus autocapture identity — you can't see the page, so don't claim to."
    )
    return "\n".join(lines)


def _viewport_band(vmin: int | None, vmax: int | None) -> str | None:
    if vmin is None and vmax is None:
        return None
    if vmin is not None and vmax is not None:
        return f"_Filtered to viewports {vmin}–{vmax}px wide._"
    if vmin is not None:
        return f"_Filtered to viewports ≥{vmin}px wide._"
    return f"_Filtered to viewports ≤{vmax}px wide._"
