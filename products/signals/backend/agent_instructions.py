from enum import StrEnum

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
