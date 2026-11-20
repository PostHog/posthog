import pytest
from unittest.mock import MagicMock, patch

from products.slack_app.backend.logic.onboarding.step import OnboardingContext
from products.slack_app.backend.temporal.activities.slack_app_work_focus import index_slack_app_daily_summary_activity
from products.slack_app.backend.temporal.types import SlackAppDailySummaryIndexInputs

ONBOARDING = "products.slack_app.backend.logic.onboarding"


@pytest.mark.parametrize(
    "approved, out_of_credits, wants, access, builds",
    [
        (True, False, True, True, True),
        (False, False, True, True, False),
        (True, True, True, True, False),
        (True, False, False, True, False),
        (True, False, True, False, False),
    ],
    ids=["builds", "no_ai_consent", "out_of_ai_credits", "nobody_gets_the_summary", "nobody_can_open_the_project"],
)
def test_the_index_is_built_only_for_a_run_that_could_send(
    approved: bool, out_of_credits: bool, wants: bool, access: bool, builds: bool
) -> None:
    # Building reads every channel and spends AI credits under the project, so it waits for someone it can serve.
    with (
        patch(
            "products.slack_app.backend.services.workspace_integrations.get_workspace_integration",
            return_value=MagicMock(team_id=1),
        ),
        patch(f"{ONBOARDING}.checks.has_ai_approval", return_value=approved),
        patch(f"{ONBOARDING}.checks.out_of_ai_credits", return_value=out_of_credits),
        patch(f"{ONBOARDING}.daily_summary.wants_summary", return_value=wants),
        patch.object(OnboardingContext, "has_project_access", new=property(lambda self: access)),
        patch(f"{ONBOARDING}.daily_summary.build_workspace_index", return_value=3) as build,
    ):
        built = index_slack_app_daily_summary_activity(
            SlackAppDailySummaryIndexInputs(integration_id=1, slack_team_id="T1", slack_user_ids=["U1"])
        )

    assert build.called is builds
    assert built == (3 if builds else 0)
