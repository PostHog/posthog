from posthog.dataclasses import frozen

from products.error_tracking.backend.logic.team_flags import team_flag_enabled, team_flag_payload

AUTO_ASSIGNMENT_FLAG = "error-tracking-auto-assignment"


def auto_assignment_enabled(team_id: int) -> bool:
    # The billing entitlement check goes here, beside the flag, when auto-assignment becomes a paid feature.
    return team_flag_enabled(AUTO_ASSIGNMENT_FLAG, team_id)


@frozen
class HistoryConfig:
    top_k: int = 3
    # A past issue votes only when its cosine distance to the new issue is at most this.
    max_distance: float = 0.15
    min_confidence: float = 0.66


@frozen
class AutoAssignmentConfig:
    history: HistoryConfig = HistoryConfig()


def _bounded(value: object, default: float, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        return default
    return float(value)


def parse_auto_assignment_config(payload: object) -> AutoAssignmentConfig:
    payload = payload if isinstance(payload, dict) else {}
    raw_history = payload.get("history")
    history: dict[str, object] = raw_history if isinstance(raw_history, dict) else {}
    defaults = HistoryConfig()
    return AutoAssignmentConfig(
        history=HistoryConfig(
            top_k=int(_bounded(history.get("top_k"), defaults.top_k, 1, 20)),
            max_distance=_bounded(history.get("max_distance"), defaults.max_distance, 0, 2),
            min_confidence=_bounded(history.get("min_confidence"), defaults.min_confidence, 0, 1),
        )
    )


def load_auto_assignment_config(team_id: int) -> AutoAssignmentConfig:
    return parse_auto_assignment_config(team_flag_payload(AUTO_ASSIGNMENT_FLAG, team_id))
