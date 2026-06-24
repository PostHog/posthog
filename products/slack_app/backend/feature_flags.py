"""Feature-flag checks for the Slack app backend.

One module per flag-check function, so flag rollouts are easy to find and
audit. Every check here is fail-closed: a flaky ``posthoganalytics.feature_enabled``
call must not silently enable a feature for everyone.
"""

import structlog
import posthoganalytics

from posthog.models.integration import Integration
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)


SLACK_APP_OAUTH_FLAG = "slack-app-oauth"


def slack_oauth_link_enabled(integration: Integration, slack_team_id: str) -> bool:
    """Gate for the Slack user-identity OAuth link feature, covering both
    backend (offering the invite button, accepting the link callback,
    listing/starting from settings) and frontend (rendering the Slack card
    in Personal integrations) decisions.

    Evaluated against the workspace's PostHog organization so we can roll
    out org-by-org, with the deployment region carried as a person property
    so a flag rule like ``region equals US`` targets a single Cloud region.

    Fail-closed on any error: a flaky feature-flag check must not silently
    enable the feature for everyone.
    """
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SLACK_APP_OAUTH_FLAG,
                f"slack_workspace:{slack_team_id}",
                groups={"organization": str(integration.team.organization_id)},
                person_properties={"region": get_instance_region() or "unknown"},
                # Hot path: every inbound Slack event (every @mention, link_shared,
                # message-in-watched-channel) hits this. Local evaluation avoids a
                # synchronous HTTPS call to PostHog's `decide` endpoint that would
                # compete with Slack's 3s webhook ack deadline. The org-level rules
                # and region person-property all evaluate fine locally.
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception(
            "slack_app_user_link_feature_flag_check_failed",
            slack_team_id=slack_team_id,
            integration_id=integration.id,
        )
        return False
