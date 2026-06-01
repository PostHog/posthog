import json
import asyncio
import logging
from dataclasses import asdict
from typing import Any, Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import WebAnalyticsAssistantFilters

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.dags.common.owners import JobOwners
from posthog.models import Team, User
from posthog.models.health_issue import HealthIssue
from posthog.queries.property_values import get_person_property_values_for_key, get_property_values_for_key
from posthog.rbac.user_access_control import AccessControlLevel
from posthog.scopes import APIScopeObject
from posthog.sync import database_sync_to_async, database_sync_to_async_pool
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from posthog.temporal.health_checks.processing import _process_batch_detection
from posthog.temporal.health_checks.registry import HEALTH_CHECKS, ensure_registry_loaded, get_detect_fn

from products.web_analytics.backend.attribution import AttributionResult, attribute_change
from products.web_analytics.backend.weekly_digest import DigestFilterSpec, build_digest_from_spec, spec_from_filter_dict

from ee.hogai.chat_agent.taxonomy.agent import TaxonomyAgent
from ee.hogai.chat_agent.taxonomy.format import enrich_props_with_descriptions, format_properties_xml
from ee.hogai.chat_agent.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.chat_agent.taxonomy.toolkit import TaxonomyAgentToolkit, TaxonomyErrorMessages
from ee.hogai.chat_agent.taxonomy.tools import TaxonomyTool, ask_user_for_help, base_final_answer
from ee.hogai.chat_agent.taxonomy.types import TaxonomyAgentState
from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import (
    COMPARE_FILTER_PROMPT,
    DATE_FIELDS_PROMPT,
    FILTER_EXAMPLES_PROMPT,
    FILTER_FIELDS_TAXONOMY_PROMPT,
    INVESTIGATOR_PROMPT,
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
                values = await database_sync_to_async(get_property_values_for_key)(
                    property_name, self._team, event_names=None, value=None
                )
        else:
            return TaxonomyErrorMessages.property_not_found(property_name, property_type)

        return self._format_property_values(property_name, values, sample_count=len(values))


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


INVESTIGATE_WEB_ANALYTICS_DESCRIPTION = """
- Investigate the current team's web analytics: identify what's notable in their traffic and, crucially,
  explain WHY it changed — by decomposing the change across channels, entry pages, devices, countries and
  referrers to find the segment driving it, and correlating with annotations, error spikes, and running
  experiments. Ends by offering concrete next steps (pull session recordings of the affected users, create
  an insight, or set an alert).
- When to use the tool:
  * When the user asks WHY a metric changed ("why did visitors drop", "what's driving my bounce rate")
  * When the user asks "what changed" / "what's notable" / "any anomalies" / "investigate my traffic"
  * When the user wants more than the dashboard shows — an explanation, not just the numbers
    - synonyms: "recap", "overview", "what's going on with", "how is", "summarize", "dig into"
- Do NOT use the tool:
  * When the user wants to change filters on the page (use `filter_web_analytics` instead)
  * When the user is debugging why their setup looks wrong or data is missing (use `web_analytics_doctor`)
""".strip()


class InvestigateWebAnalyticsArgs(BaseModel):
    date_from: str | None = Field(
        default=None,
        description="Start of the analysis window, e.g. '-7d' or '2026-01-01'. Falls back to the filters the user is viewing, then to the last 7 days.",
    )
    date_to: str | None = Field(
        default=None,
        description="End of the analysis window. Same formats as date_from, or omit for an open-ended range up to now.",
    )
    compare: bool | None = Field(
        default=None,
        description="Whether to include period-over-period change against the prior equal-length period.",
    )
    filter_test_accounts: bool | None = Field(
        default=None, description="Whether to exclude internal/test-account events from the analysis."
    )
    do_path_cleaning: bool | None = Field(
        default=None, description="Whether to apply the team's path-cleaning rules before bucketing by page path."
    )


class InvestigateWebAnalyticsTool(MaxTool):
    name: str = "investigate_web_analytics"
    description: str = INVESTIGATE_WEB_ANALYTICS_DESCRIPTION
    context_prompt_template: str = "Current web analytics filters are: {filters}"
    args_schema: type[BaseModel] = InvestigateWebAnalyticsArgs

    def get_required_resource_access(
        self,
    ) -> list[tuple[APIScopeObject, AccessControlLevel]]:
        return [("web_analytics", "viewer")]

    def _resolve_spec(self, args: dict[str, Any]) -> DigestFilterSpec:
        filters: dict[str, Any] = dict(self.context.get("filters") or {})
        for key, value in args.items():
            if value is not None:
                filters[key] = value
        return spec_from_filter_dict(filters)

    async def _arun_impl(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        compare: bool | None = None,
        filter_test_accounts: bool | None = None,
        do_path_cleaning: bool | None = None,
    ) -> tuple[str, dict[str, Any]]:
        spec = self._resolve_spec(
            {
                "date_from": date_from,
                "date_to": date_to,
                "compare": compare,
                "filter_test_accounts": filter_test_accounts,
                "do_path_cleaning": do_path_cleaning,
            }
        )
        digest = await database_sync_to_async(build_digest_from_spec)(self._team, spec)

        # attribute_change never raises (returns None on failure), so the investigation always renders.
        attribution = await database_sync_to_async(attribute_change)(self._team, spec, digest)

        content = _format_investigation_content(spec, digest, attribution=attribution)
        return content, {
            "digest": digest,
            "attribution": asdict(attribution) if attribution else None,
        }


def _format_investigation_content(
    spec: DigestFilterSpec,
    digest: dict[str, Any],
    *,
    attribution: AttributionResult | None = None,
) -> str:
    sections = [INVESTIGATOR_PROMPT, "", "Filter context:", _format_filter_context_for_prompt(spec)]

    if attribution and attribution.primary_driver:
        sections += [
            "",
            "Change attribution (what's driving the visitor change):",
            _format_attribution_for_prompt(attribution),
        ]

    sections += ["", "Data (period-over-period change present when available):", json.dumps(digest, default=str)]
    return "\n".join(sections)


def _format_attribution_for_prompt(attribution: AttributionResult) -> str:
    driver = attribution.primary_driver
    lines = [
        f"- Overall **{attribution.metric}**: {attribution.overall_previous} → {attribution.overall_current} "
        f"(Δ {attribution.overall_delta:+})",
    ]
    if driver:
        share = f" ({driver.contribution_pct}% of the change)" if driver.contribution_pct is not None else ""
        lines.append(
            f"- Primary driver — **{driver.dimension} = `{driver.segment}`**: {driver.previous} → {driver.current} "
            f"(Δ {driver.delta:+}){share}"
        )
    for f in attribution.per_dimension:
        if driver and f.dimension == driver.dimension:
            continue
        # Other dimensions are alternative slices of the same change, not additive — show the segment and
        # delta but no contribution %, since summing %s across overlapping slices would be meaningless.
        lines.append(f"- Also visible by {f.dimension}: `{f.segment}` Δ {f.delta:+}")
    return "\n".join(lines)


def _format_filter_context_for_prompt(spec: DigestFilterSpec) -> str:
    lines = []
    date_from = spec.date_range.date_from or "(beginning of available data)"
    date_to = spec.date_range.date_to or "(now)"
    lines.append(f"- Date range: {date_from} to {date_to}")
    lines.append(f"- Period comparison: {'on (vs prior equal-length period)' if spec.compare else 'off'}")
    lines.append(f"- Filter test accounts: {spec.filter_test_accounts}")
    lines.append(f"- Path cleaning: {spec.do_path_cleaning}")
    if spec.conversion_goal is not None:
        lines.append(f"- Conversion goal: {json.dumps(spec.conversion_goal.model_dump(), default=str)}")
    if spec.properties:
        lines.append(f"- Property filters: {json.dumps(spec.properties, default=str)}")
    else:
        lines.append("- Property filters: none")
    return "\n".join(lines)


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
