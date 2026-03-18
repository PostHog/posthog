from posthog.models.team.team import Team

from products.error_tracking.backend.api.suppression_rules import get_client_safe_suppression_rules


def build_error_tracking_config(team: Team) -> dict:
    return {
        "autocaptureExceptions": bool(team.autocapture_exceptions_opt_in),
        "suppressionRules": get_client_safe_suppression_rules(team),
    }
