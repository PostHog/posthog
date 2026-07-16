"""Eval cases for the ``render-ui`` umbrella tool conventions.

Grades the "when to render a visualization" behaviour spelled out in the
``render-ui`` tool prompt (``services/mcp/src/templates/render-ui-prompt.md``)
and its exec-reference pointer (``services/mcp/src/templates/sections/cli-rendering.md``).

The categories the prompt tells the agent to render on, and the cases that
exercise each (all use the experiment family — the only entity in the hedgebox
demo that is both richly seeded and renderable):

* **Status / health** (``status_experiment``) — "how is X going" renders the
  experiment.
* **Lists / inventory** (``list_experiments``) — "what do we have" renders the
  ``*-list`` view rather than a markdown table.
* **Results / stats** (``experiment_results``) — "is it significant" renders the
  experiment's results view.

Two cross-cutting rules are graded alongside:

* ``ExecBeforeRender`` — ``render-ui`` is the final presentation step; every
  render must be preceded by a successful ``exec`` discovery call (resolve the
  real ID, confirm the data), never rendered first or with a guessed input.
* ``eval_no_render_for_query_results`` — ``query-trends`` & friends render via
  their own app automatically and must NOT be routed through ``render-ui``.

Not exercised here (sandbox/scope limits, not prompt gaps):

* **Error-tracking** (lists / evidence-mid-investigation) — the demo seeds
  Postgres issue rows + raw exception events but the sandbox's ClickHouse
  error-tracking *issues* aren't populated, so ``query-error-tracking-*`` returns
  an empty list and the agent has no issue to render.
* **Post-mutation** (create/launch/pause → render to confirm) — requires write
  side effects against the shared demo project.
* **Surveys** — the hedgebox demo seeds none.

``render-ui`` is registered only for MCP Apps hosts, which the sandboxed eval
client presents as, and the MCP server now serves the ``cli`` surface it lives
on by default.

To run a single eval:
    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_renders_entity_ui"
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.cli_mcp.scorers import (
    CalledTargetTool,
    DidNotRenderUi,
    ExecBeforeRender,
    RenderedEntityUi,
)

# Renderable experiment tools (detail + results). The agent may render the detail
# view (``experiment-get``) or a results view for a status/results question. Two
# results tools exist: ``experiment-results-get`` (handwritten — what the agent
# reaches for in practice) and ``experiment-timeseries-results`` (generated).
EXPERIMENT_RENDER_TOOLS = ["experiment-results-get", "experiment-get", "experiment-timeseries-results"]


async def eval_renders_entity_ui(ctx: EvalContext) -> None:
    """Entity-centric answers must render the entity (in addition to summarizing it)."""

    cases: list[SandboxedEvalCase] = [
        # Status / health → render the experiment ("File engagement boost" runs in the demo).
        SandboxedEvalCase(
            name="status_experiment",
            prompt="How is the 'File engagement boost' experiment going?",
            expected={
                "rendered_entity_ui": {"tool_name_any_of": EXPERIMENT_RENDER_TOOLS},
                "exec_before_render": {},
            },
        ),
        # Lists / inventory → render the experiment list, not a markdown table.
        SandboxedEvalCase(
            name="list_experiments",
            prompt="What experiments do we have in this project?",
            expected={
                "rendered_entity_ui": {"tool_name_any_of": ["experiment-list"]},
                "exec_before_render": {},
            },
        ),
        # Results / stats → render the experiment's results/detail view.
        SandboxedEvalCase(
            name="experiment_results",
            prompt="Show me the results of the 'Pricing page redesign' experiment — did it reach significance?",
            expected={
                "rendered_entity_ui": {"tool_name_any_of": EXPERIMENT_RENDER_TOOLS},
                "exec_before_render": {},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-mcp-renders-entity-ui-cli",
        cases=cases,
        scorers=[RenderedEntityUi(), ExecBeforeRender()],
        ctx=ctx,
    )


async def eval_no_render_for_query_results(ctx: EvalContext) -> None:
    """Insight/trends answers must NOT be routed through ``render-ui``.

    ``query-trends`` (and the other insight ``query-*`` tools) carry the custom
    ``query-results`` app, which renders automatically — they are not in
    ``render-ui``'s enum. The agent should answer with the query tool and never
    call ``render-ui``.
    """

    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="trends_chart_not_via_render_ui",
            prompt="Show me a trends chart of `$pageview` events over the last 7 days.",
            expected={
                "called_target_tool": {"tool": "query-trends"},
                "did_not_render_ui": {},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-cli-mcp-no-render-for-query-cli",
        cases=cases,
        scorers=[CalledTargetTool(), DidNotRenderUi()],
        ctx=ctx,
    )
