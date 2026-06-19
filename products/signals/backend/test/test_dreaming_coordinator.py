from __future__ import annotations

import random
from datetime import timedelta

import pytest

from django.utils import timezone

from posthog.models import Organization, Team

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.temporal.dreaming.coordinator import (
    DreamingTeamRun,
    _collect_due_dreaming_runs,
    _overdue_seconds,
    _stamp_dispatched,
)
from products.signals.backend.temporal.dreaming.enrollment import (
    DREAMING_RUN_INTERVAL_MINUTES,
    DREAMING_SKILL_NAME,
    force_enable_dreaming,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org() -> Organization:
    return Organization.objects.create(name=f"DreamOrg-{random.randint(1, 99999)}")


@pytest.fixture
def team(org: Organization) -> Team:
    t = Team.objects.create(organization=org, name=f"DreamTeam-{random.randint(1, 99999)}")
    return t


class TestForceEnableDreaming:
    def test_creates_enabled_config_with_nightly_interval(self, team: Team):
        config = force_enable_dreaming(team.id)
        assert config.skill_name == DREAMING_SKILL_NAME
        assert config.enabled is True
        assert config.run_interval_minutes == DREAMING_RUN_INTERVAL_MINUTES

    def test_reasserts_enabled_when_disabled(self, team: Team):
        force_enable_dreaming(team.id)
        SignalScoutConfig.all_teams.filter(team_id=team.id, skill_name=DREAMING_SKILL_NAME).update(enabled=False)

        config = force_enable_dreaming(team.id)
        assert config.enabled is True
        # Reasserted in the DB, not just the returned instance.
        reloaded = SignalScoutConfig.all_teams.get(team_id=team.id, skill_name=DREAMING_SKILL_NAME)
        assert reloaded.enabled is True

    def test_idempotent_single_row(self, team: Team):
        force_enable_dreaming(team.id)
        force_enable_dreaming(team.id)
        assert SignalScoutConfig.all_teams.filter(team_id=team.id, skill_name=DREAMING_SKILL_NAME).count() == 1


class TestOverdueSeconds:
    def test_never_run_is_maximally_overdue(self):
        assert _overdue_seconds(None, timezone.now(), 60) == float("inf")

    def test_not_yet_due_returns_none(self):
        now = timezone.now()
        last = now - timedelta(minutes=10)
        assert _overdue_seconds(last, now, 60) is None

    def test_past_interval_is_due(self):
        now = timezone.now()
        last = now - timedelta(minutes=120)
        overdue = _overdue_seconds(last, now, 60)
        assert overdue is not None and overdue > 0


class TestCollectDueRuns:
    def test_enrolled_team_force_enabled_and_due(self, team: Team):
        runs = _collect_due_dreaming_runs({team.id})
        assert DreamingTeamRun(team_id=team.id) in runs
        # The config was force-created as a side effect.
        assert SignalScoutConfig.all_teams.filter(team_id=team.id, skill_name=DREAMING_SKILL_NAME).exists()

    def test_recently_run_team_not_due(self, team: Team):
        force_enable_dreaming(team.id)
        SignalScoutConfig.all_teams.filter(team_id=team.id, skill_name=DREAMING_SKILL_NAME).update(
            last_run_at=timezone.now()
        )
        runs = _collect_due_dreaming_runs({team.id})
        assert DreamingTeamRun(team_id=team.id) not in runs

    def test_unenrolled_team_not_collected(self, team: Team):
        runs = _collect_due_dreaming_runs(set())
        assert runs == []

    def test_most_overdue_first_then_stable_by_team_id(self, org: Organization):
        # Two enrolled teams, both due (never run) -> both selected, sorted stable by team id.
        t1 = Team.objects.create(organization=org, name="t1")
        t2 = Team.objects.create(organization=org, name="t2")
        runs = _collect_due_dreaming_runs({t1.id, t2.id})
        team_ids = [r.team_id for r in runs]
        assert team_ids == sorted(team_ids)
        assert set(team_ids) == {t1.id, t2.id}

    def test_stamp_advances_last_run_at(self, team: Team):
        force_enable_dreaming(team.id)
        _stamp_dispatched([DreamingTeamRun(team_id=team.id)])
        config = SignalScoutConfig.all_teams.get(team_id=team.id, skill_name=DREAMING_SKILL_NAME)
        assert config.last_run_at is not None


class TestEnrollmentReadFromFlag:
    def test_collect_uses_force_enable_per_enrolled_team(self, org: Organization):
        teams = [Team.objects.create(organization=org, name=f"e{i}") for i in range(3)]
        enrolled = {t.id for t in teams}
        runs = _collect_due_dreaming_runs(enrolled)
        assert {r.team_id for r in runs} == enrolled
        for t in teams:
            assert SignalScoutConfig.all_teams.filter(
                team_id=t.id, skill_name=DREAMING_SKILL_NAME, enabled=True
            ).exists()
