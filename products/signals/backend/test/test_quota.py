from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from unittest.mock import patch

from products.signals.backend.quota import SelfDrivingQuotaGate, is_team_signals_quota_limited, self_driving_quota_gate

if TYPE_CHECKING:
    from posthog.models import Team


def _team() -> "Team":
    # The gate only reads api_token / organization_id, so a stub keeps these tests DB-free.
    return cast("Team", SimpleNamespace(api_token="phc_token", organization_id="0195a000-0000-0000-0000-000000000000"))


@pytest.mark.parametrize(
    ("limited", "expected"),
    [
        (True, True),
        (False, False),
    ],
)
def test_reflects_quota_limiter(limited, expected):
    with patch("products.signals.backend.quota.is_team_limited", return_value=limited) as mock_limited:
        assert is_team_signals_quota_limited("phc_token") is expected
    # Always queries the signals_credits resource for the given token.
    args = mock_limited.call_args.args
    assert args[0] == "phc_token"
    assert args[1].value == "signals_credits"


def test_fails_open_on_error():
    with patch("products.signals.backend.quota.is_team_limited", side_effect=RuntimeError("redis down")):
        assert is_team_signals_quota_limited("phc_token") is False


def test_fail_open_metric_noops_outside_activity():
    # The fail-open counter only records inside a Temporal activity; outside one it must not raise.
    with patch("products.signals.backend.quota.is_team_limited", side_effect=RuntimeError("redis down")):
        with patch("products.signals.backend.quota.get_metric_meter") as mock_meter:
            assert is_team_signals_quota_limited("phc_token") is False
            mock_meter.assert_not_called()


@pytest.mark.parametrize(
    ("limited", "flag_on", "expected_enforced"),
    [
        (False, True, False),
        (True, True, True),
        # Dark launch: a limited team with the enforcement flag off must never be blocked.
        (True, False, False),
    ],
)
def test_self_driving_quota_gate_enforces_only_when_limited_and_flag_on(limited, flag_on, expected_enforced):
    with (
        patch("products.signals.backend.quota.is_team_limited", return_value=limited),
        patch("products.signals.backend.quota.posthoganalytics.feature_enabled", return_value=flag_on) as flag_mock,
    ):
        assert self_driving_quota_gate(_team()) == SelfDrivingQuotaGate(limited=limited, enforced=expected_enforced)
    if not limited:
        # The flag is network I/O and must stay off the fleet-wide not-limited hot path.
        flag_mock.assert_not_called()


def test_self_driving_quota_gate_fails_open_on_flag_error():
    # A flag-service outage must not start blocking pipelines: limited stays visible, enforcement off.
    with (
        patch("products.signals.backend.quota.is_team_limited", return_value=True),
        patch(
            "products.signals.backend.quota.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("flags down"),
        ),
    ):
        assert self_driving_quota_gate(_team()) == SelfDrivingQuotaGate(limited=True, enforced=False)
