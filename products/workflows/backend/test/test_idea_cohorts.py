from dataclasses import replace
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import EventDefinition, Organization, OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.signals.backend.models import SignalScoutConfig
from products.workflows.backend.models import HogFlow, WorkflowIdeaTrial
from products.workflows.backend.services import idea_cohorts
from products.workflows.backend.services.idea_cohorts import (
    DEFAULT_SETTINGS,
    SCOUT_SKILL_NAME,
    Candidate,
    _balanced_cohort,
    rotate_idea_cohort,
    select_candidates,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
ON = replace(DEFAULT_SETTINGS, enabled=True, cohort_size=6)


def _candidate(team_id: int, segment: WorkflowIdeaTrial.Segment, score: float) -> Candidate:
    return Candidate(team_id=team_id, segment=segment, score=score, selection={})


class TestBalancedCohort(SimpleTestCase):
    def test_takes_an_even_share_per_segment_and_fills_a_short_segment_with_the_best_of_the_rest(self) -> None:
        competitor = [_candidate(i, WorkflowIdeaTrial.Segment.COMPETITOR, 10 - i) for i in range(1, 5)]
        greenfield = [_candidate(i, WorkflowIdeaTrial.Segment.GREENFIELD, 1.0) for i in range(10, 13)]

        picked = _balanced_cohort(competitor + greenfield, 6)

        assert [c.team_id for c in picked] == [1, 2, 10, 11, 3, 4]


class TestIdeaCohorts(BaseTest):
    def _project(self, name: str, *, ai_approved: bool = True, active_members: int = 2) -> Team:
        organization = Organization.objects.create(name=f"{name} org", is_ai_data_processing_approved=ai_approved)
        team = Team.objects.create(organization=organization, name=name)
        for index in range(active_members):
            user = User.objects.create(email=f"{index}@{name.replace(' ', '-')}.example.com", last_login=timezone.now())
            OrganizationMembership.objects.create(organization=organization, user=user)
        for event in ("purchase", "user_signed_up"):
            EventDefinition.objects.create(team=team, name=event, last_seen_at=timezone.now())
        return team

    def _select(
        self, emailable: dict[int, int], billable: dict[int, int], exclude: set[int] | None = None
    ) -> list[Candidate]:
        with (
            patch.object(idea_cohorts, "_emailable_daily_people", return_value=emailable),
            patch.object(idea_cohorts, "_billable_invocations_by_team", return_value=billable),
        ):
            return select_candidates(ON, exclude_team_ids=exclude or set())

    def test_selection_keeps_only_reachable_production_projects_and_segments_them(self) -> None:
        competitor = self._project("Shop")
        HogFunction.objects.create(
            team=competitor,
            name="cio",
            type="destination",
            hog="return event",
            template_id="template-customerio",
            enabled=True,
        )
        stalled = self._project("Booking app")
        HogFlow.objects.create(team=stalled, name="Welcome", status=HogFlow.State.DRAFT)
        greenfield = self._project("Big consumer app")
        greenfield_env = Team.objects.create(
            organization=greenfield.organization, parent_team=greenfield, name="Big consumer app web"
        )
        heavy = self._project("Heavy sender")
        no_consent = self._project("No consent", ai_approved=False)
        nobody_home = self._project("Abandoned", active_members=0)
        staging = self._project("Shop staging")
        cooled = self._project("Tried last month")
        emailable = {
            t.id: 20_000 for t in (competitor, stalled, greenfield, heavy, no_consent, nobody_home, staging, cooled)
        }
        emailable[greenfield_env.id] = 5_000

        picked = self._select(emailable, billable={heavy.id: 50_000}, exclude={cooled.id})

        assert {c.team_id: c.segment for c in picked} == {
            competitor.id: WorkflowIdeaTrial.Segment.COMPETITOR,
            stalled.id: WorkflowIdeaTrial.Segment.STALLED,
            greenfield.id: WorkflowIdeaTrial.Segment.GREENFIELD,
        }
        assert next(c for c in picked if c.team_id == competitor.id).selection["messaging_tools"] == [
            "template-customerio"
        ]
        assert next(c for c in picked if c.team_id == greenfield.id).selection["emailable_daily_people"] == 25_000

    def test_rotation_runs_a_cohort_for_its_trial_then_records_outcomes_and_moves_on(self) -> None:
        adopter = self._project("Adopter")
        idle = self._project("Idle")
        launcher = self._project("Launcher")
        old_draft = HogFlow.objects.create(team=launcher, name="Old draft", status=HogFlow.State.DRAFT)
        HogFlow.objects.filter(pk=old_draft.pk).update(created_at=NOW - timedelta(days=30))
        newcomer = self._project("Newcomer")
        emailable = {adopter.id: 9_000, idle.id: 8_000, launcher.id: 7_500}

        with (
            patch.object(idea_cohorts, "_emailable_daily_people", return_value=emailable),
            patch.object(idea_cohorts, "_billable_invocations_by_team", return_value={}),
            patch.object(idea_cohorts, "_capture"),
        ):
            first = rotate_idea_cohort(settings=ON, now=NOW)
            assert (first.cohort, first.started) == (1, 3)
            assert _source_configs() == {adopter.id, idle.id, launcher.id}

            assert rotate_idea_cohort(settings=ON, now=NOW + timedelta(days=13)).started == 0

            flow = HogFlow.objects.create(team=adopter, name="Cart recovery", status=HogFlow.State.ACTIVE)
            HogFlow.objects.filter(pk=flow.pk).update(created_at=NOW + timedelta(days=3))
            launch = ActivityLog.objects.create(
                team_id=launcher.id,
                scope="HogFlow",
                item_id=str(old_draft.id),
                activity="updated",
                detail={
                    "changes": [
                        {
                            "type": "HogFlow",
                            "field": "status",
                            "action": "changed",
                            "before": "draft",
                            "after": "active",
                        }
                    ]
                },
            )
            ActivityLog.objects.filter(pk=launch.pk).update(created_at=NOW + timedelta(days=5))
            emailable[newcomer.id] = 7_000
            second = rotate_idea_cohort(settings=ON, now=NOW + timedelta(days=14))

        assert (second.ended, second.cohort, second.started) == (3, 2, 1)
        outcomes = dict(WorkflowIdeaTrial.objects.unscoped().filter(cohort=1).values_list("team_id", "outcome"))
        assert outcomes == {
            adopter.id: WorkflowIdeaTrial.Outcome.ADOPTED,
            idle.id: WorkflowIdeaTrial.Outcome.NO_CHANGE,
            launcher.id: WorkflowIdeaTrial.Outcome.ADOPTED,
        }
        assert _source_configs() == {newcomer.id}

    @parameterized.expand([("flag turned off", False), ("trial still running", True)])
    def test_turning_the_flag_off_ends_running_trials(self, _name: str, enabled: bool) -> None:
        team = self._project("Running")
        with (
            patch.object(idea_cohorts, "_emailable_daily_people", return_value={team.id: 9_000}),
            patch.object(idea_cohorts, "_billable_invocations_by_team", return_value={}),
            patch.object(idea_cohorts, "_capture"),
        ):
            rotate_idea_cohort(settings=ON, now=NOW)
            rotate_idea_cohort(settings=replace(ON, enabled=enabled), now=NOW + timedelta(days=1))

        trial = WorkflowIdeaTrial.objects.unscoped().get(team_id=team.id)
        assert (trial.outcome == WorkflowIdeaTrial.Outcome.RUNNING) is enabled
        assert (_source_configs() == {team.id}) is enabled


def _source_configs() -> set[int]:
    return set(
        SignalScoutConfig.all_teams.filter(skill_name=SCOUT_SKILL_NAME, source_product="workflows").values_list(
            "team_id", flat=True
        )
    )
