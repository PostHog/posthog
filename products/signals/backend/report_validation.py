"""The prompt a report hands its reader to check the finding on their own machine.

A validation prompt is part of a report's content, not an entry in its log — it lives on
`SignalReport.validation_prompt` alongside the summary it was written against, so it is replaced
with that summary rather than accumulating versions beside it. Kept out of `artefact_schemas.py`
for that reason, and kept as dependency-light as `report_prompts.py` for the same one: it loads
with the signals models, so it must not drag `posthog.schema` onto every process's
`django.setup()` path.

The prompt stays on the report and never reaches the pull request. A reviewer who wants to trust a
self-driving PR has to be able to reproduce the finding first, and the steps that make that
possible often name a replica, an internal dashboard, or a staff-only tool. The report sits behind
PostHog auth; the target repository is frequently public, so the same text there would publish
them. `auto_start._build_autostart_task_description` takes the summary and not this field, which is
what keeps the two apart.
"""

from __future__ import annotations

from collections.abc import Sequence

from products.signals.backend.enums import SignalSourceProduct

# One prompt, in characters. Long enough to carry a query, a plan, and the commands around them;
# short enough that a reader still reads it before pasting it into an agent.
MAX_VALIDATION_PROMPT_LENGTH = 6000


def normalize_validation_prompt(prompt: str) -> str:
    """The prompt as it should be stored: outer whitespace trimmed, over-long text refused.

    Returns `""` for anything unusable, because the inbox renders the block only when the field has
    content — a blank or truncated prompt reads as a broken feature, where no prompt at all reads
    as a report that had nothing to say about reproducing itself.
    """
    stripped = prompt.strip()
    if len(stripped) > MAX_VALIDATION_PROMPT_LENGTH:
        return ""
    return stripped


# What the presentation turn is told to write into `validation_prompt`. Generic across sources: the
# two questions a reviewer asks of any finding are "can I see this happening" and "how will I know
# the fix worked".
VALIDATION_PROMPT_GUIDANCE = """## The local validation prompt

`validation_prompt` is a prompt the reader copies into a coding agent running on their own machine, so they can check this finding themselves before they trust a pull request written from it. Write it as instructions addressed to that agent, not as prose about the report.

It stays on the report and is never copied into a pull request, so it is the one place in your output where you may name an internal host, a replica, a dashboard, or a staff-only tool. Use that: a prompt that only says "reproduce the issue" hands the reader nothing they did not already have.

Cover two things, in this order:

- **Recreate.** How to observe the problem again from scratch: the exact command, query, URL, or user action, the data or environment it needs, and what a person sees when it is happening. Name the files and functions the reader has to open, with the paths you found during research.
- **Test.** How to tell a fix worked: the measurement to take before changing anything, the value it should reach afterwards, and the tests or checks to run. Say what would show the fix is wrong as well as what would show it is right.

Rules:

- Only claim steps you actually confirmed this session. A plausible reproduction that does not run costs the reader more than no prompt.
- Give the reader the evidence, not a pointer to it: paste the query, the error, or the numbers rather than telling them to go and look the finding up.
- Leave it empty when you could not work out how to reproduce the finding. An honest gap is better than invented steps."""


# Per-source additions to the guidance above, keyed by `source_product`. A source earns an entry
# when its findings are judged on evidence the generic two-part prompt would not ask for — for
# pganalyze, a plan from a database that holds real data, which no local checkout can produce.
_SOURCE_VALIDATION_GUIDANCE: dict[str, str] = {
    SignalSourceProduct.PGANALYZE: """### Signals from pganalyze

A database finding cannot be checked against an empty local database: the same query takes a different plan once the tables hold real data and the statistics reflect it. So the prompt has to hand over what the reader needs to reproduce the plan, and say where to run it.

Include:

- The pganalyze check that fired and what it reported, quoted rather than paraphrased.
- The full query text, and the relation or index it names.
- Where the query comes from in the codebase: the file and function that builds it, so the reader can change it. Say plainly if you could not find it.
- The numbers pganalyze gave for it — call count, mean and total time, rows read — so the reader knows what "slow" means here.
- `EXPLAIN (ANALYZE, BUFFERS)` on a read replica rather than a local database, and the plan lines to compare: which node the time sits in, and whether it reads an index or scans the relation.
- For an index recommendation, how to test it before shipping it: build the index on the replica with `CREATE INDEX CONCURRENTLY`, re-run the plan, and compare against the plan you captured first. Say what a planner that ignores the new index would mean.""",
}


def render_previous_validation_prompt(previous_validation_prompt: str | None) -> str:
    """The prompt a report already carries, offered back to a re-research run.

    Without this the reader loses their prompt every time research repeats: the presentation turn
    never sees the stored one, so it cannot re-send what still holds.
    """
    if not previous_validation_prompt:
        return ""
    return (
        "### The validation prompt this report already carries\n\n"
        "Send it again if your research this run leaves it accurate, replace it if the new findings "
        "change how a reader would reproduce or test this, and leave the field out if you can no "
        "longer reproduce the finding at all — the report then keeps what it has.\n\n"
        f"```\n{previous_validation_prompt}\n```"
    )


def source_validation_guidance(source_products: Sequence[str]) -> str:
    """The per-source guidance blocks for a report's sources, in a stable order.

    Deduplicated because a report's signals often repeat a source, and ordered by
    `_SOURCE_VALIDATION_GUIDANCE` rather than by the signals so the prompt a run sends is decided
    by the source set alone — the same set of sources always renders the same prompt.
    """
    present = set(source_products)
    return "\n\n".join(guidance for source, guidance in _SOURCE_VALIDATION_GUIDANCE.items() if source in present)
