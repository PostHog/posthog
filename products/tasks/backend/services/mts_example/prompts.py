from __future__ import annotations

import json

from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    PriorityAssessment,
    ReportPresentationOutput,
    SignalFinding,
)
from products.tasks.backend.services.mts_example.schemas import CursedItemCandidates

_PREAMBLE = """You are an agent surfacing cursed code — the worst-named identifiers and the ugliest stale comments — inside the PostHog/posthog repository.
Your job is to discover a small set of genuinely cursed items, then research each one thoroughly enough that a downstream coding agent could act on it (rename, delete, document).

You have two investigation tools:
1. **The codebase** — the full PostHog/posthog repository is cloned on disk. Use file search, grep, code reading, `git log`, and `git blame`.
2. **PostHog MCP** — query PostHog product data via tools such as `execute-sql`, `list-event-definitions`, `list-property-definitions`, `list-feature-flags`, `insights-get-all`, `experiment-get-all`, `dashboards-get-all`. Use these to check whether the cursedness has also leaked into user-facing telemetry."""


def build_discovery_prompt(max_items: int) -> str:
    schema = json.dumps(CursedItemCandidates.model_json_schema(), indent=2)
    return f"""{_PREAMBLE}

## Step 1 — Discover up to {max_items} cursed items

Scan the repository for the worst offenders across two categories:

- **kind = "identifier"** — variables, functions, classes, or constants with lazy, confusing, or misleading names. For example: `x`, `tmp2`, `data`, `foo_v2_new`, `handleClick2Real`, non-trivial single-letter names, ambiguous abbreviations, or obviously-stale `_old`/`_legacy` names still wired into live code.
- **kind = "comment"** — comments that are stale (e.g. TODOs dated years ago), panicked ("DO NOT TOUCH THIS"), or that confess a bug/hack that still lives in the code.

Be selective — pick items that are genuinely the most cursed. Prefer items inside real product code over tests, fixtures, or vendored files.

For each item, record:
- `content` — the exact identifier name, or the exact comment text
- `file_path` — repo-relative path
- `line_number` — 1-based
- `cursedness_reason` — one sentence explaining why it's cursed

Respond with a JSON object matching this schema:

<jsonschema>
{schema}
</jsonschema>"""


def build_research_prompt(
    *,
    item_content: str,
    item_kind: str,
    file_path: str,
    line_number: int,
    cursedness_reason: str,
    index: int,
    total: int,
    synthetic_signal_id: str,
) -> str:
    schema = json.dumps(SignalFinding.model_json_schema(), indent=2)
    return f"""## Step 2 — Research item {index}/{total}

**Item ({item_kind}):** `{item_content}`
**Location:** `{file_path}:{line_number}`
**Why it's cursed:** {cursedness_reason}

Investigate this item so a downstream coding agent could act on it:

1. **Blame & commits:** run `git blame` on `{file_path}` around line {line_number} and trace the commit(s) that introduced the cursed item. Include 1–3 commit short-SHAs in `relevant_commit_hashes`. In each `reason`, name the blame author (e.g. "introduced by @jane in the original refactor").
2. **Codebase context:** read the surrounding file and key call sites. Add the most impactful paths to `relevant_code_paths`, with `{file_path}` first.
3. **PostHog MCP (required):** call at least one PostHog MCP tool to check whether the cursedness reaches user-facing telemetry — for example, a similarly-named event in `list-event-definitions`, a property in `list-property-definitions`, a flag key in `list-feature-flags`, or an `execute-sql` on `events` confirming the code actually fires. Record in `data_queried` which MCP tool(s) you called and what they returned. If MCP shows no leak into telemetry, that's still a valid result — say so.

Return a `SignalFinding` JSON object with:
- `signal_id` = `{synthetic_signal_id}` (use exactly this value)
- `verified=true` only if you confirmed the cursedness via both code AND PostHog data (MCP)

<jsonschema>
{schema}
</jsonschema>"""


def build_actionability_prompt(total_items: int) -> str:
    schema = json.dumps(ActionabilityAssessment.model_json_schema(), indent=2)
    return f"""## Step 3 — Actionability

You've researched {total_items} cursed item(s). Assess whether this report is actionable:

- **immediately_actionable** — the items are clear renames/cleanups/doc fixes a coding agent could ship today.
- **requires_human_input** — actionable but needs someone to weigh naming conventions, deprecation policy, or team ownership first.
- **not_actionable** — the items turn out to be fine on reflection, or already addressed.

Base your assessment on the concrete findings, not vibes.

Respond with JSON matching:

<jsonschema>
{schema}
</jsonschema>"""


def build_priority_prompt(total_items: int) -> str:
    schema = json.dumps(PriorityAssessment.model_json_schema(), indent=2)
    return f"""## Step 4 — Priority

Assign a P0–P4 priority across the {total_items} cursed item(s). Lean on the MCP evidence you gathered: cursedness that leaked into user-facing telemetry or live product code is higher priority; cursedness buried in tests or dead code is lower.

- **P0** — Cursedness directly reaches customers (e.g. event/property names shipped in product data) and actively causes confusion.
- **P1** — Prominent cursedness in a hot code path.
- **P2** — Cursedness in real product code with limited blast radius.
- **P3** — Minor, mostly cosmetic.
- **P4** — Negligible.

<jsonschema>
{schema}
</jsonschema>"""


def build_presentation_prompt(total_items: int) -> str:
    schema = json.dumps(ReportPresentationOutput.model_json_schema(), indent=2)
    return f"""## Step 5 — Title and summary

Write a PR-style `title` (≤70 chars, sentence case, conventional-commit style) and an Axios-style `summary` covering all {total_items} cursed item(s). A lightly wry framing is fine (for example, `chore(cleanup): Cursed identifier research — 3 stowaway names in product/`) but keep both factual and PR-ready.

<jsonschema>
{schema}
</jsonschema>"""
