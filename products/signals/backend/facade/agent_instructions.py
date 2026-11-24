from products.signals.backend.agent_instructions import (
    SignalAgentInstructions,
    SignalAgentRole,
    resolve_custom_image_id,
)

# Discussion runs on a report work in the same repository as its implementation runs.
_REPORT_RUN_IMAGE_STAGES = frozenset({"implementation", "inbox"})


def get_agent_instructions(*, team_id: int, origin_product: str, ai_stage: str | None) -> str:
    return SignalAgentInstructions().resolve(team_id, origin_product, ai_stage)


def get_report_run_custom_image_id(*, team_id: int, ai_stage: str | None) -> str | None:
    if ai_stage not in _REPORT_RUN_IMAGE_STAGES:
        return None
    return resolve_custom_image_id(team_id, SignalAgentRole.IMPLEMENTATION)
