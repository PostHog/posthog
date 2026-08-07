"""Eval cases for the ``posthog:exec`` cli workflow conventions.

Eval functions, each grading a single behavior the cli prompts spell out
in ``services/mcp/src/templates/cli-proxy-tool.md`` and
``services/mcp/src/templates/cli-proxy-command.md``:

* ``eval_typo_recovery`` — when prompted to use a deprecated or misspelled
  tool name, the agent recovers via the redirect / unknown-tool error and
  ends up calling a correct replacement.
* ``eval_schema_drilldown`` — for a non-trivial trends question, the agent
  drills into nested fields (``series``, ``breakdownFilter``) before the
  final ``call``.
* ``eval_search_first`` — for an open-ended request the agent prefers
  ``search <regex>`` over the bare ``tools`` listing.
* ``eval_info_before_call`` — every successful ``call <tool>`` is preceded
  by an ``info <tool>`` in the same run.
* ``eval_verify_event_before_query`` — for ``query-*`` calls, the agent
  verifies the event/property exists via ``read-data-schema`` first.

Every case exercises the ``posthog:exec`` tool, which the MCP server now
registers by default.

To run a single eval:
    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_typo_recovery"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.cli_mcp.scorers import (
    CalledTargetTool,
    DrilledIntoSchema,
    InfoBeforeCall,
    PreferredSearchOverTools,
    RanPythonPostProcessing,
    RecoveredToCorrectTool,
    UsedJsonOutputFormat,
    VerifiedEventBeforeQuery,
)


async def eval_typo_recovery(ctx: EvalContext) -> None:
    """Prompted with a deprecated or typo'd tool name, the agent must recover."""

    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="deprecated_query_run",
            prompt=("Use the `query-run` tool to find how many `$pageview` events we had in the last 7 days."),
            expected={
                "recovered_to_correct_tool": {
                    "wrong": "query-run",
                    "correct_any_of": ["query-trends", "execute-sql"],
                },
            },
        ),
        SandboxedEvalCase(
            name="typo_insight_create",
            prompt=("Create an insight named 'Daily pageviews' using the `insite-create` tool."),
            expected={
                "recovered_to_correct_tool": {
                    "wrong": "insite-create",
                    "correct_any_of": ["insight-create"],
                },
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-mcp-typo-recovery-cli",
        cases=cases,
        scorers=[RecoveredToCorrectTool()],
        ctx=ctx,
    )


async def eval_schema_drilldown(ctx: EvalContext) -> None:
    """Trends question with breakdown — the agent must drill into nested schema fields."""

    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="trends_with_action_and_breakdown",
            # Uses a seeded hedgebox action ("Visited Marius Tech Tips campaign")
            # rather than a canonical event so the agent can't reach for
            # `EventsNode` from priors or copy the worked example in the
            # query-trends description — it must drill into `series` to discover
            # `ActionsNode` and its `id` field.
            prompt=(
                "Run a trends query for the `Visited Marius Tech Tips campaign` "
                "action over the last 14 days, broken down by `$browser`. Return the result."
            ),
            expected={
                "drilled_into_schema": {
                    "tool": "query-trends",
                    "fields": ["series", "breakdownFilter"],
                },
                "called_target_tool": {"tool": "query-trends"},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-mcp-schema-drilldown-cli",
        cases=cases,
        scorers=[CalledTargetTool(), DrilledIntoSchema()],
        ctx=ctx,
    )


async def eval_search_first(ctx: EvalContext) -> None:
    """Open-ended discovery — the agent must prefer ``search`` over bare ``tools``."""

    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="find_feature_flag_tool",
            prompt="List all feature flags in this project.",
            expected={
                "preferred_search_over_tools": {},
                "called_target_tool": {"tool": "feature-flag-get-all"},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-mcp-search-first-cli",
        cases=cases,
        scorers=[CalledTargetTool(), PreferredSearchOverTools()],
        ctx=ctx,
    )


async def eval_info_before_call(ctx: EvalContext) -> None:
    """Every successful ``call <tool>`` must be preceded by ``info <tool>``."""

    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="info_before_dashboard_create",
            prompt="Create a dashboard named 'Onboarding signals'.",
            expected={
                "info_before_call": {"tool": "dashboard-create"},
                "called_target_tool": {"tool": "dashboard-create"},
            },
        ),
        SandboxedEvalCase(
            name="info_before_read_data_schema",
            prompt="What event names contain the word 'feedback' in this project?",
            expected={
                "info_before_call": {"tool": "read-data-schema"},
                "called_target_tool": {"tool": "read-data-schema"},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-mcp-info-before-call-cli",
        cases=cases,
        scorers=[CalledTargetTool(), InfoBeforeCall()],
        ctx=ctx,
    )


async def eval_json_for_post_processing(ctx: EvalContext) -> None:
    """Post-processing scenario — agent must request raw JSON and run Python on it.

    The default ``output_format: "optimized"`` is token-efficient but lossy
    (truncated, formatted) and not safe to ``json.loads``. When the agent's
    plan involves programmatic post-processing (counting, filtering, math),
    it should opt into ``output_format: "json"`` so the result is a parseable
    JSON document, then drive Python via ``Bash`` to compute the answer.
    """

    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="dashboards_python_postprocess",
            prompt=(
                "List every dashboard in this project, then write a small Python "
                "script that counts how many dashboard names have more than 3 words "
                "(words = whitespace-separated tokens). Return that count along with "
                "the names of those dashboards. Use the JSON output of the listing "
                "tool so you can parse it cleanly in Python."
            ),
            expected={
                "called_target_tool": {"tool": "dashboards-get-all"},
                "used_json_output_format": {"tool": "dashboards-get-all"},
                "ran_python_post_processing": {},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-mcp-json-postprocess-cli",
        cases=cases,
        scorers=[
            CalledTargetTool(),
            UsedJsonOutputFormat(),
            RanPythonPostProcessing(),
        ],
        ctx=ctx,
    )


async def eval_verify_event_before_query(ctx: EvalContext) -> None:
    """``query-*`` calls must be preceded by a successful ``read-data-schema`` call."""

    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="trends_pageview_verifies_first",
            prompt="How many `$pageview` events did we have last week?",
            expected={
                "verified_event_before_query": {"query_tool": "query-trends"},
                "called_target_tool": {"tool": "query-trends"},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-mcp-verify-event-cli",
        cases=cases,
        scorers=[CalledTargetTool(), VerifiedEventBeforeQuery()],
        ctx=ctx,
    )
