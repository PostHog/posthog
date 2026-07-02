"""Feature-flag checks for the Slack app backend.

One module for every Slack-app flag check so rollouts are easy to find and audit.

All gates share the same evaluation settings, so behaviour is uniform across the
surfaces:

- **Remote evaluation** (``only_evaluate_locally=False``) — no deployment needs a
  local-evaluation personal API key for these to work; evaluation goes through
  PostHog's flags endpoint with the project token.
- **Region targeting** — the deployment region rides along as the ``region``
  person property (via ``_region_properties``) so a flag rule like
  ``region equals DEV`` can target a single Cloud region.
- ``send_feature_flag_events=False`` — these are control checks, not analytics.
- **Fail-closed** — any error returns ``False`` so a flaky flag call never
  silently enables a feature for everyone.
"""

from __future__ import annotations

import structlog
import posthoganalytics

from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)


SLACK_APP_OAUTH_FLAG = "slack-app-oauth"
SLACK_APP_HOME_FLAG = "slack-app-home"
SLACK_APP_AGENT_DESIGN_FLAG = "slack-app-agent-design"
SLACK_APP_ASSISTANT_FLAG = "slack-app-assistant"
UNTAGGED_THREAD_FOLLOWUPS_FLAG = "posthog-slack-app-untagged-thread-followups"


def _region_properties() -> dict[str, str]:
    """The deployment region as a person property, shared by every gate so a
    ``region equals DEV`` rule targets one Cloud region. Falls back to ``dev``
    when the region is unset (local), matching the value dev rules target."""
    return {"region": get_instance_region() or "dev"}


def is_slack_app_oauth_enabled(integration: Integration, slack_team_id: str) -> bool:
    """Gate for the Slack user-identity OAuth link feature, covering both backend
    (offering the invite button, accepting the link callback, listing/starting
    from settings) and frontend (rendering the Slack card in Personal
    integrations) decisions. Keyed on the Slack workspace + PostHog org."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SLACK_APP_OAUTH_FLAG,
                f"slack_workspace:{slack_team_id}",
                groups={"organization": str(integration.team.organization_id)},
                person_properties=_region_properties(),
                only_evaluate_locally=False,
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


def is_slack_app_home_enabled(integration: Integration) -> bool:
    """Gate for the App Home tab surface and the AI-settings resolver that feeds
    Slack-triggered task runs. Keyed on the Slack workspace + PostHog org."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SLACK_APP_HOME_FLAG,
                f"slack_workspace:{integration.integration_id}",
                groups={"organization": str(integration.team.organization_id)},
                person_properties=_region_properties(),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception(
            "slack_app_home_feature_flag_check_failed",
            integration_id=integration.id,
        )
        return False


def is_slack_app_agent_design_enabled(integration: Integration) -> bool:
    """Gate for the agent-design plan-block streaming surface on Slack task runs.
    Keyed on the Slack workspace + PostHog org, matching ``is_slack_app_home_enabled``."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SLACK_APP_AGENT_DESIGN_FLAG,
                f"slack_workspace:{integration.integration_id}",
                groups={"organization": str(integration.team.organization_id)},
                person_properties=_region_properties(),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception(
            "slack_app_agent_design_feature_flag_check_failed",
            integration_id=integration.id,
        )
        return False


def is_slack_app_untagged_thread_followups_enabled(integration: Integration, slack_team_id: str) -> bool:
    """Gate for the untagged-thread followup path: when on, every message in a
    tagged thread is eligible for classification + forward instead of requiring
    a fresh ``@PostHog`` mention. Keyed on the Slack workspace + PostHog org."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                UNTAGGED_THREAD_FOLLOWUPS_FLAG,
                f"slack_workspace:{slack_team_id}",
                groups={"organization": str(integration.team.organization_id)},
                person_properties=_region_properties(),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception(
            "slack_app_thread_message_feature_flag_check_failed",
            slack_team_id=slack_team_id,
            integration_id=integration.id,
        )
        return False


def is_slack_app_assistant_enabled(team: Team) -> bool:
    """Kill-switch for the DM assistant. Evaluated on the workspace's team (a
    stable key) so the feature can be checked before resolving the DMing user —
    i.e. it stays dark when off."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SLACK_APP_ASSISTANT_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id)},
                person_properties=_region_properties(),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("assistant_feature_flag_eval_failed")
        return False


SLACK_APP_PERSONA_ONBOARDING_FLAG = "slack-app-persona-onboarding"


def is_persona_onboarding_enabled(team: Team) -> bool:
    """Gate for the persona onboarding flow: the DM conversation, the DM/thread
    intercepts, and the App Home "Start onboarding" card. Evaluated on the
    workspace's team so the whole surface stays dark when off."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SLACK_APP_PERSONA_ONBOARDING_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id)},
                person_properties=_region_properties(),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("persona_onboarding_feature_flag_eval_failed")
        return False
