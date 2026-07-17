"""Error-tracking issues-list eval cases for the sandboxed agent.

Targets ``query-error-tracking-issues-list`` (added in
``feat(mcp): add generated error tracking query tools``). Each case asks
a broad "what's broken" / "which errors" style question and grades the
agent on:

* whether it called the new typed list tool at all (vs. hallucinating or
  reaching for a generic SQL workaround), and
* whether the filters it passed line up with what the user actually asked
  for (status, search, url substring, ordering, etc.).

``seed_error_tracking_issues`` (see ``seeders.py``) owns the full setup
per-case: it wipes the stale Hedgebox PSQL rows (whose CH events never
land in the sandboxed-eval environment), creates three deterministic
issues with fresh UUIDs, and writes the matching ``$exception`` events
directly to ClickHouse so the MCP tools resolve them. Cases that name a
specific seeded issue (e.g. "Team invite rejected" for the TypeError
search case) work out of the box, and the returned ``lookup_issues`` map
lets a future ``LookupIssueIdInOutput`` extension verify the agent's
final message references the per-case UUID.

To run::

    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_issues_list"
"""

from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import NoToolCall
from products.posthog_ai.evals.error_tracking.scorers import (
    ERROR_TRACKING_WRITE_TOOLS,
    IssuesListInputAlignment,
    IssuesListToolUsed,
)
from products.posthog_ai.evals.error_tracking.seeders import seed_error_tracking_issues


def _list_case(
    *,
    name: str,
    prompt: str,
    expected_input: dict[str, Any],
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={"issues_list_input": expected_input},
        setup=seed_error_tracking_issues,
    )


async def eval_issues_list(ctx: EvalContext) -> None:
    cases = [
        _list_case(
            name="issues_list_active_default",
            prompt="Which errors are happening in production right now?",
            expected_input={},
        ),
        _list_case(
            name="issues_list_top_by_users",
            prompt="What's the error affecting the most users this week? Just give me the issue name.",
            expected_input={"orderBy": "users", "dateRange": {"date_from": "-7d"}},
        ),
        _list_case(
            name="issues_list_filter_by_url_substring",
            prompt="Show me errors that happened on the /app/files page in the last week.",
            expected_input={"url": "/app/files", "dateRange": {"date_from": "-7d"}},
        ),
        _list_case(
            name="issues_list_resolved",
            prompt="List the errors we've already resolved.",
            expected_input={"status": "resolved"},
        ),
        _list_case(
            name="issues_list_search_typeerror",
            prompt="Find error issues related to TypeError.",
            expected_input={"searchQuery": "TypeError"},
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-error-tracking-issues-list-cli",
        cases=cases,
        scorers=[
            NoToolCall(forbidden=ERROR_TRACKING_WRITE_TOOLS, name="no_error_tracking_write"),
            IssuesListToolUsed(),
            IssuesListInputAlignment(),
        ],
        ctx=ctx,
    )
