from enum import StrEnum
from uuid import UUID

from products.signals.backend.models import SignalTeamConfig

AGENT_STEERING_MAX_LENGTH = 20_000


class SignalAgentRole(StrEnum):
    SCOUT = "scout"
    RESEARCH = "research"
    IMPLEMENTATION = "implementation"


STEERING_FIELDS = {
    SignalAgentRole.SCOUT: "scout_instructions",
    SignalAgentRole.RESEARCH: "research_instructions",
    SignalAgentRole.IMPLEMENTATION: "implementation_instructions",
}

CUSTOM_IMAGE_FIELDS = {
    SignalAgentRole.SCOUT: "scout_custom_image_id",
    SignalAgentRole.RESEARCH: "research_custom_image_id",
    SignalAgentRole.IMPLEMENTATION: "implementation_custom_image_id",
}


def resolve_custom_image_id(
    team_id: int, role: SignalAgentRole, scout_custom_image_id: UUID | None = None
) -> str | None:
    if scout_custom_image_id is not None:
        return str(scout_custom_image_id)
    image_id = (
        SignalTeamConfig.objects.filter(team_id=team_id).values_list(CUSTOM_IMAGE_FIELDS[role], flat=True).first()
    )
    return str(image_id) if image_id is not None else None


class SignalAgentInstructions:
    @staticmethod
    def role_for_run(origin_product: str, ai_stage: str | None) -> SignalAgentRole | None:
        if origin_product == "signals_scout":
            return SignalAgentRole.SCOUT
        if origin_product == "signal_report":
            if ai_stage == "research":
                return SignalAgentRole.RESEARCH
            if ai_stage == "implementation":
                return SignalAgentRole.IMPLEMENTATION
        return None

    def resolve(self, team_id: int, origin_product: str, ai_stage: str | None) -> str:
        role = self.role_for_run(origin_product, ai_stage)
        if role is None:
            return ""
        instructions = (
            SignalTeamConfig.objects.filter(team_id=team_id).values_list(STEERING_FIELDS[role], flat=True).first() or ""
        ).strip()
        if not instructions:
            return ""
        return (
            f"# Self-driving {role.value} instructions\n\n"
            f"You are part of PostHog Self-driving. Your role is {role.value}. "
            "Apply these role-specific instructions together with the project instructions.\n\n"
            f"{instructions}"
        )
