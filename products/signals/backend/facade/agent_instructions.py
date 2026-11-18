from products.signals.backend.agent_instructions import SignalAgentInstructions


def get_agent_instructions(*, team_id: int, origin_product: str, ai_stage: str | None) -> str:
    return SignalAgentInstructions().resolve(team_id, origin_product, ai_stage)
