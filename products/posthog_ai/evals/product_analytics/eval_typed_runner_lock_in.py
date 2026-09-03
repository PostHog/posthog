"""Multi-turn routing evals for the ``execute-sql`` lock-in.

Once the agent falls back to ``execute-sql``, it stays there: it uses SQL even
for questions a typed runner answered earlier in the same chat. These suites
measure that drift. Each case runs one agent session across four turns and
grades tool routing per turn with ``FirstRelevantTool(turn=N)``:

1. Turn 1 is typed-runner shaped and sets the habit (expect ``query-trends``).
2. Turn 2 forces the fallback: a row-level or windowed request only
   ``execute-sql`` can answer. It is a manipulation check, not a metric — drop
   any case whose turn 2 missed ``execute-sql`` before comparing arms.
3. Turn 3 asks a new typed-runner-shaped question. This is the headline number:
   does the agent recover to ``query-trends`` after the SQL turn?
4. Turn 4 asks another. It catches one-call recovery — and it is not optional:
   a fix that appends a routing hint to the SQL *result* (the re-anchor
   approach) fires only after the turn-3 route is chosen, so it cannot move
   turn 3 at all. Without turn 4 the harness is blind to that fix.

``eval_typed_runner_no_lock_in_control`` runs the same turns 3 and 4, but its
turn 2 is also typed-runner shaped. If turn 3 scores low in both arms, the
cause is conversation depth, not SQL lock-in, and every lock-in fix is aimed
wrong — run the control every time; the between-arm delta is the only number
that isolates the bug.

Turn 3 and 4 prompts must be new questions, not rephrasings of turn 1, or the
score confounds routing with "I answered this already".
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPublicEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import NoToolCall
from products.posthog_ai.evals.cli_mcp.scorers import FirstRelevantTool
from products.posthog_ai.evals.product_analytics.scorers import INSIGHT_WRITE_TOOLS

from .eval_sql_shaped_routing import ANALYSIS_QUERY_TOOLS

# See harness/discovery.py — scales the per-case timeout for every suite here.
MULTI_TURN_CASES = True


def _lock_in_case(
    *,
    name: str,
    turn1_prompt: str,
    turn2_prompt: str,
    turn3_prompt: str,
    turn4_prompt: str,
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=turn1_prompt,
        followups=[turn2_prompt, turn3_prompt, turn4_prompt],
        expected={"first_relevant_tool": {"tool": "query-trends"}},
    )


def _lock_in_scorers(*, turn2_expected: str) -> list:
    """One ``FirstRelevantTool`` per turn; turn 2 is a manipulation check.

    ``expected`` is per-case, so every turn scorer shares the one
    ``first_relevant_tool.tool`` (``query-trends``). Turn 2's target is the
    arm's defining difference, so its scorer takes an explicit ``tool``
    override instead of reading ``expected``.
    """
    return [
        NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
        FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS, turn=1),
        FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS, turn=2, tool=turn2_expected),
        FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS, turn=3),
        FirstRelevantTool(relevant_tools=ANALYSIS_QUERY_TOOLS, turn=4),
    ]


async def eval_typed_runner_no_lock_in_control(ctx: EvalContext) -> None:
    """Control arm: every turn is typed-runner shaped, so no SQL lock-in can set in.

    Built before the treatment arm on purpose: if turn 3 is low here too, the
    failure is conversation depth and the lock-in fixes are aimed wrong.
    """
    cases = [
        _lock_in_case(
            name="control_upload_trends_throughout",
            turn1_prompt="Count uploaded_file events per day over the last 30 days",
            turn2_prompt="Show downloaded_file events grouped by file_type over the last 30 days",
            turn3_prompt="How did weekly deleted_file events trend over the last 8 weeks?",
            turn4_prompt="Which day of the week sees the most shared_file_link events, over the last 8 weeks?",
        ),
        _lock_in_case(
            name="control_signup_trends_throughout",
            turn1_prompt="Write me a query showing the number of signed_up events per week over the last 8 weeks",
            turn2_prompt="Count distinct users who fired logged_in in the last 7 days",
            turn3_prompt="Break weekly uploaded_file counts down by file_type over the last 8 weeks",
            turn4_prompt="Show daily $pageview counts for /pricing/ over the last 30 days",
        ),
        _lock_in_case(
            name="control_download_trends_throughout",
            turn1_prompt="Show downloaded_file events grouped by file_type over the last 30 days",
            turn2_prompt="What is the average file_size_b on uploaded_file events over the last 30 days?",
            turn3_prompt="Count distinct users who uploaded a file each week over the last 8 weeks",
            turn4_prompt="How do weekly uploaded_file counts compare between the last 4 weeks and the 4 before that?",
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-typed-runner-no-lock-in-control-cli",
        cases=cases,
        scorers=_lock_in_scorers(turn2_expected="query-trends"),
        ctx=ctx,
    )


async def eval_typed_runner_lock_in(ctx: EvalContext) -> None:
    """Treatment arm: turn 2 forces ``execute-sql``; turns 3 and 4 measure recovery."""
    cases = [
        _lock_in_case(
            name="lock_in_upload_trends",
            turn1_prompt="Count uploaded_file events per day over the last 30 days",
            turn2_prompt="List the 10 largest files by file_size_b from uploaded_file, with their file_name",
            turn3_prompt="How did weekly deleted_file events trend over the last 8 weeks?",
            turn4_prompt="Which day of the week sees the most shared_file_link events, over the last 8 weeks?",
        ),
        _lock_in_case(
            name="lock_in_signup_trends",
            turn1_prompt="Write me a query showing the number of signed_up events per week over the last 8 weeks",
            turn2_prompt="For each account, show the first and last logged_in timestamp",
            turn3_prompt="Break weekly uploaded_file counts down by file_type over the last 8 weeks",
            turn4_prompt="Show daily $pageview counts for /pricing/ over the last 30 days",
        ),
        _lock_in_case(
            name="lock_in_download_trends",
            turn1_prompt="Show downloaded_file events grouped by file_type over the last 30 days",
            turn2_prompt="What is the median file_size_b on uploaded_file, and which accounts upload above it?",
            turn3_prompt="Count distinct users who uploaded a file each week over the last 8 weeks",
            turn4_prompt="How do weekly uploaded_file counts compare between the last 4 weeks and the 4 before that?",
        ),
    ]

    await SandboxedPublicEval(
        experiment_name="sandboxed-typed-runner-lock-in-cli",
        cases=cases,
        scorers=_lock_in_scorers(turn2_expected="execute-sql"),
        ctx=ctx,
    )
