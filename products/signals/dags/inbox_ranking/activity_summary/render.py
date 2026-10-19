"""Pure functions that turn one person's recent activity into the input of an activity summary.

Nothing here reads a database. `dag.py` fetches the rows, and this module filters, caps, samples and
renders them, and estimates what a summary update would cost.
"""

import re
import math
import random
import hashlib
import datetime
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence

import numpy as np

from posthog.dataclasses import frozen

# Bump on any change to the filters, the sampling or the rendered layout, so partitions stay comparable.
RENDER_VERSION = 1

WINDOW_DAYS = 28
MAX_CHAIN_INTENTS = 15
# A chain shorter than this after filtering says too little about what the person tried to do.
MIN_CHAIN_INTENTS = 2
UNITS_PER_SOURCE = 10
RECENCY_HALF_LIFE_DAYS = 7
# The same intent text more often than this on one day, for one person, is a scheduled job.
REPEATED_INTENT_DAILY_LIMIT = 5
# p90 of a first prompt is far below this, so the cap only trims pasted logs and documents.
MAX_PROMPT_CHARS = 500
CHARS_PER_TOKEN = 4

CHAIN_SEPARATOR = " --> "
MCP_HEADER = "MCP sessions:"
AI_HEADER = "PostHog AI questions:"

# Tools an agent calls to find its way around, not to do the work: tool and skill discovery, schema
# reads, docs and knowledge lookups, and project lookup or switching. Their intents restate the task.
PLUMBING_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "business-knowledge-document-window-retrieve",
        "business-knowledge-documents-search",
        "business-knowledge-repositories-search",
        "docs-search",
        "generate-app-url",
        "metric-describe",
        "metric-list",
        "organization-details-get",
        "project-get",
        "projects-get",
        "read-data-schema",
        "skill-file-get",
        "skill-get",
        "switch-organization",
        "switch-project",
    }
)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL_QUERY = re.compile(r"(https?://[^\s?#]+)[?#]\S*")
# Long runs of letters and digits mixed together: API keys, session tokens, hashes, UUIDs.
_TOKEN = re.compile(r"\b(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]{24,}\b")
_WHITESPACE = re.compile(r"\s+")


@frozen
class McpCall:
    at: datetime.datetime
    tool: str
    intent: str


@frozen
class McpSession:
    calls: tuple[McpCall, ...]


@frozen
class AiPrompt:
    at: datetime.datetime
    prompt: str


@frozen
class Unit:
    """One rendered line: an MCP chain or an AI prompt, dated by its latest activity."""

    at: datetime.datetime
    text: str


@frozen
class RenderedInput:
    text: str
    n_mcp_sessions: int
    n_ai_conversations: int
    input_chars: int
    input_tokens_estimate: int


def clean_text(text: str) -> str:
    """Strip emails, URL query strings and token-like strings, and fold the text onto one line."""
    text = _EMAIL.sub("<email>", text)
    text = _URL_QUERY.sub(r"\1", text)
    text = _TOKEN.sub("<token>", text)
    return _WHITESPACE.sub(" ", text).strip()


def job_intents(sessions: Iterable[McpSession]) -> frozenset[tuple[datetime.date, str]]:
    """The (UTC day, intent) pairs that one person sent more than `REPEATED_INTENT_DAILY_LIMIT` times.

    Pass every session of the person, across projects, because a job does not stop being a job when
    it switches project."""
    counts = Counter(
        (call.at.astimezone(datetime.UTC).date(), call.intent.strip()) for session in sessions for call in session.calls
    )
    return frozenset(key for key, count in counts.items() if count > REPEATED_INTENT_DAILY_LIMIT)


def collapse_repeats(intents: Sequence[str]) -> list[str]:
    return [intent for index, intent in enumerate(intents) if index == 0 or intent != intents[index - 1]]


def cap_chain(intents: Sequence[str]) -> list[str]:
    """Keep the first intents, which set the goal, and the last one, which shows where it ended."""
    if len(intents) <= MAX_CHAIN_INTENTS:
        return list(intents)
    return [*intents[: MAX_CHAIN_INTENTS - 1], intents[-1]]


def mcp_chain(session: McpSession, jobs: frozenset[tuple[datetime.date, str]]) -> Unit | None:
    """The session as one filtered intent chain, or None when too little of it is left."""
    calls = sorted(session.calls, key=lambda call: call.at)
    intents = [
        clean_text(call.intent)
        for call in calls
        if call.tool not in PLUMBING_TOOL_NAMES
        and (call.at.astimezone(datetime.UTC).date(), call.intent.strip()) not in jobs
    ]
    chain = cap_chain(collapse_repeats([intent for intent in intents if intent]))
    if len(chain) < MIN_CHAIN_INTENTS:
        return None
    return Unit(at=calls[-1].at, text=CHAIN_SEPARATOR.join(chain))


def prompt_unit(prompt: AiPrompt) -> Unit | None:
    text = clean_text(prompt.prompt)[:MAX_PROMPT_CHARS].strip()
    return Unit(at=prompt.at, text=text) if text else None


def dedupe_latest(units: Iterable[Unit]) -> list[Unit]:
    """One unit per distinct text, the latest one, in chronological order."""
    latest: dict[str, Unit] = {}
    for unit in units:
        if unit.text not in latest or unit.at > latest[unit.text].at:
            latest[unit.text] = unit
    return sorted(latest.values(), key=lambda unit: (unit.at, unit.text))


def sampling_seed(partition_key: str, team_id: int, user_id: int) -> int:
    # Not hash(): Python salts it per process, and a re-run must pick the same units.
    digest = hashlib.sha256(f"{partition_key}:{team_id}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def sample_units(units: Sequence[Unit], *, limit: int, as_of: datetime.datetime, seed: int) -> list[Unit]:
    """Up to `limit` units without replacement, weighted towards recent ones, in chronological order.

    Weighted reservoir keys (Efraimidis and Spirakis): each unit draws `u ** (1 / weight)` and the
    largest keys win, so one busy afternoon cannot fill every slot."""
    if len(units) <= limit:
        return sorted(units, key=lambda unit: (unit.at, unit.text))
    rng = random.Random(seed)
    keyed: list[tuple[float, Unit]] = []
    for unit in sorted(units, key=lambda unit: (unit.at, unit.text)):
        age_days = max((as_of - unit.at).total_seconds(), 0.0) / 86400
        weight = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
        keyed.append((rng.random() ** (1 / weight), unit))
    chosen = sorted(keyed, key=lambda pair: pair[0], reverse=True)[:limit]
    return sorted((unit for _, unit in chosen), key=lambda unit: (unit.at, unit.text))


def estimate_tokens(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


def render_input(chains: Sequence[Unit], prompts: Sequence[Unit]) -> str:
    lines: list[str] = []
    if chains:
        lines.extend([MCP_HEADER, *(unit.text for unit in chains)])
    if prompts:
        lines.extend([AI_HEADER, *(unit.text for unit in prompts)])
    return "\n".join(lines)


def build_input(
    sessions: Iterable[McpSession],
    prompts: Iterable[AiPrompt],
    *,
    jobs: frozenset[tuple[datetime.date, str]],
    as_of: datetime.datetime,
    seed: int,
) -> RenderedInput | None:
    """The rendered input of one (project, person) pair, or None when nothing survives the filters."""
    chains = dedupe_latest(unit for session in sessions if (unit := mcp_chain(session, jobs)) is not None)
    questions = dedupe_latest(unit for prompt in prompts if (unit := prompt_unit(prompt)) is not None)
    if not chains and not questions:
        return None
    # Separate seeds per source, so a new prompt does not reshuffle which chains are picked.
    text = render_input(
        sample_units(chains, limit=UNITS_PER_SOURCE, as_of=as_of, seed=seed),
        sample_units(questions, limit=UNITS_PER_SOURCE, as_of=as_of, seed=seed + 1),
    )
    return RenderedInput(
        text=text,
        n_mcp_sessions=len(chains),
        n_ai_conversations=len(questions),
        input_chars=len(text),
        input_tokens_estimate=estimate_tokens(len(text)),
    )


@frozen
class PairActivity:
    """Counts and lengths for one (project, person) pair, as the projection SQL computes them."""

    mcp_sessions: int
    mcp_chain_chars: float
    ai_conversations: int
    ai_prompt_chars: float

    @property
    def units(self) -> int:
        return self.mcp_sessions + self.ai_conversations


def estimated_input_chars(activity: PairActivity) -> int:
    """The length `render_input` would give the pair: a sample of average-length units per source,
    one per line, under its header."""
    chars = 0.0
    for count, total_chars, header in (
        (activity.mcp_sessions, activity.mcp_chain_chars, MCP_HEADER),
        (activity.ai_conversations, activity.ai_prompt_chars, AI_HEADER),
    ):
        if count <= 0:
            continue
        sampled = min(count, UNITS_PER_SOURCE)
        chars += len(header) + sampled * (total_chars / count + 1)
    return round(chars)


def calibration_ratio(
    actual_chars: Mapping[tuple[int, str], int], estimated_chars: Mapping[tuple[int, str], int]
) -> float:
    """How far the SQL estimate is from the real rendered length, over the pairs both sides have.

    1.0 when no pair matches, so a missing inputs partition leaves the estimate as it is."""
    keys = [key for key in actual_chars if estimated_chars.get(key, 0) > 0]
    estimated = sum(estimated_chars[key] for key in keys)
    if not estimated:
        return 1.0
    return sum(actual_chars[key] for key in keys) / estimated


def updates_per_window(units: int, *, min_units: int, min_days: int) -> int:
    """Updates a pair earns in the window: one per `min_units` new units, at most one per `min_days`."""
    return min(units // min_units, WINDOW_DAYS // min_days)


MIN_UNITS_OPTIONS = (3, 5, 10)
MIN_DAYS_OPTIONS = (7, 14)
DAYS_PER_MONTH = 30


@frozen
class ProjectionPrices:
    prompt_overhead_tokens: int
    output_tokens_per_update: int
    input_price_per_million_tokens: float | None
    output_price_per_million_tokens: float | None


def _percentile(values: Sequence[int], q: float) -> int | None:
    return int(np.percentile(values, q)) if values else None


def projection_rows(activities: Sequence[PairActivity], *, ratio: float, prices: ProjectionPrices) -> list[dict]:
    """One row per (`MIN_UNITS`, `MIN_DAYS`) option: eligible pairs, input token percentiles, and the
    monthly volume and cost. Counts only: no pair is named."""
    tokens = [estimate_tokens(round(estimated_input_chars(activity) * ratio)) for activity in activities]
    rows: list[dict] = []
    for min_units in MIN_UNITS_OPTIONS:
        eligible = [index for index, activity in enumerate(activities) if activity.units >= min_units]
        eligible_tokens = [tokens[index] for index in eligible]
        for min_days in MIN_DAYS_OPTIONS:
            monthly_updates = [
                updates_per_window(activities[index].units, min_units=min_units, min_days=min_days)
                * DAYS_PER_MONTH
                / WINDOW_DAYS
                for index in eligible
            ]
            updates = sum(monthly_updates)
            input_tokens = sum(
                count * (tokens[index] + prices.prompt_overhead_tokens)
                for count, index in zip(monthly_updates, eligible, strict=True)
            )
            output_tokens = updates * prices.output_tokens_per_update
            cost = None
            if prices.input_price_per_million_tokens is not None and prices.output_price_per_million_tokens is not None:
                cost = (
                    input_tokens * prices.input_price_per_million_tokens
                    + output_tokens * prices.output_price_per_million_tokens
                ) / 1_000_000
            rows.append(
                {
                    "min_units": min_units,
                    "min_days": min_days,
                    "eligible_pairs": len(eligible),
                    "input_tokens_p50": _percentile(eligible_tokens, 50),
                    "input_tokens_p90": _percentile(eligible_tokens, 90),
                    "input_tokens_p99": _percentile(eligible_tokens, 99),
                    "updates_per_month": updates,
                    "input_tokens_per_month": input_tokens,
                    "output_tokens_per_month": output_tokens,
                    "projected_monthly_cost_usd": cost,
                    "calibration_ratio": ratio,
                }
            )
    return rows
