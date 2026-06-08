"""LLM narrative enrichment for Pulse findings."""

import json
import asyncio
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field

from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL
from posthog.models import OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.sync import database_sync_to_async

from products.annotations.backend.models.annotation import Annotation
from products.pulse.backend.temporal.detection import MAX_BASELINE_WEEKS, MIN_BASELINE_WEEKS, _extract_weekly_series
from products.pulse.backend.temporal.types import EnrichedFinding, Finding, run_trends_query_sync

from ee.hogai.llm import MaxChatOpenAI

logger = structlog.get_logger(__name__)


ATTRIBUTION_PROPERTY_CANDIDATES = [
    "$browser",
    "$os",
    "$device_type",
    "$geoip_country_name",
    "$referring_domain",
]

# Breakdown placeholders that don't name a real segment — never a meaningful attribution or
# a worthwhile replay lookup. A property that's mostly unset makes its null bucket the biggest
# mover, so skipping these keeps attribution on a real segment.
SYNTHETIC_BREAKDOWN_VALUES = {"Other", "unknown", "", BREAKDOWN_OTHER_STRING_LABEL, BREAKDOWN_NULL_STRING_LABEL}

ENRICHMENT_CONCURRENCY = 5
ATTRIBUTION_CONCURRENCY = 5

# Narrative-only LLM: deterministic backbone does detection, the model just writes prose.
# Non-reasoning model on purpose — short factual prose with a hard max_tokens cap. A reasoning
# model (e.g. gpt-5-mini) spends the token budget thinking and returns an empty completion here.
NARRATIVE_MODEL = "gpt-4.1"
NARRATIVE_MAX_TOKENS = 600
NARRATIVE_TIMEOUT_SECONDS = 45.0

# Per-finding references shown as chips, and the label length each one renders at. The prompt asks the
# model for the ~3 most relevant signals; this is a backstop with one slot of slack, not the real control.
MAX_FINDING_REFERENCES = 4
MAX_REFERENCE_LABEL = 60
# Upper bound on how many coincident signals we feed the narrative LLM to choose from — the per-type
# fetch caps already bound this; the extra ceiling keeps the prompt small when many things changed.
MAX_SIGNAL_CATALOG = 30


@dataclass(frozen=True)
class CoincidentSignal:
    """One same-period change the narrative LLM can reference by id, and the UI can turn into a chip.

    `ref_id` is the opaque id the model echoes back in `related_signal_ids`; `detail_id` is the real
    entity pk the frontend builds a deep link from (empty when the entity has no detail page).
    """

    ref_id: str  # opaque id the LLM references, e.g. "s0"
    ref_type: str  # "experiment" | "feature_flag" | "annotation"
    label: str  # display name (flag/experiment name, or annotation note)
    detail_id: str  # entity pk for the deep link, or "" when not linkable
    summary: str  # short human phrase for the prompt, e.g. "turned on 2026-05-20"
    timestamp: str = ""  # full ISO instant, so a referenced signal can be placed on the finding's timeline
    change: str = ""  # the verb (turned on / launched / created), empty for annotations


class _NarrativeOutput(BaseModel):
    """Structured narrative result: the prose plus the ids of the signals the model actually cited."""

    narrative: str = Field(description="The 1-3 sentence explanation of the metric change.")
    related_signal_ids: list[str] = Field(
        default_factory=list,
        description="The `id`s of the coincident_signals you referenced in the narrative. Empty if you cited none.",
    )


def _resolve_service_user(team: Team, user_id: int | None) -> User:
    """Resolve the user MaxChatOpenAI bills/attributes the narrative to.

    Pulse runs without a request, so we pick the subscription creator (passed as
    user_id) and fall back to an org admin. MaxChatOpenAI requires a User even with
    inject_context=False (it reads team.id, not the user, for $ai_generation).
    """
    if user_id is not None:
        user = User.objects.filter(id=user_id).first()
        if user is not None:
            return user
    admin = (
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id, level__gte=OrganizationMembership.Level.ADMIN
        )
        .order_by("-level")
        .select_related("user")
        .first()
    )
    if admin is None:
        raise ValueError(f"No service user available for Pulse narrative on team {team.id}")
    return admin.user


NARRATIVE_SYSTEM_PROMPT = """You are PostHog Pulse, explaining ONE flagged metric change to a product team in 1-3 short sentences.

The reader already sees the metric name, the headline percentage, and the weekly totals next to your text, so do NOT restate them. Add the insight they can't get at a glance:
- WHERE the change is concentrated. If an attribution segment is given, name it with its own numbers — e.g. "Almost all of the gain came from Chrome users (140 vs ~70/week typical)." If no segment is given, say the change looks broad-based rather than tied to one segment.
- A single plausible hypothesis for WHY, framed as something to verify and never as a proven cause. Ground it in the segment's nature: a browser- or device-concentrated change suggests a client release or a campaign reaching that segment; a country-concentrated change suggests a regional launch or seasonality; a referrer- or channel-concentrated change suggests one acquisition source.

You may also be given coincident_signals: things that changed in the SAME period (deploy notes, feature-flag changes, experiment launches), each with an `id`. Most of them will be unrelated noise — be selective. Pick at most the THREE most directly relevant to THIS metric (by name, segment, or timing); if one could plausibly affect it, mention it as a coincidence worth checking — e.g. "lines up with turning on the 'new-onboarding' flag" — and put its `id` in related_signal_ids. Only include ids for signals you actually mention; never list one you didn't reference, and never list one just because it changed this period. If none are clearly relevant, leave related_signal_ids empty.

Stay factual and humble: at most one hypothesis, clearly hedged ("worth checking", "could be"). No recommendations, jargon, emoji, or markdown. Maximum 3 sentences.""".strip()


def _build_breakdown_query(base_query: dict, breakdown_property: str) -> dict:
    query = json.loads(json.dumps(base_query))  # deep copy
    # Attribution is intentionally pinned to a fixed ~4-week window; detection's baseline window is configurable but the breakdown stays fixed for simplicity.
    query["dateRange"] = {"date_from": "-42d", "date_to": None}
    query["interval"] = "week"
    query["breakdownFilter"] = {"breakdown": breakdown_property, "breakdown_type": "event"}
    return query


def _build_daily_query(base_query: dict, period_start: str, period_end: str) -> dict:
    """A daily trends query over the digest period — the line behind the per-finding chart."""
    query = json.loads(json.dumps(base_query))  # deep copy
    query["dateRange"] = {
        "date_from": datetime.fromisoformat(period_start).date().isoformat(),
        "date_to": datetime.fromisoformat(period_end).date().isoformat(),
    }
    query["interval"] = "day"
    if "breakdownFilter" in query:
        query["breakdownFilter"] = None  # headline metric, no breakdown
    return query


async def _fetch_daily_series(team: Team, finding: Finding, period_start: str, period_end: str) -> list[float]:
    """Daily metric values across the period for the finding chart (markers spread intra-day on this axis).

    Best-effort: any failure degrades to [] and the chart falls back to the weekly detection series.
    """
    if not period_start or not period_end:
        return []
    try:
        result = await run_trends_query_sync(
            team, _build_daily_query(finding.descriptor.query, period_start, period_end)
        )
        return _extract_weekly_series(result)  # generic results[0].data extractor (daily values here)
    except Exception as exc:
        logger.warning(
            "pulse_fetch_daily_series_failed", team_id=team.id, metric=finding.descriptor.label, error=str(exc)
        )
        return []


def _pick_top_contributor(result: Any) -> tuple[str, float, float] | None:
    """Find the breakdown value that contributed most to the change.

    Mirrors detection: drop the in-progress (partial) week, compare the last completed week to the
    median of the prior completed weeks, and skip synthetic ("Other"/"no value") buckets — otherwise
    a mostly-unset property makes its null bucket the biggest mover.
    """
    if not isinstance(result, dict):
        return None
    series = result.get("results") or []
    best: tuple[str, float, float] | None = None
    best_delta = 0.0
    for s in series:
        if not isinstance(s, dict):
            continue
        value = str(s.get("breakdown_value") or s.get("label") or "unknown")
        if value in SYNTHETIC_BREAKDOWN_VALUES:
            continue
        data = [float(v) for v in (s.get("data") or []) if isinstance(v, int | float) and not isinstance(v, bool)]
        if len(data) < MIN_BASELINE_WEEKS + 2:
            continue
        completed = data[:-1]  # drop the partial current week
        current = completed[-1]
        baseline = completed[:-1][-MAX_BASELINE_WEEKS:]
        if len(baseline) < MIN_BASELINE_WEEKS:
            continue
        baseline_median = statistics.median(baseline)
        delta = abs(current - baseline_median)
        if delta > best_delta:
            best_delta = delta
            best = (value, current, baseline_median)
    return best


async def _attribute_finding(
    team: Team, finding: Finding, attribution_semaphore: asyncio.Semaphore
) -> dict[str, Any] | None:
    async def _try_property(prop: str) -> tuple[str, dict[str, Any]] | None:
        async with attribution_semaphore:
            try:
                result = await run_trends_query_sync(team, _build_breakdown_query(finding.descriptor.query, prop))
            except Exception as exc:
                logger.exception(
                    "pulse_attribution_breakdown_failed",
                    team_id=team.id,
                    metric=finding.descriptor.label,
                    property=prop,
                    error=str(exc),
                )
                return None
            top = _pick_top_contributor(result)
            if top is None:
                return None
            value, current, prior = top
            return prop, {
                "property": prop,
                # Sanitized at the source: the segment value can be externally influenced (e.g. a
                # $referring_domain), and it flows into the LLM prompt, the fallback prose, and the UI.
                "value": _sanitize_for_prompt(str(value)),
                "current": current,
                "baseline": prior,
                "_contribution": abs(current - prior),
            }

    results = await asyncio.gather(*[_try_property(p) for p in ATTRIBUTION_PROPERTY_CANDIDATES])
    best = max(
        (r[1] for r in results if r is not None),
        key=lambda d: d["_contribution"],
        default=None,
    )
    if best is None:
        return None
    best.pop("_contribution", None)
    return best


async def _generate_narrative(
    team: Team,
    user: User,
    finding: Finding,
    attribution: dict[str, Any] | None,
    signal_catalog: list[CoincidentSignal] | None = None,
) -> tuple[str, list[str]]:
    """Write the per-finding prose and return which coincident signals the model tied to it.

    The model is shown the catalog (each signal carries an `id`) and asked to echo back the ids it
    actually references — so the UI can show exactly the related changes that prompted this finding,
    not the whole period's churn. Returns (narrative, related_ref_ids); ref_ids are validated against
    the catalog, so a hallucinated id is dropped.
    """
    catalog = signal_catalog or []
    facts = {
        "metric": _sanitize_for_prompt(finding.descriptor.label),
        "direction": "up" if finding.change_pct > 0 else "down",
        "current_value": round(finding.current_value, 2),
        "baseline_value": round(finding.baseline_value, 2),
        "absolute_change": round(finding.current_value - finding.baseline_value, 2),
        "change_pct": round(finding.change_pct, 3),
        "robust_z": round(finding.robust_z, 2),
        "attribution": attribution,
        "coincident_signals": [
            {"id": s.ref_id, "type": s.ref_type, "name": s.label, "when": s.summary} for s in catalog
        ]
        or None,
    }

    llm = MaxChatOpenAI(
        model=NARRATIVE_MODEL,
        user=user,
        team=team,
        temperature=0.2,
        max_tokens=NARRATIVE_MAX_TOKENS,
        request_timeout=NARRATIVE_TIMEOUT_SECONDS,
        streaming=False,
        disable_streaming=True,
        max_retries=3,
        billable=False,
        inject_context=False,
        posthog_properties={"ai_product": "pulse", "domain": "pulse"},
    )
    structured_llm = llm.with_structured_output(_NarrativeOutput, method="function_calling", include_raw=False)
    messages = [
        SystemMessage(content=NARRATIVE_SYSTEM_PROMPT),
        HumanMessage(content=f"Finding facts:\n{json.dumps(facts, default=str)}"),
    ]
    result = await structured_llm.ainvoke(messages)
    output = result if isinstance(result, _NarrativeOutput) else _NarrativeOutput.model_validate(result)
    valid_ids = {s.ref_id for s in catalog}
    related = [ref_id for ref_id in dict.fromkeys(output.related_signal_ids) if ref_id in valid_ids]
    return output.narrative.strip(), related


def _fallback_narrative(finding: Finding, attribution: dict[str, Any] | None = None) -> str:
    """Deterministic narrative used when the LLM is unavailable or returns nothing.

    Points at WHERE the change concentrated rather than restating the headline numbers — those already
    sit on the card next to this line. Falls back to a broad-based note when no single segment moved.
    """
    if attribution and attribution.get("value"):
        segment = attribution["value"]
        prop = attribution.get("property")
        prop_clause = f" ({prop})" if prop else ""
        return f"The change is concentrated in {segment}{prop_clause} — the biggest mover, worth a look."
    return "No single segment stands out, so the change looks broad-based across users — worth a look at what's common."


REPLAY_EVIDENCE_LIMIT = 3


def _finding_event(finding: Finding) -> str | None:
    """Pull the headline event name out of the finding's TrendsQuery-shaped descriptor, if it has one."""
    series = finding.descriptor.query.get("series") or []
    if not series or not isinstance(series[0], dict):
        return None
    event = series[0].get("event")
    return event if isinstance(event, str) and event else None


def _query_session_ids(
    team: Team, event_name: str, prop_key: str, prop_value: Any, date_from: str, date_to: str
) -> list[str]:
    """Up to REPLAY_EVIDENCE_LIMIT session ids where `event_name` fired with `prop_key=prop_value`.

    Synchronous — executes a ClickHouse query — so it is only ever called via database_sync_to_async.
    """
    # Lazy import: the pulse package is eagerly preloaded via posthog.api; importing the recordings
    # query layer at module level risks an app-init circular import (see selection.py / delivery.py).
    from posthog.schema import RecordingOrder, RecordingsQuery  # noqa: PLC0415

    from posthog.session_recordings.queries.session_recording_list_from_query import (  # noqa: PLC0415
        SessionRecordingListFromQuery,
    )

    query = RecordingsQuery(
        events=[
            {
                "id": event_name,
                "name": event_name,
                "type": "events",  # entity type is plural
                "properties": [
                    {
                        "type": "event",
                        "key": prop_key,
                        "value": prop_value,
                        "operator": "exact",
                    },  # property type is singular
                ],
            }
        ],
        date_from=date_from,
        date_to=date_to,
        limit=REPLAY_EVIDENCE_LIMIT,
        filter_test_accounts=True,
        order=RecordingOrder.START_TIME,
    )
    result = SessionRecordingListFromQuery(team=team, query=query, max_execution_time=30).run()
    return [sid for row in result.results[:REPLAY_EVIDENCE_LIMIT] if (sid := row.get("session_id"))]


async def _collect_replay_evidence(
    team: Team, finding: Finding, attribution: dict[str, Any] | None, period_start: str, period_end: str
) -> list[str]:
    """Find a few example replay session ids for the segment that drove the change.

    Targeted: only runs when there is a concrete attribution segment (a headline event plus a real,
    non-synthetic breakdown value) and a period window. Best-effort — degrades to [] on any error or
    zero matches, which is common (sampling, retention, server-side events).
    """
    if not attribution or not period_start or not period_end:
        return []
    prop_key = attribution.get("property")
    prop_value = attribution.get("value")
    if not prop_key or prop_value is None or str(prop_value) in SYNTHETIC_BREAKDOWN_VALUES:
        return []
    event_name = _finding_event(finding)
    if not event_name:
        return []
    try:
        date_from = datetime.fromisoformat(period_start).date().isoformat()
        date_to = datetime.fromisoformat(period_end).date().isoformat()
        return await database_sync_to_async(_query_session_ids, thread_sensitive=False)(
            team, event_name, prop_key, prop_value, date_from, date_to
        )
    except Exception as exc:
        logger.warning("pulse_replay_evidence_failed", team_id=team.id, metric=finding.descriptor.label, error=str(exc))
        return []


async def _enrich_one(
    team: Team,
    user: User,
    finding: Finding,
    enrichment_semaphore: asyncio.Semaphore,
    attribution_semaphore: asyncio.Semaphore,
    period_start: str = "",
    period_end: str = "",
    signal_catalog: list[CoincidentSignal] | None = None,
) -> EnrichedFinding:
    async with enrichment_semaphore:
        # Attribution and evidence are independent of the narrative LLM, so collect them first and
        # keep them even if narrative generation falls back.
        catalog_by_id = {s.ref_id: s for s in (signal_catalog or [])}
        attribution: dict[str, Any] | None = None
        session_ids: list[str] = []
        daily_series: list[float] = []
        references: list[dict[str, str]] = []
        try:
            attribution = await _attribute_finding(team, finding, attribution_semaphore)
            session_ids = await _collect_replay_evidence(team, finding, attribution, period_start, period_end)
            daily_series = await _fetch_daily_series(team, finding, period_start, period_end)
            narrative, related_ids = await _generate_narrative(team, user, finding, attribution, signal_catalog)
            if not narrative:  # empty LLM response — keep a useful, attribution-aware line (no relevance signal)
                narrative = _fallback_narrative(finding, attribution)
            else:
                # Only the same-period changes the model tied to THIS finding — relevant, not period-wide.
                references = [
                    _signal_to_reference(catalog_by_id[ref_id]) for ref_id in related_ids if ref_id in catalog_by_id
                ][:MAX_FINDING_REFERENCES]
        except Exception as exc:
            logger.exception(
                "pulse_enrich_finding_failed",
                team_id=team.id,
                metric=finding.descriptor.label,
                error=str(exc),
            )
            narrative = _fallback_narrative(finding, attribution)
        # Evidence carries the trend sparkline series, example replays, and the linkable same-period changes.
        evidence: dict[str, Any] = {}
        if finding.series:
            evidence["series"] = finding.series
        if daily_series:
            evidence["daily_series"] = daily_series
        if session_ids:
            evidence["session_ids"] = session_ids
        if references:
            evidence["references"] = references
        return EnrichedFinding(
            descriptor=finding.descriptor,
            current_value=finding.current_value,
            baseline_value=finding.baseline_value,
            change_pct=finding.change_pct,
            impact=finding.impact,
            robust_z=finding.robust_z,
            attribution_breakdown=attribution,
            evidence=evidence or None,
            narrative=narrative,
        )


async def enrich_findings(
    team_id: int,
    user_id: int | None,
    findings: list[Finding],
    max_findings: int,
    period_start: str = "",
    period_end: str = "",
) -> list[EnrichedFinding]:
    ranked = sorted(findings, key=lambda f: f.impact, reverse=True)[:max_findings]

    @database_sync_to_async
    def _resolve() -> tuple[Team, User, list[CoincidentSignal]]:
        team = Team.objects.get(id=team_id)
        user = _resolve_service_user(team, user_id)
        # Same-period deploys / flag changes / experiment launches, so the narrative LLM can tie a finding
        # to a real coincidence — and the ones it cites become that finding's clickable reference chips.
        annotations, flag_changes, experiment_changes = _fetch_period_signals(team_id, period_start, period_end)
        signal_catalog = _build_signal_catalog(annotations, flag_changes, experiment_changes)
        return team, user, signal_catalog

    team, user, signal_catalog = await _resolve()
    enrichment_semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)
    attribution_semaphore = asyncio.Semaphore(ATTRIBUTION_CONCURRENCY)
    return list(
        await asyncio.gather(
            *[
                _enrich_one(
                    team,
                    user,
                    f,
                    enrichment_semaphore,
                    attribution_semaphore,
                    period_start,
                    period_end,
                    signal_catalog,
                )
                for f in ranked
            ]
        )
    )


SYNTHESIS_MAX_TOKENS = 320
MAX_FLAG_CHANGES_FOR_AI_CONTEXT = 15
MAX_NEW_ISSUES_FOR_AI_CONTEXT = 5

SYNTHESIS_SYSTEM_PROMPT = """You are PostHog Pulse, giving a product team the BIG-PICTURE read across this week's flagged metric changes — the layer ABOVE the individual findings.

Each finding already has its own card below explaining its metric, its % change, where it concentrated, and the specific deploy, feature-flag change, experiment, or error it lines up with. So do NOT restate individual metrics, percentages, or their per-finding explanations — the reader can already see those, and repeating them just causes fatigue. Your job is the synthesis a card-by-card scan can't give:
- THEMES: group the findings into the distinct stories or areas they form (e.g. "a checkout regression" or "a Chrome-driven growth surge"), naming the area to focus on rather than re-listing each metric. One bullet per theme.
- CONNECTIONS: when several findings plausibly share one driver that isn't obvious from any single card — one deploy, feature-flag change, experiment launch, or new error issue — call it out as a coincidence to check, never proven cause.

Order the bullets by priority — lead with the theme that most deserves attention (biggest downside, or clearest shared cause). The ORDER is how you signal what to look at first, so do NOT add a separate "the most important focus is…" bullet, and do NOT repeat that something is "the most urgent" across bullets; state why a theme matters once, inside its own bullet. Every bullet must introduce a NEW theme or insight — never restate the same conclusion in different words.

Write 2-4 short bullet points (one per line, each starting with "- "), most important first, so the team can skim. Stay factual and humble — no recommendations beyond "worth investigating", no jargon or emoji. Use a plain "- " bullet list and no other markdown (no bold, headers, links, or nesting); keep each bullet to one sentence.

If the findings genuinely share no theme or driver, say so in one bullet rather than forcing a connection — never pad by re-listing the findings.""".strip()


def _sanitize_for_prompt(text: str) -> str:
    """Strip characters usable for prompt injection from team-authored free text (flag names, annotations)."""
    cleaned = "".join(c for c in text if c == " " or (c.isprintable() and c not in "<>"))
    return cleaned[:200]


def _describe_flag_change(activity: str, detail: dict[str, Any] | None) -> str:
    """Short human label for a FeatureFlag ActivityLog row: created / deleted / turned on / turned off / updated."""
    if activity == "created":
        return "created"
    if activity == "deleted":
        return "deleted"
    for change in (detail or {}).get("changes") or []:
        if isinstance(change, dict) and change.get("field") == "active":
            return "turned on" if change.get("after") else "turned off"
    return "updated"


def _fetch_flag_changes(team_id: int, start: datetime, end: datetime) -> list[dict[str, str]]:
    """Feature-flag mutations in the period, as coincident-signal context for synthesis (never causation).

    ActivityLog is a plain team_id-scoped model (no fail-closed manager), so a direct filter is correct.
    """
    rows = (
        ActivityLog.objects.filter(
            team_id=team_id,
            scope="FeatureFlag",
            activity__in=["created", "updated", "deleted"],
            created_at__gte=start,
            created_at__lte=end,
        )
        .order_by("created_at")
        .values_list("created_at", "activity", "detail", "item_id")[:MAX_FLAG_CHANGES_FOR_AI_CONTEXT]
    )
    return [
        {
            "date": created_at.date().isoformat(),
            # Full ISO instant for the per-finding timeline (chronological, tz-consistent with period bounds).
            "timestamp": created_at.isoformat(),
            "flag": _sanitize_for_prompt(str((detail or {}).get("name") or "a feature flag")),
            "change": _describe_flag_change(activity, detail),
            # item_id is the flag's pk; the UI turns it into a /feature_flags/:id link (None when absent).
            "id": str(item_id) if item_id else "",
        }
        for created_at, activity, detail, item_id in rows
    ]


def _describe_experiment_change(activity: str, detail: dict[str, Any] | None) -> str:
    """Short human label for an Experiment ActivityLog row: created / deleted / launched / stopped / updated."""
    if activity == "created":
        return "created"
    if activity == "deleted":
        return "deleted"
    for change in (detail or {}).get("changes") or []:
        if isinstance(change, dict) and change.get("field") == "start_date":
            return "launched" if change.get("after") else "stopped"
    return "updated"


def _fetch_experiment_changes(team_id: int, start: datetime, end: datetime) -> list[dict[str, str]]:
    """Experiment changes in the period (launched / created / stopped) — a strong coincident signal.

    Read from ActivityLog (scope="Experiment"), exactly like flag changes: a plain team_id-scoped model, so
    no products import or team scoping is needed, and item_id is the experiment's id for the UI link.
    """
    rows = (
        ActivityLog.objects.filter(
            team_id=team_id,
            scope="Experiment",
            activity__in=["created", "updated", "deleted"],
            created_at__gte=start,
            created_at__lte=end,
        )
        .order_by("created_at")
        .values_list("created_at", "activity", "detail", "item_id")[:MAX_FLAG_CHANGES_FOR_AI_CONTEXT]
    )
    return [
        {
            "date": created_at.date().isoformat(),
            "timestamp": created_at.isoformat(),
            "experiment": _sanitize_for_prompt(str((detail or {}).get("name") or "an experiment")),
            "change": _describe_experiment_change(activity, detail),
            "id": str(item_id) if item_id else "",
        }
        for created_at, activity, detail, item_id in rows
    ]


def _build_signal_catalog(
    annotations: list[dict[str, str]],
    flag_changes: list[dict[str, str]],
    experiment_changes: list[dict[str, str]],
) -> list[CoincidentSignal]:
    """Flatten the period's coincident changes into one list the narrative LLM picks from by id.

    Experiments first, then flags, then annotations — that's both the priority order and the order the
    catalog is trimmed in if it exceeds the ceiling. Deduped within a type by entity id (an item that
    changed several times in the period becomes ONE referenceable signal). Each entry gets a dense opaque
    ref_id ("s0", "s1", …) the model echoes back to mark which it tied to a finding.
    """
    catalog: list[CoincidentSignal] = []
    seen: set[tuple[str, str]] = set()

    def _add(ref_type: str, detail_id: str, label: str, summary: str, timestamp: str, change: str = "") -> None:
        key = (ref_type, detail_id or label)
        if key in seen:
            return
        seen.add(key)
        catalog.append(
            CoincidentSignal(
                ref_id=f"s{len(catalog)}",
                ref_type=ref_type,
                label=label,
                detail_id=detail_id,
                summary=summary,
                timestamp=timestamp,
                change=change,
            )
        )

    for exp in experiment_changes:
        _add(
            "experiment",
            exp.get("id", ""),
            exp["experiment"],
            f"{exp['change']} {exp.get('date', '')}".strip(),
            exp.get("timestamp", ""),
            exp.get("change", ""),
        )
    for flag in flag_changes:
        _add(
            "feature_flag",
            flag.get("id", ""),
            flag["flag"],
            f"{flag['change']} {flag.get('date', '')}".strip(),
            flag.get("timestamp", ""),
            flag.get("change", ""),
        )
    for ann in annotations:
        _add(
            "annotation",
            ann.get("id", ""),
            ann["note"],
            f"noted {ann.get('date', '')}".strip(),
            ann.get("timestamp", ""),
        )

    return catalog[:MAX_SIGNAL_CATALOG]


def _signal_to_reference(signal: CoincidentSignal) -> dict[str, str]:
    """Project a referenced signal into the chip shape the UI renders ({type, label, timestamp, id?, change?}).

    The timestamp lets the finding chart place this change on its own axis — self-contained, so it never
    depends on a digest-wide cap dropping it.
    """
    label = signal.label if len(signal.label) <= MAX_REFERENCE_LABEL else signal.label[:MAX_REFERENCE_LABEL] + "…"
    reference = {"type": signal.ref_type, "label": label}
    if signal.timestamp:  # lets the UI place it on the finding's timeline
        reference["timestamp"] = signal.timestamp
    if signal.detail_id:  # no detail id → a label-only chip (no deep link)
        reference["id"] = signal.detail_id
    if signal.change:
        reference["change"] = signal.change
    return reference


def _fetch_period_signals(
    team_id: int, period_start: str, period_end: str
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Annotations, feature-flag changes, and experiment launches within the digest period.

    Coincident-signal context only — shared by per-finding narrative (a metric-specific hypothesis) and
    digest synthesis (the cross-metric read). Returns ([], [], []) without period bounds. Never causation.
    """
    if not period_start or not period_end:
        return [], [], []
    start = datetime.fromisoformat(period_start)
    end = datetime.fromisoformat(period_end)
    rows = (
        Annotation.objects.filter(
            team_id=team_id,
            deleted=False,
            date_marker__gte=start,
            date_marker__lte=end,
        )
        .order_by("date_marker")
        .values_list("id", "date_marker", "content")[:20]
    )
    annotations = [
        # id lets a referenced annotation deep-link to /data-management/annotations/:id, like flags/experiments.
        {
            "id": str(pk),
            "date": dm.date().isoformat(),
            "timestamp": dm.isoformat(),
            "note": _sanitize_for_prompt(content),
        }
        for pk, dm, content in rows
        if content
    ]
    flag_changes = _fetch_flag_changes(team_id, start, end)
    experiment_changes = _fetch_experiment_changes(team_id, start, end)
    return annotations, flag_changes, experiment_changes


def _fetch_error_signals(team: Team) -> list[dict[str, Any]]:
    """New error-tracking issues seen recently, as coincident-signal context for synthesis (never causation).

    Uses the error-tracking facade's recent-new-issues query (a ~7-day window, which lines up with the
    weekly digest period). Best-effort: any failure — including ClickHouse being unavailable or the team
    not using error tracking — degrades to no signal rather than breaking the additive synthesis step.
    """
    # Lazy import: the pulse package is eagerly preloaded via posthog.api, and importing the
    # error-tracking facade at module level risks an app-init circular import (see delivery.py).
    from products.error_tracking.backend.facade import api as error_tracking_api  # noqa: PLC0415

    try:
        issues = error_tracking_api.get_new_issues_for_team(team)
    except Exception as exc:
        logger.warning("pulse_fetch_error_signals_failed", team_id=team.id, error=str(exc))
        return []
    return [
        {
            "name": _sanitize_for_prompt(str(issue.get("name") or "Untitled issue")),
            "count": int(issue.get("occurrence_count") or 0),
        }
        for issue in issues[:MAX_NEW_ISSUES_FOR_AI_CONTEXT]
    ]


async def synthesize_digest(
    team_id: int,
    user_id: int | None,
    findings: list[EnrichedFinding],
    period_start: str = "",
    period_end: str = "",
) -> str:
    """Digest-level "big picture" across ALL findings — co-movement hypotheses, not per-metric prose.

    Runs once per digest (vs _generate_narrative, which is per-finding). Pulls in the period's annotations,
    flag changes, experiment launches, and new error issues as coincident context. Returns "" when there is
    too little to synthesize across or the call fails — the summary is additive, never load-bearing.
    """
    if len(findings) < 2:
        return ""

    @database_sync_to_async
    def _resolve() -> tuple[
        Team, User, list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]
    ]:
        team = Team.objects.get(id=team_id)
        user = _resolve_service_user(team, user_id)
        # New error issues use a ~7-day window internally, independent of the digest period bounds.
        error_signals = _fetch_error_signals(team)
        annotations, flag_changes, experiment_changes = _fetch_period_signals(team_id, period_start, period_end)
        return team, user, annotations, flag_changes, experiment_changes, error_signals

    team, user, annotations, flag_changes, experiment_changes, error_signals = await _resolve()
    facts = {
        "findings": [
            {
                "metric": _sanitize_for_prompt(f.descriptor.label),
                "change_pct": round(f.change_pct, 3),
                "attribution": f.attribution_breakdown,
            }
            for f in findings
        ],
        "annotations": annotations,
        "feature_flag_changes": flag_changes,
        "experiment_changes": experiment_changes,
        "new_error_issues": error_signals,
    }

    llm = MaxChatOpenAI(
        model=NARRATIVE_MODEL,
        user=user,
        team=team,
        temperature=0.3,
        max_tokens=SYNTHESIS_MAX_TOKENS,
        request_timeout=NARRATIVE_TIMEOUT_SECONDS,
        streaming=False,
        disable_streaming=True,
        max_retries=3,
        billable=False,
        inject_context=False,
        posthog_properties={"ai_product": "pulse", "domain": "pulse_synthesis"},
    )
    chain = llm | StrOutputParser()
    messages = [
        SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
        HumanMessage(
            content=f"This period's findings, annotations, flag changes, experiment launches, and new error issues:\n{json.dumps(facts, default=str)}"
        ),
    ]
    try:
        result = await chain.ainvoke(messages)
        return result.strip()
    except Exception as exc:
        logger.exception("pulse_synthesize_digest_failed", team_id=team_id, error=str(exc))
        return ""
