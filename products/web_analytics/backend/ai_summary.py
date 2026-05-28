import json
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.cache import cache

import structlog
from langchain_core.messages import HumanMessage

from posthog.schema import DateRange

from posthog.models import Team
from posthog.models.user import User
from posthog.utils import relative_date_parse

from products.web_analytics.backend.weekly_digest import DigestFilterSpec

from ee.hogai.llm import MaxChatAnthropic

logger = structlog.get_logger(__name__)


MODEL_ID = "claude-haiku-4-5"
LIVE_RANGE_TTL = timedelta(hours=1)
PAST_RANGE_TTL = timedelta(hours=24)
MAX_SUMMARY_WORDS = 150
MAX_OUTPUT_TOKENS = 700
CACHE_KEY_PREFIX = "web_analytics_ai_summary"


def _normalize_spec(spec: DigestFilterSpec) -> dict:
    return {
        "date_from": spec.date_range.date_from,
        "date_to": spec.date_range.date_to,
        "compare": spec.compare,
        "properties": sorted(spec.properties, key=lambda p: json.dumps(p, sort_keys=True, default=str)),
        "conversion_goal": spec.conversion_goal.model_dump() if spec.conversion_goal is not None else None,
        "filter_test_accounts": spec.filter_test_accounts,
        "do_path_cleaning": spec.do_path_cleaning,
    }


def compute_cache_key(spec: DigestFilterSpec, *, team: Team) -> tuple[str, dict]:
    # The key is built from the raw (unresolved) spec — relative tokens like '-7d' stay as-is so the
    # key is stable over time and freshness is governed solely by the TTL, not by a wall-clock hour.
    normalized = _normalize_spec(spec)
    payload = json.dumps(normalized, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{team.pk}:{digest}", normalized


def _range_contains_now(date_range: DateRange, *, team: Team, now: datetime) -> bool:
    if date_range.date_to is None:
        return True
    try:
        resolved = relative_date_parse(date_range.date_to, ZoneInfo(team.timezone), now=now, increase=True)
    except Exception:
        return True
    return resolved >= now


def cache_ttl_for(spec: DigestFilterSpec, *, team: Team, now: datetime | None = None) -> timedelta:
    # Live ranges (ending at/after now) churn, so expire quickly; closed past ranges are stable.
    now = now or datetime.now(ZoneInfo(team.timezone))
    return LIVE_RANGE_TTL if _range_contains_now(spec.date_range, team=team, now=now) else PAST_RANGE_TTL


def get_cached_summary(cache_key: str) -> dict | None:
    return cache.get(cache_key)


def cache_summary(cache_key: str, *, summary_text: str, ttl: timedelta, now: datetime | None = None) -> dict:
    payload = {
        "summary_text": summary_text,
        "model_id": MODEL_ID,
        "created_at": now or datetime.now(ZoneInfo("UTC")),
    }
    cache.set(cache_key, payload, timeout=int(ttl.total_seconds()))
    return payload


def _format_filter_context_for_prompt(normalized: dict) -> str:
    lines = []
    date_from = normalized.get("date_from") or "(beginning of available data)"
    date_to = normalized.get("date_to") or "(now)"
    lines.append(f"- Date range: {date_from} to {date_to}")
    lines.append(f"- Period comparison: {'on (vs prior equal-length period)' if normalized['compare'] else 'off'}")
    lines.append(f"- Filter test accounts: {normalized['filter_test_accounts']}")
    lines.append(f"- Path cleaning: {normalized['do_path_cleaning']}")
    if normalized.get("conversion_goal"):
        lines.append(f"- Conversion goal: {json.dumps(normalized['conversion_goal'], default=str)}")
    if normalized.get("properties"):
        lines.append(f"- Property filters: {json.dumps(normalized['properties'], default=str)}")
    else:
        lines.append("- Property filters: none")
    return "\n".join(lines)


def _format_context_events_for_prompt(events: list[dict]) -> str:
    lines = []
    for event in events:
        date = (event.get("date") or "")[:10] or "unknown date"
        kind = (event.get("kind") or "event").replace("_", " ")
        name = event.get("name") or "(unnamed)"
        summary = event.get("summary") or ""
        suffix = f" — {summary}" if summary else ""
        lines.append(f"- {date} · {kind}: `{name}`{suffix}")
    return "\n".join(lines)


def _build_prompt(normalized_spec: dict, digest: dict) -> str:
    filter_context = _format_filter_context_for_prompt(normalized_spec)
    context_events = digest.get("context_events") or []
    context_section = ""
    if context_events:
        context_section = (
            "Recent project events (use to add explanatory color for metric changes when timing plausibly aligns):\n"
            f"{_format_context_events_for_prompt(context_events)}\n\n"
        )
    return (
        "You are a web analytics expert summarizing a project's web traffic for a busy operator.\n\n"
        "Filter context:\n"
        f"{filter_context}\n\n"
        f"{context_section}"
        "Data (period-over-period change present when available):\n"
        f"{json.dumps(digest, default=str)}\n\n"
        "Style rules:\n"
        "- Format the output as GitHub-flavored markdown.\n"
        "- 4-6 concise bullet points using `-` for list items.\n"
        "- Lead with the single most notable change (spike, drop, anomaly).\n"
        "- Use `**bold**` to highlight the metric or entity each bullet is about (e.g. `**Visitors:** ...`).\n"
        "- Quantify every claim with absolute numbers and percentage change "
        '(e.g., "+15% to 12,453 visitors", "bounce rate dropped from 4.2% to 2.1%").\n'
        "- Wrap specific page paths and source names in backticks (e.g. `` `/pricing` ``, `` `google.com` ``).\n"
        "- When a metric change plausibly aligns in time with a listed project event, you may mention it "
        '(use phrasing like "coincides with" or "following"). Never assert causation.\n'
        "- At most one event mention per bullet. Do not list events that have no plausible link to a metric.\n"
        "- If nothing notable changed, say so in one sentence.\n"
        "- Do not use headings (no `#`). Do not wrap the whole response in code fences.\n"
        f"- Stay under {MAX_SUMMARY_WORDS} words total.\n"
    )


def generate_web_analytics_summary(*, team: Team, normalized_spec: dict, digest: dict, user: User) -> str:
    prompt = _build_prompt(normalized_spec, digest)
    llm = MaxChatAnthropic(
        model=MODEL_ID,
        user=user,
        team=team,
        billable=False,
        inject_context=False,
        max_retries=2,
        temperature=0,
        max_tokens=MAX_OUTPUT_TOKENS,
        stream_usage=False,
        disable_streaming=True,
        posthog_properties={"ai_product": "web_analytics", "ai_feature": "dashboard-summary"},
    )
    result = llm.generate([[HumanMessage(content=prompt)]])
    message = result.generations[0][0].message  # type: ignore[union-attr]
    content = message.content if isinstance(message.content, str) else "".join(str(c) for c in message.content)
    return content.strip()
