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
- **Organization targeting** — the PostHog organization rides along as a group, so a
  rule like ``$group_key equals <org uuid>`` targets one customer.
- **Region targeting** — the deployment region rides along as the ``region``
  person property (via ``_region_properties``) so a flag rule like
  ``region equals DEV`` can target a single Cloud region.
- **Person targeting** — a gate told which PostHog user it is deciding for is keyed
  on that user, so the person's own record answers the rule. That makes the usual
  internal rollout rules work unchanged: ``email ends_with @posthog.com``, a cohort,
  any person property. Nothing here forwards those properties; the person already
  carries them.
- ``send_feature_flag_events=False`` — these are control checks, not analytics.
- **Fail-closed** — any error returns ``False`` so a flaky flag call never
  silently enables a feature for everyone.

The identity a gate is keyed on is also the identity it buckets on. So give a gate
either a user on every call or on none, and read a rollout percentage on a
user-keyed gate as a share of people rather than of workspaces.
"""

from __future__ import annotations

import structlog
import posthoganalytics

from posthog.integrations import IntegrationRecord
from posthog.models.team import Team
from posthog.utils import get_instance_region

from products.slack_app.backend.services.slack_scopes import REQUIRED_SLACK_SCOPES, has_scopes

logger = structlog.get_logger(__name__)


SLACK_APP_AGENT_DESIGN_FLAG = "slack-app-agent-design"
SLACK_APP_FORKING_FLAG = "slack-app-forking"
SLACK_APP_BYOS_FLAG = "slack-app-byos"


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


def _organization_id(integration: IntegrationRecord) -> str:
    return str(Team.objects.values_list("organization_id", flat=True).get(id=integration.team_id))


def _workspace_flag_enabled(
    flag: str,
    integration: IntegrationRecord,
    *,
    failure_log_key: str,
    distinct_id: str | None = None,
) -> bool:
    """Evaluate one gate under the settings this module documents.

    The uniformity the docstring above promises is only real if there is one place that
    spells it out. A gate that needs more than a flag — scopes, say — checks that itself
    and calls this for the flag half.

    ``distinct_id`` identifies the PostHog user the check is being made for, and becomes
    the identity the flag resolves against. It is a distinct ID rather than a user id so
    a caller can pass what it already holds.
    Without one the gate falls back to the Slack workspace, which no person rule can
    match.
    """
    try:
        return bool(
            posthoganalytics.feature_enabled(
                flag,
                distinct_id or f"slack_workspace:{integration.integration_id}",
                groups={"organization": _organization_id(integration)},
                person_properties=_region_properties(),
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.exception(failure_log_key, integration_id=integration.id)
        return False


def is_slack_app_oauth_enabled(integration: IntegrationRecord) -> bool:
    """Gate for the Slack user-identity OAuth link feature, covering both backend
    (offering the invite button, accepting the link callback, listing/starting
    from settings) and frontend (rendering the Slack card in Personal
    integrations) decisions. Linking resolves the Slack profile and its email,
    so the install must hold the identity scopes."""
    return has_scopes(integration, OAUTH_REQUIRED_SCOPES)


def is_slack_app_agent_design_enabled(integration: IntegrationRecord, distinct_id: str | None = None) -> bool:
    """Gate for the agent-design plan-block streaming surface on Slack task runs.
    Posts through the ``chat:write`` the mention flow already requires, so this is the
    flag alone.

    ``distinct_id`` identifies the PostHog user whose run this is. The decision is about
    that person's run, so the flag resolves against them and an internal rollout can name
    them the way every other one does. Without it the gate falls back to the workspace.
    """
    return _workspace_flag_enabled(
        SLACK_APP_AGENT_DESIGN_FLAG,
        integration,
        failure_log_key="slack_app_agent_design_feature_flag_check_failed",
        distinct_id=distinct_id,
    )


def is_slack_app_byos_enabled(
    integration: IntegrationRecord, distinct_id: str | None, *, adapter: str = "codex"
) -> bool:
    """Gate for Slack runs that bill to the user's own plan.

    Depends on the tasks rollout flag for that plan, which is checked first. A Slack run
    marked for a plan whose rollout is off fails when it starts, so Slack must never mark one.
    ``distinct_id`` is the PostHog user whose plan the run would use.
    """
    from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415 — keeps tasks off this import path

    if not tasks_facade.own_subscription_cloud_enabled(
        adapter, distinct_id=distinct_id, organization_id=_organization_id(integration)
    ):
        return False
    return _workspace_flag_enabled(
        SLACK_APP_BYOS_FLAG,
        integration,
        failure_log_key="slack_app_byos_feature_flag_check_failed",
        distinct_id=distinct_id,
    )


def is_slack_app_assistant_enabled(integration: IntegrationRecord) -> bool:
    """Gate for the DM assistant: the install must hold the scopes the DM surface
    calls — ``im:history`` in particular, without which the assistant would answer
    once and then go deaf to follow-ups."""
    return has_scopes(integration, ASSISTANT_REQUIRED_SCOPES)


def is_slack_app_forking_enabled(integration: IntegrationRecord) -> bool:
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
    return _workspace_flag_enabled(
        SLACK_APP_FORKING_FLAG,
        integration,
        failure_log_key="slack_app_forking_feature_flag_check_failed",
    )
