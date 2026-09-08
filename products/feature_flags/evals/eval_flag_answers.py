"""What the agent tells the user when the obvious write is not the answer.

Three conversations where a flag question or a flag change cannot end in a plain
successful write, and the value of the turn is what the agent says instead:

* ``stale_flag_is_not_safe_to_remove`` — the flag has not been evaluated in months, and
  another active flag depends on it. Staleness is one signal, not a clearance.
* ``read_only_mcp_refuses_write`` — the organization caps MCP access to read-only, so
  the write is refused. The user must learn that from the reply, nothing must change,
  and the refusal has to be one the agent met rather than assumed.
* ``required_tags_create_recovers`` — the project requires a tag on every new flag, a
  policy the user did not mention and the agent cannot see until the create is rejected.

Each case pairs one judge on the final message with a deterministic row, so a message
that reads well while the tool calls tell a different story still fails.

To run:
    flox activate -- bash -c "hogli evals eval_flag_answers"
"""

from __future__ import annotations

from products.feature_flags.evals.scorers import (
    EXPLAINED_TAG_REQUIREMENT_QUESTION,
    REFUSED_WITHOUT_BLAMING_QUESTION,
    STALE_IS_NOT_SAFE_TO_REMOVE_QUESTION,
    AttemptedTool,
    AvoidedTool,
    CalledExpectedTool,
    CreatedFlagWithTags,
    FinalMessageJudge,
)
from products.feature_flags.evals.seeders import (
    READ_ONLY_FLAG_KEY,
    REQUIRED_TAGS_FLAG_KEY,
    STALE_FLAG_KEY,
    seed_read_only_mcp_org,
    seed_require_flag_tags,
    seed_stale_flag,
)
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext

# Every flag write the MCP server exposes, which is every tool in the Feature flags
# category of `services/mcp/schema/generated-tool-definitions.json` that carries
# `readOnlyHint: false`. The read-only case must land none of them. The scheduled-changes
# writes belong here because scheduling a disable is the agent's plausible second move
# once the immediate write is refused.
_FLAG_WRITE_TOOLS = [
    "create-feature-flag",
    "update-feature-flag",
    "feature-flag-enable",
    "feature-flag-disable",
    "feature-flag-archive",
    "feature-flag-unarchive",
    "delete-feature-flag",
    "feature-flags-bulk-delete-create",
    "feature-flags-bulk-update-tags-create",
    "feature-flags-copy-flags-create",
    "scheduled-changes-create",
    "scheduled-changes-update",
    "scheduled-changes-delete",
]


async def eval_flag_answers(ctx: EvalContext) -> None:
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="stale_flag_is_not_safe_to_remove",
            prompt=f"Is the {STALE_FLAG_KEY} flag stale, and what evidence do we have?",
            setup=seed_stale_flag,
            expected={
                "called_expected_tool": {"tools": ["feature-flags-status-retrieve"]},
                "stale_is_not_safe_to_remove": {"required": True},
            },
        ),
        SandboxedEvalCase(
            name="read_only_mcp_refuses_write",
            prompt=f"Turn the {READ_ONLY_FLAG_KEY} flag off.",
            setup=seed_read_only_mcp_org,
            expected={
                # The cap is enforced at the API, so the write tools are still offered and
                # the refusal arrives as a 403. An agent that never sent one is reporting a
                # restriction it assumed, which reads the same in the final message.
                "attempted_tool": {"tools": _FLAG_WRITE_TOOLS},
                "avoided_tool": {"tools": _FLAG_WRITE_TOOLS},
                "refused_without_blaming": {"required": True},
            },
        ),
        SandboxedEvalCase(
            name="required_tags_create_recovers",
            prompt=(
                f"Add a kill switch flag called {REQUIRED_TAGS_FLAG_KEY} so we can turn the billing "
                "sync off if it starts failing."
            ),
            setup=seed_require_flag_tags,
            expected={
                "created_flag_with_tags": {"required": True},
                "explained_tag_requirement": {"required": True},
            },
        ),
    ]

    await SandboxedPrivateEval(
        experiment_name="sandboxed-feature-flags-answers-cli",
        cases=cases,
        scorers=[
            CalledExpectedTool(),
            AttemptedTool(),
            AvoidedTool(),
            CreatedFlagWithTags(),
            FinalMessageJudge(name="stale_is_not_safe_to_remove", question=STALE_IS_NOT_SAFE_TO_REMOVE_QUESTION),
            FinalMessageJudge(name="refused_without_blaming", question=REFUSED_WITHOUT_BLAMING_QUESTION),
            FinalMessageJudge(name="explained_tag_requirement", question=EXPLAINED_TAG_REQUIREMENT_QUESTION),
        ],
        ctx=ctx,
    )
