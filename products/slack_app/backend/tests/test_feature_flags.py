import pytest
from unittest.mock import patch

from products.slack_app.backend import feature_flags

SLACK_TEAM_ID = "T12345"

# (gate, scopes the feature calls, trailing args the gate takes)
SCOPED_GATES = [
    (feature_flags.is_slack_app_oauth_enabled, feature_flags.OAUTH_REQUIRED_SCOPES, (SLACK_TEAM_ID,)),
    (feature_flags.is_slack_app_assistant_enabled, feature_flags.ASSISTANT_REQUIRED_SCOPES, ()),
]

IDS = [gate.__name__ for gate, *_ in SCOPED_GATES]


def _grant(integration, scopes):
    integration.config = {"scope": ",".join(sorted(scopes))}
    integration.save()


@pytest.mark.parametrize(("gate", "required", "extra_args"), SCOPED_GATES, ids=IDS)
def test_gate_opens_when_the_flag_is_on_and_the_scopes_are_granted(workspace_integration, gate, required, extra_args):
    _grant(workspace_integration, required)

    with patch("posthoganalytics.feature_enabled", return_value=True):
        assert gate(workspace_integration, *extra_args) is True


@pytest.mark.parametrize(("gate", "required", "extra_args"), SCOPED_GATES, ids=IDS)
def test_gate_stays_closed_when_a_required_scope_is_missing(workspace_integration, gate, required, extra_args):
    _grant(workspace_integration, required - {min(required)})

    with patch("posthoganalytics.feature_enabled", return_value=True):
        assert gate(workspace_integration, *extra_args) is False


@pytest.mark.parametrize(("gate", "required", "extra_args"), SCOPED_GATES, ids=IDS)
def test_gate_stays_closed_when_the_flag_is_off_despite_full_scopes(workspace_integration, gate, required, extra_args):
    _grant(workspace_integration, required)

    with patch("posthoganalytics.feature_enabled", return_value=False):
        assert gate(workspace_integration, *extra_args) is False
