from products.signals.backend.agent_instructions import (
    SignalAgentInstructions,
    SignalAgentRole,
    resolve_custom_image_id,
)


def get_agent_instructions(*, team_id: int, origin_product: str, ai_stage: str | None) -> str:
    return SignalAgentInstructions().resolve(team_id, origin_product, ai_stage)


def get_report_run_custom_image_id(*, team_id: int) -> str | None:
    """The project's implementation image. Discussion runs on a report work in the same repository, so they use it too."""
    return resolve_custom_image_id(team_id, SignalAgentRole.IMPLEMENTATION)
