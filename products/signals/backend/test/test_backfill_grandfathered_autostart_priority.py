from io import StringIO
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from parameterized import parameterized

from products.signals.backend.autostart_priority_backfill import organization_outcome
from products.signals.backend.models import SignalTeamConfig
from products.signals.backend.trial.policy import TrialFlagDecision

_FLAG = "products.signals.backend.trial.policy.posthoganalytics.feature_enabled"
_ACTIVATED_BEFORE_LAUNCH = {"completed_at": "2026-01-01T00:00:00+00:00"}


class TestOrganizationOutcome(SimpleTestCase):
    @parameterized.expand(
        [
            ("grandfathered", True, False, TrialFlagDecision(enabled=False, confirmed=True), "grandfathered"),
            ("flag_on", True, False, TrialFlagDecision(enabled=True, confirmed=True), "usage_based_pricing"),
            ("cached_flag_off", True, False, TrialFlagDecision(enabled=False, confirmed=False), "flag_unconfirmed"),
            ("flag_unknown", True, False, TrialFlagDecision(enabled=None, confirmed=False), "flag_unconfirmed"),
            (
                "cutover_pending",
                True,
                True,
                TrialFlagDecision(enabled=False, confirmed=True),
                "billing_cutover_pending",
            ),
            (
                "activated_after_launch",
                False,
                False,
                TrialFlagDecision(enabled=False, confirmed=True),
                "activated_after_launch",
            ),
        ]
    )
    def test_outcome(
        self, _name: str, activated: bool, cutover_pending: bool, flag: TrialFlagDecision, expected: str
    ) -> None:
        assert (
            organization_outcome(activated_before_launch=activated, billing_cutover_pending=cutover_pending, flag=flag)
            == expected
        )


class TestBackfillGrandfatheredAutostartPriority(APIBaseTest):
    def _config(self, **fields: Any) -> SignalTeamConfig:
        return SignalTeamConfig.objects.create(team=self.team, **{"onboarding": _ACTIVATED_BEFORE_LAUNCH, **fields})

    def _run(self, *args: str, flag: bool | None = False) -> str:
        out = StringIO()
        with patch(_FLAG, return_value=flag):
            call_command("backfill_grandfathered_autostart_priority", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing_and_apply_sets_p2(self) -> None:
        config = self._config()

        output = self._run()
        config.refresh_from_db()
        assert config.default_autostart_priority == "P4"
        assert "grandfathered: 1" in output

        output = self._run("--apply", "--team-id", str(self.team.id))
        config.refresh_from_db()
        assert config.default_autostart_priority == "P2"
        assert "updated: 1" in output

    @parameterized.expand(
        [
            ("autostart_off", {"autostart_enabled": False}, False, "P4"),
            ("lower_threshold_already_set", {"default_autostart_priority": "P1"}, False, "P1"),
            (
                "picked_p4_in_setup",
                {"onboarding": {**_ACTIVATED_BEFORE_LAUNCH, "draft": {"implementation_priority": "P4"}}},
                False,
                "P4",
            ),
            ("usage_based_pricing", {}, True, "P4"),
            ("flag_unavailable", {}, None, "P4"),
            ("activated_after_launch", {"onboarding": None}, False, "P4"),
        ]
    )
    def test_apply_leaves_the_threshold(
        self, _name: str, fields: dict[str, Any], flag: bool | None, expected: str
    ) -> None:
        config = self._config(**fields)

        self._run("--apply", flag=flag)

        config.refresh_from_db()
        assert config.default_autostart_priority == expected

    def test_apply_leaves_a_p4_threshold_that_a_person_set(self) -> None:
        config = self._config()
        url = f"/api/projects/{self.team.id}/signals/config/"
        for priority in ("P1", "P4"):
            response = self.client.post(url, {"default_autostart_priority": priority}, format="json")
            assert response.status_code == 200, response.json()

        self._run("--apply")

        config.refresh_from_db()
        assert config.default_autostart_priority == "P4"
