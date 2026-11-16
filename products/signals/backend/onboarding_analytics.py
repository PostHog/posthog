from __future__ import annotations

from typing import TYPE_CHECKING

import posthoganalytics

from posthog.event_usage import groups

from products.signals.backend.onboarding_state import setup_mode

if TYPE_CHECKING:
    from posthog.models.user import User

    from products.signals.backend.models import SignalTeamConfig


class InboxOnboardingAnalytics:
    @staticmethod
    def pricing_flag(config: SignalTeamConfig, user: User | None) -> bool | None:
        try:
            result = posthoganalytics.feature_enabled(
                "self-driving-ubp",
                str(user.distinct_id if user else config.team.uuid),
                groups=groups(team=config.team),
                send_feature_flag_events=False,
            )
            return result if isinstance(result, bool) else None
        except Exception:
            # A lookup failure must not put this project in the legacy-pricing cohort.
            return None

    @classmethod
    def properties(cls, config: SignalTeamConfig, user: User | None = None) -> dict[str, object]:
        draft = (config.onboarding or {}).get("draft") or {}
        return {
            **({"activation_mode": draft["activation_mode"]} if draft.get("activation_mode") else {}),
            "project_id": config.team_id,
            "flow_version": "ui-first-v1",
            "inbox_client": "cloud",
            "setup_mode": setup_mode(config.onboarding or {}),
            "self_driving_ubp": cls.pricing_flag(config, user),
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
