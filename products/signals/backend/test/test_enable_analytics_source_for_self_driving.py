from io import StringIO
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized

from products.signals.backend.anomaly_scores.config import covers_team, parse_config
from products.signals.backend.contracts import ALERT_SCOPE_SOURCE, AlertScope
from products.signals.backend.facade.source_configs import get_analytics_alert_scope
from products.signals.backend.models import SignalSourceConfig, SignalTeamConfig

_COMPLETED = {"completed_at": "2026-11-01T00:00:00Z"}
_SOURCE_PRODUCT, _SOURCE_TYPE = ALERT_SCOPE_SOURCE


class TestEnableAnalyticsSourceForSelfDriving(BaseTest):
    def _run(self, *args: str) -> str:
        payload = {"enabled": True, "organization_ids": [str(self.organization.id)]}
        out = StringIO()
        with patch("products.signals.backend.anomaly_scores.config.read_flag_payload", return_value=payload):
            call_command("enable_analytics_source_for_self_driving", *args, stdout=out)
        return out.getvalue()

    def _row(self) -> SignalSourceConfig | None:
        return SignalSourceConfig.objects.filter(
            team_id=self.team.id, source_product=_SOURCE_PRODUCT, source_type=_SOURCE_TYPE
        ).first()

    def _covered(self) -> bool:
        return covers_team(parse_config({"enabled": True, "organization_ids": [str(self.organization.id)]}), self.team)

    def _add_row(self, **fields: Any) -> SignalSourceConfig:
        return SignalSourceConfig.objects.create(
            team=self.team, source_product=_SOURCE_PRODUCT, source_type=_SOURCE_TYPE, **fields
        )

    @parameterized.expand(
        [
            ("setup_completed", {"onboarding": _COMPLETED}, None, True),
            ("setup_not_completed", {"onboarding": {"step": "repos"}}, None, False),
            ("completed_at_null", {"onboarding": {"completed_at": None}}, None, False),
            ("scoring_turned_off", {"onboarding": _COMPLETED, "anomaly_scoring_enabled": False}, None, False),
            ("source_turned_off", {"onboarding": _COMPLETED}, {"enabled": False}, False),
            (
                "source_on",
                {"onboarding": _COMPLETED},
                {"enabled": True, "config": {"alert_scope": "all_firing_alerts"}},
                False,
            ),
        ]
    )
    def test_apply_writes_the_row_only_for_self_driving_projects_without_one(
        self, _name: str, team_config: dict, existing_row: dict | None, expect_created: bool
    ) -> None:
        SignalTeamConfig.objects.create(team=self.team, **team_config)
        if existing_row is not None:
            self._add_row(**existing_row)
        before = self._row()
        before_state = (before.enabled, before.config) if before else None

        output = self._run("--team-ids", str(self.team.id))

        assert f"Matched: {int(expect_created)}" in output
        assert f"In the scoring rollout now: {int(expect_created)}" in output
        row = self._row()
        assert ((row.enabled, row.config) if row else None) == before_state

        output = self._run("--apply")

        assert f"Created: {int(expect_created)}" in output
        row = self._row()
        if expect_created:
            assert row is not None and row.enabled
            assert get_analytics_alert_scope(team_id=self.team.id) == AlertScope.OFF
            assert self._covered()
        else:
            assert ((row.enabled, row.config) if row else None) == before_state

        assert "Created: 0" in self._run("--apply")

    @parameterized.expand(
        [
            ("unchanged", {}, True),
            ("person_set_alert_scope", {"config": {"alert_scope": "investigated_only"}}, False),
            ("person_turned_off", {"enabled": False}, False),
            ("onboarding_enabled", {"created_by": "user"}, False),
        ]
    )
    def test_revert_deletes_only_rows_nobody_changed(self, _name: str, change: dict, expect_deleted: bool) -> None:
        SignalTeamConfig.objects.create(team=self.team, onboarding=_COMPLETED)
        self._run("--apply")
        row = self._row()
        assert row is not None
        if "config" in change:
            row.config = {**row.config, **change["config"]}
        if "enabled" in change:
            row.enabled = change["enabled"]
        if change.get("created_by") == "user":
            row.created_by = self.user
        row.save()

        assert "Deleted" not in self._run("--revert")
        assert self._row() is not None

        output = self._run("--revert", "--apply")

        assert f"Deleted: {int(expect_deleted)}" in output
        assert (self._row() is None) == expect_deleted
