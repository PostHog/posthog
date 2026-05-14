"""LLM-driven synthesis of a PR's blast radius.

This sits ON TOP of the deterministic pipeline — it doesn't replace it.
The orchestrator receives:
  - the diff text
  - the touched file paths
  - the confirmed flag/event references with reach numbers
  - the related-signal candidates
  - the dashboard + issue references
  - the team's known flag keys and event names (as a searchable catalog)

…and is asked to produce a structured analysis (headline, summary, top
picks) by reasoning over those inputs and optionally calling tools to
dig deeper. The tools route back to the same deterministic logic that
produced the candidate set — so numbers the model cites are *real*.

Failure modes are explicit: missing API key, transport errors, the
model going off the rails. All return ``None`` from ``run_orchestrator``
and the rest of the report renders without the AI section.
"""

import json
import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings

import anthropic

from .event_reach import compute_per_event_reach
from .flag_reach import compute_per_flag_reach
from .issue_refs import find_referencing_issues
from .web_paths import cap_llm_paths, compute_pageview_reach

if TYPE_CHECKING:
    from posthog.models import Team

    from ..facade.contracts import (
        AffectedEstimate,
        DashboardReference,
        EventReach,
        EventReference,
        FlagReach,
        FlagReference,
        IssueReference,
        LLMAnalysis,
        RelatedSignal,
        WebPathReach,
    )


logger = logging.getLogger(__name__)


_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096
_MAX_TURNS = 6
_DIFF_CHAR_LIMIT = 40_000  # ~10k tokens, leaves headroom for catalogs + tool results
_KNOWN_VOCAB_LIMIT = 400  # how many flag keys / event names to put in the prompt


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit - 200]
    return head + f"\n\n[... truncated, original length {len(text)} chars ...]"


def _build_tools() -> list[dict[str, Any]]:
    """Tool definitions the model can call.

    Cached via prompt caching since they're identical across requests.
    """
    return [
        {
            "name": "search_flag_keys",
            "description": (
                "Substring-match against the team's flag keys catalog. Use this to find flags "
                "you suspect this PR affects but don't see in the confirmed-references list. "
                "Returns up to `limit` matching keys."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Case-insensitive substring to match within flag keys.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 20).",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "search_event_names",
            "description": (
                "Substring-match against the team's recently-fired event names. Use this to find "
                "events whose name is related to the diff but isn't in the confirmed-references list."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Case-insensitive substring to match."},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_flag_reach",
            "description": (
                "Measure empirical reach (distinct users, sessions, total evaluations) for one or "
                "more flag keys over the lookback window. Use this to attach real numbers to a flag "
                "you've identified via search_flag_keys. Do not guess numbers."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Flag keys to measure. Max 10 per call.",
                    },
                },
                "required": ["keys"],
            },
        },
        {
            "name": "get_event_reach",
            "description": (
                "Measure empirical reach (distinct users, sessions, total fires) for one or more "
                "event names over the lookback window."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Event names to measure. Max 10 per call.",
                    },
                },
                "required": ["names"],
            },
        },
        {
            "name": "get_pageview_reach",
            "description": (
                "Measure $pageview reach (total pageviews, unique visitors, sessions) for one or "
                "more URL paths over the lookback window. Use this for PRs that touch routes / pages: "
                "the deterministic pass picks up obvious path literals like '/pricing' from the diff, "
                "but you can identify additional paths from framework conventions — Next.js "
                "`app/pricing/page.tsx` → `/pricing`, Express `router.get('/users')`, Django URLconf "
                "entries, etc. — and look them up here. Match is exact against `properties.$pathname`."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "URL paths to measure, each starting with '/' (e.g. '/pricing', "
                            "'/checkout/start'). Max 10 per call. Do not include query strings or origins."
                        ),
                    },
                },
                "required": ["paths"],
            },
        },
        {
            "name": "find_issues_for_terms",
            "description": (
                "Look up Error Tracking issues whose recent $exception events mention any of these terms. "
                "Use this AFTER discovering new flag keys or event names via search — the initial issues "
                "list was built from the original confirmed terms only, so it won't include issues "
                "associated with surfaces you've since found. Always call this if you've discovered any "
                "new flag keys or event names that the deterministic pass didn't already include."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Flag keys, event names, or file path fragments to search exception "
                            "payloads for. Max 15 per call."
                        ),
                    },
                },
                "required": ["terms"],
            },
        },
        {
            "name": "submit_analysis",
            "description": (
                "Submit the final structured analysis. Call this exactly once when you've gathered "
                "enough evidence. After this call, no further tool calls are made."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "headline": {
                        "type": "string",
                        "description": (
                            "One sentence answering 'who in production is affected, and how?' — never "
                            "'what does this code do'. Must reference at least one PostHog signal "
                            "(reach number, issue, dashboard) or explicitly state no data. "
                            "GOOD: 'Affects ~12k iOS users who track flights; resolves 2 active issues.' "
                            "BAD: 'Adds Live Activity push-to-start support and refactors alerts.'"
                        ),
                    },
                    "summary": {
                        "type": "string",
                        "description": (
                            "2-4 sentences. Every sentence MUST cite a real PostHog data point — a "
                            "measured user/event/session count, an issue, a dashboard, or an explicit "
                            "'no data' observation. Do NOT describe what the code does in "
                            "implementation terms (that's GitHub's job). If a change in the diff "
                            "doesn't connect to any PostHog data, omit it entirely. Cite numbers from "
                            "tool calls or the confirmed-references list."
                        ),
                    },
                    "affected": {
                        "type": "object",
                        "description": (
                            "Glanceable answer to 'how many users will this affect?'. This is the "
                            "single most important field — the UI surfaces it as the loud metric. "
                            "Be honest: if you don't have data, say so via confidence='low' and unit='unknown'."
                        ),
                        "properties": {
                            "headline": {
                                "type": "string",
                                "description": (
                                    "Short glanceable phrase, under 5 words. Examples: 'Most users', "
                                    "'Many users', 'Few users', '~14k users', 'iOS users only', "
                                    "'Net-new surface', '0 users yet'. Use 'Unknown' ONLY when you "
                                    "genuinely cannot identify a surface — if you have audience or "
                                    "top_picks, the headline must NOT be 'Unknown'. Net-new code with "
                                    "0 reach is 'Net-new surface', not 'Unknown'."
                                ),
                            },
                            "unit": {
                                "type": "string",
                                "enum": ["users", "events", "requests", "unknown"],
                                "description": (
                                    "Use 'users' for client-side reach where person_id = human. Use "
                                    "'events' or 'requests' when the dominant signal is server-side "
                                    "capture (one identity, many calls). Use 'unknown' when no real "
                                    "data is available."
                                ),
                            },
                            "lower": {
                                "type": ["integer", "null"],
                                "description": "Numeric lower bound. Null if not estimable.",
                            },
                            "upper": {
                                "type": ["integer", "null"],
                                "description": "Numeric upper bound. Null if not estimable.",
                            },
                            "share_lower": {
                                "type": ["number", "null"],
                                "description": "Fraction of the team's active base (0.0 - 1.0), lower bound. Null if not estimable.",
                            },
                            "share_upper": {
                                "type": ["number", "null"],
                                "description": "Fraction of the team's active base (0.0 - 1.0), upper bound.",
                            },
                            "confidence": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                                "description": (
                                    "Confidence in IDENTIFYING what this PR affects — NOT the size of "
                                    "the numbers. A confident 'this is a new pricing page with 0 visitors "
                                    "yet' is HIGH confidence because the identification is solid. "
                                    "high = the surface and audience are clear (whether reach is 0 or 14k); "
                                    "medium = surface identified but partially inferred; "
                                    "low = mostly guessing what's being changed from a vague diff."
                                ),
                            },
                            "rationale": {
                                "type": "string",
                                "description": "1-2 sentences explaining how you arrived at this estimate. Reference numbers.",
                            },
                        },
                        "required": ["headline", "unit", "confidence", "rationale"],
                    },
                    "audience": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "1-4 short phrases describing WHO is affected. Examples: 'iOS users', "
                            "'users with active flights', 'users on the paid plan', 'API service'. "
                            "Pull from the diff context (platform, file paths, feature area)."
                        ),
                        "default": [],
                    },
                    "top_picks": {
                        "type": "array",
                        "description": (
                            "3-5 most important signals a reviewer should look at, in priority order. "
                            "Pull from the confirmed references, related signals, dashboards, or issues "
                            "you've considered."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {
                                    "type": "string",
                                    "enum": ["flag", "event", "dashboard", "issue", "page"],
                                },
                                "key": {
                                    "type": "string",
                                    "description": "Flag key / event name / dashboard name / issue name / URL path.",
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "Why this is in the top picks. Reference numbers where possible.",
                                },
                            },
                            "required": ["kind", "key", "reason"],
                        },
                    },
                    "caveats": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional honest caveats — 'no recent data', 'server-side only', etc.",
                        "default": [],
                    },
                },
                "required": ["headline", "summary", "top_picks", "affected"],
            },
        },
    ]


_SYSTEM_PROMPT = """You are a code review assistant analyzing a pull request's *blast radius* — \
the set of production surfaces (feature flags, events, dashboards, errors) that this change affects, \
and the real number of users who interact with them.

You will be given:
- The PR diff (or a truncated version).
- Files this PR touches.
- A pre-computed list of "confirmed references" — flag keys and event names literally mentioned in the \
diff, with their measured reach.
- A pre-computed list of "related signals" — flag keys and event names that share filename tokens with \
the PR but aren't literally referenced. Treat these as candidates to consider, not as confirmed.
- Saved dashboards / insights that reference the matched keys.
- Error Tracking issues whose stack frames mention touched files.
- URL paths found in the diff with their $pageview reach (pageviews, visitors, sessions).
- A catalog of the team's known flag keys and recent event names you can search.

Your job (execute these in order):
1. Read the diff to understand what user-facing surfaces it touches.
2. If you suspect there are additional flags or events worth checking (especially for refactor-y PRs \
that don't reference instrumentation directly), use `search_flag_keys` / `search_event_names` to find \
candidates, then `get_flag_reach` / `get_event_reach` to attach real numbers.
3. **If the PR touches routes / pages**, identify the URL paths from framework conventions: \
Next.js `app/foo/page.tsx` → `/foo`, Next.js `pages/foo.tsx` → `/foo`, Express `router.get('/foo')` → \
`/foo`, Django URLconf entries, etc. The deterministic pass already picks up obvious literals like \
`"/pricing"` but file-derived paths need you. Call `get_pageview_reach` with the inferred paths to \
attach real traffic numbers.
4. **Check for Error Tracking issues against everything you found.** The initial issues list in the \
context was built from the original confirmed terms only — it does NOT yet include issues for any \
flags/events you've discovered via search. Call `find_issues_for_terms` with the new keys to close that \
loop. Issues are first-class signals; a 1-issue / 200-user / unresolved error on a touched code path \
is more important than 10k extra users hitting a different surface. Do not skip this step unless you \
genuinely found zero new keys in step 2.
5. Reason about which signals matter most for a reviewer trying to decide whether this PR is risky.
6. Call `submit_analysis` exactly once with your final structured output.

The single most important field is `affected` — it's the loud metric the UI renders at the top of the \
widget. It answers "how many and who" at a glance. Treat it as the headline, not the wall-of-text \
summary.

`confidence` semantics — read carefully. It rates your confidence in *identifying what this PR affects*, \
NOT the size of the numbers. A confident "this is a brand-new pricing page with 0 visitors yet" is \
`confidence="high"` because the identification is solid. A guess based on a vague diff with no \
PostHog data is `confidence="low"` because the identification itself is weak.

`headline` rules:
- Use a concrete description whenever you can identify the surface: "Net-new surface", "0 users (new \
feature)", "Many users", "Few users", "iOS users only", "~14k API requests", etc.
- Use "Unknown" ONLY as a last resort — when you genuinely cannot tell from the diff what's being \
changed. If you have an audience to put in `audience`, or a surface in `top_picks`, the headline must \
NOT be "Unknown".
- Net-new code with zero historical reach is NOT "Unknown" — it's "Net-new surface" or "0 users yet" \
with `unit="users"`, `lower=0`, `upper=0`, `confidence="high"`.

`unit` rules:
- "users" / "events" / "requests" when you have a counted surface (even if the count is 0).
- "unknown" only when you couldn't identify a surface to count at all.

Worked examples:

- For a PR with confirmed events firing 14k users / 30d, ~30% of MAU:
  headline="Many users", unit="users", lower=12000, upper=16000, share_lower=0.25, share_upper=0.35, \
confidence="high", rationale="checkout_started (12k) + checkout_completed (8k) overlap to ~14k unique users in 30d"

- For a server-side flag eval at 14k evals from a single service identity:
  headline="~14k API requests", unit="requests", lower=14000, upper=14000, share_lower=null, share_upper=null, \
confidence="high", rationale="aviationstack-flight-provider evaluated 14k times by waypoint-api service identity"

- For a net-new user-facing feature (e.g. PR adds a new /pricing route + a new checkout_session_requested \
event, both with 0 historical activity):
  headline="Net-new surface", unit="users", lower=0, upper=0, share_lower=null, share_upper=null, \
confidence="high", rationale="adds /pricing route and checkout_session_requested event — both net-new \
(0 pageviews / 0 fires in 30d). Reach starts at zero and grows from here."

- For a PR with no PostHog signals but clear scope from the diff (e.g. iOS Live Activity refactor):
  headline="iOS users only", unit="users", lower=null, upper=null, share_lower=null, share_upper=null, \
confidence="medium", rationale="diff touches iOS Live Activity code; no recent events fired against \
the touched files but the platform scope is clear"

- For a truly opaque diff with no identifiable surface (rare — e.g. config-only change to internal \
build tooling, no events / flags / routes / files in any catalog):
  headline="Unknown", unit="unknown", lower=null, upper=null, share_lower=null, share_upper=null, \
confidence="low", rationale="no events, flags, routes, or instrumented files in this PR; cannot \
identify a user-facing surface"

THE CARDINAL RULE — read carefully:

This is a *blast radius* tool, not a PR summarizer. Every claim you make in `headline` and `summary` \
MUST connect a change in the diff to a measured user-side effect from PostHog data. The point of \
this widget is to show real production impact — describing what the code does is GitHub's job, not \
yours. If you can't tie a change to PostHog data, do not describe that change at all.

What counts as "PostHog data":
- A flag key with measured reach (users / sessions / call_count from a tool call or the confirmed list).
- An event name with measured reach.
- A saved insight or dashboard from the references list.
- An Error Tracking issue from the references list (status, occurrences, users hit).
- A URL path with $pageview reach (pageviews, visitors, sessions).
- A 'no data' / 'no recent activity' observation about a specific surface — also legitimate.

Anti-examples (do NOT write summaries like these):
- "This PR adds iOS Live Activity push-to-start support and refactors the alerts service." \
  (Pure code summary. Where are the users? No PostHog data cited.)
- "Adds a new pickLeg flow and refactors APNs error handling." \
  (Same problem.)
- "Improves notification reliability by detecting dead tokens." \
  (Plausible-sounding but cites zero PostHog data.)

Good examples (write summaries like these):
- "Affects ~12k iOS users (89% of MAU) who track flights — extends the push pipeline that fired 145k \
notifications in last 30d. Resolves 2 active issues: `apns_dead_token` (412 users hit) and \
`live_activity_failed` (38 users hit). The new push-to-start path is green-field; no reach data yet."
- "Reaches every user evaluating `aviationstack-flight-provider` — 14.2k server-side evaluations / \
30d on the `waypoint-api` identity. No user-level reach measurable for this surface, no active issues \
touching the changed files."
- "No measurable user reach: scanned 247 flag keys and 500 event names, found no overlap with \
touched files. Issue tracking is clean on these paths over the last 30 days. Likely a green-field \
internal-only change."

How to frame a change you can't connect to data:
- Don't mention it. If the diff has 10 changes and only 3 connect to PostHog data, the summary covers \
the 3 — silently skip the rest.
- Exception: if the WHOLE diff has no connection to data, say that explicitly (third example above).

Hard rules:
- Never cite a number you didn't get from a tool call or the confirmed-references list. No guessing.
- Never invent a flag key or event name. Only use ones you've seen.
- If reach data is server-side (one identity, many calls), the `affected` unit MUST be 'events' or \
'requests', NOT 'users' — saying "14k users" when it's one service is the worst kind of misleading.
- `confidence` should be 'low' when you're inferring from the diff alone without PostHog data backing it.
- `audience` should describe WHO at a human level: platform ('iOS users'), feature area ('users with \
active flights'), or service ('API service'). Pull from the diff — file paths, framework hints, etc.
- If there's genuinely nothing to say (no signals, all unknowns), say that. Don't pad.
- Keep tool calls focused. You have a budget of ~6 turns. Submit your analysis when you have what you need.
"""


class _ToolRunner:
    """Bundles the team + cached vocabulary, exposes the tool implementations."""

    def __init__(
        self,
        team: "Team",
        lookback_days: int,
        known_flag_keys: list[str],
        known_event_names: list[str],
        changed_files: list[str],
    ) -> None:
        self.team = team
        self.lookback_days = lookback_days
        self.changed_files = changed_files
        self._flag_keys_lower = [(k, k.lower()) for k in known_flag_keys]
        self._event_names_lower = [(n, n.lower()) for n in known_event_names]

    def search_flag_keys(self, query: str, limit: int = 20) -> list[str]:
        q = (query or "").lower()
        if not q:
            return []
        out = [k for k, lower in self._flag_keys_lower if q in lower]
        return out[: max(1, min(int(limit or 20), 50))]

    def search_event_names(self, query: str, limit: int = 20) -> list[str]:
        q = (query or "").lower()
        if not q:
            return []
        out = [n for n, lower in self._event_names_lower if q in lower]
        return out[: max(1, min(int(limit or 20), 50))]

    def get_flag_reach(self, keys: list[str]) -> list[dict[str, Any]]:
        bounded = [str(k) for k in (keys or [])][:10]
        if not bounded:
            return []
        rows = compute_per_flag_reach(self.team, bounded, self.lookback_days)
        return [
            {
                "key": r.key,
                "users_affected": r.users_affected,
                "sessions_affected": r.sessions_affected,
                "call_count": r.call_count,
                "has_data": r.has_data,
                "is_server_side": r.is_server_side,
            }
            for r in rows
        ]

    def get_event_reach(self, names: list[str]) -> list[dict[str, Any]]:
        bounded = [str(n) for n in (names or [])][:10]
        if not bounded:
            return []
        rows = compute_per_event_reach(self.team, bounded, self.lookback_days)
        return [
            {
                "name": r.name,
                "users_affected": r.users_affected,
                "sessions_affected": r.sessions_affected,
                "call_count": r.call_count,
                "has_data": r.has_data,
                "is_server_side": r.is_server_side,
            }
            for r in rows
        ]

    def get_pageview_reach(self, paths: list[str]) -> list[dict[str, Any]]:
        bounded = cap_llm_paths([str(p) for p in (paths or [])])
        if not bounded:
            return []
        rows = compute_pageview_reach(self.team, bounded, self.lookback_days, matched_from="llm_tool")
        return [
            {
                "path": r.path,
                "pageviews": r.pageviews,
                "unique_visitors": r.unique_visitors,
                "sessions": r.sessions,
                "has_data": r.has_data,
            }
            for r in rows
        ]

    def find_issues_for_terms(self, terms: list[str]) -> list[dict[str, Any]]:
        bounded = [str(t) for t in (terms or []) if str(t).strip()][:15]
        if not bounded:
            return []
        # Always include the PR's changed files alongside the supplied terms —
        # an exception stack that hits a touched file is implicated even if
        # the supplied terms don't appear in its payload.
        issues = find_referencing_issues(
            self.team,
            changed_files=self.changed_files,
            key_terms=bounded,
            lookback_days=self.lookback_days,
        )
        return [
            {
                "id": issue.id,
                "name": issue.name,
                "status": issue.status,
                "occurrences": issue.occurrences,
                "users_affected": issue.users_affected,
                "sample_message": issue.sample_message[:200],
                "matched_terms": list(issue.matched_terms),
            }
            for issue in issues
        ]

    def dispatch(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "search_flag_keys":
            return self.search_flag_keys(tool_input.get("query", ""), tool_input.get("limit", 20))
        if tool_name == "search_event_names":
            return self.search_event_names(tool_input.get("query", ""), tool_input.get("limit", 20))
        if tool_name == "get_flag_reach":
            return self.get_flag_reach(tool_input.get("keys", []))
        if tool_name == "get_event_reach":
            return self.get_event_reach(tool_input.get("names", []))
        if tool_name == "find_issues_for_terms":
            return self.find_issues_for_terms(tool_input.get("terms", []))
        if tool_name == "get_pageview_reach":
            return self.get_pageview_reach(tool_input.get("paths", []))
        return {"error": f"unknown tool: {tool_name}"}


def _initial_user_message(
    diff_text: str,
    changed_files: list[str],
    flag_references: list["FlagReference"],
    per_flag_reach: list["FlagReach"],
    event_references: list["EventReference"],
    per_event_reach: list["EventReach"],
    related_signals: list["RelatedSignal"],
    dashboard_references: list["DashboardReference"],
    issue_references: list["IssueReference"],
    web_paths: list["WebPathReach"],
    lookback_days: int,
) -> str:
    """Compose the structured context the model starts from."""
    parts: list[str] = []
    parts.append(f"Lookback window: last {lookback_days} days.")
    parts.append(f"Touched files ({len(changed_files)}):")
    for path in changed_files[:60]:
        parts.append(f"  - {path}")
    if len(changed_files) > 60:
        parts.append(f"  ... +{len(changed_files) - 60} more")

    # Error Tracking issues come first — they're the urgent risk signal, and
    # the model is less likely to forget about them when they're at the top.
    parts.append("\nError Tracking issues touching this PR's files / keys:")
    if not issue_references:
        parts.append("  (none — but you can call find_issues_for_terms if you discover new keys)")
    for issue in issue_references[:10]:
        parts.append(
            f"  - {issue.name} [{issue.status}]: {issue.occurrences} events, "
            f"{issue.users_affected} users — sample: {issue.sample_message[:120]!r} "
            f"(matched: {', '.join(issue.matched_terms[:4])})"
        )

    flag_lookup = {r.key: r for r in per_flag_reach}
    parts.append("\nConfirmed flag references:")
    if not flag_references:
        parts.append("  (none)")
    for ref in flag_references[:20]:
        reach = flag_lookup.get(ref.key)
        if reach is None:
            parts.append(f"  - {ref.key} (no reach measured)")
        else:
            parts.append(
                f"  - {ref.key}: {reach.users_affected} users, {reach.call_count} calls, "
                f"has_data={reach.has_data}, server_side={reach.is_server_side}"
            )

    event_lookup = {r.name: r for r in per_event_reach}
    parts.append("\nConfirmed event references:")
    if not event_references:
        parts.append("  (none)")
    for ref in event_references[:20]:
        reach = event_lookup.get(ref.name)
        if reach is None:
            parts.append(f"  - {ref.name} (no reach measured)")
        else:
            parts.append(
                f"  - {ref.name}: {reach.users_affected} users, {reach.call_count} fires, "
                f"has_data={reach.has_data}, server_side={reach.is_server_side}"
            )

    parts.append("\nRelated signals (filename-token candidates, NOT confirmed):")
    if not related_signals:
        parts.append("  (none)")
    for sig in related_signals[:15]:
        parts.append(
            f"  - [{sig.kind}] {sig.key}: {sig.users_affected} users, {sig.call_count} calls "
            f"(matched on: {', '.join(sig.matched_tokens)})"
        )

    parts.append("\nDashboard / insight references:")
    if not dashboard_references:
        parts.append("  (none)")
    for ref in dashboard_references[:15]:
        parts.append(f"  - [{ref.kind}] {ref.name} (via: {', '.join(ref.matched_keys)})")

    parts.append("\nURL paths found in the diff (with $pageview reach):")
    if not web_paths:
        parts.append("  (none — call get_pageview_reach if you infer paths from framework conventions)")
    for path in web_paths[:15]:
        if path.has_data:
            parts.append(
                f"  - {path.path}: {path.pageviews} pageviews, {path.unique_visitors} visitors, "
                f"{path.sessions} sessions (matched_from={path.matched_from})"
            )
        else:
            parts.append(f"  - {path.path}: no pageviews in window (matched_from={path.matched_from})")

    parts.append(f"\n--- PR DIFF (truncated as needed) ---\n{_truncate(diff_text, _DIFF_CHAR_LIMIT)}\n--- END DIFF ---")
    parts.append(
        "\nAnalyze the above. Use tools to search for additional flags/events if the diff suggests "
        "areas the confirmed list misses. Call submit_analysis exactly once when done."
    )
    return "\n".join(parts)


def _coerce_int(value: Any) -> int | None:
    """Best-effort coercion of LLM-emitted numbers — they sometimes come as strings."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_share(value: Any) -> float | None:
    """Clamp share values into [0.0, 1.0] when present."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f < 0:
        return 0.0
    if f > 1:
        return 1.0
    return f


def _parse_affected(raw: Any) -> "AffectedEstimate | None":
    from ..facade.contracts import AffectedEstimate

    if not isinstance(raw, dict):
        return None
    headline = str(raw.get("headline", "")).strip()
    if not headline:
        return None
    unit = str(raw.get("unit", "")).strip().lower()
    if unit not in {"users", "events", "requests", "unknown"}:
        unit = "unknown"
    confidence = str(raw.get("confidence", "")).strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    return AffectedEstimate(
        headline=headline[:80],
        unit=unit,
        lower=_coerce_int(raw.get("lower")),
        upper=_coerce_int(raw.get("upper")),
        share_lower=_coerce_share(raw.get("share_lower")),
        share_upper=_coerce_share(raw.get("share_upper")),
        confidence=confidence,
        rationale=str(raw.get("rationale", "")).strip()[:400],
    )


def _parse_submit_analysis(tool_input: dict[str, Any]) -> "LLMAnalysis":
    from ..facade.contracts import LLMAnalysis, LLMPick

    headline = str(tool_input.get("headline", "")).strip() or "No analysis produced"
    summary = str(tool_input.get("summary", "")).strip()
    raw_picks = tool_input.get("top_picks") or []
    picks: list[LLMPick] = []
    for raw in raw_picks:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind", "")).strip()
        key = str(raw.get("key", "")).strip()
        reason = str(raw.get("reason", "")).strip()
        if not key or kind not in {"flag", "event", "dashboard", "issue", "page"}:
            continue
        picks.append(LLMPick(kind=kind, key=key, reason=reason))

    raw_caveats = tool_input.get("caveats") or []
    caveats = tuple(str(c).strip() for c in raw_caveats if str(c).strip())

    raw_audience = tool_input.get("audience") or []
    audience = tuple(str(a).strip()[:80] for a in raw_audience if str(a).strip())[:4]

    affected = _parse_affected(tool_input.get("affected"))

    return LLMAnalysis(
        headline=headline,
        summary=summary,
        top_picks=tuple(picks),
        affected=affected,
        audience=audience,
        caveats=caveats,
        tool_calls_used=0,  # set by caller
    )


def run_orchestrator(
    team: "Team",
    *,
    diff_text: str,
    changed_files: list[str],
    lookback_days: int,
    known_flag_keys: list[str],
    known_event_names: list[str],
    flag_references: list["FlagReference"],
    per_flag_reach: list["FlagReach"],
    event_references: list["EventReference"],
    per_event_reach: list["EventReach"],
    related_signals: list["RelatedSignal"],
    dashboard_references: list["DashboardReference"],
    issue_references: list["IssueReference"],
    web_paths: list["WebPathReach"],
) -> "LLMAnalysis | None":
    """Run the tool-use loop. Returns None on any failure (no API key, transport, parse)."""
    from ..facade.contracts import LLMAnalysis

    api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
    if not api_key:
        logger.info("githog: ANTHROPIC_API_KEY not configured — skipping LLM analysis")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=1)
    except Exception:
        logger.exception("githog: failed to construct Anthropic client")
        return None

    runner = _ToolRunner(
        team=team,
        lookback_days=lookback_days,
        # Cap vocabulary so the search tools don't degrade into "scan 10k strings" on giant teams.
        known_flag_keys=known_flag_keys[:_KNOWN_VOCAB_LIMIT],
        known_event_names=known_event_names[:_KNOWN_VOCAB_LIMIT],
        changed_files=changed_files,
    )

    tools = _build_tools()
    # Mark last tool definition with cache_control so the whole tools block is cached.
    tools[-1]["cache_control"] = {"type": "ephemeral"}

    system = [
        {
            "type": "text",
            "text": _SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    initial_text = _initial_user_message(
        diff_text=diff_text,
        changed_files=changed_files,
        flag_references=flag_references,
        per_flag_reach=per_flag_reach,
        event_references=event_references,
        per_event_reach=per_event_reach,
        related_signals=related_signals,
        dashboard_references=dashboard_references,
        issue_references=issue_references,
        web_paths=web_paths,
        lookback_days=lookback_days,
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": initial_text}]
    final_analysis: LLMAnalysis | None = None
    tool_calls_used = 0

    for _turn in range(_MAX_TURNS):
        try:
            response = client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=system,
                tools=tools,
                messages=messages,
            )
        except Exception:
            logger.exception("githog: LLM orchestrator call failed")
            return None

        messages.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})

        tool_results: list[dict[str, Any]] = []
        submit_seen = False
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            tool_calls_used += 1
            name = block.name
            tool_input = block.input or {}

            if name == "submit_analysis":
                try:
                    final_analysis = _parse_submit_analysis(tool_input)
                except Exception:
                    logger.exception("githog: failed to parse submit_analysis input")
                    final_analysis = None
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({"accepted": final_analysis is not None}),
                    }
                )
                submit_seen = True
                continue

            try:
                result = runner.dispatch(name, tool_input)
                content = json.dumps(result, default=str)
            except Exception as e:
                logger.warning("githog: tool %s raised; returning error to model", name, exc_info=True)
                content = json.dumps({"error": str(e)})
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})

        if submit_seen:
            break

        if response.stop_reason == "end_turn":
            # Model decided it was done without calling submit_analysis. Bail.
            break

        if not tool_results:
            # No tool calls AND not end_turn — likely an empty/odd response. Bail.
            break

        messages.append({"role": "user", "content": tool_results})

    if final_analysis is None:
        return None

    # Patch in the tool-call accounting (LLMAnalysis is frozen, so reconstruct).
    return LLMAnalysis(
        headline=final_analysis.headline,
        summary=final_analysis.summary,
        top_picks=final_analysis.top_picks,
        affected=final_analysis.affected,
        audience=final_analysis.audience,
        caveats=final_analysis.caveats,
        tool_calls_used=tool_calls_used,
    )
