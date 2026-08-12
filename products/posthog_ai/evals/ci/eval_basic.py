"""Placeholder eval cases for the sandboxed coding agent.

To run:
    flox activate -- bash -c "set -a; source .env; set +a; python -m products.posthog_ai.eval_harness.harness eval_basic"

Example eval case pattern:

    1. Define a SandboxedEvalCase with prompt + expected outcomes
    2. Call SandboxedPublicEval (or SandboxedPrivateEval) with scorers
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.evals.cli_mcp.scorers import CalledTargetTool, SurfacedGeneratedAppUrl


async def eval_bugfix(ctx: EvalContext) -> None:
    cases = [
        SandboxedEvalCase(
            name="fix_divide_bug",
            prompt="The divide function in calculator.py returns wrong results. Fix the bug so all tests pass.",
            repo_fixture="bugfix_calculator",
        ),
        SandboxedEvalCase(
            name="mcp_pageview_count_last_week",
            prompt=(
                "Using the PostHog MCP tools available to you, query how many $pageview events "
                "were captured in the last 7 days for the current project. Run a HogQL query "
                "via the PostHog MCP server and report the total count as a single integer in "
                "your final reply."
            ),
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-bugfix-cli",
        cases=cases,
        scorers=[],
        ctx=ctx,
    )


async def eval_app_link_generation(ctx: EvalContext) -> None:
    """Entity links must be resolved via ``generate-app-url``, not hand-built.

    Reproduces the reported failure where the MCP confidently returned 404 links — a person
    UUID under the singular ``/person/`` slug instead of ``/persons/``, and session ids mistyped
    into ``/replay/`` paths. The trigger is an entity discovered via ``execute-sql``: there is no
    tool-attached ``_posthogUrl`` on a raw query result, so the agent must call ``generate-app-url``
    and surface the url it returns verbatim rather than guessing the slug or retyping the id.

    Runs in both mcp modes — ``generate-app-url`` is registered in each.
    """
    cases: list[SandboxedEvalCase] = [
        # Person by UUID: the exact reported slug bug (`/persons/<uuid>`, not `/person/<uuid>`).
        # Forcing the UUID via SQL keeps the agent off persons-retrieve's `_posthogUrl` shortcut,
        # so `generate-app-url` is the only correct path.
        SandboxedEvalCase(
            name="person_profile_link",
            prompt=(
                "Using SQL, find one person in this project and read their UUID. Then give me a "
                "clickable link to open that person's profile page in PostHog."
            ),
            expected={
                "called_target_tool": {"tool": "generate-app-url"},
                "surfaced_generated_app_url": {},
            },
        ),
        # Event link: another raw-SQL entity with no `_posthogUrl` tool, where ids must be passed
        # as params rather than transcribed into the path.
        SandboxedEvalCase(
            name="event_link",
            prompt=(
                "Using SQL, find one recent `$pageview` event and read its uuid and timestamp. "
                "Then give me a clickable link to view that specific event in PostHog."
            ),
            expected={
                "called_target_tool": {"tool": "generate-app-url"},
                "surfaced_generated_app_url": {},
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-app-link-generation-cli",
        cases=cases,
        scorers=[CalledTargetTool(), SurfacedGeneratedAppUrl()],
        ctx=ctx,
    )
