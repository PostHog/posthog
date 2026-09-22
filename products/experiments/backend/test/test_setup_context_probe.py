from datetime import timedelta
from io import StringIO

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone

from products.experiments.backend.hogql_queries.exposure_query_logic import DEFAULT_EXPOSURE_EVENT
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.setup_context_probe import (
    SECTION_NAMES,
    SetupContextProbe,
    teams_with_recent_experiments,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestSetupContextProbe(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="probe-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        Experiment.objects.create(team=self.team, name="Probe experiment", feature_flag=flag, created_by=self.user)
        _create_person(team=self.team, distinct_ids=["visitor"])
        _create_event(
            team=self.team,
            event=DEFAULT_EXPOSURE_EVENT,
            distinct_id="visitor",
            timestamp=timezone.now() - timedelta(hours=1),
            properties={
                "$feature_flag": "probe-flag",
                "$feature_flag_response": "test",
                "$lib": "web",
                "$device_id": "device-1",
                "$is_identified": "false",
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="visitor",
            timestamp=timezone.now() - timedelta(hours=1),
            properties={"$lib": "web", "$device_id": "device-1", "$is_identified": "false"},
        )
        flush_persons_and_events()

    def test_scorecard_reports_every_section_and_every_decisive_fact(self) -> None:
        scorecard = SetupContextProbe(target_event="$pageview").run([self.team])

        assert scorecard.teams == 1
        assert scorecard.failed_teams == 0
        assert [section.name for section in scorecard.sections] == list(SECTION_NAMES)
        # candidate_metric is skipped without a metric event, so it reports a status but no timing.
        assert {section.name: section.p50_ms is None for section in scorecard.sections}["candidate_metric"]
        assert set(scorecard.fact_coverage) == {
            "sdk_libs_empty",
            "libs_on_any_event_used",
            "anonymous_share_null",
            "anonymous_share_crosses_identification",
            "device_id_bucketing_plausible",
            "server_lib_evaluates_locally",
            "previous_experiment_count",
            "shared_metric_count",
        }
        assert scorecard.readings[0].facts is not None
        assert scorecard.readings[0].facts.previous_experiment_count == 1

    def test_teams_with_recent_experiments_finds_the_seeded_project(self) -> None:
        assert self.team in teams_with_recent_experiments(limit=5)

    def test_command_prints_a_scorecard_without_user_authored_strings(self) -> None:
        out = StringIO()
        call_command(
            "probe_experiment_setup_context",
            f"--team-id={self.team.pk}",
            "--target-event=$pageview",
            "--per-team",
            stdout=out,
        )
        printed = out.getvalue()

        for name in SECTION_NAMES:
            assert name in printed
        assert str(self.team.pk) in printed
        assert "Probe experiment" not in printed
        assert "probe-flag" not in printed
