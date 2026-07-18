from posthog.models.team.team import Team

from products.error_tracking.backend.logic import get_client_safe_suppression_rules
from products.error_tracking.backend.models import autocapture_exceptions_enabled


def build_error_tracking_config(team: Team) -> dict:
    return {
        "autocaptureExceptions": autocapture_exceptions_enabled(team),
        "suppressionRules": get_client_safe_suppression_rules(team.id),
    }
