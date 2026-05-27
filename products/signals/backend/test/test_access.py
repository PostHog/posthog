"""Tests for `access.py` — the per-user `signals-scout-inbox` gate.

Locks the contract with `posthoganalytics.feature_enabled`: remote eval (so a person-level
allowlist actually decides instead of coming back `None`), organization + project group
context, a `distinct_id` guard that short-circuits before evaluating, and fail-closed on any
eval exception.
"""

from __future__ import annotations

from posthog.test.base import BaseTest
from unittest.mock import patch

from products.signals.backend.access import SIGNALS_SCOUT_INBOX_FLAG, user_can_see_signals_scout_reports


class TestUserCanSeeSignalsScoutReports(BaseTest):
    def test_returns_true_when_flag_evaluates_true(self) -> None:
        with patch(
            "products.signals.backend.access.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            assert user_can_see_signals_scout_reports(self.user, self.team) is True

    def test_returns_false_when_flag_evaluates_false(self) -> None:
        with patch(
            "products.signals.backend.access.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            assert user_can_see_signals_scout_reports(self.user, self.team) is False

    def test_returns_false_without_evaluating_when_user_has_no_distinct_id(self) -> None:
        self.user.distinct_id = ""
        with patch(
            "products.signals.backend.access.posthoganalytics.feature_enabled",
        ) as mock_eval:
            assert user_can_see_signals_scout_reports(self.user, self.team) is False
            mock_eval.assert_not_called()

    def test_fails_closed_on_eval_exception(self) -> None:
        with (
            patch(
                "products.signals.backend.access.posthoganalytics.feature_enabled",
                side_effect=RuntimeError("posthoganalytics misconfigured"),
            ),
            patch("products.signals.backend.access.capture_exception") as captured,
        ):
            assert user_can_see_signals_scout_reports(self.user, self.team) is False
            captured.assert_called_once()

    def test_evaluates_remotely_with_distinct_id_and_groups(self) -> None:
        with patch(
            "products.signals.backend.access.posthoganalytics.feature_enabled",
            return_value=True,
        ) as mock_eval:
            user_can_see_signals_scout_reports(self.user, self.team)
        mock_eval.assert_called_once()
        args, kwargs = mock_eval.call_args
        assert args[0] == SIGNALS_SCOUT_INBOX_FLAG
        assert args[1] == self.user.distinct_id
        assert kwargs["only_evaluate_locally"] is False
        assert kwargs["send_feature_flag_events"] is False
        assert kwargs["groups"] == {
            "organization": str(self.team.organization_id),
            "project": str(self.team.id),
        }
