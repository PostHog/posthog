from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, User

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.posthog_ai.evals.experiments.seeders import (
    AA_TEST_FLAG_KEY,
    seed_existing_user_project,
    seed_newcomer_project,
)
from products.tasks.backend.facade.agents import CustomPromptSandboxContext


class TestGuidedCreationSeeders(APIBaseTest):
    def _context(self) -> CustomPromptSandboxContext:
        return CustomPromptSandboxContext(team_id=self.team.id, user_id=self.user.id)

    def _seed_newcomer(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with (
            patch("posthog.persons_db.persons_db_connection", MagicMock()),
            patch("posthog.persons_seed.insert_seed_person", return_value=1),
            patch("posthog.persons_seed.insert_seed_distinct_id"),
            patch("posthog.models.person.util.create_person"),
            patch("posthog.models.person.util.create_person_distinct_id"),
            patch("posthog.models.event.util.bulk_create_events") as bulk_create_events,
            patch("products.demo.backend.facade.api.infer_taxonomy_for_team"),
        ):
            seed = seed_newcomer_project(self._context())
        return seed, bulk_create_events.call_args.args[0]

    def test_newcomer_project_gets_about_ten_visitors_a_month(self) -> None:
        seed, events = self._seed_newcomer()

        since = datetime.now(tz=UTC) - timedelta(days=30)
        recent_visitors = {
            event["distinct_id"] for event in events if event["event"] == "$pageview" and event["timestamp"] >= since
        }
        assert seed["visitors_last_30_days"] == len(recent_visitors) == 10

    def test_newcomer_aa_test_is_running_and_was_created_by_the_user(self) -> None:
        seed, events = self._seed_newcomer()

        experiment = Experiment.objects.get(id=seed["aa_experiment_id"])
        assert experiment.created_by_id == self.user.id
        assert experiment.start_date is not None and experiment.end_date is None
        assert experiment.status == Experiment.Status.RUNNING
        assert FeatureFlag.objects.get(id=experiment.feature_flag_id).key == AA_TEST_FLAG_KEY
        exposures = [event for event in events if event["event"] == "$feature_flag_called"]
        assert exposures and all(event["timestamp"] >= experiment.start_date for event in exposures)

    def test_seeders_hide_the_case_name_from_the_agent(self) -> None:
        self._seed_newcomer()

        assert Organization.objects.get(id=self.organization.id).name == "Hedgebox"
        assert User.objects.get(id=self.user.id).email == f"karen-{self.user.id}@hedgebox.example"

    def test_existing_user_project_needs_an_ended_experiment(self) -> None:
        with self.assertRaises(RuntimeError):
            seed_existing_user_project(self._context())

    def test_existing_user_project_summarises_the_ended_experiments(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="pricing-page-v3")
        Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Pricing page redesign",
            feature_flag=flag,
            start_date=datetime.now(tz=UTC) - timedelta(days=40),
            end_date=datetime.now(tz=UTC) - timedelta(days=10),
            conclusion="inconclusive",
        )
        with patch("posthog.clickhouse.client.sync_execute", return_value=[(1234,)]):
            seed = seed_existing_user_project(self._context())

        assert seed["ended_experiment_count"] == 1
        assert seed["visitors_last_30_days"] == 1234
        assert "'Pricing page redesign' (inconclusive)" in seed["project_summary"]
