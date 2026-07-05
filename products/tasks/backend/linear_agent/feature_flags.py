"""Feature-flag checks for the Linear agent integration.

Fail-closed, mirroring the Slack app's flag module: a flaky
``posthoganalytics.feature_enabled`` call must not silently enable webhook-driven
task creation for everyone.
"""

from __future__ import annotations

import structlog
import posthoganalytics

from posthog.models.integration import Integration
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)

POSTHOG_BOT_EVERYWHERE_FLAG = "posthog-bot-everywhere"


def linear_agent_enabled(integration: Integration) -> bool:
    """Gate for the whole Linear agent feature, evaluated against the installing
    workspace's PostHog organization so rollout is org-by-org, with the deployment
    region carried as a person property so flag rules can target a single Cloud region.
    """
    try:
        return bool(
            posthoganalytics.feature_enabled(
                POSTHOG_BOT_EVERYWHERE_FLAG,
                f"linear_org:{integration.integration_id}",
                groups={"organization": str(integration.team.organization_id)},
                person_properties={"region": get_instance_region() or "unknown"},
                # Evaluated on every inbound Linear webhook — local evaluation avoids a
                # synchronous HTTPS call competing with the processing latency budget.
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception(
            "linear_agent_feature_flag_check_failed",
            integration_id=integration.id,
            team_id=integration.team_id,
        )
        return False
