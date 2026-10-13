"""Which write the agent picks when a user asks to change a feature flag.

The flag lifecycle tools (`feature-flag-enable`, `-disable`, `-archive`, `-unarchive`)
each change one state field and send no body, so a targeting change someone else made
between the agent's read and its write survives. `update-feature-flag` is a PATCH whose
`filters` replaces the whole object. Both can leave a flag in the state the user asked
for; only one of them is safe. So these cases grade the tool and the payload, not the
final state, which cannot tell the two apart.

Five conversations, one per way the choice goes wrong:

* ``metadata_rename_and_description`` — a rename must land both edits and must not
  carry `filters`.
* ``existing_key_create_recovers`` — an already-taken key must resolve by key and
  continue, not create a second flag or dead-end.
* ``disable_uses_lifecycle_tool`` / ``enable_uses_lifecycle_tool`` — a state flip must
  not go through the generic update.
* ``rollout_10_to_25_preserves_config`` — a rollout change genuinely needs the generic
  update, and must merge rather than replace.

The rollout case runs against `update-feature-flag` on purpose. Dedicated rollout tools
are not built yet; when they land, this case retargets to them and the preservation
assertion moves to whatever payload they take.

To run:
    flox activate -- bash -c "hogli evals eval_flag_tool_selection"
"""

from __future__ import annotations

from products.feature_flags.evals.scorers import (
    EXPLAINED_KEY_REUSE_QUESTION,
    AvoidedTool,
    CalledExpectedTool,
    FinalMessageJudge,
    GenericUpdateOmitsFields,
    GenericUpdateSetsFields,
    PreservedUnrelatedConfig,
    UpdatedRolloutTo,
)
from products.feature_flags.evals.seeders import (
    DISABLE_FLAG_KEY,
    ENABLE_FLAG_KEY,
    EXISTING_FLAG_KEY,
    EXISTING_FLAG_TO_PERCENTAGE,
    METADATA_FLAG_KEY,
    ROLLOUT_FLAG_KEY,
    ROLLOUT_FROM_PERCENTAGE,
    ROLLOUT_TO_PERCENTAGE,
    seed_active_flag,
    seed_existing_key_flag,
    seed_inactive_flag,
    seed_metadata_flag,
    seed_rollout_flag,
)
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall

# The rename case asks for these two values, so the prompt and the scorer read the same
# constants: a prompt that changed without the expectation would grade the old request.
METADATA_RENAMED_KEY = "file-preview-tiles"
METADATA_NEW_DESCRIPTION = "Show grid thumbnails in the file browser"


async def eval_flag_tool_selection(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="metadata_rename_and_description",
            prompt=(
                f"Rename the {METADATA_FLAG_KEY} feature flag to {METADATA_RENAMED_KEY}, and change its "
                f"description to '{METADATA_NEW_DESCRIPTION}'."
            ),
            setup=seed_metadata_flag,
            expected={
                "called_expected_tool": {"tools": ["update-feature-flag"]},
                # A rename has no reason to send targeting. Sending it replaces the
                # seeded plan condition with whatever the agent last read.
                "generic_update_omits_fields": {"fields": ["filters"]},
                # `name` is the description on this model, so the two halves of the
                # request land in two different fields and an agent can write one into
                # the other.
                "generic_update_sets_fields": {
                    "fields": {"key": METADATA_RENAMED_KEY, "name": METADATA_NEW_DESCRIPTION}
                },
            },
        ),
        SandboxedEvalCase(
            name="existing_key_create_recovers",
            prompt=(
                f"Create a feature flag called {EXISTING_FLAG_KEY} so we can gate the new multi-file "
                f"download behind it, at a {EXISTING_FLAG_TO_PERCENTAGE}% rollout."
            ),
            setup=seed_existing_key_flag,
            expected={
                # The prompt gives an exact key, which is what the by-key lookup is for.
                "called_expected_tool": {"tools": ["feature-flag-get-definition-by-key"]},
                "avoided_tool": {"tools": ["create-feature-flag"]},
                # The judge reads the final message, so "I reused the existing flag"
                # scores the same whether or not the write happened. This makes the
                # claim answerable from the tool calls.
                "updated_rollout_to": {"percentage": EXISTING_FLAG_TO_PERCENTAGE},
                # The seeded flag carries a 20% condition the update must not drop.
                "preserved_unrelated_config": {"required": True},
                "explained_key_reuse": {"required": True},
            },
        ),
        SandboxedEvalCase(
            name="disable_uses_lifecycle_tool",
            prompt=f"Turn the {DISABLE_FLAG_KEY} flag off, we're seeing complaints about it.",
            setup=seed_active_flag,
            expected={
                "called_expected_tool": {"tools": ["feature-flag-disable"]},
                "generic_update_omits_fields": {"fields": ["active", "archived", "filters"]},
            },
        ),
        SandboxedEvalCase(
            name="enable_uses_lifecycle_tool",
            prompt=f"Switch the {ENABLE_FLAG_KEY} flag on.",
            setup=seed_inactive_flag,
            expected={
                "called_expected_tool": {"tools": ["feature-flag-enable"]},
                "generic_update_omits_fields": {"fields": ["active", "archived", "filters"]},
            },
        ),
        SandboxedEvalCase(
            name="rollout_10_to_25_preserves_config",
            prompt=(
                f"Take the {ROLLOUT_FLAG_KEY} flag from a {ROLLOUT_FROM_PERCENTAGE}% rollout to "
                f"{ROLLOUT_TO_PERCENTAGE}%."
            ),
            setup=seed_rollout_flag,
            expected={
                "called_expected_tool": {"tools": ["update-feature-flag"]},
                "preserved_unrelated_config": {"required": True},
            },
            metadata={"retarget_when": "dedicated rollout tools land"},
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-feature-flags-tool-selection-cli",
        cases=cases,
        scorers=[
            # Every prompt names its flag by key, and the write tools take a numeric id.
            # An agent that resolved neither never reached the write, so this row keeps a
            # case that failed early from reading as a clean tool-selection result.
            RequiredToolCall(
                {"feature-flag-get-definition-by-key", "feature-flag-get-all", "feature-flag-get-definition"},
                name="resolved_flag_by_key",
            ),
            CalledExpectedTool(),
            AvoidedTool(),
            GenericUpdateOmitsFields(),
            GenericUpdateSetsFields(),
            PreservedUnrelatedConfig(),
            UpdatedRolloutTo(),
            FinalMessageJudge(name="explained_key_reuse", question=EXPLAINED_KEY_REUSE_QUESTION),
        ],
        ctx=ctx,
    )
