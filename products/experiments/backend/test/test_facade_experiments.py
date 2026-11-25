from dataclasses import asdict, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import serializers, status

from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import replace_tags_on_object
from posthog.models import Organization, User
from posthog.models.team import Team
from posthog.paging import PageRequest

from products.actions.backend.facade.testing import create_action
from products.cohorts.backend.facade.api import create_empty_static_cohort
from products.experiments.backend.facade.contracts import ExperimentBasic, ExperimentCreator, ExperimentListFilters
from products.experiments.backend.facade.experiments import get_experiment, list_experiments
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentHoldout,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.test.test_rule_linked_experiment import RULE_A, _experiment_rule, _v2_filters
from products.feature_flags.backend.api.feature_flag import MinimalFeatureFlagSerializer
from products.feature_flags.backend.models.evaluation_context import EvaluationContext, FeatureFlagEvaluationContext
from products.feature_flags.backend.models.feature_flag import FeatureFlag

_API_KEYS = {"exposure_cohort_id": "exposure_cohort", "experiment_id": "experiment", "saved_metric_id": "saved_metric"}
_CONTRACT_ONLY_KEYS = {"team_id", "created_by_id"}
# The API adds the access level of the viewer, and `health` and `saved_metrics_ids`, which it always renders as null.
_API_ONLY_KEYS = {"user_access_level", "health", "saved_metrics_ids"}

_CASES = ["fully_populated", "rule_linked_draft", "launched", "null_deleted_in_another_environment"]


def _rendered(value: Any) -> Any:
    if isinstance(value, ExperimentCreator):
        return dict(UserBasicSerializer(value).data)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            _API_KEYS.get(field.name, field.name): _rendered(getattr(value, field.name))
            for field in fields(value)
            if not (isinstance(value, ExperimentBasic) and field.name in _CONTRACT_ONLY_KEYS)
        }
    if isinstance(value, datetime):
        return serializers.DateTimeField().to_representation(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, list | tuple):
        return [_rendered(item) for item in value]
    if isinstance(value, dict):
        return {key: _rendered(item) for key, item in value.items()}
    return value


def _without_api_only_keys(row: dict[str, Any]) -> dict[str, Any]:
    row = {key: value for key, value in row.items() if key not in _API_ONLY_KEYS}
    if row.get("holdout"):
        row["holdout"] = _without_api_only_keys(row["holdout"])
    return row


class ExperimentFixtures:
    team: Team
    user: User
    organization: Organization

    def _flag(self, key: str, *, team: Team | None = None, **attributes: Any) -> FeatureFlag:
        return FeatureFlag.objects.create(team=team or self.team, key=key, created_by=self.user, **attributes)

    def _create_fully_populated(self, index: int = 0) -> Experiment:
        flag = self._flag(
            f"populated-flag-{index}",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 75}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
                "payloads": {"test": '{"color": "red"}'},
                "aggregation_group_type_index": 0,
            },
        )
        context = EvaluationContext.objects.create(team=self.team, name=f"context-{index}")
        FeatureFlagEvaluationContext.objects.create(feature_flag=flag, evaluation_context=context)
        action = create_action(team=self.team, name=f"Signed up {index}", steps_json=[{"event": "signed_up"}])
        action_metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "uuid": f"action-metric-{index}",
            "source": {"kind": "ActionsNode", "id": action.id, "name": "Stale name"},
        }
        experiment = Experiment.objects.create(
            team=self.team,
            name=f"Populated {index}",
            description="A red button converts better.",
            feature_flag=flag,
            holdout=ExperimentHoldout.objects.create(
                team=self.team,
                name=f"Holdout {index}",
                created_by=self.user,
                filters=[{"properties": [], "rollout_percentage": 10, "variant": f"holdout-{index}"}],
            ),
            exposure_cohort_id=create_empty_static_cohort(
                team_id=self.team.id, name=f"Exposed {index}", description="", created_by_id=self.user.id
            ).id,
            created_by=self.user,
            start_date=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
            end_date=datetime(2026, 2, 5, 10, 0, tzinfo=UTC),
            type="web",
            # Stale flag config, which the read replaces with the config of the flag.
            parameters={"variant_notes": {"test": "Red button"}, "rollout_percentage": 5, "feature_flag_variants": []},
            running_time_calculation={"minimum_detectable_effect": 5},
            excluded_variants=["test"],
            conclusion="won",
            conclusion_comment="Clear win.",
            repository="posthog/posthog",
            flag_cleanup_task_id=uuid4(),
            metrics=[action_metric],
            metrics_secondary=[{**action_metric, "uuid": f"secondary-action-metric-{index}"}],
            secondary_metrics=[{"name": "Old secondary"}],
            filters={"events": [{"id": "$pageview", "order": 0}]},
            exposure_criteria={"filterTestAccounts": True},
            stats_config={"method": "bayesian"},
            scheduling_config={"timeseries": True},
            primary_metrics_ordered_uuids=[f"action-metric-{index}"],
            only_count_matured_users=True,
            version=3,
        )
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team, name=f"Saved {index}", created_by=self.user, query=action_metric
        )
        ExperimentToSavedMetric.objects.create(
            experiment=experiment,
            saved_metric=saved_metric,
            metadata={"type": "primary", "breakdowns": [{"property": "$browser", "type": "event"}]},
        )
        legacy_metric = ExperimentSavedMetric.objects.create(
            team=self.team, name=f"Legacy {index}", created_by=self.user, query={"kind": "ExperimentFunnelsQuery"}
        )
        ExperimentToSavedMetric.objects.create(
            experiment=experiment, saved_metric=legacy_metric, metadata={"type": "secondary"}
        )
        replace_tags_on_object(["growth", "pricing"], experiment)
        return experiment

    def _create_rule_linked_draft(self) -> Experiment:
        return Experiment.objects.create(
            team=self.team,
            name="On a rule",
            feature_flag=self._flag("flag-with-rules", filters=_v2_filters(_experiment_rule(RULE_A))),
            feature_flag_rule_id=RULE_A,
            created_by=self.user,
            parameters={"rollout_percentage": 5, "aggregation_group_type_index": 1},
        )

    def _create_launched(self) -> Experiment:
        return Experiment.objects.create(
            team=self.team,
            name="Launched",
            feature_flag=self._flag("launched-flag"),
            created_by=self.user,
            start_date=timezone.now() - timedelta(days=3),
        )

    def _create_null_deleted_in_another_environment(self) -> Experiment:
        environment = Team.objects.create(organization=self.organization, project=self.team.project, name="Staging")
        return Experiment.objects.create(
            team=environment,
            name="In staging",
            feature_flag=self._flag("staging-flag", team=environment),
            deleted=None,
        )


class TestExperimentReadFacade(ExperimentFixtures, APIBaseTest):
    maxDiff = None

    @parameterized.expand(_CASES)
    def test_get_experiment_matches_the_api(self, case: str) -> None:
        experiment = getattr(self, f"_create_{case}")()
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        detail = get_experiment(team=self.team, experiment_id=experiment.id)

        assert detail is not None
        self.assertEqual(_rendered(detail), _without_api_only_keys(response.json()))
        self.assertEqual(_rendered(detail.feature_flag), MinimalFeatureFlagSerializer(experiment.feature_flag).data)

    @parameterized.expand(
        [
            ("default", ExperimentListFilters()),
            ("order", ExperimentListFilters(order="-name")),
            ("search", ExperimentListFilters(search="populated")),
            ("status", ExperimentListFilters(status="running")),
        ]
    )
    def test_list_experiments_matches_the_api(self, _name: str, filters: ExperimentListFilters) -> None:
        for case in _CASES:
            getattr(self, f"_create_{case}")()
        other_project = Team.objects.create(organization=self.organization, name="Other project")
        Experiment.objects.create(
            team=other_project, name="Elsewhere", feature_flag=self._flag("x", team=other_project)
        )
        query = urlencode({name: value for name, value in asdict(filters).items() if value})
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/?{query}")
        body = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK, body)

        page = list_experiments(team=self.team, filters=filters, access=None, page=PageRequest(limit=100))

        self.assertEqual(page.count, body["count"])
        self.assertEqual([row.id for row in page.results], [row["id"] for row in body["results"]])
        self.assertTrue(page.results)
        for contract, api_row in zip(page.results, body["results"]):
            self.assertEqual(_rendered(contract), _without_api_only_keys(api_row))

    @parameterized.expand(
        [
            ("live", {}, {}, True),
            ("deleted", {"deleted": True}, {}, False),
            ("deleted_with_include_deleted", {"deleted": True}, {"include_deleted": True}, True),
        ]
    )
    def test_get_experiment_finds_the_experiment_the_lookup_names(
        self, _name: str, stored: dict[str, Any], options: dict[str, Any], found: bool
    ) -> None:
        experiment = Experiment.objects.create(
            team=self.team, name="Lookup", feature_flag=self._flag("lookup-flag"), **stored
        )

        detail = get_experiment(team=self.team, experiment_id=experiment.id, **options)

        self.assertEqual(detail is not None, found)

    def test_get_experiment_reads_only_the_project(self) -> None:
        other_project = Team.objects.create(organization=self.organization, name="Other project")
        experiment = Experiment.objects.create(
            team=other_project, name="Elsewhere", feature_flag=self._flag("elsewhere", team=other_project)
        )

        self.assertIsNone(get_experiment(team=self.team, experiment_id=experiment.id))

    def test_get_experiment_reads_each_relation_once(self) -> None:
        experiment = self._create_fully_populated()

        # The experiment, the flag's evaluation contexts, the shared metrics, the tags, the legacy check, the team's
        # experiment settings, and one action lookup per metric that references an action.
        with self.assertNumQueries(9):
            get_experiment(team=self.team, experiment_id=experiment.id)

    def test_list_experiments_query_count_stays_flat_as_rows_grow(self) -> None:
        self._create_fully_populated(0)

        # The count, the page, the flags' evaluation contexts and the tags.
        with self.assertNumQueries(4):
            list_experiments(team=self.team, filters=ExperimentListFilters(), access=None, page=PageRequest(limit=10))

        for index in range(1, 5):
            self._create_fully_populated(index)

        with self.assertNumQueries(4):
            page = list_experiments(
                team=self.team, filters=ExperimentListFilters(), access=None, page=PageRequest(limit=10)
            )
        self.assertEqual(page.count, 5)
