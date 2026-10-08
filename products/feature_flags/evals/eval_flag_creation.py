from __future__ import annotations

from typing import Any

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.evals.creation_scorers import CreatedFlagConfiguration
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

FLAG_KEY = "bulk-file-export-preview"


def seed_flag_creation(context: CustomPromptSandboxContext) -> dict[str, Any]:
    if FeatureFlag.objects.for_team(context.team_id).filter(key=FLAG_KEY).exists():
        raise ValueError("Flag creation eval requires an unused key")
    return {"team_id": context.team_id}


async def eval_flag_creation(ctx: EvalContext) -> None:
    await SandboxedPrivateEval(
        experiment_name="sandboxed-feature-flags-creation-cli",
        cases=[
            SandboxedEvalCase(
                name="boolean_flag_with_targeted_rollout",
                prompt=(
                    f"Create an active boolean feature flag with the key '{FLAG_KEY}'. "
                    "Roll it out to 25% of people whose plan is exactly 'business/standard'. "
                    "Do not include any other audience or variants."
                ),
                setup=seed_flag_creation,
                expected={
                    "created_flag_configuration": {
                        "key": FLAG_KEY,
                        "rollout_percentage": 25,
                        "property": {
                            "key": "plan",
                            "type": "person",
                            "operator": "exact",
                            "value": ["business/standard"],
                        },
                    }
                },
            )
        ],
        scorers=[CreatedFlagConfiguration()],
        ctx=ctx,
    )
