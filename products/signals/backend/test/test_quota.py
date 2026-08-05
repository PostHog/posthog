from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from unittest.mock import patch

from products.signals.backend.quota import (
    SelfDrivingQuotaGate,
    is_team_signals_quota_limited,
    reserve_self_driving_pr_slot,
    self_driving_pr_reservation_limit,
    self_driving_quota_gate,
)

if TYPE_CHECKING:
    from posthog.models import Team
    from posthog.models.organization import Organization


def _team() -> "Team":
    # The gate only reads api_token / organization_id, so a stub keeps these tests DB-free.
    return cast("Team", SimpleNamespace(api_token="phc_token", organization_id="0195a000-0000-0000-0000-000000000000"))


def _org(usage: dict | None, *, org_id: str = "org-1") -> "Organization":
    return cast("Organization", SimpleNamespace(usage=usage, id=org_id))


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


@pytest.mark.parametrize(
    ("usage", "expected_limit_prs"),
    [
        (None, None),
        ({}, None),
        ({"signals_credits": {}}, None),
        ({"signals_credits": {"limit": None}}, None),
        # 1500 credits per PR ($15) — a 19,500-credit cap is exactly 13 PRs.
        ({"signals_credits": {"limit": 19500}}, 13),
    ],
)
def test_self_driving_pr_reservation_limit(usage, expected_limit_prs):
    assert self_driving_pr_reservation_limit(_org(usage)) == expected_limit_prs


def test_reserve_self_driving_pr_slot_requires_atomic_block():
    # The advisory lock this function takes only protects the reservation for as long as it's
    # held, which ends when the current transaction does. Calling it outside one would silently
    # reopen the exact concurrent-overshoot race it exists to close.
    team = cast("Team", SimpleNamespace(organization=_org({"signals_credits": {"limit": 1500}})))
    with patch("products.signals.backend.quota.connection") as mock_connection:
        mock_connection.in_atomic_block = False
        with pytest.raises(RuntimeError):
            reserve_self_driving_pr_slot(team)


def test_reserve_self_driving_pr_slot_locks_per_organization():
    # The lock key must be org-scoped, not per-team or per-report — a narrower key would let
    # concurrent creations for different reports (or different teams) in the same org bypass each
    # other's lock and reintroduce the cross-report race this function closes.
    org = _org({"signals_credits": {"limit": 1500}}, org_id="org-42")
    team = cast("Team", SimpleNamespace(organization=org, organization_id=org.id))
    with (
        patch("products.signals.backend.quota.connection") as mock_connection,
        patch("products.signals.backend.billing.count_self_driving_pr_reservations_in_period", return_value=0),
        patch("products.signals.backend.billing.current_billing_period_bounds"),
    ):
        mock_connection.in_atomic_block = True
        reserve_self_driving_pr_slot(team)
    cursor = mock_connection.cursor.return_value.__enter__.return_value
    sql, params = cursor.execute.call_args.args
    assert "pg_advisory_xact_lock" in sql
    assert params == ["self-driving-pr-quota:org-42"]


@pytest.mark.parametrize(
    ("reserved", "limit_prs", "expected_limited"),
    [
        (0, 1, False),
        (1, 1, True),
        (2, 1, True),
    ],
)
def test_reserve_self_driving_pr_slot_gates_on_live_reservation_count(reserved, limit_prs, expected_limited):
    org = _org({"signals_credits": {"limit": limit_prs * 1500}})
    team = cast("Team", SimpleNamespace(organization=org, organization_id=org.id))
    with (
        patch("products.signals.backend.quota.connection") as mock_connection,
        patch(
            "products.signals.backend.billing.count_self_driving_pr_reservations_in_period",
            return_value=reserved,
        ),
        patch("products.signals.backend.billing.current_billing_period_bounds"),
        patch("products.signals.backend.quota.posthoganalytics.feature_enabled", return_value=True),
    ):
        mock_connection.in_atomic_block = True
        gate = reserve_self_driving_pr_slot(team)
    assert gate == SelfDrivingQuotaGate(limited=expected_limited, enforced=expected_limited)


def test_reserve_self_driving_pr_slot_falls_back_when_uncapped():
    # No billing-synced limit yet (fresh org, self-hosted) must fail open the same way every
    # other quota gate does, rather than blocking on an unresolved denominator.
    team = cast("Team", SimpleNamespace(organization=_org(None)))
    with patch(
        "products.signals.backend.quota.self_driving_quota_gate",
        return_value=SelfDrivingQuotaGate(limited=False, enforced=False),
    ) as mock_gate:
        gate = reserve_self_driving_pr_slot(team)
    mock_gate.assert_called_once_with(team)
    assert gate == SelfDrivingQuotaGate(limited=False, enforced=False)
