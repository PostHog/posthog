import pytest
from unittest.mock import patch

from products.slack_app.backend import feature_flags
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID

PERSON_GATES = [
    feature_flags.is_slack_app_onboarding_enabled,
    feature_flags.is_slack_app_link_search_scopes_enabled,
    feature_flags.is_slack_app_connect_tool_from_chat_enabled,
    feature_flags.is_slack_app_daily_work_focus_enabled,
    feature_flags.is_slack_app_slack_mcp_enabled,
]

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


# (gate, what it takes for the acting user)
USER_KEYED_GATES = [
    (feature_flags.is_slack_app_agent_design_enabled, "distinct_id"),
    *((gate, "user_id") for gate in PERSON_GATES),
]


@pytest.mark.parametrize(("gate", "takes"), USER_KEYED_GATES, ids=[gate.__name__ for gate, _ in USER_KEYED_GATES])
@pytest.mark.parametrize("known", [True, False], ids=["known user", "no user"])
def test_user_keyed_gate_resolves_against_the_acting_user(
    settings, workspace_integration, org_team_user, gate, takes, known
):
    # The identity decides which rules can match at all. Resolving a known user against the
    # workspace instead would silently stop every person rule, `email ends_with
    # @posthog.com` included, from matching anyone.
    settings.CLOUD_DEPLOYMENT = "DEV"
    org, _, user = org_team_user
    acting = (user.distinct_id if takes == "distinct_id" else user.id) if known else None

    with patch("posthoganalytics.feature_enabled", return_value=True) as feature_enabled:
        assert gate(workspace_integration, acting) is True

    expected_identity = user.distinct_id if known else f"slack_workspace:{SLACK_TEAM_ID}"
    assert feature_enabled.call_args.args[1] == expected_identity
    assert feature_enabled.call_args.kwargs["person_properties"] == {"region": "DEV"}
    assert feature_enabled.call_args.kwargs["groups"] == {"organization": str(org.id)}


@pytest.mark.parametrize(
    ("plan_rollout_on", "slack_flag_on", "expected"),
    [(True, True, True), (False, True, False), (True, False, False)],
    ids=["both on", "plan rollout off", "slack flag off"],
)
def test_byos_gate_depends_on_the_plan_rollout_flag(workspace_integration, plan_rollout_on, slack_flag_on, expected):
    # A Slack run marked for a plan whose rollout is off fails when it starts, so the Slack
    # flag alone must never open the gate.
    def feature_enabled(key, *args, **kwargs):
        if key == feature_flags.SLACK_APP_BYOS_FLAG:
            return slack_flag_on
        return plan_rollout_on

    with patch("posthoganalytics.feature_enabled", side_effect=feature_enabled):
        assert feature_flags.is_slack_app_byos_enabled(workspace_integration, "user-1") is expected
