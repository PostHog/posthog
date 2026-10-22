from __future__ import annotations

from typing import Any

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.evals.creation_scorers import CreatedFlagConfiguration
from products.feature_flags.evals.offline_config import offline_suite
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

NO_SEND_LOGS = True

FLAG_KEY = "bulk-file-export-preview"


def seed_flag_creation(context: CustomPromptSandboxContext) -> dict[str, Any]:
    if FeatureFlag.objects.filter(team_id=context.team_id, key=FLAG_KEY).exists():
        raise ValueError("Flag creation eval requires an unused key")
    return {"team_id": context.team_id}


async def eval_flag_creation(ctx: EvalContext) -> None:
    await SandboxedPrivateEval(
        no_send_logs=NO_SEND_LOGS,
        experiment_name="sandboxed-feature-flags-creation-cli",
        offline_suite=offline_suite(
            "feature_flags/eval_flag_creation::eval_flag_creation",
            metrics=["created_flag_configuration"],
        ),
        send_to_posthog=True,
        cases=[
            SandboxedEvalCase(
                name="boolean_flag_with_targeted_rollout",
                prompt=(
                    f"Create an active boolean feature flag with the key '{FLAG_KEY}'. "
                    "Roll it out to 25% of account groups whose plan is exactly 'business/standard'. "
                    "Do not include any other audience or variants."
                ),
                setup=seed_flag_creation,
                expected={
                    "created_flag_configuration": {
                        "key": FLAG_KEY,
                        "rollout_percentage": 25,
                        "aggregation_group_type_index": 0,
                        "property": {
                            "key": "plan",
                            "type": "group",
                            "group_type_index": 0,
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
