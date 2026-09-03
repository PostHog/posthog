import pytest
from unittest.mock import patch

from products.slack_app.backend import feature_flags
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID

# (gate, scopes the feature calls)
SCOPED_GATES = [
    (feature_flags.is_slack_app_oauth_enabled, feature_flags.OAUTH_REQUIRED_SCOPES),
    (feature_flags.is_slack_app_assistant_enabled, feature_flags.ASSISTANT_REQUIRED_SCOPES),
]

IDS = [gate.__name__ for gate, *_ in SCOPED_GATES]


def _grant(integration, scopes):
    integration.config = {"scope": ",".join(sorted(scopes))}
    integration.save()


@pytest.mark.parametrize(("gate", "required"), SCOPED_GATES, ids=IDS)
def test_gate_opens_when_the_scopes_are_granted(workspace_integration, gate, required):
    _grant(workspace_integration, required)

    assert gate(workspace_integration) is True


@pytest.mark.parametrize(("gate", "required"), SCOPED_GATES, ids=IDS)
def test_gate_stays_closed_when_a_required_scope_is_missing(workspace_integration, gate, required):
    _grant(workspace_integration, required - {min(required)})

    assert gate(workspace_integration) is False


@pytest.mark.parametrize(
    ("distinct_id", "expected_identity"),
    [
        ("user-1", "user-1"),
        (None, f"slack_workspace:{SLACK_TEAM_ID}"),
    ],
    ids=["known user", "no user"],
)
def test_agent_design_gate_resolves_against_the_acting_user(
    settings, workspace_integration, org_team_user, distinct_id, expected_identity
):
    # The identity decides which rules can match at all. Resolving a known user against the
    # workspace instead would silently stop every person rule, `email ends_with
    # @posthog.com` included, from matching anyone.
    settings.CLOUD_DEPLOYMENT = "DEV"
    org, _, _ = org_team_user

    with patch("posthoganalytics.feature_enabled", return_value=True) as feature_enabled:
        feature_flags.is_slack_app_agent_design_enabled(workspace_integration, distinct_id)

    assert feature_enabled.call_args.args[1] == expected_identity
    assert feature_enabled.call_args.kwargs["person_properties"] == {"region": "DEV"}
    assert feature_enabled.call_args.kwargs["groups"] == {"organization": str(org.id)}


def test_space_routing_gate_requires_a_resolved_user(settings, workspace_integration, org_team_user):
    settings.CLOUD_DEPLOYMENT = "DEV"
    org, _, user = org_team_user

    with patch("posthoganalytics.feature_enabled", return_value=True) as feature_enabled:
        assert feature_flags.is_slack_space_routing_enabled(workspace_integration, distinct_id=None) is False
        assert (
            feature_flags.is_slack_space_routing_enabled(workspace_integration, distinct_id=str(user.distinct_id))
            is True
        )

    assert feature_enabled.call_count == 1
    assert feature_enabled.call_args.args[0] == feature_flags.SLACK_SPACE_ROUTING_FLAG
    assert feature_enabled.call_args.args[1] == str(user.distinct_id)
    assert feature_enabled.call_args.kwargs["groups"] == {"organization": str(org.id)}
