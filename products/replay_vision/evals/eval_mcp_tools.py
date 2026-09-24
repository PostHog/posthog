"""Does a coding agent drive the Replay Vision MCP tools correctly?

Each case asks for one multi-step job an agent is likely to be given: set up an alert with a
destination, backfill history, and recover a failed scan.

Run: hogli evals eval_replay_vision_mcp_tools
"""

from __future__ import annotations

from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.replay_vision.evals.mcp_scorers import (
    CreatedMatchAlertWithWebhook,
    EstimatedBeforeBackfill,
    RetriedFailedObservation,
)
from products.replay_vision.evals.mcp_seeders import FAILED_SESSION_ID, SCANNER_NAME, seed_replay_vision_scanner

WEBHOOK_URL = "https://example.com/hooks/replay-vision"


async def eval_replay_vision_mcp_tools(ctx: EvalContext) -> None:
    await SandboxedPrivateEval(
        experiment_name="sandboxed-replay-vision-mcp-tools-cli",
        cases=[
            SandboxedEvalCase(
                name="alert_with_webhook",
                prompt=(
                    f'Send a webhook to {WEBHOOK_URL} every time the "{SCANNER_NAME}" Replay Vision scanner '
                    "flags a session."
                ),
                setup=seed_replay_vision_scanner,
                expected={"created_match_alert_with_webhook": {"webhook_url": WEBHOOK_URL}},
            ),
            SandboxedEvalCase(
                name="backfill_last_week",
                prompt=f'Run the "{SCANNER_NAME}" Replay Vision scanner over the last 7 days of recordings.',
                setup=seed_replay_vision_scanner,
                expected={"estimated_before_backfill": {}},
            ),
            SandboxedEvalCase(
                name="retry_failed_scan",
                prompt=(
                    f'The "{SCANNER_NAME}" scanner has no result for session {FAILED_SESSION_ID}. '
                    "Find out why and get it scanned."
                ),
                setup=seed_replay_vision_scanner,
                expected={"retried_failed_observation": {}},
            ),
        ],
        scorers=[CreatedMatchAlertWithWebhook(), EstimatedBeforeBackfill(), RetriedFailedObservation()],
        ctx=ctx,
    )
