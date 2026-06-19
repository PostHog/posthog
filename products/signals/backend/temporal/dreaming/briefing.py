"""Project briefing generation for the Dreaming Agent.

Every nightly run produces a crisp, casual project briefing: the top-3 things that matter
in the project right now. Voice is direct, Silicon-Valley-coded — like a sharp teammate
catching you up, not a status report.

Inputs that shape a briefing (best-effort — any can be absent):

- the team's custom + canonical scout skills (what this team cares about watching),
- the inbox reports that surfaced recently (what the pipeline actually found),
- real PostHog data via the agent's MCP tools (deferred to the workflow's data-gathering
  layer; this module consumes whatever structured context it's handed),
- TODO(memory): the (separate-worktree) memory store, once it lands.

This module is structured so the *exactly-three-items* contract and the prompt assembly are
unit-testable without a live LLM: `coerce_to_three_items` enforces the contract on any model
output, and `build_briefing_prompt` is pure. `generate_briefing` wires them to `call_llm`
with a deterministic fallback so a flaky model never produces a malformed briefing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

BRIEFING_ITEM_COUNT = 3

# Cap each field so a runaway model can't blow the inbox card / Slack block size, and so the
# briefing stays crisp by construction.
_MAX_HEADLINE_LEN = 120
_MAX_DETAIL_LEN = 400


@dataclass(frozen=True)
class BriefingItem:
    """One of the three things that matter right now."""

    headline: str
    detail: str


@dataclass(frozen=True)
class Briefing:
    """The project briefing: exactly three items plus a one-line intro."""

    intro: str
    items: tuple[BriefingItem, ...]

    def to_dict(self) -> dict:
        return {"intro": self.intro, "items": [asdict(item) for item in self.items]}


@dataclass(frozen=True)
class BriefingContext:
    """Structured, already-gathered context the briefing is generated from.

    Kept as plain primitives so the data-gathering layer (workflow activities, MCP reads)
    stays decoupled from prompt assembly, and so tests can construct context directly.
    """

    project_name: str
    scout_skills: tuple[str, ...]
    recent_report_titles: tuple[str, ...]
    profile_highlights: tuple[str, ...]
    # Dismissal-derived noise signal: terse lines describing what users dismissed since the
    # last run and why (counts by reason / source, representative notes). A first-class "what
    # matters" input — a class of signal being mass-dismissed as not_a_bug is signal-quality
    # news. Defaults to empty so callers that don't gather it (and existing tests) stay valid.
    dismissal_notes: tuple[str, ...] = ()
    # TODO(memory): a `memory_notes: tuple[str, ...]` slot will plug in here once the memory
    # store exists in its own worktree. The prompt already leaves room for it; until then it's
    # simply absent and the briefing leans on profile + inbox + skills.


_SYSTEM_PROMPT = """You are the PostHog Dreaming Agent writing a nightly project briefing.

Like dreaming, you've spent the night organizing everything that happened in this project and
distilling it down. Produce the top 3 things that matter RIGHT NOW — the things a sharp
teammate would lead with over coffee.

Voice: casual, direct, Silicon-Valley-coded. No corporate filler, no hedging, no "it appears
that". Short punchy headlines. Concrete details. You can be opinionated.

Return STRICT JSON, no markdown, exactly this shape:
{
  "intro": "one casual sentence framing the briefing",
  "items": [
    {"headline": "punchy < 12 words", "detail": "1-2 crisp sentences, concrete"},
    {"headline": "...", "detail": "..."},
    {"headline": "...", "detail": "..."}
  ]
}

EXACTLY 3 items. Not 2, not 4. If you genuinely have less than 3 things, invent the most
useful next thing to look at — never pad with fluff, but always return 3."""


def build_briefing_prompt(context: BriefingContext) -> str:
    """Assemble the user prompt from gathered context. Pure — no I/O."""
    lines: list[str] = [f"Project: {context.project_name}", ""]

    if context.scout_skills:
        lines.append("What this team watches (active scouts):")
        lines.extend(f"- {skill}" for skill in context.scout_skills)
        lines.append("")

    if context.recent_report_titles:
        lines.append("Recent inbox reports (what the pipeline surfaced):")
        lines.extend(f"- {title}" for title in context.recent_report_titles)
        lines.append("")

    if context.profile_highlights:
        lines.append("Project profile highlights (deterministic ground truth):")
        lines.extend(f"- {highlight}" for highlight in context.profile_highlights)
        lines.append("")

    if context.dismissal_notes:
        lines.append("What users dismissed recently (signal-quality / noise news):")
        lines.extend(f"- {note}" for note in context.dismissal_notes)
        lines.append(
            "If a class of signal is getting mass-dismissed (e.g. lots of not_a_bug from one "
            "source), that's worth leading with — it means the pipeline is generating noise."
        )
        lines.append("")

    lines.append("Write the briefing now. Exactly 3 items.")
    return "\n".join(lines)


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())  # collapse whitespace / newlines
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _fallback_items(context: BriefingContext) -> list[BriefingItem]:
    """Deterministic three-item briefing for when the LLM is unavailable or malformed.

    Leans on whatever concrete context we have so the fallback is still useful, not generic.
    """
    candidates: list[BriefingItem] = []

    if context.dismissal_notes:
        candidates.append(
            BriefingItem(
                headline="Users are dismissing reports — check the noise",
                detail=_clip(
                    "Recent dismissals: " + " ".join(context.dismissal_notes),
                    _MAX_DETAIL_LEN,
                ),
            )
        )
    if context.recent_report_titles:
        top = context.recent_report_titles[0]
        candidates.append(
            BriefingItem(
                headline="Fresh inbox signal worth a look",
                detail=f"The pipeline just surfaced: {_clip(top, 200)}. Triage it before it goes stale.",
            )
        )
    if context.profile_highlights:
        candidates.append(
            BriefingItem(
                headline="Where the project stands",
                detail=_clip("; ".join(context.profile_highlights[:3]), _MAX_DETAIL_LEN),
            )
        )
    if context.scout_skills:
        candidates.append(
            BriefingItem(
                headline="Your scouts are on patrol",
                detail=_clip(
                    f"{len(context.scout_skills)} scouts active, including {', '.join(context.scout_skills[:3])}. "
                    "Tune cadence if any are too noisy or too quiet.",
                    _MAX_DETAIL_LEN,
                ),
            )
        )

    # Top up to exactly three with neutral-but-actionable prompts.
    backstops = [
        BriefingItem(
            headline="Check your instrumentation coverage",
            detail="Recent merges may have shipped without analytics, error tracking, or LLM observability. "
            "The dreaming cleanup PR has the details.",
        ),
        BriefingItem(
            headline="Nothing's on fire — keep shipping",
            detail="No urgent anomalies tonight. A quiet inbox is a good inbox.",
        ),
        BriefingItem(
            headline="Revisit a stale report",
            detail="Older reports may have new evidence by now. Worth a second pass.",
        ),
    ]
    for item in backstops:
        if len(candidates) >= BRIEFING_ITEM_COUNT:
            break
        candidates.append(item)
    return candidates[:BRIEFING_ITEM_COUNT]


def coerce_to_three_items(raw_items: list[Any], context: BriefingContext) -> tuple[BriefingItem, ...]:
    """Force any model output into EXACTLY three well-formed items.

    Drops malformed entries, clips overlong fields, truncates a too-long list, and tops up a
    too-short list with deterministic fallbacks. This is the hard guarantee behind the
    exactly-three contract — callers never have to trust the model's count.
    """
    cleaned: list[BriefingItem] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        headline = entry.get("headline")
        detail = entry.get("detail")
        if not isinstance(headline, str) or not headline.strip():
            continue
        if not isinstance(detail, str):
            detail = ""
        cleaned.append(
            BriefingItem(
                headline=_clip(headline, _MAX_HEADLINE_LEN),
                detail=_clip(detail, _MAX_DETAIL_LEN),
            )
        )
        if len(cleaned) == BRIEFING_ITEM_COUNT:
            break

    if len(cleaned) < BRIEFING_ITEM_COUNT:
        for item in _fallback_items(context):
            if len(cleaned) >= BRIEFING_ITEM_COUNT:
                break
            # Avoid an exact-duplicate headline when topping up.
            if all(existing.headline != item.headline for existing in cleaned):
                cleaned.append(item)
    # If duplicate-avoidance still left us short (pathological), pad unconditionally.
    while len(cleaned) < BRIEFING_ITEM_COUNT:
        cleaned.append(_fallback_items(context)[len(cleaned)])

    return tuple(cleaned[:BRIEFING_ITEM_COUNT])


def _validate_briefing(raw: str, context: BriefingContext) -> Briefing:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("briefing response is not a JSON object")
    intro = data.get("intro")
    if not isinstance(intro, str) or not intro.strip():
        intro = "Here's what matters in the project right now."
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("briefing 'items' is not a list")
    items = coerce_to_three_items(raw_items, context)
    return Briefing(intro=_clip(intro, _MAX_HEADLINE_LEN), items=items)


async def generate_briefing(team_id: int, context: BriefingContext) -> Briefing:
    """Generate the briefing via the signals LLM, with a deterministic fallback.

    Never raises for content reasons: a model/transport failure degrades to a useful
    three-item fallback rather than failing the dreaming run. The exactly-three contract
    holds on every path.
    """
    from products.signals.backend.temporal.llm import call_llm

    prompt = build_briefing_prompt(context)
    try:
        return await call_llm(
            team_id=team_id,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=prompt,
            validate=lambda raw: _validate_briefing(raw, context),
            temperature=0.7,
            stage="dreaming_briefing",
        )
    except Exception:
        logger.warning(
            "dreaming briefing: LLM generation failed; using deterministic fallback",
            extra={"team_id": team_id},
        )
        return Briefing(
            intro="Here's what matters in the project right now.",
            items=tuple(_fallback_items(context)),
        )
