import pytest
from unittest.mock import patch

from posthog.models import Organization, Team

from products.signals.backend.free_trial import SELF_DRIVING_FREE_TRIAL_FLAG, self_driving_free_trial_enabled


@pytest.mark.django_db
@pytest.mark.parametrize(
    "flag_result,expected",
    [
        (True, True),
        (False, False),
        (None, False),
        (RuntimeError("flag service down"), False),
    ],
)
def test_self_driving_free_trial_enabled_reads_the_org_flag_and_fails_open(flag_result, expected):
    organization = Organization.objects.create(name="trial-org")
    team = Team.objects.create(organization=organization, name="trial-team")
    kwargs = {"side_effect": flag_result} if isinstance(flag_result, Exception) else {"return_value": flag_result}

    with patch("products.signals.backend.free_trial.posthoganalytics.feature_enabled", **kwargs) as feature_enabled:
        assert self_driving_free_trial_enabled(team) is expected

    org_id = str(organization.id)
    feature_enabled.assert_called_once_with(
        SELF_DRIVING_FREE_TRIAL_FLAG,
        org_id,
        groups={"organization": org_id},
        group_properties={"organization": {"id": org_id}},
    )
