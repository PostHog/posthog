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

import json
from pathlib import Path

from products.feature_flags.evals.scorers import (
    EXPLAINED_TAG_REQUIREMENT_QUESTION,
    REFUSED_WITHOUT_BLAMING_QUESTION,
    STALE_IS_NOT_SAFE_TO_REMOVE_QUESTION,
    AttemptedTool,
    AvoidedTool,
    CalledExpectedTool,
    CreatedFlagWithTags,
    FinalMessageJudge,
    FinalMessageNames,
)
from products.feature_flags.evals.seeders import (
    DEPENDENT_FLAG_KEY,
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

_TOOL_DEFINITIONS = Path(__file__).parents[3] / "services/mcp/schema/generated-tool-definitions.json"
FLAG_TOOL_CATEGORY = "Feature flags"


def flag_write_tools() -> list[str]:
    """Every flag write the MCP server exposes, read from the generated catalog.

    Derived rather than copied. The read-only case passes as soon as none of these
    landed, so a write tool added to the category later and missed here would be a
    write the case never looked for. Scheduling a change counts as a write, which is
    why `scheduled-changes-*` arrive with the rest.
    """
    definitions = json.loads(_TOOL_DEFINITIONS.read_text())
    return sorted(
        name
        for name, entry in definitions.items()
        if entry.get("category") == FLAG_TOOL_CATEGORY and entry.get("annotations", {}).get("readOnlyHint") is False
    )


async def eval_flag_answers(ctx: EvalContext) -> None:
    write_tools = flag_write_tools()
    cases: list[SandboxedEvalCase] = [
        SandboxedEvalCase(
            name="stale_flag_is_not_safe_to_remove",
            prompt=f"Is the {STALE_FLAG_KEY} flag stale, and what evidence do we have?",
            setup=seed_stale_flag,
            expected={
                "called_expected_tool": {"tools": ["feature-flags-status-retrieve"]},
                "stale_is_not_safe_to_remove": {"required": True},
                # The judge grades how the answer reads. This grades whether the agent
                # found the blocker at all, which it can only do by looking past the
                # status endpoint to the flag's dependents.
                "final_message_names": {"text": [DEPENDENT_FLAG_KEY]},
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
                "attempted_tool": {"tools": write_tools},
                "avoided_tool": {"tools": write_tools},
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
            FinalMessageNames(),
            FinalMessageJudge(name="stale_is_not_safe_to_remove", question=STALE_IS_NOT_SAFE_TO_REMOVE_QUESTION),
            FinalMessageJudge(name="refused_without_blaming", question=REFUSED_WITHOUT_BLAMING_QUESTION),
            FinalMessageJudge(name="explained_tag_requirement", question=EXPLAINED_TAG_REQUIREMENT_QUESTION),
        ],
        ctx=ctx,
    )
