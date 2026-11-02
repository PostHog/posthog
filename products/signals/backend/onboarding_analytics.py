from __future__ import annotations

from typing import TYPE_CHECKING

from products.signals.backend.onboarding_pricing import onboarding_usage_based_pricing
from products.signals.backend.onboarding_state import setup_mode

if TYPE_CHECKING:
    from posthog.models.user import User

    from products.signals.backend.models import SignalTeamConfig


class InboxOnboardingAnalytics:
    @staticmethod
    def pricing_flag(config: SignalTeamConfig, user: User | None) -> bool | None:
        return onboarding_usage_based_pricing(config.team, user)

    @classmethod
    def properties(cls, config: SignalTeamConfig, user: User | None = None) -> dict[str, object]:
        state = config.onboarding or {}
        draft = state.get("draft") or {}
        return {
            **({"activation_mode": draft["activation_mode"]} if draft.get("activation_mode") else {}),
            "project_id": config.team_id,
            "flow_version": "ui-first-v1",
            "inbox_client": "cloud",
            "setup_mode": setup_mode(config.onboarding or {}),
            "self_driving_ubp": cls.pricing_flag(config, user),
            **({"entrypoint": state["entrypoint"]} if state.get("entrypoint") else {}),
        }

    @classmethod
    def completion_properties(cls, config: SignalTeamConfig, user: User | None = None) -> dict[str, object]:
        draft = (config.onboarding or {}).get("draft") or {}
        return {
            **cls.properties(config, user),
            "automatic_implementation": config.autostart_enabled,
            "implementation_priority": config.default_autostart_priority,
            "enabled_source_products": sorted(
                {source["source_product"] for source in draft.get("sources", []) if source["enabled"]}
                | ({"replay_vision"} if draft.get("scanner_ids") else set())
                | ({"signals_scout"} if draft.get("suggestions") else set())
            )
            if draft
            else None,
            "scout_count": len(draft.get("suggestions", [])) if draft else None,
        }
