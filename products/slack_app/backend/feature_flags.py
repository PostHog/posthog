"""Feature-flag checks for the Slack app backend.

One module for every Slack-app flag check so rollouts are easy to find and audit.

A flag says a workspace opted into a rollout; it doesn't say the install can make
the Slack API calls the feature needs. So a gate that depends on scopes checks
both, and the scopes it requires are declared here next to its flag. Scopes are
read first — that's a dict lookup, while the flag check is a network call.

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

from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES, has_scopes
from posthog.models.integration import Integration
from posthog.models.team.team import Team
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)


SLACK_APP_OAUTH_FLAG = "slack-app-oauth"
SLACK_APP_HOME_FLAG = "slack-app-home"
SLACK_APP_AGENT_DESIGN_FLAG = "slack-app-agent-design"
SLACK_APP_ASSISTANT_FLAG = "slack-app-assistant"
SLACK_APP_LIVING_ARTIFACTS_FLAG = "slack-app-living-artifacts"
SLACK_APP_CANVAS_FILE_ARTIFACTS_FLAG = "slack-app-canvas-file-artifacts"
SLACK_APP_MODEL_CLASSIFIER_FLAG = "slack-app-model-classifier"
SLACK_APP_FORKING_FLAG = "slack-app-forking"
UNTAGGED_THREAD_FOLLOWUPS_FLAG = "posthog-slack-app-untagged-thread-followups"


# Linking a Slack identity to a PostHog user resolves the Slack profile and its email.
OAUTH_REQUIRED_SCOPES: frozenset[str] = frozenset({"users:read", "users:read.email"})

# The DM/agent surface needs the base coding-agent scopes plus the assistant container scopes.
# Kept separate from REQUIRED_SLACK_SCOPES so the mention flow isn't gated on im:history.
ASSISTANT_REQUIRED_SCOPES: frozenset[str] = REQUIRED_SLACK_SCOPES | frozenset({"assistant:write", "im:history"})


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
    if not has_scopes(integration, OAUTH_REQUIRED_SCOPES):
        return False
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
    Slack-triggered task runs. Publishing a Home view needs no scope of its own, so
    this is the flag alone. Keyed on the Slack workspace + PostHog org."""
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


def is_slack_app_model_classifier_enabled(integration: Integration) -> bool:
    """Gate for reading a one-off model choice out of the mention text ("use fable
    for this one") and running that task on it. Reads text the bot already receives,
    so this is the flag alone. Keyed on the Slack workspace + PostHog org, matching
    the other Slack-app gates.

    Also gates the provenance footer under a finished reply: naming a model in a mention
    and being told which model ran are two halves of the same feature, and splitting them
    across two flags would let a workspace pick a model and then not be shown it.

    Independent of ``slack-app-home``: an override applies whether or not the
    workspace has opted into the settings tab."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SLACK_APP_MODEL_CLASSIFIER_FLAG,
                f"slack_workspace:{integration.integration_id}",
                groups={"organization": str(integration.team.organization_id)},
                person_properties=_region_properties(),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception(
            "slack_app_model_classifier_feature_flag_check_failed",
            integration_id=integration.id,
        )
        return False


def is_slack_app_agent_design_enabled(integration: Integration) -> bool:
    """Gate for the agent-design plan-block streaming surface on Slack task runs.
    Posts through the ``chat:write`` the mention flow already requires, so this is the
    flag alone. Keyed on the Slack workspace + PostHog org, matching
    ``is_slack_app_home_enabled``."""
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


def is_slack_app_canvas_file_artifacts_enabled(integration: Integration) -> bool:
    """Gate for living-artifact delivery that depends on ``canvases:write`` (the canvas
    adapter) and ``files:write`` (the file adapter). Both are approved but recent, so an
    install authorized earlier won't have them until it reconnects.

    The flag alone: the two adapters need one scope each, so they check theirs at point
    of use and can name the one to grant, and chart images post by public url on
    ``chat:write`` alone, so this flag can roll charts out ahead of those grants. Keyed
    on the Slack workspace + PostHog org."""
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SLACK_APP_CANVAS_FILE_ARTIFACTS_FLAG,
                f"slack_workspace:{integration.integration_id}",
                groups={"organization": str(integration.team.organization_id)},
                person_properties=_region_properties(),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception(
            "slack_app_canvas_file_artifacts_feature_flag_check_failed",
            integration_id=integration.id,
        )
        return False


def is_slack_app_living_artifacts_enabled(integration: Integration) -> bool:
    """Gate for creating, editing, and delivering living artifacts from Slack runs.

    Keyed on the Slack workspace + PostHog org. This is the umbrella artifact gate;
    canvas and file adapters additionally require their scope rollout flag.
    """
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SLACK_APP_LIVING_ARTIFACTS_FLAG,
                f"slack_workspace:{integration.integration_id}",
                groups={"organization": str(integration.team.organization_id)},
                person_properties=_region_properties(),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception(
            "slack_app_living_artifacts_feature_flag_check_failed",
            integration_id=integration.id,
        )
        return False


def is_slack_app_untagged_thread_followups_enabled(integration: Integration, slack_team_id: str) -> bool:
    """Gate for the untagged-thread followup path: when on, every message in a
    tagged thread is eligible for classification + forward instead of requiring
    a fresh ``@PostHog`` mention. Keyed on the Slack workspace + PostHog org.

    The flag alone: a followup only reaches this after a mention in the same thread, and
    that path already enforces ``REQUIRED_SLACK_SCOPES`` — which covers reading channel
    history — while telling the user which scopes to grant."""
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


def is_slack_app_assistant_flag_enabled(team: Team) -> bool:
    """Kill-switch for the DM assistant. Evaluated on the workspace's team (a
    stable key) so the feature can be checked before resolving the DMing user —
    i.e. it stays dark when off.

    Kept apart from ``is_slack_app_assistant_enabled`` because the two answers call
    for opposite responses: a workspace outside the rollout gets silence, one that
    opted in but lacks scopes gets told which scopes to grant."""
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


def is_slack_app_assistant_enabled(integration: Integration) -> bool:
    """Gate for the DM assistant: rolled out to this workspace, and installed with
    the scopes the DM surface calls."""
    if not has_scopes(integration, ASSISTANT_REQUIRED_SCOPES):
        return False
    return is_slack_app_assistant_flag_enabled(integration.team)


def is_slack_app_forking_enabled(integration: Integration) -> bool:
    """Gate for the "Fork to DM" menu under a reply.

    A fork lands in a DM and is answered there, so it inherits the assistant
    surface's scope requirements wholesale — ``im:history`` in particular, without
    which the forked thread would answer once and then go deaf to follow-ups.
    Gating on the assistant scopes rather than its flag keeps the two rollouts
    independent: a workspace can get forking without opting into cold-start DMs.

    Keyed on the Slack workspace like its neighbours, not the team: the menu hangs off
    a reply, and a workspace connected to two projects would otherwise show it on some
    replies and not others.
    """
    if not has_scopes(integration, ASSISTANT_REQUIRED_SCOPES):
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SLACK_APP_FORKING_FLAG,
                f"slack_workspace:{integration.integration_id}",
                groups={"organization": str(integration.team.organization_id)},
                person_properties=_region_properties(),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception("slack_app_forking_feature_flag_check_failed", integration_id=integration.id)
        return False
