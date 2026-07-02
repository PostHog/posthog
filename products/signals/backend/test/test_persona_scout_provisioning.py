from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from products.signals.backend.facade.api import collect_scout_run_digests, provision_persona_scouts
from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.test.test_scout_harness_api import _make_run
from products.skills.backend.models.skills import LLMSkill

CSM_SKILLS = [
    "signals-scout-csm-account-pulse",
    "signals-scout-csm-support-watch",
    "signals-scout-csm-revenue-watch",
]
FIRE_PATH = "products.signals.backend.facade.api._fire_first_scout_runs"


def _fire_all(team_id, skill_names):
    return set(skill_names)


class TestProvisionPersonaScouts(BaseTest):
    def _provision(self, **overrides):
        kwargs: dict = {
            "team": self.team,
            "created_by": self.user,
            "slack_integration_id": 42,
            "channel_id": "C_ALERTS",
            "channel_name": "account-pulse",
            "skill_names": CSM_SKILLS,
        }
        kwargs.update(overrides)
        return provision_persona_scouts(**kwargs)

    @patch(FIRE_PATH, side_effect=_fire_all)
    def test_fresh_team_gets_seeded_enabled_fleet_with_delivery_and_first_runs(self, fire_mock) -> None:
        results = self._provision()
        assert [r.skill_name for r in results] == CSM_SKILLS
        assert all(r.created and r.first_run_started and r.channel_conflict is None for r in results)
        for skill_name in CSM_SKILLS:
            assert LLMSkill.objects.filter(team=self.team, name=skill_name, deleted=False).exists()
            config = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name=skill_name)
            assert config.enabled is True
            assert config.emit is True
            assert config.run_interval_minutes == 1440
            assert config.delivery_config["slack"]["channel_id"] == "C_ALERTS"
            assert config.delivery_config["slack"]["integration_id"] == 42
        # One shared-connection batch dispatch for the whole fleet, not one connect per skill.
        assert fire_mock.call_count == 1
        assert sorted(fire_mock.call_args.args[1]) == sorted(CSM_SKILLS)

    @patch(FIRE_PATH, side_effect=_fire_all)
    def test_existing_config_with_other_channel_is_not_overwritten(self, fire_mock) -> None:
        skill = CSM_SKILLS[0]
        SignalScoutConfig.objects.create(
            team=self.team,
            skill_name=skill,
            enabled=False,
            delivery_config={"slack": {"integration_id": 7, "channel_id": "C_OLD", "channel_name": "cs-alerts"}},
        )
        results = self._provision(skill_names=[skill])
        assert results[0].channel_conflict == "cs-alerts"
        assert results[0].created is False
        assert results[0].first_run_started is False
        config = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name=skill)
        assert config.delivery_config["slack"]["channel_id"] == "C_OLD"
        assert config.enabled is True
        # A conflicting scout is excluded from the first-run batch.
        assert fire_mock.call_args.args[1] == []

    @patch(FIRE_PATH, side_effect=_fire_all)
    def test_existing_config_without_delivery_is_adopted(self, fire_mock) -> None:
        skill = CSM_SKILLS[0]
        SignalScoutConfig.objects.create(team=self.team, skill_name=skill, enabled=False)
        results = self._provision(skill_names=[skill])
        assert results[0].created is False
        assert results[0].channel_conflict is None
        config = SignalScoutConfig.objects.for_team(self.team.id).get(skill_name=skill)
        assert config.enabled is True
        assert config.delivery_config["slack"]["channel_id"] == "C_ALERTS"

    def test_unknown_skill_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown canonical scout skill"):
            self._provision(skill_names=["signals-scout-does-not-exist"])

    @patch(FIRE_PATH, return_value=set())
    def test_first_run_dispatch_failure_does_not_fail_provisioning(self, fire_mock) -> None:
        results = self._provision(skill_names=[CSM_SKILLS[0]])
        assert results[0].created is True
        assert results[0].first_run_started is False
        assert SignalScoutConfig.objects.for_team(self.team.id).filter(skill_name=CSM_SKILLS[0]).exists()

    @patch(FIRE_PATH, side_effect=_fire_all)
    def test_tombstoned_skill_is_skipped_not_resurrected(self, fire_mock) -> None:
        skill = CSM_SKILLS[0]
        self._provision(skill_names=[skill])
        LLMSkill.objects.filter(team=self.team, name=skill).update(deleted=True, is_latest=False)
        SignalScoutConfig.objects.for_team(self.team.id).filter(skill_name=skill).delete()
        results = self._provision(skill_names=[skill])
        assert results[0].skipped_reason == "skill_tombstoned"
        assert results[0].config_id is None
        assert not LLMSkill.objects.filter(team=self.team, name=skill, deleted=False).exists()
        assert not SignalScoutConfig.objects.for_team(self.team.id).filter(skill_name=skill).exists()


class TestCollectScoutRunDigests(BaseTest):
    def _digests(self, config_ids, since="2020-01-01T00:00:00"):
        return collect_scout_run_digests(team_id=self.team.id, scout_config_ids=config_ids, since_iso=since)

    def test_returns_none_until_a_run_completes(self):
        run = _make_run(self.team, task_run_status="in_progress")
        assert self._digests([str(run.scout_config_id)]) is None

    def test_completed_runs_digest_with_newest_per_skill(self):
        older = _make_run(self.team, task_run_status="completed", summary="old sweep")
        newer = _make_run(
            self.team,
            task_run_status="completed",
            summary="fresh sweep, all clear",
            scout_config=older.scout_config,
            notifications=[{"ts": "1"}],
            emitted_report_ids=["r1"],
        )
        digests = self._digests([str(older.scout_config_id)])
        assert digests is not None
        assert len(digests) == 1
        assert digests[0].summary == "fresh sweep, all clear"
        assert digests[0].notifications_sent == 1
        assert digests[0].reports_filed == 1
        assert newer.skill_name == digests[0].skill_name

    def test_runs_before_provisioning_are_excluded(self):
        run = _make_run(self.team, task_run_status="completed", summary="pre-existing run")
        future = (timezone.now() + timedelta(hours=1)).isoformat()
        assert self._digests([str(run.scout_config_id)], since=future) is None
