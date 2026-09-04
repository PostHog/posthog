"""Seed helpers for the stale-flag cleanup evals.

Each seeder creates one invented flag in the case's isolated team, shaped to land in a
specific branch of ``cleaning-up-stale-feature-flags``. The keys are invented and must not
exist in the sandbox's ``posthog/hedgebox`` checkout — the cleanup cases assert a
no-references outcome, so a key that ever appears in that repo would flip the case.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

STALE_FULL_ROLLOUT_FLAG_KEY = "sunset-widget-rollout"
STALE_PARTIAL_ROLLOUT_FLAG_KEY = "beta-search-ranking"

# Mirrors eval_instrument_flags: the shared file-edit scorers match Claude's named file
# tools (Edit/Write/MultiEdit), which the codex runtime does not carry, so a codex run
# would report edit-direction numbers that are artifacts of the harness, not the agent.
_CODEX_UNSUPPORTED = (
    "This suite grades file-edit direction via Claude's named file tools, which the codex "
    "runtime does not have. Run without --agent-runtime codex."
)


def _require_claude_runtime(context: CustomPromptSandboxContext) -> None:
    """Refuse codex runs as an infra error rather than scoring a corrupt mean."""
    if context.runtime_adapter == "codex":
        raise RuntimeError(_CODEX_UNSUPPORTED)


def guard_claude_runtime(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Setup for cases that seed nothing but still must not run under codex."""
    _require_claude_runtime(context)
    return {}


def seed_stale_full_rollout_flag(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """A configuration-stale boolean flag: 100% rollout, no conditions, never called, 90 days old."""
    _require_claude_runtime(context)
    flag = FeatureFlag.objects.create(
        team_id=context.team_id,
        key=STALE_FULL_ROLLOUT_FLAG_KEY,
        name="Sunset widget rollout",
        created_by_id=context.user_id,
        active=True,
        created_at=datetime.now(UTC) - timedelta(days=90),
        filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
    )
    return {"flag_id": flag.id, "flag_key": flag.key, "rollout": "full"}


def seed_stale_partial_rollout_flag(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """A usage-stale flag stuck at a 40% rollout — a candidate no agent may edit code for."""
    _require_claude_runtime(context)
    flag = FeatureFlag.objects.create(
        team_id=context.team_id,
        key=STALE_PARTIAL_ROLLOUT_FLAG_KEY,
        name="Beta search ranking",
        created_by_id=context.user_id,
        active=True,
        created_at=datetime.now(UTC) - timedelta(days=120),
        last_called_at=datetime.now(UTC) - timedelta(days=60),
        filters={"groups": [{"properties": [], "rollout_percentage": 40}]},
    )
    return {"flag_id": flag.id, "flag_key": flag.key, "rollout": "partial"}
