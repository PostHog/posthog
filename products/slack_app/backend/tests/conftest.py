"""Shared fixtures for slack_app backend tests.

Combines two unrelated concerns that both want module-level conftest scope:

1) ``_bypass_slack_auth_filter`` (autouse): the resolver's ``load_integrations``
   now eagerly runs Slack ``auth.test`` on cache miss (see
   ``services/slack_auth.check_integrations_auth_and_filter``). Without
   intervention, every test that constructs an ``Integration`` row but doesn't
   patch the Slack SDK ends up making the resolver try a real Slack call with
   a fake token, which fails, drops the candidate, and breaks downstream
   routing assertions in ways that have nothing to do with what the test is
   actually checking. This fixture turns the filter into a pass-through for
   the whole package; tests that actually want to exercise the filter
   (``test_slack_auth.py``, ``TestLoadIntegrationsAuthStateFilter``) opt back
   in by patching at the module the resolver imports from.

2) User-link fixtures (``org_team_user``, ``workspace_integration``,
   ``link_user``): scoped to the user-OAuth-link feature. Tests under
   ``tests/services/`` and ``tests/views/`` both consume them via pytest's
   conftest autodiscovery, so the same fixture identity flows across the two
   files that exercise the inbound resolver and the OAuth callback views.
"""

from typing import Any

import pytest
from unittest.mock import patch

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import user_slack_integration_from_identity

SLACK_TEAM_ID = "T12345"
SLACK_USER_ID = "U999"
SLACK_USER_ACCESS_TOKEN = "xoxp-user-test"


@pytest.fixture(autouse=True)
def _bypass_slack_auth_filter():
    """Pass-through the resolver's auth-state pre-filter for unit tests.

    The filter's job is to drop integrations whose bot token has gone bad.
    For tests that pre-construct an ``Integration`` with a stub
    ``access_token`` and never exercise the OAuth round-trip, the eager
    ``auth.test`` call would always fail and the resolver would always return
    an empty candidate list. That's the wrong default — most tests want to
    exercise *routing* against the integrations they created, not the
    auth-state mechanism itself.

    Tests that DO want to exercise the filter (``test_slack_auth.py``,
    ``TestLoadIntegrationsAuthStateFilter`` in ``test_integration_resolver.py``)
    stop this fixture from taking effect by patching at the module the
    resolver imports from — see those files for the pattern.
    """
    # ``load_integrations`` inline-imports ``check_integrations_auth_and_filter``
    # from ``slack_auth``, so we patch at the source module rather than at the
    # resolver's import site (the import re-runs on every call and would miss
    # an import-site patch).
    with patch(
        "products.slack_app.backend.services.slack_auth.check_integrations_auth_and_filter",
        side_effect=lambda candidates, **_: candidates,
    ):
        yield


@pytest.fixture
def org_team_user(db):
    org = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=org, name="Test Team")
    user = User.objects.create(email="dev@example.com", distinct_id="user-1")
    OrganizationMembership.objects.create(user=user, organization=org)
    return org, team, user


@pytest.fixture
def workspace_integration(org_team_user):
    _, team, _ = org_team_user
    return Integration.objects.create(
        team=team,
        kind="slack",
        integration_id=SLACK_TEAM_ID,
        sensitive_config={"access_token": "xoxb-test"},
    )


@pytest.fixture
def link_user():
    """Returns a callable that creates a Slack ``UserIntegration`` link with
    sensible defaults so individual tests can stay focused on the slack_user_id
    / team_id / org-scoping behavior they actually want to exercise.
    """

    def _link(user, **overrides):
        # `dict[str, Any]` so the optional `slack_team_name` / `slack_email_at_link`
        # entries (which carry `None`) don't narrow the union value type and break
        # the keyword-arg type check on `user_slack_integration_from_identity`.
        defaults: dict[str, Any] = {
            "slack_user_id": SLACK_USER_ID,
            "slack_team_id": SLACK_TEAM_ID,
            "slack_team_name": None,
            "slack_email_at_link": None,
            "user_access_token": SLACK_USER_ACCESS_TOKEN,
        }
        defaults.update(overrides)
        return user_slack_integration_from_identity(user, **defaults)

    return _link
