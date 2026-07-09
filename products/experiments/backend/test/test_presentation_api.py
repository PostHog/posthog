from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import unittest
from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, FuzzyInt, _create_event, _create_person, flush_persons_and_events
from unittest.mock import ANY, MagicMock, patch

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from dateutil import parser
from parameterized import parameterized
from rest_framework import status

from posthog.auth import IDJagAccessTokenAuthentication, OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models import Organization, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.test_journeys import journeys_for

from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.experiments.backend.models.experiment import (
    EXPOSURE_FROZEN_GROUP_KEY,
    EXPOSURE_FROZEN_GROUP_MARKER,
    Experiment,
    ExperimentHoldout,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.models.web_experiment import WebExperiment
from products.experiments.backend.presentation.views import LIST_DEFERRED_FIELDS, EnterpriseExperimentsViewSet
from products.feature_flags.backend.models.evaluation_context import EvaluationContext, FeatureFlagEvaluationContext
from products.feature_flags.backend.models.feature_flag import FeatureFlag, get_feature_flags_for_team_in_cache

from ee.api.test.base import APILicensedTest
from ee.clickhouse.views.experiment_saved_metrics import ExperimentToSavedMetricSerializer


def _make(cls, **attrs):
    """Build an auth instance without running __init__, setting only the attributes the test needs."""
    instance = cls.__new__(cls)
    for key, value in attrs.items():
        setattr(instance, key, value)
    return instance


_FLAG_CONFIG_KEYS = (
    "feature_flag_variants",
    "rollout_percentage",
    "aggregation_group_type_index",
    "feature_flag_payloads",
    "ensure_experience_continuity",
)


def _hoist_flag_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Test helper: rewrite an experiment write payload that sets up flag config through the
    deprecated `parameters` keys into the `feature_flag` object the write API now requires. Non-flag
    `parameters` keys are preserved, and any `feature_flag` already on the payload is merged into."""
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict) or not any(key in parameters for key in _FLAG_CONFIG_KEYS):
        return payload
    payload = {**payload}
    parameters = {**parameters}
    feature_flag: dict[str, Any] = {**(payload.get("feature_flag") or {})}
    filters: dict[str, Any] = {**(feature_flag.get("filters") or {})}
    if "feature_flag_variants" in parameters:
        filters["multivariate"] = {"variants": parameters.pop("feature_flag_variants")}
    if "rollout_percentage" in parameters:
        filters["groups"] = [{"properties": [], "rollout_percentage": parameters.pop("rollout_percentage")}]
    if "aggregation_group_type_index" in parameters:
        filters["aggregation_group_type_index"] = parameters.pop("aggregation_group_type_index")
    if "feature_flag_payloads" in parameters:
        filters["payloads"] = parameters.pop("feature_flag_payloads")
    if "ensure_experience_continuity" in parameters:
        feature_flag["ensure_experience_continuity"] = parameters.pop("ensure_experience_continuity")
    if filters:
        feature_flag["filters"] = filters
    payload["feature_flag"] = feature_flag
    payload["parameters"] = parameters
    return payload


class _HoistFlagConfigClientMixin:
    """Flag config now belongs on the `feature_flag` object. The API still accepts it through the
    deprecated `parameters` keys (copying it onto the object for backward compatibility), but many
    fixtures in this file set it up via `parameters` as a convenience. This mixin transparently
    relocates those keys on experiment create/update requests so setup exercises the explicit
    `feature_flag` object path. Requests that already send a `feature_flag` object (or carry no flag
    config) pass through untouched.

    Tests that assert the deprecated-`parameters` copy behavior itself must NOT use this mixin — they
    send the deprecated keys directly (see TestExperimentParametersFlagConfigCompatibility)."""

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        real_post = self.client.post  # type: ignore[attr-defined]
        real_patch = self.client.patch  # type: ignore[attr-defined]

        def _wrap(method: Any) -> Any:
            def wrapper(path: str, data: Any = None, *args: Any, **kwargs: Any) -> Any:
                if isinstance(data, dict) and "/experiments/" in path.rstrip("/") + "/":
                    data = _hoist_flag_config(data)
                return method(path, data, *args, **kwargs)

            return wrapper

        self.client.post = _wrap(real_post)  # type: ignore[attr-defined]
        self.client.patch = _wrap(real_patch)  # type: ignore[attr-defined]


class TestExperimentCRUD(_HoistFlagConfigClientMixin, APILicensedTest):
    # List experiments
    def test_can_list_experiments(self):
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            (None, None),
            (None, []),
            ([], None),
        ]
    )
    def test_can_list_experiments_with_null_metrics(self, metrics: list | None, metrics_secondary: list | None) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="null-metrics-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        experiment = Experiment.objects.create(
            team=self.team,
            name="Null metrics experiment",
            feature_flag=flag,
            metrics=metrics,
            metrics_secondary=metrics_secondary,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_can_list_eligible_feature_flags(self) -> None:
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="eligible-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="wrong-order-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                    ]
                },
            },
        )
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="single-variant-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 100},
                    ]
                },
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/eligible_feature_flags/?order=key")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual([flag["key"] for flag in response.json()["results"]], ["eligible-flag"])

    @parameterized.expand(
        [
            ("draft", "draft"),
            ("running", "running"),
            ("exposure_frozen", "exposure_frozen"),
            ("paused", "paused"),
            ("stopped", "stopped"),
            ("complete", "stopped"),
        ]
    )
    def test_can_filter_experiments_by_status(self, status_filter: str, expected_status: str) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Draft experiment",
                "feature_flag_key": "draft-filter-flag",
                "parameters": None,
            },
        )
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Running experiment",
                "feature_flag_key": "running-filter-flag",
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
        )
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Stopped experiment",
                "feature_flag_key": "stopped-filter-flag",
                "start_date": "2021-12-01T10:23",
                "end_date": "2021-12-10T00:00",
                "parameters": None,
            },
        )
        # A running experiment with the freeze marker on its flag groups: must show up only under
        # exposure_frozen — and its presence proves the running filter excludes frozen experiments.
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Frozen experiment",
                "feature_flag_key": "frozen-filter-flag",
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
        )
        frozen_flag = FeatureFlag.objects.get(team=self.team, key="frozen-filter-flag")
        frozen_flag.filters = {
            **frozen_flag.filters,
            "groups": [
                {**group, EXPOSURE_FROZEN_GROUP_KEY: True, "description": EXPOSURE_FROZEN_GROUP_MARKER}
                for group in frozen_flag.filters.get("groups", [])
            ],
        }
        frozen_flag.save()
        # A frozen experiment that was then paused (flag deactivated, stamps still on the groups):
        # paused takes precedence, so it must show up under paused — not under exposure_frozen,
        # where it would misreport a flag that serves no one as still holding variants.
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Paused frozen experiment",
                "feature_flag_key": "paused-frozen-filter-flag",
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
        )
        paused_frozen_flag = FeatureFlag.objects.get(team=self.team, key="paused-frozen-filter-flag")
        paused_frozen_flag.filters = {
            **paused_frozen_flag.filters,
            "groups": [
                {**group, EXPOSURE_FROZEN_GROUP_KEY: True, "description": EXPOSURE_FROZEN_GROUP_MARKER}
                for group in paused_frozen_flag.filters.get("groups", [])
            ],
        }
        paused_frozen_flag.active = False
        paused_frozen_flag.save()

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/?status={status_filter}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["status"], expected_status)

    def test_status_filter_treats_partially_stamped_flag_as_running(self) -> None:
        # A frozen flag with a manually-added unstamped group reopens enrollment through that group.
        # The status filter must classify it the same way Experiment.is_exposure_frozen does (all groups
        # stamped, not just some): running, not exposure_frozen. Guards the list query against regressing
        # to a "some group is stamped" JSONB-containment match.
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Reopened experiment",
                "feature_flag_key": "reopened-filter-flag",
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
        )
        experiment_id = create_response.json()["id"]
        flag = FeatureFlag.objects.get(team=self.team, key="reopened-filter-flag")
        flag.filters = {
            **flag.filters,
            "groups": [
                *(
                    {**group, EXPOSURE_FROZEN_GROUP_KEY: True, "description": EXPOSURE_FROZEN_GROUP_MARKER}
                    for group in flag.filters.get("groups", [])
                ),
                {"properties": [], "rollout_percentage": 100},
            ],
        }
        flag.save()

        frozen_ids = [e["id"] for e in self._status_filter_results("exposure_frozen")]
        running_ids = [e["id"] for e in self._status_filter_results("running")]
        assert experiment_id not in frozen_ids
        assert experiment_id in running_ids

    def _status_filter_results(self, status_filter: str) -> list[dict[str, Any]]:
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/?status={status_filter}")
        assert response.status_code == status.HTTP_200_OK
        return response.json()["results"]

    def _create_experiment_with_metric_event(self, name: str, flag_key: str, event: str) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=flag_key,
            name=f"Flag for {flag_key}",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        return Experiment.objects.create(
            team=self.team,
            name=name,
            feature_flag=flag,
            metrics=[
                {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "EventsNode", "event": event}}
            ],
        )

    def test_can_filter_experiments_by_event(self) -> None:
        purchase_experiment = self._create_experiment_with_metric_event("Purchase", "purchase-flag", "purchase")
        self._create_experiment_with_metric_event("Signup", "signup-flag", "signup")

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/?event=purchase")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], purchase_experiment.id)

    def test_filter_by_event_resolves_actions(self) -> None:
        action = Action.objects.create(team=self.team, name="Checked out", steps_json=[{"event": "checkout"}])
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="action-flag",
            name="Flag for action-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        experiment = Experiment.objects.create(
            team=self.team,
            name="Action experiment",
            feature_flag=flag,
            metrics=[
                {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "ActionsNode", "id": action.id}}
            ],
        )

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/?event=checkout")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], experiment.id)

    def test_filter_by_event_matches_saved_metric(self) -> None:
        experiment = self._create_experiment_with_metric_event("Saved metric", "saved-metric-flag", "primary_event")
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="Conversion",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "saved_event"},
            },
        )
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved_metric)

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/?event=saved_event")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], experiment.id)

    def test_getting_experiments_is_not_nplus1(self) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            data={
                "name": "Test Experiment",
                "feature_flag_key": f"flag_0",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
            format="json",
        ).json()

        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            data={
                "name": "Test Experiment",
                "feature_flag_key": f"exp_flag_000",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "end_date": "2021-12-01T10:23",
                "archived": True,
                "parameters": None,
            },
            format="json",
        ).json()

        with self.assertNumQueries(FuzzyInt(13, 17)):
            response = self.client.get(f"/api/projects/{self.team.id}/experiments")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        for i in range(1, 5):
            self.client.post(
                f"/api/projects/{self.team.id}/experiments/",
                data={
                    "name": "Test Experiment",
                    "feature_flag_key": f"flag_{i}",
                    "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                    "start_date": "2021-12-01T10:23",
                    "parameters": None,
                },
                format="json",
            ).json()

        with self.assertNumQueries(FuzzyInt(13, 17)):
            response = self.client.get(f"/api/projects/{self.team.id}/experiments")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def _create_fully_populated_experiment(self, index: int) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"populated-flag-{index}",
            created_by=self.user,
        )
        context = EvaluationContext.objects.create(team=self.team, name=f"context-{index}")
        FeatureFlagEvaluationContext.objects.create(feature_flag=flag, evaluation_context=context)

        holdout = ExperimentHoldout.objects.create(
            team=self.team,
            name=f"Holdout {index}",
            created_by=self.user,
            filters=[{"properties": [], "rollout_percentage": 10, "variant": f"holdout-{index}"}],
        )
        cohort = Cohort.objects.create(team=self.team, name=f"Cohort {index}")

        experiment = Experiment.objects.create(
            team=self.team,
            name=f"Populated experiment {index}",
            feature_flag=flag,
            holdout=holdout,
            exposure_cohort=cohort,
            created_by=self.user,
            start_date=datetime(2021, 12, 1, 10, 23, tzinfo=UTC),
        )

        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            name=f"Saved metric {index}",
            created_by=self.user,
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
        )
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved_metric)
        return experiment

    def test_listing_experiments_with_related_objects_is_not_nplus1(self) -> None:
        # Each experiment carries a feature flag (+ evaluation context), a holdout (+ created_by),
        # an exposure cohort, and a saved metric — the relations that previously triggered N+1 queries.
        self._create_fully_populated_experiment(0)

        with CaptureQueriesContext(connection) as single_row:
            response = self.client.get(f"/api/projects/{self.team.id}/experiments")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["count"], 1)

        for i in range(1, 5):
            self._create_fully_populated_experiment(i)

        with CaptureQueriesContext(connection) as five_rows:
            response = self.client.get(f"/api/projects/{self.team.id}/experiments")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["count"], 5)

        # Query count must stay flat as rows grow — five experiments must not cost more than one.
        self.assertLessEqual(len(five_rows.captured_queries), len(single_row.captured_queries))

    def _create_experiment_with_action_metrics(self, index: int) -> tuple[Experiment, Action]:
        action = Action.objects.create(team=self.team, name=f"Action {index}", steps_json=[{"event": f"event_{index}"}])
        flag = FeatureFlag.objects.create(team=self.team, key=f"action-metric-flag-{index}", created_by=self.user)
        experiment = Experiment.objects.create(
            team=self.team,
            name=f"Action metric experiment {index}",
            feature_flag=flag,
            created_by=self.user,
            metrics=[
                {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "ActionsNode", "id": action.id}}
            ],
            metrics_secondary=[
                {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "ActionsNode", "id": action.id}}
            ],
        )
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            name=f"Saved action metric {index}",
            created_by=self.user,
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "ActionsNode", "id": action.id},
            },
        )
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved_metric)
        return experiment, action

    def test_listing_experiments_with_action_metrics_is_not_nplus1(self) -> None:
        # The list serializer omits metrics, so no per-metric Action lookups happen during
        # serialization. Query count must stay flat as rows grow.
        self._create_experiment_with_action_metrics(0)

        with CaptureQueriesContext(connection) as single_row:
            response = self.client.get(f"/api/projects/{self.team.id}/experiments")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["count"], 1)

        for i in range(1, 5):
            self._create_experiment_with_action_metrics(i)

        with CaptureQueriesContext(connection) as five_rows:
            response = self.client.get(f"/api/projects/{self.team.id}/experiments")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["count"], 5)

        self.assertLessEqual(len(five_rows.captured_queries), len(single_row.captured_queries))

    def test_list_query_defers_heavy_metric_columns(self) -> None:
        # Omitting the metric fields lets the list query defer the heavy JSON columns — they must not
        # be SELECTed from posthog_experiment. metrics/metrics_secondary are the exception: the
        # is_legacy annotation references them in its predicate (see list_is_legacy_annotation), so
        # they appear in the WHERE/CASE but never in the SELECT output — the response still omits them
        # (test_list_omits_heavy_metric_fields_kept_on_detail). The other deferred columns stay absent.
        self._create_experiment_with_action_metrics(0)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(f"/api/projects/{self.team.id}/experiments")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment_selects = [
            query["sql"] for query in ctx.captured_queries if 'FROM "posthog_experiment"' in query["sql"]
        ]
        self.assertTrue(experiment_selects, "expected at least one SELECT against posthog_experiment")
        # Inspected by the is_legacy predicate, so allowed in the SQL (but not in the SELECT output).
        predicate_columns = {"metrics", "metrics_secondary"}
        for sql in experiment_selects:
            for column in LIST_DEFERRED_FIELDS:
                if column in predicate_columns:
                    continue
                # Table-qualified so a same-named column on a joined table (e.g. feature_flag.filters)
                # doesn't trigger a false positive.
                self.assertNotIn(f'"posthog_experiment"."{column}"', sql)

    def test_list_reports_is_legacy(self) -> None:
        # is_legacy must survive the metric omission — it's computed in SQL on the list path so the
        # frontend badge/duplicate/copy guards keep working without loading the deferred metric JSON.
        # Cover the inline-metric path and the saved-metric (EXISTS) path, plus a non-legacy control.
        non_legacy, action = self._create_experiment_with_action_metrics(0)

        legacy_inline = Experiment.objects.create(
            team=self.team,
            name="Legacy inline",
            feature_flag=FeatureFlag.objects.create(team=self.team, key="legacy-inline", created_by=self.user),
            created_by=self.user,
            metrics=[{"kind": "ExperimentTrendsQuery"}],
        )

        legacy_via_saved = Experiment.objects.create(
            team=self.team,
            name="Legacy via saved metric",
            feature_flag=FeatureFlag.objects.create(team=self.team, key="legacy-saved", created_by=self.user),
            created_by=self.user,
            metrics=[
                {"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "ActionsNode", "id": action.id}}
            ],
        )
        legacy_saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="Legacy saved metric",
            created_by=self.user,
            query={"kind": "ExperimentFunnelsQuery"},
        )
        ExperimentToSavedMetric.objects.create(experiment=legacy_via_saved, saved_metric=legacy_saved_metric)

        results = self.client.get(f"/api/projects/{self.team.id}/experiments").json()["results"]
        by_id = {r["id"]: r for r in results}

        self.assertFalse(by_id[non_legacy.id]["is_legacy"])
        self.assertTrue(by_id[legacy_inline.id]["is_legacy"])
        self.assertTrue(by_id[legacy_via_saved.id]["is_legacy"])

    def test_detail_reports_is_legacy(self) -> None:
        experiment, _ = self._create_experiment_with_action_metrics(0)
        Experiment.objects.filter(pk=experiment.pk).update(metrics=[{"kind": "ExperimentTrendsQuery"}])

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["is_legacy"])

    def test_retrieving_experiment_refreshes_action_names(self) -> None:
        # Action-name refresh lives on the detail response — the list endpoint no longer
        # returns metrics (see ExperimentBasicSerializer).
        experiment, action = self._create_experiment_with_action_metrics(0)
        action.name = "Renamed action"
        action.save()

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()

        self.assertEqual(result["metrics"][0]["source"]["name"], "Renamed action")
        self.assertEqual(result["metrics_secondary"][0]["source"]["name"], "Renamed action")
        self.assertEqual(result["saved_metrics"][0]["query"]["source"]["name"], "Renamed action")

    def test_list_omits_heavy_metric_fields_kept_on_detail(self) -> None:
        # The list view never renders metric definitions, so they're excluded from the list
        # response (letting the query defer the JSON columns and skip the saved-metric prefetch).
        # The detail response still includes them.
        experiment, _ = self._create_experiment_with_action_metrics(0)

        list_result = next(
            r
            for r in self.client.get(f"/api/projects/{self.team.id}/experiments").json()["results"]
            if r["id"] == experiment.id
        )
        for omitted in ["metrics", "metrics_secondary", "saved_metrics"]:
            self.assertNotIn(omitted, list_result)
        # Fields the list view does use are still present.
        for kept in ["name", "status", "feature_flag", "parameters"]:
            self.assertIn(kept, list_result)

        detail_result = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment.id}").json()
        for present in ["metrics", "metrics_secondary", "saved_metrics"]:
            self.assertIn(present, detail_result)

    def test_creating_updating_basic_experiment(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)
        self.assertEqual(response.json()["stats_config"], {"method": "bayesian"})

        id = response.json()["id"]
        experiment = Experiment.objects.get(pk=id)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])

        end_date = "2021-12-10T00:00"

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "end_date": end_date},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")
        assert experiment.end_date is not None
        self.assertEqual(experiment.end_date.strftime("%Y-%m-%dT%H:%M"), end_date)

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_creating_experiment_reports_user_action(self, mock_report_user_action, _mock_on_commit):
        ff_key = "tracked-experiment"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Tracked Experiment",
                "description": "",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}],
                    "properties": [],
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        mock_report_user_action.assert_called_once()
        self.assertEqual(mock_report_user_action.call_args.args[0], self.user)
        self.assertEqual(mock_report_user_action.call_args.args[1], "experiment created")
        self.assertEqual(
            mock_report_user_action.call_args.args[2],
            {
                "experiment_id": response.json()["id"],
                "experiment_name": "Tracked Experiment",
                "feature_flag_key": ff_key,
                "type": "product",
                "status": "draft",
                "metrics_count": 0,
                "secondary_metrics_count": 0,
                "saved_metrics_count": 0,
                "has_description": False,
                "has_conclusion_comment": False,
                "variant_count": 2,
                "created_at": ANY,
                "creation_mode": "new",
                "experiment_create_deprecated_fields": ["filters"],
            },
        )
        self.assertEqual(mock_report_user_action.call_args.kwargs["team"], self.team)
        self.assertIsNotNone(mock_report_user_action.call_args.kwargs["request"])

    @parameterized.expand(
        [
            ("explicit_true_team_false", False, True, True),
            ("explicit_false_team_false", False, False, False),
            ("omitted_team_false", False, None, False),
            ("omitted_team_true", True, None, True),
            ("explicit_false_overrides_team_true", True, False, False),
        ]
    )
    def test_creating_experiment_ensure_experience_continuity(
        self, _name, flags_persistence_default, params_value, expected
    ):
        self.team.flags_persistence_default = flags_persistence_default
        self.team.save()

        ff_key = f"test-continuity-{_name}"
        parameters: dict = {}
        if params_value is not None:
            parameters["ensure_experience_continuity"] = params_value

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": f"Test Experiment {_name}",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": parameters,
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.ensure_experience_continuity, expected)

    def test_creating_experiment_with_rollout_percentage(self):
        ff_key = "test-rollout-flag"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment with Rollout",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {"rollout_percentage": 50},
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.filters["groups"][0]["rollout_percentage"], 50)

    def test_creating_experiment_without_rollout_percentage_defaults_to_100(self):
        ff_key = "test-default-rollout-flag"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment Default Rollout",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.filters["groups"][0]["rollout_percentage"], 100)

    def test_updating_experiment_preserves_release_conditions(self):
        ff_key = "test-update-rollout-flag"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment Update Rollout",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {"rollout_percentage": 80},
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.filters["groups"][0]["rollout_percentage"], 80)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                        {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                    ],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        created_ff.refresh_from_db()
        self.assertEqual(created_ff.filters["groups"][0]["rollout_percentage"], 80)

    def test_updating_experiment_applies_rollout_percentage_to_feature_flag(self):
        ff_key = "test-rollout-flag"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment Rollout",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {"rollout_percentage": 80},
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                        {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                    ],
                    "rollout_percentage": 30,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        flag = FeatureFlag.objects.get(key=ff_key, team=self.team)
        self.assertEqual(flag.filters["groups"][0]["rollout_percentage"], 30)

    def test_creating_updating_web_experiment(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "type": "web",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)
        web_experiment_id = response.json()["id"]
        self.assertEqual(
            WebExperiment.objects.get(pk=web_experiment_id).variants,
            {"test": {"rollout_percentage": 50}, "control": {"rollout_percentage": 50}},
        )

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])

        id = response.json()["id"]
        end_date = "2021-12-10T00:00"

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "end_date": end_date},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")
        assert experiment.end_date is not None
        self.assertEqual(experiment.end_date.strftime("%Y-%m-%dT%H:%M"), end_date)

    def test_cannot_assign_holdout_from_another_team(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_holdout = ExperimentHoldout.objects.create(
            team=other_team,
            name="Other Team Holdout",
            filters=[{"properties": [], "rollout_percentage": 20, "variant": "holdout"}],
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "holdout-idor-test",
                "holdout_id": other_holdout.id,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("does not exist", response.json()["detail"])

    def test_transferring_holdout_to_another_group(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts/",
            data={
                "name": "Test Experiment holdout",
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": 20,
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )

        holdout_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment holdout")
        self.assertEqual(
            response.json()["filters"],
            [{"properties": [], "rollout_percentage": 20, "variant": f"holdout-{holdout_id}"}],
        )

        # Generate draft experiment to be part of holdout
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
                "holdout_id": holdout_id,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(
            created_ff.filters["holdout"],
            {"id": holdout_id, "exclusion_percentage": 20},
        )

        exp_id = response.json()["id"]

        # new holdout, and update experiment
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts/",
            data={
                "name": "Test Experiment holdout 2",
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": 5,
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )
        holdout_2_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"holdout_id": holdout_2_id},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=exp_id)
        self.assertEqual(experiment.holdout_id, holdout_2_id)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(
            created_ff.filters["holdout"],
            {"id": holdout_2_id, "exclusion_percentage": 5},
        )

        # update parameters
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
            },
        )

        experiment = Experiment.objects.get(pk=exp_id)
        self.assertEqual(experiment.holdout_id, holdout_2_id)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(
            created_ff.filters["holdout"],
            {"id": holdout_2_id, "exclusion_percentage": 5},
        )
        self.assertEqual(
            created_ff.filters["multivariate"]["variants"],
            [
                {"key": "control", "name": "Control Group", "rollout_percentage": 33},
                {"key": "test_1", "name": "Test Variant", "rollout_percentage": 33},
                {"key": "test_2", "name": "Test Variant", "rollout_percentage": 34},
            ],
        )

        # remove holdouts
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"holdout_id": None},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=exp_id)
        self.assertEqual(experiment.holdout_id, None)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.filters["holdout"], None)

        # try adding invalid holdout
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"holdout_id": 123456},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], 'Invalid pk "123456" - object does not exist.')

        # add back holdout
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"holdout_id": holdout_2_id},
        )

        # launch experiment and try updating holdouts again
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"start_date": "2021-12-01T10:23"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"holdout_id": holdout_id},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Can't update holdout on running Experiment")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(
            created_ff.filters["holdout"],
            {"id": holdout_2_id, "exclusion_percentage": 5},
        )

    def test_saved_metrics(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
        )

        saved_metric_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment saved metric")
        self.assertEqual(response.json()["description"], "Test description")
        saved_metric_uuid = response.json()["query"]["uuid"]
        self.assertTrue(saved_metric_uuid)
        self.assertEqual(
            response.json()["query"],
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageview"},
                "uuid": saved_metric_uuid,
            },
        )
        self.assertEqual(response.json()["created_by"]["id"], self.user.pk)

        # Generate experiment to have saved metric
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "secondary"}}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        exp_id = response.json()["id"]

        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 1)
        experiment_to_saved_metric = Experiment.objects.get(pk=exp_id).experimenttosavedmetric_set.first()
        assert experiment_to_saved_metric is not None
        self.assertEqual(experiment_to_saved_metric.metadata, {"type": "secondary"})
        saved_metric = Experiment.objects.get(pk=exp_id).saved_metrics.first()
        assert saved_metric is not None
        self.assertEqual(saved_metric.id, saved_metric_id)
        self.assertEqual(
            saved_metric.query,
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageview"},
                "uuid": saved_metric_uuid,
            },
        )

        # Now try updating experiment with new saved metric
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Experiment saved metric 2",
                "description": "Test description 2",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageleave"},
                },
            },
        )

        saved_metric_2_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment saved metric 2")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "saved_metrics_ids": [
                    {"id": saved_metric_id, "metadata": {"type": "secondary"}},
                    {"id": saved_metric_2_id, "metadata": {"type": "tertiary"}},
                ]
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 2)
        experiment_to_saved_metrics = list(Experiment.objects.get(pk=exp_id).experimenttosavedmetric_set.all())
        self.assertEqual(experiment_to_saved_metrics[0].metadata, {"type": "secondary"})
        self.assertEqual(experiment_to_saved_metrics[1].metadata, {"type": "tertiary"})
        saved_metrics = list(Experiment.objects.get(pk=exp_id).saved_metrics.all())
        self.assertEqual(sorted([saved_metrics[0].id, saved_metrics[1].id]), [saved_metric_id, saved_metric_2_id])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"saved_metrics_ids": []},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 0)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "saved_metrics_ids": [
                    {"id": saved_metric_id, "metadata": {"type": "secondary"}},
                ]
            },
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {"saved_metrics_ids": None},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 0)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "saved_metrics_ids": [
                    {"id": saved_metric_id, "metadata": {"type": "secondary"}},
                ]
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 1)

        # not updating saved metrics shouldn't change anything
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "name": "Test Experiment 2",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 1)

        # now delete saved metric
        response = self.client.delete(f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # make sure experiment in question was updated as well
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 0)

    def test_validate_saved_metrics_payload(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
        )

        saved_metric_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Generate experiment to have saved metric
        ff_key = "a-b-tests"
        exp_data = {
            "name": "Test Experiment",
            "description": "",
            "start_date": "2021-12-01T10:23",
            "end_date": None,
            "feature_flag_key": ff_key,
            "parameters": None,
            "filters": {
                "events": [
                    {"order": 0, "id": "$pageview"},
                    {"order": 1, "id": "$pageleave"},
                ],
                "properties": [],
            },
        }
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"xxx": "secondary"}}],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(
            response.json()["detail"],
            "Metadata must have a type key",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": [{"saved_metric": saved_metric_id}],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(response.json()["detail"], "Saved metric must have an id")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": [{"id": 12345678}],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(response.json()["detail"], "Saved metric does not exist or does not belong to this project")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": {"id": saved_metric_id},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(response.json()["detail"], 'Expected a list of items but got type "dict".')

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": [[saved_metric_id]],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(response.json()["detail"], "Saved metric must be an object")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                **exp_data,
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": "secondary"}],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(response.json()["detail"], "Metadata must be an object")

    @freeze_time("2025-02-10T13:00:00Z")
    def test_fetching_experiment_with_stale_metric_dates_applies_experiment_date_range(self):
        test_feature_flag = FeatureFlag.objects.create(
            name=f"Test experiment flag",
            key="test-flag",
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "test",
                            "name": "Test",
                            "rollout_percentage": 50,
                        },
                    ]
                },
            },
            created_by=self.user,
        )
        funnel_query = {
            "kind": "ExperimentFunnelsQuery",
            "funnels_query": {
                "kind": "FunnelsQuery",
                "series": [
                    {"kind": "EventsNode", "name": "[jan-16-running] seen", "event": "[jan-16-running] seen"},
                    {"kind": "EventsNode", "name": "[jan-16-running] payment", "event": "[jan-16-running] payment"},
                ],
                "dateRange": {"date_to": "2025-02-13T23:59", "date_from": "2025-01-30T12:16", "explicitDate": True},
                "funnelsFilter": {
                    "layout": "horizontal",
                    "funnelVizType": "steps",
                    "funnelWindowInterval": 14,
                    "funnelWindowIntervalUnit": "day",
                },
                "filterTestAccounts": True,
            },
        }
        trends_query = {
            "kind": "ExperimentTrendsQuery",
            "count_query": {
                "kind": "TrendsQuery",
                "series": [
                    {
                        "kind": "EventsNode",
                        "math": "total",
                        "name": "[jan-16-running] event one",
                        "event": "[jan-16-running] event one",
                    }
                ],
                "interval": "day",
                "dateRange": {"date_to": "2025-01-16T23:59", "date_from": "2025-01-02T13:54", "explicitDate": True},
                "trendsFilter": {"display": "ActionsLineGraph"},
                "filterTestAccounts": True,
            },
        }
        saved_trends_metric = ExperimentSavedMetric.objects.create(
            name="Test saved metric",
            description="Test description",
            query=trends_query,
            team=self.team,
            created_by=self.user,
        )
        saved_funnel_metric = ExperimentSavedMetric.objects.create(
            name="Test saved metric",
            description="Test description",
            query=funnel_query,
            team=self.team,
            created_by=self.user,
        )
        experiment = Experiment.objects.create(
            name="Test Experiment with stale dates",
            team=self.team,
            feature_flag=test_feature_flag,
            start_date=datetime(2025, 2, 1),
            end_date=None,
            metrics=[funnel_query],
            metrics_secondary=[trends_query],
        )

        for saved_metric_data in [saved_funnel_metric, saved_trends_metric]:
            saved_metric_serializer = ExperimentToSavedMetricSerializer(
                data={
                    "experiment": experiment.id,
                    "saved_metric": saved_metric_data.id,
                    "metadata": {"type": "secondary"},
                },
            )
            saved_metric_serializer.is_valid(raise_exception=True)
            saved_metric_serializer.save()

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["metrics"][0]["funnels_query"]["dateRange"]["date_from"], "2025-02-01T00:00:00Z"
        )
        self.assertEqual(response.json()["metrics"][0]["funnels_query"]["dateRange"]["date_to"], "")
        self.assertEqual(
            response.json()["metrics_secondary"][0]["count_query"]["dateRange"]["date_from"], "2025-02-01T00:00:00Z"
        )
        self.assertEqual(response.json()["metrics_secondary"][0]["count_query"]["dateRange"]["date_to"], "")
        self.assertEqual(
            response.json()["saved_metrics"][0]["query"]["funnels_query"]["dateRange"]["date_from"],
            "2025-02-01T00:00:00Z",
        )
        self.assertEqual(response.json()["saved_metrics"][0]["query"]["funnels_query"]["dateRange"]["date_to"], "")
        self.assertEqual(
            response.json()["saved_metrics"][1]["query"]["count_query"]["dateRange"]["date_from"],
            "2025-02-01T00:00:00Z",
        )
        self.assertEqual(response.json()["saved_metrics"][1]["query"]["count_query"]["dateRange"]["date_to"], "")

    def test_adding_behavioral_cohort_filter_to_experiment_fails(self):
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        },
                    ],
                }
            },
            name="cohort_behavioral",
        )
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        id = response.json()["id"]

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"filters": {"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["type"], "validation_error")
        self.assertEqual(
            response.json()["detail"],
            "Experiments do not support global filter properties",
        )

    def test_invalid_create(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": None,  # invalid
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "This field may not be null.")

    def test_rejects_metrics_with_dict_properties_on_create(self):
        dict_properties_metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {
                "kind": "EventsNode",
                "event": "$pageview",
                "properties": {
                    "$current_url": {
                        "value": "/start",
                        "operator": "icontains",
                    }
                },
            },
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Bad metrics experiment",
                "feature_flag_key": "bad-metrics-flag",
                "parameters": {},
                "filters": {},
                "metrics": [dict_properties_metric],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "metrics")

    def test_rejects_metrics_with_dict_properties_on_update(self):
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Good experiment",
                "feature_flag_key": "update-metrics-flag",
                "parameters": {},
                "filters": {},
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        experiment_id = create_response.json()["id"]

        dict_properties_metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {
                "kind": "EventsNode",
                "event": "$pageview",
                "properties": {
                    "$current_url": {
                        "value": "/start",
                        "operator": "icontains",
                    }
                },
            },
        }

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {"metrics": [dict_properties_metric]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "metrics")

    def test_rejects_metrics_with_invalid_kind(self):
        """Regression test: invalid metric kinds should be rejected, not silently skipped."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Invalid kind experiment",
                "feature_flag_key": "invalid-kind-flag",
                "parameters": {},
                "filters": {},
                "metrics": [{"kind": "ExperimentEventMetric", "event": "test"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "metrics")

    def test_accepts_metrics_with_array_properties(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Good metrics experiment",
                "feature_flag_key": "good-metrics-flag",
                "parameters": {},
                "filters": {},
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "properties": [
                                {
                                    "key": "$current_url",
                                    "value": "/start",
                                    "operator": "icontains",
                                    "type": "event",
                                }
                            ],
                        },
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_experiment_date_validation(self):
        ff_key = "a-b-tests"

        # Test 1: End date same as start date
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2024-02-10T00:00:00Z",
                "end_date": "2024-02-10T00:00:00Z",
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "End date must be after start date")

        # Test 2: End date before start date
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2024-02-10T00:00:00Z",
                "end_date": "2024-02-09T00:00:00Z",
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "End date must be after start date")

        # Test 3: Valid dates
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2024-02-10T00:00:00Z",
                "end_date": "2024-02-11T00:00:00Z",
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["start_date"], "2024-02-10T00:00:00Z")
        self.assertEqual(response.json()["end_date"], "2024-02-11T00:00:00Z")

        # Test 4: Update with invalid dates
        experiment_id = response.json()["id"]
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {
                "start_date": "2024-02-15T00:00:00Z",
                "end_date": "2024-02-14T00:00:00Z",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "End date must be after start date")

        # Test 5: Only start date provided (should be valid)
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2024-02-10T00:00:00Z",
                "end_date": None,
                "feature_flag_key": ff_key + "_2",
                "parameters": {},
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["start_date"], "2024-02-10T00:00:00Z")
        self.assertIsNone(response.json()["end_date"])

        # Test 6: Only end date provided (should be valid)
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": "2024-02-11T00:00:00Z",
                "feature_flag_key": ff_key + "_3",
                "parameters": {},
                "filters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.json()["start_date"])
        self.assertEqual(response.json()["end_date"], "2024-02-11T00:00:00Z")

    def test_invalid_update(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {},
                "feature_flag_key": "new_key",
            },  # invalid
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Can't update keys: get_feature_flag_key on Experiment",
        )

    def test_draft_experiment_doesnt_have_FF_active(self):
        # Draft experiment
        ff_key = "a-b-tests"
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

    def test_draft_experiment_doesnt_have_FF_active_even_after_updates(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [{"id": "$pageview"}],
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)  # didn't change to enabled while still draft

        # Now launch experiment
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"start_date": "2021-12-01T10:23"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertTrue(created_ff.active)

    def test_launching_draft_experiment_activates_FF(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": [{"id": "$pageview"}]},
            },
        )

        id = response.json()["id"]
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "start_date": "2021-12-01T10:23"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        updated_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertTrue(updated_ff.active)

    def test_draft_experiment_update_doesnt_delete_ff_payloads(self):
        # Draft experiment
        ff_key = "a-b-tests-with-flag-payloads"
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )
        id = create_response.json()["id"]

        created_ff = FeatureFlag.objects.get(key=ff_key)
        # Update feature flag payloads
        created_ff.filters["payloads"] = {"test": '"test-payload"', "control": '"control-payload"'}
        created_ff.save()

        # Update parameters on experiment
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Update parameters",
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "special",
                            "name": "Special Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
            },
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        updated_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(updated_ff.filters["payloads"], {"test": '"test-payload"', "control": '"control-payload"'})

    def test_create_multivariate_experiment_can_update_variants_in_draft(self):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, False)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test_1")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["key"], "test_2")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])

        id = response.json()["id"]

        experiment = Experiment.objects.get(id=response.json()["id"])
        self.assertTrue(experiment.is_draft)
        # Now try updating FF
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 24,
                        },
                        {
                            "key": "test_3",
                            "name": "Test Variant",
                            "rollout_percentage": 10,
                        },
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, False)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][3]["key"], "test_3")

    def test_create_multivariate_experiment(self):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, True)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test_1")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["key"], "test_2")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])

        id = response.json()["id"]

        experiment = Experiment.objects.get(id=response.json()["id"])
        self.assertFalse(experiment.is_draft)

        def _patch_flag_variants(variants: list, extra: dict | None = None) -> Any:
            return self.client.patch(
                f"/api/projects/{self.team.id}/experiments/{id}",
                {
                    "description": "Bazinga",
                    "update_feature_flag_params": True,
                    "feature_flag": {"filters": {"multivariate": {"variants": variants}}},
                    **(extra or {}),
                },
            )

        # Changing the variant count on a running experiment is rejected even with the opt-in.
        response = _patch_flag_variants(
            [
                {"key": "control", "name": "X", "rollout_percentage": 50},
                {"key": "test", "name": "Y", "rollout_percentage": 50},
            ]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Can't update feature_flag_variants on Experiment")

        # Changing only the rollout percentages of the same variants is allowed with the opt-in.
        response = _patch_flag_variants(
            [
                {"key": "control", "name": "Control Group", "rollout_percentage": 35},
                {"key": "test_1", "name": "Test Variant", "rollout_percentage": 33},
                {"key": "test_2", "name": "Test Variant", "rollout_percentage": 32},
            ],
            extra={"description": "Bazinga 222"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["description"], "Bazinga 222")
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.active, True)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["rollout_percentage"], 35)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["rollout_percentage"], 33)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["rollout_percentage"], 32)

        # Renaming variant keys on a running experiment is rejected even with the opt-in.
        response = _patch_flag_variants(
            [
                {"key": "control", "name": "Control Group", "rollout_percentage": 33},
                {"key": "test", "name": "Test Variant", "rollout_percentage": 33},
                {"key": "test2", "name": "Test Variant", "rollout_percentage": 34},
            ]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Can't update feature_flag_variants on Experiment")

        # Non-flag parameter keys update independently of the flag.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "parameters": {"recommended_sample_size": 1500}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["parameters"]["recommended_sample_size"], 1500)

    def test_parameters_feature_flag_config_is_sourced_from_the_flag(self):
        """The `parameters` projection sources feature-flag config (variants, rollout percentage,
        aggregation group type) from the linked flag, not the stored `parameters` column. This is
        what lets us stop persisting the mirror — a stale column must never surface in the response.
        """
        ff_key = "ff-config-from-flag"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Source of truth",
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                        {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                    ],
                    "rollout_percentage": 100,
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Make the flag (the source of truth) diverge from the stored mirror: new rollouts,
        # an aggregation group type, and a 20% overall rollout.
        flag = FeatureFlag.objects.get(key=ff_key, team_id=self.team.id)
        flag.filters = {
            "groups": [{"properties": [], "rollout_percentage": 20}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control Group", "rollout_percentage": 60},
                    {"key": "test", "name": "Test Variant", "rollout_percentage": 40},
                ]
            },
            "aggregation_group_type_index": 1,
        }
        flag.save()

        # Leave a deliberately stale mirror in the column — what the reverse-sync used to keep
        # fresh. The projection must ignore it entirely and read from the flag.
        experiment = Experiment.objects.get(id=experiment_id)
        experiment.parameters = {
            **(experiment.parameters or {}),
            "feature_flag_variants": [{"key": "stale", "rollout_percentage": 99}],
            "rollout_percentage": 100,
            "aggregation_group_type_index": None,
        }
        experiment.save()

        expected_variants = [
            {"key": "control", "name": "Control Group", "rollout_percentage": 60, "split_percent": 60},
            {"key": "test", "name": "Test Variant", "rollout_percentage": 40, "split_percent": 40},
        ]

        # Detail endpoint (ExperimentSerializer)
        detail_parameters = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}").json()[
            "parameters"
        ]
        self.assertEqual(detail_parameters["feature_flag_variants"], expected_variants)
        self.assertEqual(detail_parameters["rollout_percentage"], 20)
        self.assertEqual(detail_parameters["aggregation_group_type_index"], 1)

        # List endpoint (ExperimentBasicSerializer shares the same projection)
        results = self.client.get(f"/api/projects/{self.team.id}/experiments/").json()["results"]
        list_parameters = next(e["parameters"] for e in results if e["id"] == experiment_id)
        self.assertEqual(list_parameters["feature_flag_variants"], expected_variants)
        self.assertEqual(list_parameters["aggregation_group_type_index"], 1)

    def test_feature_flag_config_is_not_persisted_into_parameters(self):
        """Create and update consume feature-flag config to build/sync the flag, but never store it
        in the deprecated `parameters` column. Non-flag keys (e.g. variant_notes) are preserved.
        """
        ff_key = "ff-config-not-stored"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "No mirror",
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ],
                    "rollout_percentage": 100,
                    "variant_notes": {"control": "baseline"},
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        experiment = Experiment.objects.get(id=experiment_id)
        assert experiment.parameters is not None
        self.assertNotIn("feature_flag_variants", experiment.parameters)
        self.assertNotIn("rollout_percentage", experiment.parameters)
        self.assertEqual(experiment.parameters["variant_notes"], {"control": "baseline"})
        flag = FeatureFlag.objects.get(key=ff_key, team_id=self.team.id)
        self.assertEqual([v["key"] for v in flag.variants], ["control", "test"])

        # A draft update that re-sends the full parameters blob also strips the flag config and
        # keeps the non-flag keys.
        self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ],
                    "variant_notes": {"control": "still baseline"},
                },
            },
        )
        experiment.refresh_from_db()
        assert experiment.parameters is not None
        self.assertNotIn("feature_flag_variants", experiment.parameters)
        self.assertEqual(experiment.parameters["variant_notes"], {"control": "still baseline"})

    def test_create_experiment_with_feature_flag_config_object(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF object create",
                "feature_flag_key": "ff-object-create",
                "feature_flag": {
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "name": "Control", "rollout_percentage": 50},
                                {"key": "test", "name": "Test", "rollout_percentage": 50},
                            ]
                        },
                        "groups": [{"properties": [], "rollout_percentage": 80}],
                    },
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())

        flag = FeatureFlag.objects.get(key="ff-object-create", team_id=self.team.id)
        self.assertEqual([v["key"] for v in flag.variants], ["control", "test"])
        self.assertEqual(flag.filters["groups"][0]["rollout_percentage"], 80)

        experiment = Experiment.objects.get(id=response.json()["id"])
        self.assertNotIn("feature_flag_variants", experiment.parameters or {})
        self.assertEqual(
            [v["key"] for v in response.json()["parameters"]["feature_flag_variants"]],
            ["control", "test"],
        )

    def test_update_draft_experiment_with_feature_flag_config_object(self):
        create = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF object update",
                "feature_flag_key": "ff-object-update",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ],
                    "minimum_detectable_effect": 30,
                },
            },
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.json())
        experiment_id = create.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {
                "feature_flag": {
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 34},
                                {"key": "test", "rollout_percentage": 33},
                                {"key": "test_2", "rollout_percentage": 33},
                            ]
                        }
                    }
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        flag = FeatureFlag.objects.get(key="ff-object-update", team_id=self.team.id)
        self.assertEqual([v["key"] for v in flag.variants], ["control", "test", "test_2"])

        # A feature_flag-only PATCH must not clobber unrelated parameters.
        experiment = Experiment.objects.get(id=experiment_id)
        self.assertEqual((experiment.parameters or {})["minimum_detectable_effect"], 30)

    def test_echoed_feature_flag_object_is_ignored_on_round_trip(self):
        create = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF echo",
                "feature_flag_key": "ff-echo",
                "feature_flag": {
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 50},
                                {"key": "test", "rollout_percentage": 50},
                            ]
                        }
                    }
                },
            },
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.json())
        experiment_id = create.json()["id"]

        # Read-modify-write client: the frontend spreads the whole GET response into the save,
        # including the serialized read-only flag (which carries `id`). That echo carries no write
        # intent and must be ignored rather than reapplied.
        echoed_flag = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}").json()[
            "feature_flag"
        ]
        self.assertIn("id", echoed_flag)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"description": "unrelated edit", "feature_flag": echoed_flag},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        flag = FeatureFlag.objects.get(key="ff-echo", team_id=self.team.id)
        self.assertEqual([v["rollout_percentage"] for v in flag.variants], [50, 50])

        # A genuine edit through a config-only object (no `id`) is applied.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {
                "feature_flag": {
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 60},
                                {"key": "test", "rollout_percentage": 40},
                            ]
                        }
                    }
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        flag.refresh_from_db()
        self.assertEqual([v["rollout_percentage"] for v in flag.variants], [60, 40])

    def test_partial_feature_flag_object_preserves_omitted_flag_config(self):
        create = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF partial",
                "feature_flag_key": "ff-partial",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "rollout_percentage": 34},
                        {"key": "red", "rollout_percentage": 33},
                        {"key": "blue", "rollout_percentage": 33},
                    ],
                    "aggregation_group_type_index": 1,
                },
            },
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.json())
        experiment_id = create.json()["id"]
        flag = FeatureFlag.objects.get(key="ff-partial", team_id=self.team.id)
        self.assertEqual(flag.filters["aggregation_group_type_index"], 1)

        # A rollout-only config object must not reset the flag's variants to defaults or clear
        # its aggregation group type — omitted config keeps the flag's current state.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"feature_flag": {"filters": {"groups": [{"properties": [], "rollout_percentage": 30}]}}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        flag.refresh_from_db()
        self.assertEqual([v["key"] for v in flag.variants], ["control", "red", "blue"])
        self.assertEqual(flag.filters["aggregation_group_type_index"], 1)
        self.assertEqual(flag.filters["groups"][0]["rollout_percentage"], 30)

    @parameterized.expand(
        [
            ("filters_not_object", {"filters": "oops"}),
            ("multivariate_not_object", {"filters": {"multivariate": [1]}}),
            ("group_not_object", {"filters": {"groups": ["x"]}}),
            (
                "group_properties_unsupported",
                {"filters": {"groups": [{"properties": [{"key": "email", "value": "a"}], "rollout_percentage": 50}]}},
            ),
            (
                "multiple_groups_unsupported",
                {"filters": {"groups": [{"rollout_percentage": 50}, {"rollout_percentage": 100}]}},
            ),
            (
                "unknown_group_key",
                {"filters": {"groups": [{"properties": [], "rollout_percentage": 50, "variant": "test"}]}},
            ),
            (
                "unknown_top_level_key",
                {"active": False, "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]}},
            ),
            ("unknown_filters_key", {"filters": {"super_groups": []}}),
        ]
    )
    def test_invalid_feature_flag_object_returns_400(self, _name, feature_flag_input):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {"name": "FF invalid", "feature_flag_key": "ff-invalid", "feature_flag": feature_flag_input},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertFalse(FeatureFlag.objects.filter(key="ff-invalid", team_id=self.team.id).exists())

    def test_feature_flag_object_normalizes_control_variant_key(self):
        # Same normalization as the legacy parameters path — LLM/MCP payloads often send 'Control'.
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF control case",
                "feature_flag_key": "ff-control-case",
                "feature_flag": {
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "Control", "rollout_percentage": 50},
                                {"key": "test", "rollout_percentage": 50},
                            ]
                        }
                    }
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        flag = FeatureFlag.objects.get(key="ff-control-case", team_id=self.team.id)
        self.assertEqual([v["key"] for v in flag.variants], ["control", "test"])

    def test_feature_flag_object_on_running_experiment_requires_opt_in(self):
        create = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF running",
                "feature_flag_key": "ff-running",
                "start_date": "2021-12-01T10:23",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.json())
        experiment_id = create.json()["id"]
        new_variants_input = {
            "feature_flag": {
                "filters": {
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 60},
                            {"key": "test", "rollout_percentage": 40},
                        ]
                    }
                }
            }
        }

        # Without the opt-in the service would sync nothing — reject loudly instead.
        response = self.client.patch(f"/api/projects/{self.team.id}/experiments/{experiment_id}", new_variants_input)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("update_feature_flag_params", str(response.json()))
        flag = FeatureFlag.objects.get(key="ff-running", team_id=self.team.id)
        self.assertEqual([v["rollout_percentage"] for v in flag.variants], [50, 50])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {**new_variants_input, "update_feature_flag_params": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        flag.refresh_from_db()
        self.assertEqual([v["rollout_percentage"] for v in flag.variants], [60, 40])

    def test_feature_flag_object_payloads_and_continuity_live_on_the_flag(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF payloads",
                "feature_flag_key": "ff-payloads",
                "feature_flag": {
                    "ensure_experience_continuity": True,
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 50},
                                {"key": "test", "rollout_percentage": 50},
                            ]
                        },
                        "payloads": {"test": '"v1"'},
                    },
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        experiment_id = response.json()["id"]

        flag = FeatureFlag.objects.get(key="ff-payloads", team_id=self.team.id)
        self.assertEqual(flag.filters["payloads"], {"test": '"v1"'})
        self.assertTrue(flag.ensure_experience_continuity)
        experiment = Experiment.objects.get(id=experiment_id)
        self.assertNotIn("feature_flag_payloads", experiment.parameters or {})
        self.assertNotIn("ensure_experience_continuity", experiment.parameters or {})

        # A draft update through the object syncs payloads to the flag too.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"feature_flag": {"filters": {"payloads": {"test": '"v2"'}}}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        flag.refresh_from_db()
        self.assertEqual(flag.filters["payloads"], {"test": '"v2"'})
        self.assertEqual([v["key"] for v in flag.variants], ["control", "test"])

    def test_duplicate_experiment_carries_flag_payloads_and_continuity(self):
        create = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF clone source",
                "feature_flag_key": "ff-clone-src",
                "feature_flag": {
                    "ensure_experience_continuity": True,
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 50},
                                {"key": "test", "rollout_percentage": 50},
                            ]
                        },
                        "payloads": {"test": '"v1"'},
                    },
                },
            },
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.json())

        # The stored column carries no flag config, so the duplicate's new flag must inherit
        # payloads and continuity from the source flag, not lose them.
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{create.json()['id']}/duplicate",
            {"feature_flag_key": "ff-clone-dst"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        new_flag = FeatureFlag.objects.get(key="ff-clone-dst", team_id=self.team.id)
        self.assertEqual(new_flag.filters["payloads"], {"test": '"v1"'})
        self.assertTrue(new_flag.ensure_experience_continuity)

    def test_stale_persisted_flag_config_is_not_echoed_back_onto_the_flag(self):
        create = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF stale echo",
                "feature_flag_key": "ff-stale-echo",
                "feature_flag": {
                    "ensure_experience_continuity": True,
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 50},
                                {"key": "test", "rollout_percentage": 50},
                            ]
                        },
                        "payloads": {"test": '"live"'},
                    },
                },
            },
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.json())
        experiment_id = create.json()["id"]

        # Legacy rows still carry flag config in the column until the backfill strips it.
        Experiment.objects.filter(id=experiment_id).update(
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 90},
                    {"key": "test", "rollout_percentage": 10},
                ],
                "feature_flag_payloads": {"test": '"stale"'},
                "ensure_experience_continuity": False,
            }
        )

        # Reads must project the flag's live config so a read-modify-write client echoes live
        # values — not the stale column — into its next save.
        get_parameters = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}").json()[
            "parameters"
        ]
        self.assertEqual(get_parameters["feature_flag_payloads"], {"test": '"live"'})
        self.assertTrue(get_parameters["ensure_experience_continuity"])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"name": "FF stale echo renamed", "parameters": get_parameters},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        flag = FeatureFlag.objects.get(key="ff-stale-echo", team_id=self.team.id)
        self.assertEqual(flag.filters["payloads"], {"test": '"live"'})
        self.assertTrue(flag.ensure_experience_continuity)
        self.assertEqual([v["rollout_percentage"] for v in flag.variants], [50, 50])

    def test_partial_feature_flag_object_ignores_stale_column_config(self):
        create = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF stale column",
                "feature_flag_key": "ff-stale-column",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.json())
        experiment_id = create.json()["id"]

        # Legacy rows still carry stale flag config in the column until the backfill strips it;
        # patch semantics must backfill omitted config from the flag's live state, not the column.
        Experiment.objects.filter(id=experiment_id).update(
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 90},
                    {"key": "stale", "rollout_percentage": 10},
                ],
                "rollout_percentage": 5,
            }
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"feature_flag": {"filters": {"payloads": {"test": '"v1"'}}}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        flag = FeatureFlag.objects.get(key="ff-stale-column", team_id=self.team.id)
        self.assertEqual(flag.filters["payloads"], {"test": '"v1"'})
        self.assertEqual([v["key"] for v in flag.variants], ["control", "test"])
        self.assertEqual(flag.filters["groups"][0]["rollout_percentage"], 100)

    def test_feature_flag_object_with_null_id_is_write_intent(self):
        # Typed clients may serialize an optional id as null; only a non-null id marks an echo.
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF null id",
                "feature_flag_key": "ff-null-id",
                "feature_flag": {
                    "id": None,
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 34},
                                {"key": "test_a", "rollout_percentage": 33},
                                {"key": "test_b", "rollout_percentage": 33},
                            ]
                        }
                    },
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        flag = FeatureFlag.objects.get(key="ff-null-id", team_id=self.team.id)
        self.assertEqual([v["key"] for v in flag.variants], ["control", "test_a", "test_b"])

    def test_create_with_existing_flag_and_feature_flag_config_returns_400(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="ff-preexisting",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        # The service links an existing flag as-is, so explicit config would be silently dropped.
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF preexisting",
                "feature_flag_key": "ff-preexisting",
                "feature_flag": {
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 60},
                                {"key": "test", "rollout_percentage": 40},
                            ]
                        }
                    }
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already exists", str(response.json()))

    def test_config_free_feature_flag_stub_is_ignored(self):
        create = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF stub",
                "feature_flag_key": "ff-stub",
                "start_date": "2021-12-01T10:23",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.json())

        # An object with no config keys carries no write intent — clients that include such stubs
        # in write bodies must keep working, even on running experiments.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{create.json()['id']}",
            {"name": "FF stub renamed", "feature_flag": {"key": "ff-stub", "active": True}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["name"], "FF stub renamed")

    def test_duplicate_experiment_with_null_flag_continuity_stays_off(self):
        create = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "FF null continuity",
                "feature_flag_key": "ff-null-continuity",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.json())
        FeatureFlag.objects.filter(key="ff-null-continuity", team_id=self.team.id).update(
            ensure_experience_continuity=None
        )
        # A NULL continuity behaves as off; the clone must not pick up the team default instead.
        self.team.flags_persistence_default = True
        self.team.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{create.json()['id']}/duplicate",
            {"feature_flag_key": "ff-null-continuity-copy"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        new_flag = FeatureFlag.objects.get(key="ff-null-continuity-copy", team_id=self.team.id)
        self.assertFalse(new_flag.ensure_experience_continuity)

    def test_experiment_response_includes_feature_flag(self):
        """Test that experiment responses include the feature_flag field correctly serialized."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Feature Flag Test",
                "feature_flag_key": "test-flag-serialization",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify feature_flag is included and properly serialized
        response_data = response.json()
        self.assertIn("feature_flag", response_data)
        self.assertIsNotNone(response_data["feature_flag"])
        self.assertEqual(response_data["feature_flag"]["key"], "test-flag-serialization")
        self.assertIn("id", response_data["feature_flag"])
        self.assertIn("active", response_data["feature_flag"])

        # Also test GET to ensure serialization works for retrieval too
        experiment_id = response_data["id"]
        get_response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}")
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)

        get_data = get_response.json()
        self.assertIn("feature_flag", get_data)
        self.assertIsNotNone(get_data["feature_flag"])
        self.assertEqual(get_data["feature_flag"]["key"], "test-flag-serialization")

    def test_creating_invalid_multivariate_experiment_no_control(self):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        # no control
                        {
                            "key": "test_0",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        detail = response.json()["detail"]
        self.assertIn("must contain a variant with key 'control'", detail)
        self.assertIn("'test_0'", detail)
        self.assertIn("'test_1'", detail)
        self.assertIn("'test_2'", detail)

    @parameterized.expand(
        [
            ("Control",),
            ("CONTROL",),
            ("cOnTrOl",),
        ]
    )
    def test_creating_experiment_normalizes_capitalized_control_key(self, control_key: str):
        # LLM callers often emit `Control` or `CONTROL` from natural-language input.
        # The serializer should rewrite it to lowercase `control` instead of rejecting,
        # since intent is unambiguous and the runtime treats `control` as a reserved key.
        ff_key = f"case-insensitive-{control_key.lower()}-{control_key}"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": f"Capitalized control {control_key}",
                "description": "",
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": control_key, "name": "Control", "split_percent": 50},
                        {"key": "test", "name": "Test", "split_percent": 50},
                    ]
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        variants = response.json()["parameters"]["feature_flag_variants"]
        self.assertEqual([v["key"] for v in variants], ["control", "test"])
        # The persisted flag should also use lowercase `control`.
        flag = FeatureFlag.objects.get(key=ff_key)
        flag_keys = [v["key"] for v in flag.filters["multivariate"]["variants"]]
        self.assertEqual(flag_keys, ["control", "test"])

    def test_creating_experiment_does_not_collapse_when_control_already_present(self):
        # If both `control` and `Control` are passed, normalization must NOT run —
        # otherwise it would rewrite `Control` → `control` and produce two duplicate
        # entries. The downstream FeatureFlagSerializer may then accept (variants
        # preserved) or reject (duplicate-key error) — both prove the normalization
        # path was skipped. The signal we actively check against: the response must
        # not be the missing-control error, since that would only fire if our
        # rewrite logic got confused.
        ff_key = "control-and-capital-control"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Both controls",
                "description": "",
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "lowercase", "split_percent": 50},
                        {"key": "Control", "name": "Capitalized", "split_percent": 50},
                    ]
                },
            },
            format="json",
        )

        # Must land on a deterministic outcome — not silently bypass.
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])
        if response.status_code == status.HTTP_201_CREATED:
            variants = response.json()["parameters"]["feature_flag_variants"]
            self.assertEqual([v["key"] for v in variants], ["control", "Control"])
        else:
            # 400 path: the error must NOT be the missing-control message,
            # which would only fire if normalization had wrongly rewritten things.
            detail = str(response.json())
            self.assertNotIn("must contain a variant with key 'control'", detail)

    def test_creating_updating_experiment_with_group_aggregation(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    "aggregation_group_type_index": 1,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertTrue(created_ff.filters["aggregation_group_type_index"] is None)

        id = response.json()["id"]

        # Now update group type index on filter
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    "aggregation_group_type_index": 0,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertTrue(created_ff.filters["aggregation_group_type_index"] is None)

        # Now remove group type index
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    # "aggregation_group_type_index": None, # removed key
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertTrue(created_ff.filters["aggregation_group_type_index"] is None)

    def test_creating_experiment_with_group_aggregation_parameter(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "aggregation_group_type_index": 0,
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertEqual(created_ff.filters["aggregation_group_type_index"], 0)

        id = response.json()["id"]

        # Now update group type index on filter
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                    "aggregation_group_type_index": 1,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertEqual(created_ff.filters["aggregation_group_type_index"], 0)

    def test_used_in_experiment_is_populated_correctly_for_feature_flag_list(self) -> None:
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_experiment = response.json()["id"]

        # add another random feature flag
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": f"flag",
                "key": f"flag_0",
                "filters": {"groups": [{"rollout_percentage": 5}]},
            },
            format="json",
        ).json()

        # TODO: Make sure permission bool doesn't cause n + 1
        # +1 query for survey internal flag IDs lookup
        with self.assertNumQueries(22):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            result = response.json()

            self.assertEqual(result["count"], 2)

            self.assertCountEqual(
                [(res["key"], res["experiment_set"]) for res in result["results"]],
                [("flag_0", []), (ff_key, [created_experiment])],
            )

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_create_experiment_updates_feature_flag_cache(self, mock_on_commit):
        cache.clear()

        initial_cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        self.assertIsNone(initial_cached_flags)

        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        # save was called, but no flags saved because experiment is in draft mode, so flag is not active
        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(0, len(cached_flags))

        id = response.json()["id"]

        # launch experiment
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "start_date": "2021-12-01T10:23",
            },
        )

        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))
        self.assertEqual(cached_flags[0].key, ff_key)
        self.assertEqual(
            cached_flags[0].filters,
            {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                        "aggregation_group_type_index": None,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ]
                },
                "holdout": None,
                "aggregation_group_type_index": None,
            },
        )

        # On a running experiment, a flag-config change without the opt-in is rejected and must not
        # touch the cached flag.
        unchanged_filters: dict[str, Any] = {
            "groups": [{"properties": [], "rollout_percentage": 100, "aggregation_group_type_index": None}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control Group", "rollout_percentage": 33},
                    {"key": "test_1", "name": "Test Variant", "rollout_percentage": 33},
                    {"key": "test_2", "name": "Test Variant", "rollout_percentage": 34},
                ]
            },
            "holdout": None,
            "aggregation_group_type_index": None,
        }
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "feature_flag": {
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "name": "X", "rollout_percentage": 50},
                                {"key": "test", "name": "Y", "rollout_percentage": 50},
                            ]
                        }
                    }
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("update_feature_flag_params", str(response.json()))

        cached_flags = get_feature_flags_for_team_in_cache(self.team.pk)
        assert cached_flags is not None
        self.assertEqual(1, len(cached_flags))
        self.assertEqual(cached_flags[0].key, ff_key)
        self.assertEqual(cached_flags[0].filters, unchanged_filters)

    def test_create_draft_experiment_with_filters(self) -> None:
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

    def test_create_launched_experiment_with_filters(self) -> None:
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

    def test_create_draft_experiment_without_filters(self) -> None:
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

    def test_create_experiment_inherits_team_default_only_count_matured_users(self):
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        config.default_only_count_matured_users = True
        config.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Team Default Matured",
                "feature_flag_key": "team-default-matured",
                "parameters": None,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.json()["only_count_matured_users"])

    def test_create_experiment_explicit_false_overrides_team_default_only_count_matured_users(self):
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        config.default_only_count_matured_users = True
        config.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Override Matured",
                "feature_flag_key": "override-matured",
                "parameters": None,
                "only_count_matured_users": False,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.json()["only_count_matured_users"])

    def test_create_experiment_with_feature_flag_missing_control(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Beta feature",
            key="beta-feature",
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "test-1", "rollout_percentage": 50},
                        {"key": "test-2", "rollout_percentage": 50},
                    ]
                }
            },
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Beta experiment",
                "feature_flag_key": feature_flag.key,
                "parameters": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Feature flag must have a variant with key 'control'")

    def test_create_experiment_with_feature_flag_insufficient_variants(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Single variant flag",
            key="single-variant-flag",
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 100},
                    ]
                }
            },
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Single variant experiment",
                "feature_flag_key": feature_flag.key,
                "parameters": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Feature flag must have at least 2 variants (control and at least one test variant)",
        )

    def test_create_experiment_with_parameters_insufficient_variants(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Single variant experiment",
                "feature_flag_key": "single-variant-key",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "rollout_percentage": 100},
                    ]
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Feature flag must have at least 2 variants (control and at least one test variant)",
        )

    def test_create_experiment_with_valid_existing_feature_flag(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Beta feature",
            key="beta-feature",
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                }
            },
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Beta experiment",
                "feature_flag_key": feature_flag.key,
                "parameters": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["feature_flag"]["id"], feature_flag.id)

    def test_create_multiple_experiments_with_same_feature_flag(self):
        # Create a feature flag with proper structure for experiments
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Shared feature flag",
            key="shared-feature-flag",
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                }
            },
            created_by=self.user,
        )

        # Create first experiment with this feature flag
        first_experiment_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "First experiment",
                "feature_flag_key": feature_flag.key,
                "parameters": {},
            },
        )

        self.assertEqual(first_experiment_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first_experiment_response.json()["feature_flag"]["id"], feature_flag.id)

        # Create second experiment with the same feature flag - this would have previously failed
        second_experiment_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Second experiment",
                "feature_flag_key": feature_flag.key,
                "parameters": {},
            },
        )

        # Assert that the second experiment is created successfully
        self.assertEqual(second_experiment_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_experiment_response.json()["feature_flag"]["id"], feature_flag.id)

        # Verify both experiments exist and point to the same feature flag
        first_experiment_id = first_experiment_response.json()["id"]
        second_experiment_id = second_experiment_response.json()["id"]

        # Ensure both experiments exist in the database
        first_experiment = Experiment.objects.get(id=first_experiment_id)
        second_experiment = Experiment.objects.get(id=second_experiment_id)

        # Verify both experiments use the same feature flag
        self.assertEqual(first_experiment.feature_flag_id, feature_flag.id)
        self.assertEqual(second_experiment.feature_flag_id, feature_flag.id)

    def test_feature_flag_and_experiment_sync(self):
        # Create an experiment with control and test variants
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "My test experiment",
                "feature_flag_key": "experiment-test-flag",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                        {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                    ]
                },
                "filters": {"insight": "TRENDS", "events": [{"order": 0, "id": "$pageview"}]},
            },
        )

        self.assertEqual(response.status_code, 201)
        experiment_id = response.json()["id"]
        feature_flag_id = response.json()["feature_flag"]["id"]

        # Fetch the FeatureFlag object
        feature_flag = FeatureFlag.objects.get(id=feature_flag_id)

        variants = feature_flag.filters["multivariate"]["variants"]

        # Verify that the variants are correctly populated
        self.assertEqual(len(variants), 2)

        self.assertEqual(variants[0]["key"], "control")
        self.assertEqual(variants[0]["name"], "Control Group")
        self.assertEqual(variants[0]["rollout_percentage"], 50)

        self.assertEqual(variants[1]["key"], "test")
        self.assertEqual(variants[1]["name"], "Test Variant")
        self.assertEqual(variants[1]["rollout_percentage"], 50)

        # Change the rollout percentages and groups of the feature flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag_id}",
            {
                "filters": {
                    "groups": [
                        {"properties": [], "rollout_percentage": 99},
                        {"properties": [], "rollout_percentage": 1},
                    ],
                    "payloads": {},
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 10},
                            {"key": "test", "rollout_percentage": 90},
                        ]
                    },
                    "aggregation_group_type_index": 1,
                }
            },
        )

        # The flag is the source of truth; the experiment API projects variants and aggregation
        # group type from it (no `parameters` mirror is persisted).
        parameters = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}").json()["parameters"]
        self.assertEqual(
            parameters["feature_flag_variants"],
            [
                {"key": "control", "rollout_percentage": 10, "split_percent": 10},
                {"key": "test", "rollout_percentage": 90, "split_percent": 90},
            ],
        )
        self.assertEqual(parameters["aggregation_group_type_index"], 1)

        # Update the experiment with an unrelated change
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"name": "Updated Test Experiment"},
        )

        # Verify that the feature flag variants and groups remain unchanged
        feature_flag = FeatureFlag.objects.get(id=feature_flag_id)
        self.assertEqual(
            feature_flag.filters["multivariate"]["variants"],
            [{"key": "control", "rollout_percentage": 10}, {"key": "test", "rollout_percentage": 90}],
        )
        self.assertEqual(
            feature_flag.filters["groups"],
            [
                {"properties": [], "rollout_percentage": 99, "aggregation_group_type_index": 1},
                {"properties": [], "rollout_percentage": 1, "aggregation_group_type_index": 1},
            ],
        )

        # Test removing aggregation_group_type_index
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag_id}",
            {
                "filters": {
                    "groups": [
                        {"properties": [], "rollout_percentage": 99},
                        {"properties": [], "rollout_percentage": 1},
                    ],
                    "payloads": {},
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 10},
                            {"key": "test", "rollout_percentage": 90},
                        ]
                    },
                }
            },
        )

        # With no aggregation_group_type_index on the flag, it is absent from the projection too.
        parameters = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}").json()["parameters"]
        self.assertNotIn("aggregation_group_type_index", parameters)

    def test_update_experiment_exposure_config_valid(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Test Feature Flag",
            key="test-feature-flag",
            filters={},
        )

        experiment = Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            description="My test experiment",
            feature_flag=feature_flag,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment.id}",
            {
                "exposure_criteria": {
                    "filterTestAccounts": True,
                    "exposure_config": {
                        "event": "$pageview",
                        "properties": [
                            {"key": "plan", "operator": "is_not", "value": "free", "type": "event"},
                        ],
                    },
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(id=experiment.id)
        assert experiment.exposure_criteria is not None
        exposure_criteria = cast(dict[str, Any], experiment.exposure_criteria)
        exposure_config = cast(dict[str, Any], exposure_criteria["exposure_config"])
        self.assertEqual(exposure_criteria["filterTestAccounts"], True)
        self.assertEqual(exposure_config["event"], "$pageview")
        self.assertEqual(
            exposure_config["properties"],
            [{"key": "plan", "operator": "is_not", "value": "free", "type": "event"}],
        )

    def test_update_experiment_exposure_config_invalid(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Test Feature Flag",
            key="test-feature-flag",
            filters={},
        )

        experiment = Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            description="My test experiment",
            feature_flag=feature_flag,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment.id}",
            {
                "exposure_criteria": {
                    "filterTestAccounts": True,
                    "exposure_config": {
                        # Invalid event and properties
                        "event": "",
                        "properties": [
                            1,
                        ],
                    },
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_experiment_exposure_config_with_action(self):
        # Create an action
        action = Action.objects.create(
            name="Test Action",
            team=self.team,
            steps_json=[{"event": "purchase", "properties": [{"key": "plan", "value": "premium", "type": "event"}]}],
        )

        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Test Feature Flag",
            key="test-feature-flag",
            filters={},
        )
        experiment = Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            description="My test experiment",
            feature_flag=feature_flag,
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment.id}",
            {
                "exposure_criteria": {
                    "filterTestAccounts": False,
                    "exposure_config": {
                        "kind": "ActionsNode",
                        "id": action.id,
                    },
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        experiment = Experiment.objects.get(id=experiment.id)
        assert experiment.exposure_criteria is not None
        self.assertEqual(experiment.exposure_criteria["filterTestAccounts"], False)
        self.assertEqual(experiment.exposure_criteria["exposure_config"]["kind"], "ActionsNode")
        self.assertEqual(experiment.exposure_criteria["exposure_config"]["id"], action.id)

    def test_create_experiment_in_specific_folder(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Folder Test Experiment",
                "description": "This experiment goes in a custom folder",
                "feature_flag_key": "folder-experiment",
                # ensure the experiment is in draft so it doesn't fail if user doesn't pass certain date fields
                "start_date": None,
                "filters": {"events": [], "properties": []},
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
                "_create_in_folder": "Special Folder/Experiments",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        experiment_id = response.json()["id"]
        self.assertTrue(Experiment.objects.filter(id=experiment_id).exists())

        ff_key = response.json()["feature_flag_key"]
        self.assertTrue(FeatureFlag.objects.filter(team=self.team, key=ff_key).exists())
        ff_id = FeatureFlag.objects.filter(team=self.team, key=ff_key).first().id

        from posthog.models.file_system.file_system import FileSystem

        fs_entry = FileSystem.objects.filter(team=self.team, ref=str(experiment_id), type="experiment").first()
        assert fs_entry is not None, "Expected a FileSystem entry for the newly created experiment."
        assert "Special Folder/Experiments" in fs_entry.path, (
            f"Expected path to contain 'Special Folder/Experiments', got {fs_entry.path}"
        )

        ff_entry = FileSystem.objects.filter(team=self.team, ref=str(ff_id), type="feature_flag").first()
        assert ff_entry is not None, "Expected a FileSystem entry for the newly created feature flag."
        assert "Special Folder/Experiments" in ff_entry.path, (
            f"Expected path to contain 'Special Folder/Experiments', got {ff_entry.path}"
        )

    def test_list_endpoint_excludes_deleted_experiments(self):
        """Test that list endpoint doesn't return soft-deleted experiments"""

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-flag",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
            format="json",
        )
        experiment_id = response.json()["id"]

        response2 = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Active Experiment",
                "feature_flag_key": "active-flag",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
            format="json",
        )
        active_experiment_id = response2.json()["id"]

        # Soft delete the first experiment
        self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {"deleted": True},
            format="json",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/")
        experiment_ids = [exp["id"] for exp in response.json()["results"]]

        # Should only contain the active experiment
        self.assertIn(active_experiment_id, experiment_ids)
        self.assertNotIn(experiment_id, experiment_ids)

    def test_detail_endpoint_returns_404_for_deleted_experiment(self):
        """Test that detail endpoint returns 404 for soft-deleted experiments"""

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-flag",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
            format="json",
        )
        experiment_id = response.json()["id"]

        # Soft delete the experiment
        self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {"deleted": True},
            format="json",
        )

        # Try to get the deleted experiment
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_restore_allows_payload_with_additional_fields(self):
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Restorable Experiment",
                "feature_flag_key": "restore-flag",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
            format="json",
        )
        experiment = create_response.json()

        self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/",
            {"deleted": True},
            format="json",
        )

        restore_payload = {"deleted": False, "name": experiment["name"]}
        restore_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/",
            restore_payload,
            format="json",
        )

        self.assertEqual(restore_response.status_code, status.HTTP_200_OK)
        self.assertFalse(restore_response.json()["deleted"])

    @parameterized.expand(
        [
            ("flag_deleted", True, status.HTTP_400_BAD_REQUEST),
            ("flag_alive", False, status.HTTP_200_OK),
        ]
    )
    def test_restore_with_flag_state(self, _name, delete_flag, expected_status):
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Restore Flag State Test",
                "feature_flag_key": f"restore-flag-state-{_name}",
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
            format="json",
        )
        experiment = create_response.json()
        feature_flag_id = experiment["feature_flag"]["id"]

        self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/",
            {"deleted": True},
            format="json",
        )

        if delete_flag:
            self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{feature_flag_id}/",
                {"deleted": True},
                format="json",
            )

        restore_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment['id']}/",
            {"deleted": False, "name": experiment["name"]},
            format="json",
        )

        self.assertEqual(restore_response.status_code, expected_status)
        if expected_status == status.HTTP_400_BAD_REQUEST:
            self.assertIn("linked feature flag has been deleted", restore_response.json()["detail"])
        else:
            self.assertFalse(restore_response.json()["deleted"])

    def test_create_experiment_with_missing_parameters(self):
        ff_key = "a-b-tests"

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": ff_key,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_duplicate_experiment(self) -> None:
        """Test that experiments can be duplicated with the same settings and metrics"""
        ff_key = "duplicate-test-flag"

        # Create original experiment
        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Original Experiment",
                "description": "Original description",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                        {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                    ]
                },
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
                "metrics_secondary": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$click"},
                    }
                ],
                "stats_config": {"method": "bayesian"},
                "exposure_criteria": {"filterTestAccounts": True},
            },
        )

        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        # Duplicate the experiment
        duplicate_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/duplicate/",
            {},
        )

        self.assertEqual(duplicate_response.status_code, status.HTTP_201_CREATED)
        duplicate_experiment = duplicate_response.json()

        # Verify duplicate has correct properties
        self.assertEqual(duplicate_experiment["name"], "Original Experiment (Copy)")
        self.assertEqual(duplicate_experiment["description"], original_experiment["description"])
        self.assertEqual(duplicate_experiment["type"], original_experiment["type"])
        self.assertEqual(duplicate_experiment["parameters"], original_experiment["parameters"])
        self.assertEqual(duplicate_experiment["filters"], original_experiment["filters"])

        # Compare metric content ignoring fingerprints (they differ due to different
        # start_dates) and uuids (regenerated by clone so the duplicate has its own
        # identity space — see _regenerate_all_metric_uuids).
        def strip_identity(metrics):
            return [{k: v for k, v in metric.items() if k not in ("fingerprint", "uuid")} for metric in metrics or []]

        self.assertEqual(
            strip_identity(duplicate_experiment["metrics"]), strip_identity(original_experiment["metrics"])
        )
        self.assertEqual(
            strip_identity(duplicate_experiment["metrics_secondary"]),
            strip_identity(original_experiment["metrics_secondary"]),
        )
        # Clone must regenerate every metric uuid.
        original_uuids = {m["uuid"] for m in original_experiment["metrics"] or []}
        duplicate_uuids = {m["uuid"] for m in duplicate_experiment["metrics"] or []}
        if original_uuids:
            self.assertTrue(original_uuids.isdisjoint(duplicate_uuids))

        self.assertEqual(duplicate_experiment["stats_config"], original_experiment["stats_config"])
        self.assertEqual(duplicate_experiment["exposure_criteria"], original_experiment["exposure_criteria"])

        # Verify feature flag is reused
        self.assertEqual(duplicate_experiment["feature_flag_key"], original_experiment["feature_flag_key"])

        # Verify reset fields
        self.assertIsNone(duplicate_experiment["start_date"])
        self.assertIsNone(duplicate_experiment["end_date"])
        self.assertFalse(duplicate_experiment["archived"])
        self.assertFalse(duplicate_experiment["deleted"])

        # Verify different IDs
        self.assertNotEqual(duplicate_experiment["id"], original_experiment["id"])

    def test_duplicate_experiment_name_conflict_resolution(self) -> None:
        """Test that duplicate experiment names are handled with incremental suffixes"""
        ff_key = "name-conflict-test-flag"

        # Create original experiment
        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Conflict Test",
                "feature_flag_key": ff_key,
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
            },
        )

        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        # Create first duplicate
        first_duplicate_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/duplicate/",
            {},
        )

        self.assertEqual(first_duplicate_response.status_code, status.HTTP_201_CREATED)
        first_duplicate = first_duplicate_response.json()
        self.assertEqual(first_duplicate["name"], "Conflict Test (Copy)")

        # Create second duplicate to test name conflict resolution
        second_duplicate_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/duplicate/",
            {},
        )

        self.assertEqual(second_duplicate_response.status_code, status.HTTP_201_CREATED)
        second_duplicate = second_duplicate_response.json()
        self.assertEqual(second_duplicate["name"], "Conflict Test (Copy) 1")

    def test_duplicate_experiment_with_custom_feature_flag(self) -> None:
        """Test that experiments can be duplicated with a different feature flag"""
        # Create original experiment
        original_ff_key = "original-flag"
        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Original Experiment",
                "description": "Original description",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": original_ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                        {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                    ]
                },
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
                "metrics_secondary": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$click"},
                    }
                ],
            },
        )

        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        # Create a new feature flag to use for the duplicate
        new_flag = FeatureFlag.objects.create(
            team=self.team,
            key="duplicate-test-flag",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        # Duplicate the experiment with a custom feature flag
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/duplicate",
            {"feature_flag_key": new_flag.key},
        )

        assert response.status_code == 201
        duplicate_data = response.json()

        # Verify the duplicate uses the new feature flag
        assert duplicate_data["feature_flag_key"] == "duplicate-test-flag"
        assert duplicate_data["feature_flag"]["key"] == "duplicate-test-flag"

        # Verify the duplicate has the same settings
        assert duplicate_data["description"] == original_experiment["description"]
        assert duplicate_data["filters"] == original_experiment["filters"]

        # feature_flag_variants should come from the new flag; other parameters should match the original
        # The API response includes split_percent alongside rollout_percentage
        expected_variants = [
            {**v, "split_percent": v["rollout_percentage"]} for v in new_flag.filters["multivariate"]["variants"]
        ]
        assert duplicate_data["parameters"]["feature_flag_variants"] == expected_variants
        assert {**duplicate_data["parameters"], "feature_flag_variants": None} == {
            **original_experiment["parameters"],
            "feature_flag_variants": None,
        }

        # Compare metric content ignoring fingerprints (they differ due to different
        # start_dates) and uuids (regenerated by clone).
        def strip_identity(metrics):
            return [{k: v for k, v in metric.items() if k not in ("fingerprint", "uuid")} for metric in metrics or []]

        assert strip_identity(duplicate_data["metrics"]) == strip_identity(original_experiment["metrics"])
        assert strip_identity(duplicate_data["metrics_secondary"]) == strip_identity(
            original_experiment["metrics_secondary"]
        )
        original_uuids = {m["uuid"] for m in original_experiment["metrics"] or []}
        duplicate_uuids = {m["uuid"] for m in duplicate_data["metrics"] or []}
        if original_uuids:
            assert original_uuids.isdisjoint(duplicate_uuids)

        # Verify temporal fields are reset
        assert duplicate_data["start_date"] is None
        assert duplicate_data["end_date"] is None
        assert duplicate_data["archived"] is False

    def test_duplicate_experiment_with_existing_flag_uses_new_flag_variants(self) -> None:
        """Test that duplicating with an existing feature flag uses that flag's variants, not the original's"""
        # Create original experiment with specific variants
        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Original Experiment",
                "feature_flag_key": "original-flag",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                        {"key": "original-variant", "name": "Original Variant", "rollout_percentage": 50},
                    ]
                },
            },
        )
        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        # Create a new feature flag with DIFFERENT variants
        new_flag_variants = [
            {"key": "control", "name": "Control", "rollout_percentage": 34},
            {"key": "new-variant-1", "name": "New Variant 1", "rollout_percentage": 33},
            {"key": "new-variant-2", "name": "New Variant 2", "rollout_percentage": 33},
        ]
        new_flag = FeatureFlag.objects.create(
            team=self.team,
            key="new-flag-with-different-variants",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {"variants": new_flag_variants},
            },
        )

        # Duplicate the experiment using the new feature flag
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/duplicate",
            {"feature_flag_key": new_flag.key},
        )

        assert response.status_code == 201
        duplicate_data = response.json()

        # The duplicate should use the NEW flag's variants, not the original's
        assert duplicate_data["feature_flag_key"] == "new-flag-with-different-variants"
        # The API response includes split_percent alongside rollout_percentage
        expected_variants = [{**v, "split_percent": v["rollout_percentage"]} for v in new_flag_variants]
        assert duplicate_data["parameters"]["feature_flag_variants"] == expected_variants

    def test_duplicate_experiment_rejects_blank_feature_flag_key(self) -> None:
        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Original Experiment",
                "feature_flag_key": "original-flag",
            },
        )
        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        duplicate_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/duplicate/",
            {"feature_flag_key": ""},
        )

        self.assertEqual(duplicate_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            Experiment.objects.filter(team=self.team, name="Original Experiment (Copy)", deleted=False).count(),
            0,
        )

    @parameterized.expand(
        [
            ("duplicate", "duplicate", False),
            ("copy_to_project", "copy_to_project", True),
        ]
    )
    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_clone_experiment_reports_creation_mode(
        self,
        _name: str,
        expected_mode: str,
        needs_target_team: bool,
        mock_report_user_action: MagicMock,
        _mock_on_commit: MagicMock,
    ) -> None:
        target_team = (
            Team.objects.create(organization=self.organization, name="Target Team") if needs_target_team else None
        )

        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {"name": "Original Experiment", "feature_flag_key": f"{expected_mode}-analytics-flag"},
        )
        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_id = original_response.json()["id"]
        mock_report_user_action.reset_mock()

        if target_team:
            url = f"/api/projects/{self.team.id}/experiments/{original_id}/copy_to_project/"
            body: dict = {"target_team_id": target_team.id}
            expected_team = target_team
        else:
            url = f"/api/projects/{self.team.id}/experiments/{original_id}/duplicate/"
            body = {}
            expected_team = self.team

        response = self.client.post(url, body)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        result = response.json()

        mock_report_user_action.assert_called_once_with(
            self.user,
            "experiment created",
            {
                "experiment_id": result["id"],
                "experiment_name": result["name"],
                "feature_flag_key": result["feature_flag_key"],
                "type": result["type"],
                "status": result["status"],
                "metrics_count": 0,
                "secondary_metrics_count": 0,
                "saved_metrics_count": 0,
                "has_description": False,
                "has_conclusion_comment": False,
                "variant_count": 2,
                "created_at": ANY,
                "creation_mode": expected_mode,
                "allow_unknown_events": True,
                "experiment_create_deprecated_fields": [],
            },
            team=expected_team,
            request=ANY,
        )

    def test_copy_experiment_to_project(self) -> None:
        target_team = Team.objects.create(organization=self.organization, name="Target Team")

        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Original Experiment",
                "description": "Original description",
                "feature_flag_key": "copy-test-flag",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                        {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                    ]
                },
                "filters": {"events": [{"order": 0, "id": "$pageview"}]},
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
                "metrics_secondary": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$click"},
                    }
                ],
                "stats_config": {"method": "bayesian"},
                "exposure_criteria": {"filterTestAccounts": True},
                "allow_unknown_events": True,
            },
        )
        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        copy_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/copy_to_project/",
            {"target_team_id": target_team.id},
        )
        self.assertEqual(copy_response.status_code, status.HTTP_201_CREATED)
        copied_experiment = copy_response.json()

        self.assertEqual(copied_experiment["name"], "Original Experiment (Copy)")
        self.assertEqual(copied_experiment["description"], original_experiment["description"])
        self.assertNotEqual(copied_experiment["id"], original_experiment["id"])
        self.assertIsNone(copied_experiment["start_date"])
        self.assertIsNone(copied_experiment["end_date"])

        # Compare metric content ignoring fingerprints and uuids (regenerated by clone).
        def strip_identity(metrics):
            return [{k: v for k, v in metric.items() if k not in ("fingerprint", "uuid")} for metric in metrics or []]

        self.assertEqual(strip_identity(copied_experiment["metrics"]), strip_identity(original_experiment["metrics"]))
        self.assertEqual(
            strip_identity(copied_experiment["metrics_secondary"]),
            strip_identity(original_experiment["metrics_secondary"]),
        )
        original_uuids = {m["uuid"] for m in original_experiment["metrics"] or []}
        copied_uuids = {m["uuid"] for m in copied_experiment["metrics"] or []}
        if original_uuids:
            self.assertTrue(original_uuids.isdisjoint(copied_uuids))

        self.assertEqual(copied_experiment["stats_config"], original_experiment["stats_config"])
        self.assertEqual(copied_experiment["exposure_criteria"], original_experiment["exposure_criteria"])

        # Verify experiment was created in the target team
        target_experiment = Experiment.objects.get(id=copied_experiment["id"])
        self.assertEqual(target_experiment.team_id, target_team.id)

    def test_copy_experiment_to_project_creates_disabled_flag(self) -> None:
        target_team = Team.objects.create(organization=self.organization, name="Target Team")

        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Flag Test Experiment",
                "feature_flag_key": "disabled-flag-test",
            },
        )
        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        copy_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/copy_to_project/",
            {"target_team_id": target_team.id},
        )
        self.assertEqual(copy_response.status_code, status.HTTP_201_CREATED)

        # The feature flag in the target team should be disabled (experiment is a draft)
        target_flag = FeatureFlag.objects.get(key="disabled-flag-test", team_id=target_team.id)
        self.assertFalse(target_flag.active)

    def test_copy_experiment_to_project_reuses_existing_flag(self) -> None:
        target_team = Team.objects.create(organization=self.organization, name="Target Team")

        # Pre-create a flag in the target team
        existing_flag = FeatureFlag.objects.create(
            team=target_team,
            key="existing-flag",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Reuse Flag Experiment",
                "feature_flag_key": "existing-flag",
            },
        )
        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        copy_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/copy_to_project/",
            {"target_team_id": target_team.id},
        )
        self.assertEqual(copy_response.status_code, status.HTTP_201_CREATED)
        copied_experiment = copy_response.json()

        # Should reuse the existing flag
        self.assertEqual(copied_experiment["feature_flag"]["id"], existing_flag.id)

    def test_copy_experiment_to_project_skips_saved_metrics_and_holdout(self) -> None:
        target_team = Team.objects.create(organization=self.organization, name="Target Team")

        holdout = ExperimentHoldout.objects.create(
            team=self.team,
            name="Test Holdout",
            filters=[{"properties": [], "rollout_percentage": 10, "variant": f"holdout-test"}],
        )

        saved_metric_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Saved Metric",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )
        self.assertEqual(saved_metric_response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = saved_metric_response.json()["id"]

        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Full Experiment",
                "feature_flag_key": "saved-metric-test",
                "holdout_id": holdout.id,
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "primary"}}],
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
                "allow_unknown_events": True,
            },
            format="json",
        )
        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        # Verify original has holdout and saved metrics
        self.assertEqual(original_experiment["holdout"]["id"], holdout.id)
        self.assertTrue(len(original_experiment["saved_metrics"]) > 0)

        copy_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/copy_to_project/",
            {"target_team_id": target_team.id},
        )
        self.assertEqual(copy_response.status_code, status.HTTP_201_CREATED)
        copied_experiment = copy_response.json()

        # Holdout and saved metrics should not be copied
        self.assertIsNone(copied_experiment["holdout"])
        self.assertEqual(len(copied_experiment["saved_metrics"]), 0)

    def test_copy_experiment_to_project_unauthorized_target(self) -> None:
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Auth Test Experiment",
                "feature_flag_key": "auth-test-flag",
            },
        )
        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        copy_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/copy_to_project/",
            {"target_team_id": other_team.id},
        )
        self.assertIn(copy_response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_copy_experiment_to_project_uses_selected_target_team(self) -> None:
        target_team = Team.objects.create(organization=self.organization, name="Target Team")
        secondary_target_team = Team.objects.create(
            organization=self.organization,
            project=target_team.project,
            name="Secondary Target Team",
        )

        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Environment selection experiment",
                "feature_flag_key": "environment-selection-flag",
            },
        )
        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        copy_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/copy_to_project/",
            {"target_team_id": secondary_target_team.id},
        )
        self.assertEqual(copy_response.status_code, status.HTTP_201_CREATED)

        copied_experiment = Experiment.objects.get(id=copy_response.json()["id"])
        self.assertEqual(copied_experiment.team_id, secondary_target_team.id)

    def test_copy_experiment_to_project_missing_target(self) -> None:
        original_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Missing Target Experiment",
                "feature_flag_key": "missing-target-flag",
            },
        )
        self.assertEqual(original_response.status_code, status.HTTP_201_CREATED)
        original_experiment = original_response.json()

        copy_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{original_experiment['id']}/copy_to_project/",
            {},
        )
        self.assertEqual(copy_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_metric_fingerprinting(self):
        """Test that metric fingerprints are computed correctly on create and update"""

        # Step 1: Create experiment with 3 metrics (tests create method fingerprinting)
        ff_key = "fingerprint-test"

        initial_mean_metric = {
            "uuid": "metric-1",
            "name": "Initial Mean Metric",
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {
                "kind": "EventsNode",
                "event": "$session_duration",
            },
        }

        initial_funnel_metric = {
            "uuid": "metric-2",
            "name": "Initial Funnel Metric",
            "kind": "ExperimentMetric",
            "metric_type": "funnel",
            "series": [
                {"kind": "EventsNode", "event": "$pageview"},
                {"kind": "EventsNode", "event": "$autocapture"},
            ],
        }

        initial_ratio_metric = {
            "uuid": "metric-3",
            "name": "Initial Ratio Metric",
            "kind": "ExperimentMetric",
            "metric_type": "ratio",
            "numerator": {"kind": "EventsNode", "event": "$session_duration"},
            "denominator": {"kind": "EventsNode", "event": "$autocapture"},
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Fingerprint Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},
                "metrics": [initial_mean_metric, initial_funnel_metric, initial_ratio_metric],
                "primary_metrics_ordered_uuids": ["metric-1", "metric-2", "metric-3"],
            },
        )
        exp_id = response.json()["id"]
        initial_metrics = response.json()["metrics"]

        expected_initial_fingerprints = {
            "mean": "d2e1f06570c3ec0af658c6255890c0ee509e0a275cbc80f630d8e8718a1b8c25",
            "funnel": "dc70f252171bb66b8b40a28ba702ad2907c61d0962b54f332dee96afd67b240c",
            "ratio": "ac46d8229e2ec5558200082a3f5d2e4e6e5041585d4f07dbd28930ee90fad235",
        }

        for metric in initial_metrics:
            metric_type = metric["metric_type"]
            self.assertEqual(metric["fingerprint"], expected_initial_fingerprints[metric_type])

        # Step 2: Update with different metrics, conversion windows, start_date, stats_config, exposure_criteria
        updated_funnel_metric = {
            "goal": "increase",
            "kind": "ExperimentMetric",
            "uuid": "964398d7-ec8a-424d-890b-4e6bbc9a5c84",
            "series": [{"kind": "EventsNode", "name": "$pageview", "event": "$pageview"}],
            "metric_type": "funnel",
            "conversion_window": 14,
            "conversion_window_unit": "day",
            "funnel_order_type": "unordered",
        }

        updated_mean_metric = {
            "goal": "increase",
            "kind": "ExperimentMetric",
            "uuid": "824e38ae-f9d7-41f4-962c-74c9e744529a",
            "source": {"kind": "EventsNode", "name": "$pageview", "event": "$pageview"},
            "metric_type": "mean",
            "conversion_window": 14,
            "conversion_window_unit": "day",
            "lower_bound_percentile": 0.05,
            "upper_bound_percentile": 0.95,
        }

        updated_ratio_metric = {
            "goal": "decrease",
            "kind": "ExperimentMetric",
            "uuid": "70e0c887-1f32-4c7d-8405-0faded2e9722",
            "numerator": {"kind": "EventsNode", "name": "$pageview", "event": "$pageview"},
            "denominator": {"kind": "EventsNode", "math": "total", "name": "$pageview", "event": "$pageview"},
            "metric_type": "ratio",
            "conversion_window": 14,
            "conversion_window_unit": "day",
        }

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "allow_unknown_events": True,
                "metrics": [updated_funnel_metric, updated_mean_metric, updated_ratio_metric],
                "primary_metrics_ordered_uuids": [
                    "964398d7-ec8a-424d-890b-4e6bbc9a5c84",
                    "824e38ae-f9d7-41f4-962c-74c9e744529a",
                    "70e0c887-1f32-4c7d-8405-0faded2e9722",
                ],
                "start_date": "2024-01-01T10:00:00Z",
                "stats_config": {"method": "frequentist"},
                "exposure_criteria": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "$feature_flag_called",
                    "properties": [],
                },
            },
        )

        updated_metrics = response.json()["metrics"]

        expected_updated_fingerprints = {
            "mean": "d6a393e5456b71c16961c45e07eb17cb86e4f7972549033f9883c99430248c02",
            "funnel": "9f7888cb2f7f9c3dac2b6482a964eef6911f97e376ed53305ed6653f7f70ce9b",
            "ratio": "1b83a833a62ff9c2f01ba86be1f3e578b97749d3264e08ff9e76d863865e3ff3",
        }

        for metric in updated_metrics:
            metric_type = metric["metric_type"]
            self.assertEqual(metric["fingerprint"], expected_updated_fingerprints[metric_type])

    def test_creating_draft_experiment_sets_status_draft(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Status Draft Test",
                "feature_flag_key": "status-draft-flag",
                "parameters": None,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["status"], "draft")

    def test_launching_experiment_sets_status_running(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Status Running Test",
                "feature_flag_key": "status-running-flag",
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["status"], "running")

    def test_ending_experiment_sets_status_stopped(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Status Stopped Test",
                "feature_flag_key": "status-stopped-flag",
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
        )
        experiment_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"end_date": "2021-12-10T00:00"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "stopped")

    def test_update_draft_to_running_sets_status(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Draft to Running",
                "feature_flag_key": "draft-to-running-flag",
                "parameters": None,
            },
        )
        experiment_id = response.json()["id"]
        self.assertEqual(response.json()["status"], "draft")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"start_date": "2021-12-01T10:23"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "running")

    def test_duplicating_running_experiment_sets_status_draft(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Running Experiment",
                "feature_flag_key": "running-dup-flag",
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
        )
        self.assertEqual(response.json()["status"], "running")
        experiment_id = response.json()["id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/duplicate/",
            {"feature_flag_key": "running-dup-flag-copy"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["status"], "draft")

    def test_duplicating_stopped_experiment_sets_status_draft(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Stopped Experiment",
                "feature_flag_key": "stopped-dup-flag",
                "start_date": "2021-12-01T10:23",
                "parameters": None,
            },
        )
        experiment_id = response.json()["id"]

        self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"end_date": "2021-12-10T00:00"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/duplicate/",
            {"feature_flag_key": "stopped-dup-flag-copy"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["status"], "draft")

    # ------------------------------------------------------------------
    # Launch endpoint
    # ------------------------------------------------------------------

    def test_launch_experiment_endpoint(self):
        # Create a draft experiment with metrics
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Launch Endpoint Test",
                "feature_flag_key": "launch-endpoint-flag",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]
        self.assertEqual(response.json()["status"], "draft")

        # Verify flag is inactive
        flag = FeatureFlag.objects.get(key="launch-endpoint-flag", team=self.team)
        self.assertFalse(flag.active)

        # Launch the experiment
        launch_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/launch/",
        )
        self.assertEqual(launch_response.status_code, status.HTTP_200_OK)

        data = launch_response.json()
        self.assertEqual(data["status"], "running")
        self.assertIsNotNone(data["start_date"])

        # Verify flag is now active
        flag.refresh_from_db()
        self.assertTrue(flag.active)

    def test_launch_experiment_endpoint_already_running(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Already Running Endpoint",
                "feature_flag_key": "already-running-endpoint",
                "start_date": "2024-01-01T10:00",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        launch_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/launch/",
        )
        self.assertEqual(launch_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_launch_experiment_endpoint_without_metrics(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "No Metrics Endpoint",
                "feature_flag_key": "no-metrics-endpoint",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        launch_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/launch/",
        )
        self.assertEqual(launch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(launch_response.json()["status"], "running")

    def test_archive_experiment_endpoint(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Archive Endpoint Test",
                "feature_flag_key": "archive-endpoint-flag",
                "start_date": "2024-01-01T10:00",
                "end_date": "2024-01-15T10:00",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]
        self.assertFalse(response.json()["archived"])

        archive_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/archive/",
        )
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)
        self.assertTrue(archive_response.json()["archived"])

    def test_archive_experiment_endpoint_disables_feature_flag(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Archive And Disable Flag",
                "feature_flag_key": "archive-disable-flag",
                "start_date": "2024-01-01T10:00",
                "end_date": "2024-01-15T10:00",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]
        feature_flag_id = response.json()["feature_flag"]["id"]

        archive_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/archive/",
            {"disable_feature_flag": True},
            format="json",
        )
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)

        feature_flag = FeatureFlag.objects.get(id=feature_flag_id)
        self.assertFalse(feature_flag.active)
        self.assertTrue(feature_flag.archived)

    def test_archive_endpoint_disable_requires_feature_flag_write_scope(self):
        def _make_experiment(name: str, key: str) -> tuple[int, int]:
            resp = self.client.post(
                f"/api/projects/{self.team.id}/experiments/",
                {
                    "allow_unknown_events": True,
                    "name": name,
                    "feature_flag_key": key,
                    "start_date": "2024-01-01T10:00",
                    "end_date": "2024-01-15T10:00",
                    "metrics": [
                        {
                            "kind": "ExperimentMetric",
                            "metric_type": "mean",
                            "source": {"kind": "EventsNode", "event": "$pageview"},
                        }
                    ],
                },
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            return resp.json()["id"], resp.json()["feature_flag"]["id"]

        def _pat(scopes: list[str]) -> str:
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(user=self.user, label="t", secure_value=hash_key_value(token), scopes=scopes)
            return token

        exp_deny, _ = _make_experiment("Scope Deny", "scope-deny-flag")
        exp_no_disable, _ = _make_experiment("Scope No Disable", "scope-no-disable-flag")
        exp_allow, flag_allow = _make_experiment("Scope Allow", "scope-allow-flag")

        self.client.logout()

        # experiment:write alone can't disable the linked flag — that needs feature_flag:write.
        token = _pat(["experiment:write"])
        resp = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{exp_deny}/archive/",
            {"disable_feature_flag": True},
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN, resp.content)

        # experiment:write alone still archives when not disabling the flag.
        resp = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{exp_no_disable}/archive/",
            {"disable_feature_flag": False},
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)

        # With feature_flag:write, disabling the linked flag is allowed.
        token = _pat(["experiment:write", "feature_flag:write"])
        resp = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{exp_allow}/archive/",
            {"disable_feature_flag": True},
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        flag = FeatureFlag.objects.get(id=flag_allow)
        self.assertFalse(flag.active)
        self.assertTrue(flag.archived)

    @parameterized.expand(
        [
            # Personal API key: scopes come off the key.
            (
                "pak_denied",
                _make(PersonalAPIKeyAuthentication, personal_api_key=SimpleNamespace(scopes=["experiment:write"])),
                False,
            ),
            (
                "pak_allowed",
                _make(
                    PersonalAPIKeyAuthentication,
                    personal_api_key=SimpleNamespace(scopes=["experiment:write", "feature_flag:write"]),
                ),
                True,
            ),
            ("pak_wildcard", _make(PersonalAPIKeyAuthentication, personal_api_key=SimpleNamespace(scopes=["*"])), True),
            # OAuth: scope is a space-separated string that must be split.
            (
                "oauth_denied",
                _make(OAuthAccessTokenAuthentication, access_token=SimpleNamespace(scope="experiment:write")),
                False,
            ),
            (
                "oauth_allowed",
                _make(
                    OAuthAccessTokenAuthentication,
                    access_token=SimpleNamespace(scope="experiment:write feature_flag:write"),
                ),
                True,
            ),
            ("oauth_wildcard", _make(OAuthAccessTokenAuthentication, access_token=SimpleNamespace(scope="*")), True),
            (
                "oauth_empty_scope",
                _make(OAuthAccessTokenAuthentication, access_token=SimpleNamespace(scope=None)),
                False,
            ),
            # ID-JAG: scopes are already a list.
            ("id_jag_denied", _make(IDJagAccessTokenAuthentication, scopes=["experiment:write"]), False),
            (
                "id_jag_allowed",
                _make(IDJagAccessTokenAuthentication, scopes=["experiment:write", "feature_flag:write"]),
                True,
            ),
            ("id_jag_wildcard", _make(IDJagAccessTokenAuthentication, scopes=["*"]), True),
            # Session and other non-token auth aren't scope-limited.
            ("session_auth", None, True),
            ("other_auth", object(), True),
        ]
    )
    def test_token_can_write_feature_flag_per_token_type(self, _name, authenticator, expected):
        request = cast(Any, SimpleNamespace(successful_authenticator=authenticator))
        viewset = EnterpriseExperimentsViewSet()
        self.assertEqual(viewset._token_can_write_feature_flag(request), expected)

    def test_archive_experiment_endpoint_not_ended(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Archive Running Endpoint",
                "feature_flag_key": "archive-running-endpoint",
                "start_date": "2024-01-01T10:00",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        archive_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/archive/",
        )
        self.assertEqual(archive_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unarchive_experiment_endpoint(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Unarchive Endpoint Test",
                "feature_flag_key": "unarchive-endpoint-flag",
                "start_date": "2024-01-01T10:00",
                "end_date": "2024-01-15T10:00",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Archive first
        archive_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/archive/",
        )
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)
        self.assertTrue(archive_response.json()["archived"])

        # Unarchive
        unarchive_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/unarchive/",
        )
        self.assertEqual(unarchive_response.status_code, status.HTTP_200_OK)
        self.assertFalse(unarchive_response.json()["archived"])

    def test_unarchive_experiment_endpoint_not_archived(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Unarchive Not Archived",
                "feature_flag_key": "unarchive-not-archived-flag",
                "start_date": "2024-01-01T10:00",
                "end_date": "2024-01-15T10:00",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        unarchive_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/unarchive/",
        )
        self.assertEqual(unarchive_response.status_code, status.HTTP_400_BAD_REQUEST)

    def _create_running_experiment(self, name: str = "Running Test", flag_key: str = "running-flag") -> dict:
        """Helper: create an experiment and launch it via the API."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": name,
                "feature_flag_key": flag_key,
                "allow_unknown_events": True,
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        launch_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/launch/",
        )
        self.assertEqual(launch_response.status_code, status.HTTP_200_OK)
        return launch_response.json()

    def test_pause_experiment_endpoint(self):
        data = self._create_running_experiment(name="Pause Endpoint", flag_key="pause-endpoint-flag")
        experiment_id = data["id"]

        # Flag should be active after launch
        flag = FeatureFlag.objects.get(key="pause-endpoint-flag", team=self.team)
        self.assertTrue(flag.active)

        pause_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/pause/",
        )
        self.assertEqual(pause_response.status_code, status.HTTP_200_OK)
        self.assertEqual(pause_response.json()["status"], "paused")
        self.assertFalse(pause_response.json()["feature_flag"]["active"])

        # Verify flag is now inactive
        flag.refresh_from_db()
        self.assertFalse(flag.active)

    def test_resume_experiment_endpoint(self):
        data = self._create_running_experiment(name="Resume Endpoint", flag_key="resume-endpoint-flag")
        experiment_id = data["id"]

        # Pause first
        pause_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/pause/",
        )
        self.assertEqual(pause_response.status_code, status.HTTP_200_OK)
        self.assertEqual(pause_response.json()["status"], "paused")

        # Resume
        resume_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/resume/",
        )
        self.assertEqual(resume_response.status_code, status.HTTP_200_OK)
        self.assertEqual(resume_response.json()["status"], "running")
        self.assertTrue(resume_response.json()["feature_flag"]["active"])

        flag = FeatureFlag.objects.get(key="resume-endpoint-flag", team=self.team)
        self.assertTrue(flag.active)

    def test_pause_experiment_already_paused_returns_400(self):
        data = self._create_running_experiment(name="Double Pause", flag_key="double-pause-flag")
        experiment_id = data["id"]

        self.client.post(f"/api/projects/{self.team.id}/experiments/{experiment_id}/pause/")

        second_pause = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/pause/",
        )
        self.assertEqual(second_pause.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resume_experiment_not_paused_returns_400(self):
        data = self._create_running_experiment(name="Resume Not Paused", flag_key="resume-not-paused-flag")
        experiment_id = data["id"]

        resume_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/resume/",
        )
        self.assertEqual(resume_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pause_draft_experiment_returns_400(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Pause Draft",
                "feature_flag_key": "pause-draft-flag",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        pause_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/pause/",
        )
        self.assertEqual(pause_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pause_ended_experiment_returns_400(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Pause Ended",
                "feature_flag_key": "pause-ended-flag",
                "start_date": "2024-01-01T10:00",
                "end_date": "2024-01-15T10:00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        pause_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/pause/",
        )
        self.assertEqual(pause_response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.cohorts.backend.models.cohort.Cohort.insert_users_list_by_uuid", return_value=0)
    @patch(
        "products.experiments.backend.experiment_service.validate_person_uuids_exist",
        new=lambda team_id, uuids: uuids,
    )
    @patch(
        "products.experiments.backend.experiment_service.ExperimentService._fetch_exposed_person_uuids",
        return_value=["00000000-0000-0000-0000-000000000001"],
    )
    def test_freeze_exposure_endpoint(self, mock_fetch: MagicMock, mock_insert: MagicMock) -> None:
        data = self._create_running_experiment(name="Freeze Endpoint", flag_key="freeze-endpoint-flag")
        experiment_id = data["id"]

        freeze_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/freeze_exposure/",
        )
        self.assertEqual(freeze_response.status_code, status.HTTP_200_OK)
        body = freeze_response.json()
        # Frozen exposure is still running under the hood — precedence puts exposure_frozen first.
        self.assertEqual(body["status"], "exposure_frozen")
        # Unlike pause, the flag stays active; unlike end, end_date stays null so metrics keep flowing.
        self.assertIsNone(body["end_date"])
        self.assertTrue(body["feature_flag"]["active"])

        # A frozen-but-still-running experiment also serializes as exposure_frozen on GET.
        get_response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}/")
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.json()["status"], "exposure_frozen")

    @patch("products.cohorts.backend.models.cohort.Cohort.insert_users_list_by_uuid", return_value=0)
    @patch(
        "products.experiments.backend.experiment_service.validate_person_uuids_exist",
        new=lambda team_id, uuids: uuids,
    )
    @patch(
        "products.experiments.backend.experiment_service.ExperimentService._fetch_exposed_person_uuids",
        return_value=["00000000-0000-0000-0000-000000000001"],
    )
    def test_freeze_exposure_already_frozen_returns_400(self, mock_fetch: MagicMock, mock_insert: MagicMock) -> None:
        data = self._create_running_experiment(name="Double Freeze", flag_key="double-freeze-flag")
        experiment_id = data["id"]

        self.client.post(f"/api/projects/{self.team.id}/experiments/{experiment_id}/freeze_exposure/")

        second_freeze = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/freeze_exposure/",
        )
        self.assertEqual(second_freeze.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.cohorts.backend.models.cohort.Cohort.insert_users_list_by_uuid", return_value=0)
    @patch(
        "products.experiments.backend.experiment_service.validate_person_uuids_exist",
        new=lambda team_id, uuids: uuids,
    )
    @patch(
        "products.experiments.backend.experiment_service.ExperimentService._fetch_exposed_person_uuids",
        return_value=["00000000-0000-0000-0000-000000000001"],
    )
    def test_unfreeze_exposure_endpoint(self, mock_fetch: MagicMock, mock_insert: MagicMock) -> None:
        data = self._create_running_experiment(name="Unfreeze Endpoint", flag_key="unfreeze-endpoint-flag")
        experiment_id = data["id"]
        freeze_response = self.client.post(f"/api/projects/{self.team.id}/experiments/{experiment_id}/freeze_exposure/")
        self.assertEqual(freeze_response.status_code, status.HTTP_200_OK)

        unfreeze_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/unfreeze_exposure/",
        )
        self.assertEqual(unfreeze_response.status_code, status.HTTP_200_OK)
        self.assertEqual(unfreeze_response.json()["status"], "running")

        # Not frozen anymore — a second unfreeze is rejected.
        second_unfreeze = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/unfreeze_exposure/",
        )
        self.assertEqual(second_unfreeze.status_code, status.HTTP_400_BAD_REQUEST)

    def test_freeze_exposure_draft_returns_400(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {"name": "Freeze Draft", "feature_flag_key": "freeze-draft-flag"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        freeze_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/freeze_exposure/",
        )
        self.assertEqual(freeze_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_end_experiment_endpoint(self):
        data = self._create_running_experiment(name="End Endpoint", flag_key="end-endpoint-flag")
        experiment_id = data["id"]

        end_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/end/",
            {"conclusion": "won", "conclusion_comment": "Test variant won"},
            format="json",
        )
        self.assertEqual(end_response.status_code, status.HTTP_200_OK)
        self.assertEqual(end_response.json()["status"], "stopped")
        self.assertIsNotNone(end_response.json()["end_date"])
        self.assertEqual(end_response.json()["conclusion"], "won")
        self.assertEqual(end_response.json()["conclusion_comment"], "Test variant won")
        # Flag should remain active
        self.assertTrue(end_response.json()["feature_flag"]["active"])

    def test_end_experiment_invalid_conclusion_returns_400(self):
        data = self._create_running_experiment(name="End Invalid Conclusion", flag_key="end-invalid-conclusion-flag")
        experiment_id = data["id"]

        end_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/end/",
            {"conclusion": "amazing"},
            format="json",
        )
        self.assertEqual(end_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_end_experiment_draft_returns_400(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "End Draft",
                "feature_flag_key": "end-draft-endpoint-flag",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        end_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/end/",
            format="json",
        )
        self.assertEqual(end_response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.experiments.backend.presentation.views.has_tasks_access", return_value=True)
    @patch("products.experiments.backend.experiment_service.posthoganalytics.feature_enabled", return_value=False)
    def test_end_endpoint_cleanup_pr_requires_task_write_scope(self, _mock_flag, _mock_access):
        exp_deny = self._create_running_experiment(name="Cleanup Deny", flag_key="cleanup-deny-flag")["id"]
        exp_no_opt = self._create_running_experiment(name="Cleanup No Opt", flag_key="cleanup-no-opt-flag")["id"]
        exp_allow = self._create_running_experiment(name="Cleanup Allow", flag_key="cleanup-allow-flag")["id"]

        def _pat(scopes: list[str]) -> str:
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(user=self.user, label="t", secure_value=hash_key_value(token), scopes=scopes)
            return token

        self.client.logout()

        # experiment:write alone can't open a cleanup PR; opening one starts a task, which needs task:write.
        token = _pat(["experiment:write"])
        resp = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{exp_deny}/end/",
            {"conclusion": "won", "open_cleanup_pr": True},
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN, resp.content)

        # experiment:write alone still ends the experiment when not opening a PR.
        resp = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{exp_no_opt}/end/",
            {"conclusion": "won", "open_cleanup_pr": False},
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)

        # With task:write, opting in is allowed.
        token = _pat(["experiment:write", "task:write"])
        resp = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{exp_allow}/end/",
            {"conclusion": "won", "open_cleanup_pr": True},
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)

    @patch("products.experiments.backend.experiment_service.posthoganalytics.feature_enabled", return_value=False)
    def test_cleanup_pr_requires_code_access_for_session_users(self, _mock_flag):
        exp_end = self._create_running_experiment(name="Cleanup Session End", flag_key="cleanup-session-end-flag")["id"]
        exp_ship = self._create_running_experiment(name="Cleanup Session Ship", flag_key="cleanup-session-ship-flag")[
            "id"
        ]

        # Scopes don't apply to session auth — without Code access, opting in must be rejected
        # on both actions that can open a cleanup PR.
        with patch("products.experiments.backend.presentation.views.has_tasks_access", return_value=False):
            resp = self.client.post(
                f"/api/projects/{self.team.id}/experiments/{exp_end}/end/",
                {"conclusion": "won", "open_cleanup_pr": True},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN, resp.content)

            resp = self.client.post(
                f"/api/projects/{self.team.id}/experiments/{exp_ship}/ship_variant/",
                {"variant_key": "test", "conclusion": "won", "open_cleanup_pr": True},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN, resp.content)

            # Not opting in still ends the experiment without Code access.
            resp = self.client.post(
                f"/api/projects/{self.team.id}/experiments/{exp_end}/end/",
                {"conclusion": "won", "open_cleanup_pr": False},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)

        # With Code access, opting in succeeds on both actions ("end first, ship later" flow).
        with patch("products.experiments.backend.presentation.views.has_tasks_access", return_value=True):
            resp = self.client.post(
                f"/api/projects/{self.team.id}/experiments/{exp_ship}/end/",
                {"conclusion": "won", "open_cleanup_pr": True},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)

            resp = self.client.post(
                f"/api/projects/{self.team.id}/experiments/{exp_ship}/ship_variant/",
                {"variant_key": "test", "conclusion": "won", "open_cleanup_pr": True},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)

    def test_ship_variant_endpoint_default_preserves_groups(self):
        data = self._create_running_experiment(name="Ship Endpoint", flag_key="ship-endpoint-flag")
        experiment_id = data["id"]
        original_groups = data["feature_flag"]["filters"].get("groups", [])

        ship_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/ship_variant/",
            {"variant_key": "test", "conclusion": "won", "conclusion_comment": "Test won"},
            format="json",
        )
        self.assertEqual(ship_response.status_code, status.HTTP_200_OK)
        self.assertEqual(ship_response.json()["status"], "stopped")
        self.assertIsNotNone(ship_response.json()["end_date"])
        self.assertEqual(ship_response.json()["conclusion"], "won")
        self.assertEqual(ship_response.json()["conclusion_comment"], "Test won")

        # Variant distribution was flipped
        flag_filters = ship_response.json()["feature_flag"]["filters"]
        variants = flag_filters["multivariate"]["variants"]
        test_variant = next(v for v in variants if v["key"] == "test")
        control_variant = next(v for v in variants if v["key"] == "control")
        self.assertEqual(test_variant["rollout_percentage"], 100)
        self.assertEqual(control_variant["rollout_percentage"], 0)

        # Default behavior: existing groups preserved, no catch-all prepended
        self.assertEqual(flag_filters["groups"], original_groups)

    def test_ship_variant_endpoint_release_to_everyone_prepends_catch_all(self):
        data = self._create_running_experiment(name="Ship Everyone", flag_key="ship-everyone-flag")
        experiment_id = data["id"]

        ship_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/ship_variant/",
            {"variant_key": "test", "release_to_everyone": True, "conclusion": "won"},
            format="json",
        )
        self.assertEqual(ship_response.status_code, status.HTTP_200_OK)

        flag_filters = ship_response.json()["feature_flag"]["filters"]
        variants = flag_filters["multivariate"]["variants"]
        test_variant = next(v for v in variants if v["key"] == "test")
        self.assertEqual(test_variant["rollout_percentage"], 100)

        # release_to_everyone: catch-all prepended
        self.assertEqual(flag_filters["groups"][0]["rollout_percentage"], 100)
        self.assertEqual(flag_filters["groups"][0]["properties"], [])
        self.assertIn("Added automatically", flag_filters["groups"][0].get("description", ""))

    def test_ship_variant_on_stopped_experiment(self):
        data = self._create_running_experiment(name="Ship Stopped Endpoint", flag_key="ship-stopped-endpoint-flag")
        experiment_id = data["id"]

        # End the experiment first
        self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/end/",
            {"conclusion": "inconclusive"},
            format="json",
        )

        # Ship a variant on the already-ended experiment
        ship_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/ship_variant/",
            {"variant_key": "test", "conclusion": "won"},
            format="json",
        )
        self.assertEqual(ship_response.status_code, status.HTTP_200_OK)
        # Conclusion updated
        self.assertEqual(ship_response.json()["conclusion"], "won")

        # Flag filters rewritten
        variants = ship_response.json()["feature_flag"]["filters"]["multivariate"]["variants"]
        test_variant = next(v for v in variants if v["key"] == "test")
        self.assertEqual(test_variant["rollout_percentage"], 100)

    def test_ship_variant_invalid_variant_key_returns_400(self):
        data = self._create_running_experiment(
            name="Ship Invalid Variant", flag_key="ship-invalid-variant-endpoint-flag"
        )
        experiment_id = data["id"]

        ship_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/ship_variant/",
            {"variant_key": "nonexistent"},
            format="json",
        )
        self.assertEqual(ship_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ship_variant_missing_variant_key_returns_400(self):
        data = self._create_running_experiment(name="Ship Missing Key", flag_key="ship-missing-key-endpoint-flag")
        experiment_id = data["id"]

        ship_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/ship_variant/",
            {},
            format="json",
        )
        self.assertEqual(ship_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ship_variant_draft_returns_400(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Ship Draft",
                "feature_flag_key": "ship-draft-endpoint-flag",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        ship_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/ship_variant/",
            {"variant_key": "test"},
            format="json",
        )
        self.assertEqual(ship_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ship_variant_invalid_conclusion_returns_400(self):
        data = self._create_running_experiment(
            name="Ship Invalid Conclusion", flag_key="ship-invalid-conclusion-endpoint-flag"
        )
        experiment_id = data["id"]

        ship_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/ship_variant/",
            {"variant_key": "test", "conclusion": "amazing"},
            format="json",
        )
        self.assertEqual(ship_response.status_code, status.HTTP_400_BAD_REQUEST)

    # ------------------------------------------------------------------
    # Action ID validation & event name warnings in API responses
    # ------------------------------------------------------------------

    def test_create_with_nonexistent_action_returns_400(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Bad Action Experiment",
                "feature_flag_key": "bad-action-api-flag",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "ActionsNode", "id": 999999},
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("999999", response.json()["detail"])

    def test_create_with_unknown_event_returns_400(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Unknown Event Experiment",
                "feature_flag_key": "unknown-event-api-flag",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pagevew"},
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("$pagevew", response.json()["detail"])

    def test_create_with_known_event_succeeds(self):
        EventDefinition.objects.create(team=self.team, name="$pageview")
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Known Event Experiment",
                "feature_flag_key": "known-event-api-flag",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_update_with_unknown_event_returns_400(self):
        EventDefinition.objects.create(team=self.team, name="$pageview")
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Update Event Error Experiment",
                "feature_flag_key": "update-event-error-api-flag",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        experiment_id = create_response.json()["id"]

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "totally_fake_event"},
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_400_BAD_REQUEST)


class TestExperimentParametersFlagConfigCompatibility(APILicensedTest):
    """Flag config belongs on the `feature_flag` object now, but many external clients still send it
    through the deprecated `parameters` keys. Rather than reject those requests, the API copies that
    config into the `feature_flag` object so legacy callers keep working. This class sends the
    deprecated keys directly (it deliberately does NOT use _HoistFlagConfigClientMixin) to lock in
    the copy behavior, the read-modify-write echo tolerance, and the running-experiment guard."""

    @parameterized.expand(
        [
            (
                "variants",
                {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
                lambda p: [v["key"] for v in p["feature_flag_variants"]] == ["control", "test"],
            ),
            ("rollout", {"rollout_percentage": 50}, lambda p: p["rollout_percentage"] == 50),
            ("aggregation", {"aggregation_group_type_index": 0}, lambda p: p["aggregation_group_type_index"] == 0),
            (
                "payloads",
                {"feature_flag_payloads": {"control": '"x"'}},
                lambda p: p["feature_flag_payloads"] == {"control": '"x"'},
            ),
            ("continuity", {"ensure_experience_continuity": True}, lambda p: p["ensure_experience_continuity"] is True),
        ]
    )
    def test_create_copies_deprecated_flag_config_to_flag(self, name: str, parameters: dict, check) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {"name": f"copy {name}", "feature_flag_key": f"copy-{name}", "parameters": parameters},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertTrue(FeatureFlag.objects.filter(key=f"copy-{name}", team_id=self.team.id).exists())
        # The read response projects the linked flag's config back into `parameters`, so it reflects
        # the config the deprecated keys were copied onto the flag.
        self.assertTrue(check(response.json()["parameters"]), response.json()["parameters"])

    def _create_via_flag_object(
        self, key: str = "echo-source", start_date: str | None = None, variants: list[dict] | None = None
    ) -> int:
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": key,
                "feature_flag_key": key,
                "start_date": start_date,
                "feature_flag": {
                    "filters": {
                        "multivariate": {
                            "variants": variants
                            or [
                                {"key": "control", "name": "Control", "rollout_percentage": 50},
                                {"key": "test", "name": "Test", "rollout_percentage": 50},
                            ]
                        }
                    }
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        return response.json()["id"]

    def test_update_tolerates_unchanged_parameters_echo(self) -> None:
        experiment_id = self._create_via_flag_object()
        # A read-modify-write client spreads the GET response's `parameters` (which carries the
        # projected flag config, split_percent and all) straight back into the save. That unchanged
        # echo must be stripped and tolerated, not resynced — else every UI save breaks.
        echoed_parameters = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}").json()[
            "parameters"
        ]
        self.assertIn("feature_flag_variants", echoed_parameters)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"description": "unrelated edit", "parameters": echoed_parameters},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        # The echoed flag config never lands in the stored column.
        experiment = Experiment.objects.get(id=experiment_id)
        self.assertNotIn("feature_flag_variants", experiment.parameters or {})

    @parameterized.expand(
        [
            (
                "variants",
                {
                    "feature_flag_variants": [
                        {"key": "control", "rollout_percentage": 30},
                        {"key": "test", "rollout_percentage": 70},
                    ]
                },
                lambda flag: [v["rollout_percentage"] for v in flag.variants] == [30, 70],
            ),
            ("rollout", {"rollout_percentage": 25}, lambda flag: flag.filters["groups"][0]["rollout_percentage"] == 25),
        ]
    )
    def test_draft_update_copies_differing_parameters_flag_config_to_flag(
        self, name: str, override: dict, check
    ) -> None:
        experiment_id = self._create_via_flag_object()
        echoed_parameters = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}").json()[
            "parameters"
        ]
        # A genuine change through the deprecated surface on a draft is copied into the feature_flag
        # object and applied to the linked flag, not silently dropped.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"parameters": {**echoed_parameters, **override}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        flag = FeatureFlag.objects.get(key="echo-source", team_id=self.team.id)
        self.assertTrue(check(flag), flag.filters)

    def test_running_update_requires_opt_in_for_differing_parameters_flag_config(self) -> None:
        experiment_id = self._create_via_flag_object(key="running-echo-source", start_date="2021-12-01T10:23")
        echoed_parameters = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}").json()[
            "parameters"
        ]
        differing = {
            **echoed_parameters,
            "feature_flag_variants": [
                {"key": "control", "rollout_percentage": 60},
                {"key": "test", "rollout_percentage": 40},
            ],
        }
        # Routing through the feature_flag path means the deprecated surface can't bypass the
        # running-experiment guard: a differing change without the opt-in is rejected, not applied.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"parameters": differing},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertIn("update_feature_flag_params", str(response.json()))
        flag = FeatureFlag.objects.get(key="running-echo-source", team_id=self.team.id)
        self.assertEqual([v["rollout_percentage"] for v in flag.variants], [50, 50])

        # With the opt-in the change applies.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"parameters": differing, "update_feature_flag_params": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        flag.refresh_from_db()
        self.assertEqual([v["rollout_percentage"] for v in flag.variants], [60, 40])

    @parameterized.expand(
        [
            # Read-modify-write: echo the full flag-config projection GET returns, plus a non-flag key.
            ("echo_plus_non_flag_key", lambda echoed: {**echoed, "variant_notes": {"control": "n"}}),
            # Bare non-flag PATCH carrying no flag-config keys at all.
            ("non_flag_key_only", lambda _echoed: {"variant_notes": {"control": "n"}}),
        ]
    )
    def test_draft_non_flag_parameters_patch_preserves_flag_variants(self, name: str, build_parameters) -> None:
        key = f"preserve-{name}"
        experiment_id = self._create_via_flag_object(
            key=key,
            variants=[
                {"key": "control", "name": "Control", "rollout_percentage": 30},
                {"key": "test", "name": "Test", "rollout_percentage": 70},
            ],
        )
        echoed_parameters = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}").json()[
            "parameters"
        ]
        # A PATCH that carries no genuine flag-config change must never resync the linked flag: its
        # non-default variants must survive, not reset to DEFAULT_VARIANTS (50/50).
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}",
            {"parameters": build_parameters(echoed_parameters)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        flag = FeatureFlag.objects.get(key=key, team_id=self.team.id)
        self.assertEqual([v["rollout_percentage"] for v in flag.variants], [30, 70], flag.filters)


class TestExperimentAuxiliaryEndpoints(_HoistFlagConfigClientMixin, ClickhouseTestMixin, APILicensedTest):
    def _generate_experiment(self, start_date="2024-01-01T10:23", extra_parameters=None):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": start_date,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant",
                            "rollout_percentage": 33,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant",
                            "rollout_percentage": 34,
                        },
                    ],
                    **(extra_parameters or {}),
                },
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)
        return response

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_create_exposure_cohort_for_experiment(self, patch_on_commit: MagicMock):
        response = self._generate_experiment("2024-01-01T10:23")

        created_experiment = response.json()["id"]

        journeys_for(
            {
                "person1": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                ],
                "person2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "test_1"},
                    },
                ],
                "personX": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test2", "$feature_flag_response": "test_1"},
                    },
                ],
                # out of time range
                "person3": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2023-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                ],
                # wrong event
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2024-01-03"},
                    {"event": "$pageleave", "timestamp": "2024-01-05"},
                ],
                # doesn't have feature value set
                "person_out_of_end_date": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
            },
            self.team,
        )
        flush_persons_and_events()

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        cohort = response.json()["cohort"]
        self.assertEqual(cohort["name"], 'Users exposed to experiment "Test Experiment"')
        self.assertEqual(cohort["experiment_set"], [created_experiment])

        cohort_id = cohort["id"]

        while cohort["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")
            cohort = response.json()

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(["person1", "person2"], sorted([res["name"] for res in response.json()["results"]]))

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_create_exposure_cohort_for_experiment_with_custom_event_exposure(self, patch_on_commit: MagicMock):
        self.maxDiff = None

        cohort_extra = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "value": "http://example.com",
                            "type": "person",
                            "operator": "exact",
                        },
                    ],
                }
            },
            name="cohort_X",
        )
        response = self._generate_experiment(
            "2024-01-01T10:23",
            {
                "custom_exposure_filter": {
                    "events": [
                        {
                            "id": "custom_exposure_event",
                            "order": 0,
                            "entity_type": "events",
                            "properties": [
                                {"key": "bonk", "value": "bonk"},
                                {"key": "id", "value": cohort_extra.id, "type": "cohort"},
                                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                {"key": "bonk-person", "value": "bonk", "type": "person"},
                            ],
                        }
                    ],
                    "filter_test_accounts": False,
                }
            },
        )

        created_experiment = response.json()["id"]

        journeys_for(
            {
                "person1": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "x", "bonk": "bonk"},
                    },
                ],
                "person2": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "y", "bonk": "bonk"},
                    },
                ],
                "person2-no-bonk": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "y"},
                    },
                ],
                "person2-not-in-prop": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2024-01-02",
                        "properties": {"$current_url": "yxxxx"},
                    },
                ],
                "personX": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2024-01-02",
                        "properties": {"$feature_flag": "a-b-test2", "$feature_flag_response": "test_1"},
                    },
                ],
                # out of time range
                "person3": [
                    {
                        "event": "custom_exposure_event",
                        "timestamp": "2023-01-02",
                        "properties": {"$current_url": "y"},
                    },
                ],
                # wrong event
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2024-01-03"},
                    {"event": "$pageleave", "timestamp": "2024-01-05"},
                ],
            },
            self.team,
        )
        flush_persons_and_events()

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        cohort = response.json()["cohort"]
        self.assertEqual(cohort["name"], 'Users exposed to experiment "Test Experiment"')
        self.assertEqual(cohort["experiment_set"], [created_experiment])
        self.assertEqual(
            cohort["filters"],
            {
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "bytecode": [
                                        "_H",
                                        1,
                                        32,
                                        "custom_exposure_event",
                                        32,
                                        "event",
                                        1,
                                        1,
                                        11,
                                        32,
                                        "bonk",
                                        32,
                                        "bonk",
                                        32,
                                        "properties",
                                        1,
                                        2,
                                        11,
                                        32,
                                        "x",
                                        32,
                                        "y",
                                        44,
                                        2,
                                        32,
                                        "$current_url",
                                        32,
                                        "properties",
                                        1,
                                        2,
                                        21,
                                        3,
                                        2,
                                        3,
                                        2,
                                    ],
                                    "conditionHash": "605645c960b2c67c",
                                    "event_filters": [
                                        {"key": "bonk", "type": "event", "value": "bonk"},
                                        {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                    ],
                                    "event_type": "events",
                                    "explicit_datetime": "2024-01-01T10:23:00+00:00",
                                    "key": "custom_exposure_event",
                                    "negation": False,
                                    "type": "behavioral",
                                    "value": "performed_event",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        cohort_id = cohort["id"]

        while cohort["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")
            cohort = response.json()

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(["person1", "person2"], sorted([res["name"] for res in response.json()["results"]]))

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_create_exposure_cohort_for_experiment_with_custom_action_filters_exposure(
        self, patch_on_commit: MagicMock
    ):
        cohort_extra = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "value": "http://example.com",
                            "type": "person",
                            "operator": "exact",
                        },
                    ],
                }
            },
            name="cohort_X",
        )

        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[
                {
                    "event": "insight viewed",
                    "properties": [
                        {
                            "key": "insight",
                            "type": "event",
                            "value": ["RETENTION"],
                            "operator": "exact",
                        },
                        {
                            "key": "id",
                            "value": cohort_extra.id,
                            "type": "cohort",
                        },
                    ],
                },
                {
                    "event": "insight viewed",
                    "properties": [
                        {
                            "key": "filters_count",
                            "type": "event",
                            "value": "1",
                            "operator": "gt",
                        }
                    ],
                },
                {
                    "event": "$autocapture",
                    "url": "/123",
                    "url_matching": "regex",
                },
            ],
        )
        response = self._generate_experiment(
            datetime.now() - timedelta(days=5),
            {
                "custom_exposure_filter": {
                    "actions": [
                        {
                            "id": str(action1.id),  # should support string ids
                            "order": 0,
                            "entity_type": "actions",
                            "properties": [
                                {"key": "bonk", "value": "bonk"},
                                {"key": "id", "value": cohort_extra.id, "type": "cohort"},
                                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                {"key": "bonk-person", "value": "bonk", "type": "person"},
                            ],
                        }
                    ],
                    "filter_test_accounts": False,
                }
            },
        )

        created_experiment = response.json()["id"]

        journeys_for(
            {
                "person1": [
                    {
                        "event": "insight viewed",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {"$current_url": "x", "bonk": "bonk", "filters_count": 2},
                    },
                ],
                "person2": [
                    {
                        "event": "insight viewed",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {
                            "$current_url": "y",
                            "bonk": "bonk",
                            "insight": "RETENTION",
                        },  # missing pageview person property
                    },
                ],
                "person2-no-bonk": [
                    {
                        "event": "insight viewed",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {"$current_url": "y", "filters_count": 3},
                    },
                ],
                "person2-not-in-prop": [
                    {
                        "event": "$autocapture",
                        "timestamp": datetime.now() - timedelta(days=2),
                        "properties": {
                            "$current_url": "https://posthog.com/feedback/1234"
                        },  # can't match because clashing current_url filters
                    },
                ],
            },
            self.team,
        )

        _create_person(
            distinct_ids=["1"],
            team_id=self.team.pk,
            properties={"$pageview": "http://example.com"},
        )
        _create_event(
            event="insight viewed",
            team=self.team,
            distinct_id="1",
            properties={"insight": "RETENTION", "$current_url": "x", "bonk": "bonk"},
            timestamp=datetime.now() - timedelta(days=2),
        )
        _create_person(
            distinct_ids=["2"],
            team_id=self.team.pk,
            properties={"$pageview": "http://example.com"},
        )
        _create_event(
            event="insight viewed",
            team=self.team,
            distinct_id="2",
            properties={"insight": "RETENTION", "$current_url": "x"},
            timestamp=datetime.now() - timedelta(days=2),
        )
        flush_persons_and_events()

        cohort_extra.calculate_people_ch(pending_version=1)

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        cohort = response.json()["cohort"]
        self.assertEqual(cohort["name"], 'Users exposed to experiment "Test Experiment"')
        self.assertEqual(cohort["experiment_set"], [created_experiment])

        self.maxDiff = None
        target_filter = cohort["filters"]["properties"]["values"][0]["values"][0]
        self.assertEqual(
            target_filter["event_filters"],
            [
                {"key": "bonk", "type": "event", "value": "bonk"},
                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
            ],
            cohort["filters"],
        )
        self.assertEqual(
            target_filter["event_type"],
            "actions",
        )
        self.assertEqual(
            target_filter["key"],
            action1.id,
        )
        self.assertEqual(
            target_filter["type"],
            "behavioral",
        )
        self.assertEqual(
            target_filter["value"],
            "performed_event",
        )
        explicit_datetime = parser.isoparse(target_filter["explicit_datetime"])

        self.assertTrue(
            explicit_datetime <= datetime.now(UTC) - timedelta(days=5)
            and explicit_datetime >= datetime.now(UTC) - timedelta(days=5, hours=1)
        )

        cohort_id = cohort["id"]

        while cohort["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")
            cohort = response.json()

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(["1", "person1"], sorted([res["name"] for res in response.json()["results"]]))

    def test_create_exposure_cohort_for_experiment_with_invalid_action_filters_exposure(self):
        response = self._generate_experiment(
            "2024-01-01T10:23",
            {
                "custom_exposure_filter": {
                    "actions": [
                        {
                            "id": "oogabooga",
                            "order": 0,
                            "entity_type": "actions",
                            "properties": [
                                {"key": "bonk", "value": "bonk"},
                                {"key": "properties.$current_url in ('x', 'y')", "type": "hogql"},
                                {"key": "bonk-person", "value": "bonk", "type": "person"},
                            ],
                        }
                    ],
                    "filter_test_accounts": False,
                }
            },
        )

        created_experiment = response.json()["id"]

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Invalid action ID")

    def test_create_exposure_cohort_for_experiment_with_draft_experiment(self):
        response = self._generate_experiment(None)

        created_experiment = response.json()["id"]

        # now call to make cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Experiment does not have a start date")

    def test_create_exposure_cohort_for_experiment_with_existing_cohort(self):
        response = self._generate_experiment()

        created_experiment = response.json()["id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # now call to make cohort again
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/{created_experiment}/create_exposure_cohort_for_experiment/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Experiment already has an exposure cohort")

    def test_create_experiment_with_stats_config(self) -> None:
        """Test that stats_config can be passed from frontend and is preserved"""
        ff_key = "stats-config-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Stats Config Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {},
                "stats_config": {
                    "method": "bayesian",
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Stats Config Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        # Verify stats_config is preserved with custom fields
        stats_config = response.json()["stats_config"]
        self.assertEqual(stats_config["method"], "bayesian")

    def test_create_experiment_uses_team_default_confidence_level(self) -> None:
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        config.default_experiment_confidence_level = 0.90
        config.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-confidence-level",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        stats_config = response.json()["stats_config"]
        self.assertAlmostEqual(stats_config["bayesian"]["ci_level"], 0.90)
        self.assertAlmostEqual(stats_config["frequentist"]["alpha"], 0.10)

    def test_experiment_activity_logging_shows_correct_user_for_updates(self):
        """Test that experiment activity logs show the correct user for both creation and updates."""

        # Create a second user to test with
        second_user = User.objects.create_user(
            email="second@posthog.com", password="testpass123", first_name="Second", last_name="User"
        )
        self.organization.members.add(second_user)

        # Create experiment with first user (self.user)
        ff_key = "activity-logging-test"
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Activity Logging Test Experiment",
                "description": "Testing activity logging fix",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {},
            },
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        experiment_id = create_response.json()["id"]

        # Check creation activity log shows first user
        creation_logs = ActivityLog.objects.filter(
            scope="Experiment", item_id=str(experiment_id), activity="created"
        ).order_by("-created_at")
        self.assertEqual(len(creation_logs), 1)
        self.assertEqual(creation_logs[0].user, self.user)

        # Switch to second user and update the experiment
        self.client.force_login(second_user)
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "description": "Updated description by second user",
            },
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        # Check update activity log shows second user (not the creator)
        update_logs = ActivityLog.objects.filter(
            scope="Experiment", item_id=str(experiment_id), activity="updated"
        ).order_by("-created_at")
        self.assertEqual(len(update_logs), 1)
        self.assertEqual(update_logs[0].user, second_user)

        # Verify the fix: the update activity log should NOT show the first user
        self.assertNotEqual(update_logs[0].user, self.user)

    def test_web_experiment_activity_logging_excludes_parameters_through_main_endpoint(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Web experiment activity logging flag",
            key="web-experiment-activity-logging",
            filters={},
        )
        experiment = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Web experiment activity logging",
            description="Original description",
            type=Experiment.ExperimentType.WEB,
            parameters={},
            feature_flag=feature_flag,
        )

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment.id}/",
            {
                "description": "Updated through the main experiments endpoint",
                "parameters": None,
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        activity_log = ActivityLog.objects.filter(
            scope="Experiment", item_id=str(experiment.id), activity="updated"
        ).latest("created_at")
        assert activity_log.detail is not None

        change_fields = [change["field"] for change in activity_log.detail["changes"]]
        self.assertIn("description", change_fields)
        self.assertNotIn("parameters", change_fields)

    def test_experiment_saved_metric_activity_logging_shows_correct_user_for_updates(self):
        """Test that experiment saved metric activity logs show the correct user for both creation and updates."""

        # Create a second user to test with
        second_user = User.objects.create_user(
            email="second@posthog.com", password="testpass123", first_name="Second", last_name="User"
        )
        self.organization.members.add(second_user)

        # Create experiment saved metric with first user (self.user)
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Activity Logging Test Metric",
                "description": "Testing saved metric activity logging fix",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        metric_id = create_response.json()["id"]

        # Check creation activity log shows first user
        creation_logs = ActivityLog.objects.filter(
            scope="Experiment",  # Note: ExperimentSavedMetric logs under "Experiment" scope
            item_id=str(metric_id),
            activity="created",
        ).order_by("-created_at")
        self.assertEqual(len(creation_logs), 1)
        self.assertEqual(creation_logs[0].user, self.user)

        # Switch to second user and update the metric
        self.client.force_login(second_user)
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/{metric_id}/",
            {
                "description": "Updated description by second user",
            },
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        # Check update activity log shows second user (not the creator)
        update_logs = ActivityLog.objects.filter(
            scope="Experiment",  # Note: ExperimentSavedMetric logs under "Experiment" scope
            item_id=str(metric_id),
            activity="updated",
        ).order_by("-created_at")
        self.assertEqual(len(update_logs), 1)
        self.assertEqual(update_logs[0].user, second_user)

        # Verify the fix: the update activity log should NOT show the first user
        self.assertNotEqual(update_logs[0].user, self.user)

    def test_experiment_to_saved_metric_metadata_change_activity_logging(self):
        """Test that changes to ExperimentToSavedMetric metadata are logged under Experiment scope."""
        # Create a saved metric
        saved_metric_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Activity Test Metric",
                "description": "Testing metadata activity logging",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )
        self.assertEqual(saved_metric_response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = saved_metric_response.json()["id"]

        # Create experiment with saved metric including metadata
        experiment_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Metadata Activity Test",
                "feature_flag_key": "metadata-activity-test",
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "primary"}}],
            },
            format="json",
        )
        self.assertEqual(experiment_response.status_code, status.HTTP_201_CREATED)
        experiment_id = experiment_response.json()["id"]

        # Verify activity log was created for the saved metric config link
        created_logs = ActivityLog.objects.filter(
            scope="Experiment",
            item_id=str(experiment_id),
            activity="created",
            detail__type="saved_metric_config",
        )
        self.assertEqual(created_logs.count(), 1)
        self.assertEqual(created_logs[0].user, self.user)
        assert created_logs[0].detail is not None
        self.assertEqual(created_logs[0].detail["name"], "Activity Test Metric")

        # Update the metadata (add a breakdown)
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "saved_metrics_ids": [
                    {"id": saved_metric_id, "metadata": {"type": "primary", "breakdowns": [{"property": "country"}]}}
                ],
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        # Verify an "updated" activity log was created with the metadata change
        updated_logs = ActivityLog.objects.filter(
            scope="Experiment",
            item_id=str(experiment_id),
            activity="updated",
            detail__type="saved_metric_config",
        )
        self.assertEqual(updated_logs.count(), 1)
        self.assertEqual(updated_logs[0].user, self.user)
        assert updated_logs[0].detail is not None
        self.assertEqual(updated_logs[0].detail["name"], "Activity Test Metric")

        # Verify the changes include the metadata field
        changes = updated_logs[0].detail.get("changes", [])
        metadata_change = next((c for c in changes if c.get("field") == "metadata"), None)
        assert metadata_change is not None
        self.assertEqual(metadata_change["before"], {"type": "primary"})
        self.assertEqual(metadata_change["after"], {"type": "primary", "breakdowns": [{"property": "country"}]})

    def test_saved_metric_add_remove_does_not_log_ordering_changes(self):
        """Adding/removing saved metrics should not create redundant ordering activity logs.

        When a saved metric is added or removed and the user did not supply an explicit
        ordering, the auto-synced ordering write is persisted via a muted
        ``experiment.save(update_fields=...)`` so the only log entry is the
        ``saved_metric_config`` add/remove.
        """
        # Create a saved metric
        saved_metric_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Ordering Test Metric",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": "test-uuid-001",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )
        self.assertEqual(saved_metric_response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = saved_metric_response.json()["id"]

        # Create experiment without saved metrics
        experiment_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Ordering Activity Test",
                "feature_flag_key": "ordering-activity-test",
            },
            format="json",
        )
        self.assertEqual(experiment_response.status_code, status.HTTP_201_CREATED)
        experiment_id = experiment_response.json()["id"]

        # Count logs before adding saved metric
        logs_before_add = ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment").count()

        # Add a saved metric to the experiment
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {"saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "secondary"}}]},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        # Verify ordering was updated in the database
        experiment = Experiment.objects.get(id=experiment_id)
        self.assertIn("test-uuid-001", experiment.secondary_metrics_ordered_uuids or [])

        # Exactly 1 new log should be created (the saved_metric_config, not ordering changes)
        logs_after_add = ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment").count()
        self.assertEqual(logs_after_add - logs_before_add, 1)

        # Verify the new log is for saved_metric_config, not ordering
        config_logs = ActivityLog.objects.filter(
            item_id=str(experiment_id),
            scope="Experiment",
            activity="created",
            detail__type="saved_metric_config",
        )
        self.assertEqual(config_logs.count(), 1)

        # Verify NO ordering change logs exist
        all_logs = ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment")
        ordering_logs = [
            log
            for log in all_logs
            if log.detail
            and any(
                change.get("field") in ("primary_metrics_ordered_uuids", "secondary_metrics_ordered_uuids")
                for change in (log.detail.get("changes") or [])
            )
        ]
        self.assertEqual(len(ordering_logs), 0, "Ordering changes should not be logged")

        # Count logs before removing saved metric
        logs_before_remove = ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment").count()

        # Remove the saved metric
        remove_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {"saved_metrics_ids": []},
            format="json",
        )
        self.assertEqual(remove_response.status_code, status.HTTP_200_OK)

        # Verify ordering was updated
        experiment.refresh_from_db()
        self.assertNotIn("test-uuid-001", experiment.secondary_metrics_ordered_uuids or [])

        # Exactly 1 new log should be created (the saved_metric_config deletion)
        logs_after_remove = ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment").count()
        self.assertEqual(logs_after_remove - logs_before_remove, 1)

        # Verify the new log is for saved_metric_config deletion
        delete_logs = ActivityLog.objects.filter(
            item_id=str(experiment_id),
            scope="Experiment",
            activity="deleted",
            detail__type="saved_metric_config",
        )
        self.assertEqual(delete_logs.count(), 1)

    def test_user_initiated_metric_reorder_is_logged(self):
        """A standalone reorder (no add/remove) must produce an activity log entry."""
        # Seed the experiment with two inline metrics so there is something to reorder
        experiment_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Reorder Activity Test",
                "feature_flag_key": "reorder-activity-test",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": "reorder-uuid-a",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": "reorder-uuid-b",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                ],
                "primary_metrics_ordered_uuids": ["reorder-uuid-a", "reorder-uuid-b"],
            },
            format="json",
        )
        self.assertEqual(experiment_response.status_code, status.HTTP_201_CREATED)
        experiment_id = experiment_response.json()["id"]

        logs_before_reorder = ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment").count()

        reorder_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {"primary_metrics_ordered_uuids": ["reorder-uuid-b", "reorder-uuid-a"]},
            format="json",
        )
        self.assertEqual(reorder_response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(id=experiment_id)
        self.assertEqual(experiment.primary_metrics_ordered_uuids, ["reorder-uuid-b", "reorder-uuid-a"])

        logs_after_reorder = ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment").count()
        self.assertEqual(logs_after_reorder - logs_before_reorder, 1)

        reorder_log = (
            ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment", activity="updated")
            .order_by("-created_at")
            .first()
        )
        assert reorder_log is not None and reorder_log.detail is not None
        changes = reorder_log.detail.get("changes") or []
        ordering_change = next((c for c in changes if c.get("field") == "primary_metrics_ordered_uuids"), None)
        assert ordering_change is not None, "Explicit reorder must produce a primary_metrics_ordered_uuids change"
        self.assertEqual(ordering_change["before"], ["reorder-uuid-a", "reorder-uuid-b"])
        self.assertEqual(ordering_change["after"], ["reorder-uuid-b", "reorder-uuid-a"])

    def test_explicit_reorder_in_same_patch_as_saved_metric_add_is_logged(self):
        """If the user supplies ordering alongside an add/remove, the reorder must still be logged."""
        # Create a saved metric the experiment can later adopt
        saved_metric_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Combined PATCH Saved Metric",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": "combined-saved-uuid",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )
        self.assertEqual(saved_metric_response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = saved_metric_response.json()["id"]

        # Start with one inline primary metric so we have an existing ordering to permute
        experiment_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Combined PATCH Activity Test",
                "feature_flag_key": "combined-patch-activity",
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": "combined-inline-uuid",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                ],
                "primary_metrics_ordered_uuids": ["combined-inline-uuid"],
            },
            format="json",
        )
        self.assertEqual(experiment_response.status_code, status.HTTP_201_CREATED)
        experiment_id = experiment_response.json()["id"]

        logs_before = ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment").count()

        # Same PATCH: adds the saved metric AND explicitly reorders so the saved metric goes first.
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "primary"}}],
                "primary_metrics_ordered_uuids": ["combined-saved-uuid", "combined-inline-uuid"],
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(id=experiment_id)
        self.assertEqual(
            experiment.primary_metrics_ordered_uuids,
            ["combined-saved-uuid", "combined-inline-uuid"],
        )

        # Two new logs: the saved_metric_config add AND the experiment-level reorder.
        new_logs = ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment").count() - logs_before
        self.assertEqual(new_logs, 2)

        # The saved metric add is captured
        config_logs = ActivityLog.objects.filter(
            item_id=str(experiment_id),
            scope="Experiment",
            activity="created",
            detail__type="saved_metric_config",
        )
        self.assertEqual(config_logs.count(), 1)

        # The user-supplied reorder is also captured in a separate Experiment update log
        reorder_logs = ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment", activity="updated")
        ordering_changes = [
            change
            for log in reorder_logs
            if log.detail
            for change in (log.detail.get("changes") or [])
            if change.get("field") == "primary_metrics_ordered_uuids"
        ]
        self.assertEqual(len(ordering_changes), 1, "User-supplied reorder must be logged once")
        self.assertEqual(ordering_changes[0]["before"], ["combined-inline-uuid"])
        self.assertEqual(ordering_changes[0]["after"], ["combined-saved-uuid", "combined-inline-uuid"])

    @parameterized.expand(
        [
            ("primary", "primary_metrics_ordered_uuids", "secondary_metrics_ordered_uuids"),
            ("secondary", "secondary_metrics_ordered_uuids", "primary_metrics_ordered_uuids"),
        ]
    )
    def test_bulk_remove_shared_metrics_does_not_log_ordering_change(
        self, metric_type: str, ordering_field: str, other_ordering_field: str
    ):
        """Bulk-remove via the reorder dialog (saved_metrics_ids=[] + ordering=[]) must not log a reorder.

        The frontend sends the now-empty ordering array alongside the empty
        saved_metrics_ids on bulk remove. That mirrors auto-sync, so the ordering
        write is bookkeeping and must be muted. Only the per-link `saved_metric_config`
        deleted entries should appear.
        """
        saved_metric_uuids = ["bulk-remove-uuid-1", "bulk-remove-uuid-2"]
        saved_metric_ids: list[int] = []
        for index, uuid in enumerate(saved_metric_uuids):
            response = self.client.post(
                f"/api/projects/{self.team.id}/experiment_saved_metrics/",
                {
                    "name": f"Bulk Remove Metric {index + 1}",
                    "query": {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": uuid,
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            saved_metric_ids.append(response.json()["id"])

        experiment_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": f"Bulk Remove Activity Test ({metric_type})",
                "feature_flag_key": f"bulk-remove-activity-{metric_type}",
                "saved_metrics_ids": [
                    {"id": saved_metric_id, "metadata": {"type": metric_type}} for saved_metric_id in saved_metric_ids
                ],
                ordering_field: saved_metric_uuids,
            },
            format="json",
        )
        self.assertEqual(experiment_response.status_code, status.HTTP_201_CREATED)
        experiment_id = experiment_response.json()["id"]

        logs_before = ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment").count()

        # Mirrors the curl payload from the reorder dialog: clear inline metrics,
        # clear the ordering array, and clear saved_metrics_ids in the same PATCH.
        inline_metrics_field = "metrics" if metric_type == "primary" else "metrics_secondary"
        remove_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                inline_metrics_field: [],
                ordering_field: [],
                "saved_metrics_ids": [],
            },
            format="json",
        )
        self.assertEqual(remove_response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(id=experiment_id)
        self.assertEqual(getattr(experiment, ordering_field) or [], [])

        # Two new logs expected: one saved_metric_config deleted per removed link.
        new_logs = list(
            ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment").order_by("created_at")
        )
        added = new_logs[logs_before:]
        self.assertEqual(len(added), 2, "Two saved_metric_config deleted entries expected")
        for log in added:
            assert log.detail is not None
            self.assertEqual(log.activity, "deleted")
            self.assertEqual(log.detail["type"], "saved_metric_config")

        # No ordering change should be logged on any entry (existing or new).
        ordering_changes = [
            change
            for log in ActivityLog.objects.filter(item_id=str(experiment_id), scope="Experiment")
            if log.detail
            for change in (log.detail.get("changes") or [])
            if change.get("field") in (ordering_field, other_ordering_field)
        ]
        self.assertEqual(
            ordering_changes,
            [],
            "Bulk-remove must not log a primary/secondary ordering change",
        )

    def test_cannot_add_saved_metric_from_different_team(self):
        team_b = Team.objects.create(organization=self.organization, name="Team B")

        # Create a saved metric in team A (self.team)
        saved_metric_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Team A Metric",
                "description": "This metric belongs to Team A",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                },
            },
            format="json",
        )
        self.assertEqual(saved_metric_response.status_code, status.HTTP_201_CREATED)
        team_a_metric_id = saved_metric_response.json()["id"]

        # Create an experiment in team B
        experiment_response = self.client.post(
            f"/api/projects/{team_b.id}/experiments/",
            {
                "name": "Team B Experiment",
                "feature_flag_key": "team-b-flag",
                "parameters": None,
            },
            format="json",
        )
        self.assertEqual(experiment_response.status_code, status.HTTP_201_CREATED)
        team_b_experiment_id = experiment_response.json()["id"]

        # Try to add Team A's saved metric to Team B's experiment
        # This should fail with validation error
        update_response = self.client.patch(
            f"/api/projects/{team_b.id}/experiments/{team_b_experiment_id}/",
            {
                "saved_metrics_ids": [{"id": team_a_metric_id, "metadata": {"type": "primary"}}],
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("does not exist or does not belong to this project", str(update_response.json()))

    def test_update_auto_syncs_ordering_when_inline_metric_added_with_empty_ordering(self):
        """Test that adding a metric with an empty ordering array auto-populates the ordering"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-ordering-validation",
                "parameters": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Add a metric with an empty ordering array - backend should auto-populate
        metric_uuid = "test-metric-uuid-123"
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "allow_unknown_events": True,
                "metrics": [
                    {
                        "uuid": metric_uuid,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    }
                ],
                "primary_metrics_ordered_uuids": [],
            },
            format="json",
        )

        # Should succeed and the UUID should be in the ordering
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertIn(metric_uuid, update_response.json()["primary_metrics_ordered_uuids"])

    def test_update_auto_syncs_ordering_when_saved_metric_added_with_empty_ordering(self):
        """Test that adding a saved metric with empty ordering auto-populates the ordering"""
        saved_metric_uuid = "saved-metric-uuid-456"
        saved_metric_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Saved Metric",
                "query": {
                    "kind": "ExperimentMetric",
                    "uuid": saved_metric_uuid,
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                },
            },
            format="json",
        )
        self.assertEqual(saved_metric_response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = saved_metric_response.json()["id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-saved-metric-ordering",
                "parameters": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Add a saved metric with empty ordering - backend should auto-populate
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "primary"}}],
                "primary_metrics_ordered_uuids": [],
            },
            format="json",
        )

        # Should succeed and the UUID should be in the ordering
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertIn(saved_metric_uuid, update_response.json()["primary_metrics_ordered_uuids"])

    def test_update_succeeds_when_ordering_arrays_are_correct(self):
        """Test that updating an experiment succeeds when ordering arrays contain all metric UUIDs"""
        saved_metric_uuid = "saved-metric-uuid-789"
        saved_metric_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Saved Metric",
                "query": {
                    "kind": "ExperimentMetric",
                    "uuid": saved_metric_uuid,
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                },
            },
            format="json",
        )
        self.assertEqual(saved_metric_response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = saved_metric_response.json()["id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-correct-ordering",
                "parameters": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        inline_metric_uuid = "inline-metric-uuid-abc"
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "allow_unknown_events": True,
                "metrics": [
                    {
                        "uuid": inline_metric_uuid,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    }
                ],
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "primary"}}],
                "primary_metrics_ordered_uuids": [inline_metric_uuid, saved_metric_uuid],
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

    def test_create_auto_syncs_ordering_when_inline_metric_added_with_empty_ordering(self):
        """Test that creating an experiment with metrics and empty ordering auto-populates the ordering"""
        metric_uuid = "create-metric-uuid-123"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Test Experiment",
                "feature_flag_key": "test-create-ordering-validation",
                "parameters": None,
                "metrics": [
                    {
                        "uuid": metric_uuid,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    }
                ],
                "primary_metrics_ordered_uuids": [],
            },
            format="json",
        )

        # Should succeed and the UUID should be in the ordering
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn(metric_uuid, response.json()["primary_metrics_ordered_uuids"])

    def test_update_auto_syncs_ordering_when_inline_metric_added_without_ordering(self):
        """Test that adding a metric without sending ordering at all auto-populates the ordering"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-ordering-auto-sync",
                "parameters": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Add a metric WITHOUT sending ordering - backend should auto-populate
        metric_uuid = "auto-sync-metric-uuid-123"
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "allow_unknown_events": True,
                "metrics": [
                    {
                        "uuid": metric_uuid,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    }
                ],
            },
            format="json",
        )

        # Should succeed and the UUID should be in the ordering
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertIn(metric_uuid, update_response.json()["primary_metrics_ordered_uuids"])

    def test_update_removes_uuid_from_ordering_when_metric_removed(self):
        """Test that removing a metric also removes its UUID from the ordering array"""
        metric_uuid_1 = "remove-test-uuid-1"
        metric_uuid_2 = "remove-test-uuid-2"

        # Create experiment with two metrics
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Test Experiment",
                "feature_flag_key": "test-remove-sync",
                "parameters": None,
                "metrics": [
                    {
                        "uuid": metric_uuid_1,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    },
                    {
                        "uuid": metric_uuid_2,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageleave"}],
                    },
                ],
                "primary_metrics_ordered_uuids": [metric_uuid_1, metric_uuid_2],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Remove one metric - backend should auto-remove from ordering
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "allow_unknown_events": True,
                "metrics": [
                    {
                        "uuid": metric_uuid_1,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    },
                ],
            },
            format="json",
        )

        # Should succeed, only metric_uuid_1 should remain in ordering
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        ordering = update_response.json()["primary_metrics_ordered_uuids"]
        self.assertIn(metric_uuid_1, ordering)
        self.assertNotIn(metric_uuid_2, ordering)

    def test_update_auto_syncs_secondary_metrics_ordering(self):
        """Test that adding a secondary metric auto-populates the secondary ordering array"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-secondary-sync",
                "parameters": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Add a secondary metric without ordering
        metric_uuid = "secondary-metric-uuid-123"
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "allow_unknown_events": True,
                "metrics_secondary": [
                    {
                        "uuid": metric_uuid,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    }
                ],
            },
            format="json",
        )

        # Should succeed and the UUID should be in the secondary ordering
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertIn(metric_uuid, update_response.json()["secondary_metrics_ordered_uuids"])

    def test_update_ordering_unchanged_when_no_metrics_change(self):
        """Test that ordering arrays are not modified when only name is updated"""
        metric_uuid = "unchanged-metric-uuid"

        # Create experiment with a metric
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Test Experiment",
                "feature_flag_key": "test-unchanged-ordering",
                "parameters": None,
                "metrics": [
                    {
                        "uuid": metric_uuid,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    }
                ],
                "primary_metrics_ordered_uuids": [metric_uuid],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]
        original_ordering = response.json()["primary_metrics_ordered_uuids"]

        # Update only the name - ordering should remain unchanged
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "name": "Updated Experiment Name",
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.json()["primary_metrics_ordered_uuids"], original_ordering)

    def test_update_preserves_existing_order_when_adding_metrics(self):
        """Test that existing metric order is preserved when adding new metrics"""
        metric_uuid_1 = "preserve-order-uuid-1"
        metric_uuid_2 = "preserve-order-uuid-2"
        metric_uuid_3 = "preserve-order-uuid-3"

        # Create experiment with two metrics in specific order
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Test Experiment",
                "feature_flag_key": "test-preserve-order",
                "parameters": None,
                "metrics": [
                    {
                        "uuid": metric_uuid_1,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    },
                    {
                        "uuid": metric_uuid_2,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageleave"}],
                    },
                ],
                "primary_metrics_ordered_uuids": [metric_uuid_2, metric_uuid_1],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Add a third metric - existing order should be preserved, new one appended
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "allow_unknown_events": True,
                "metrics": [
                    {
                        "uuid": metric_uuid_1,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    },
                    {
                        "uuid": metric_uuid_2,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageleave"}],
                    },
                    {
                        "uuid": metric_uuid_3,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$custom"}],
                    },
                ],
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        ordering = update_response.json()["primary_metrics_ordered_uuids"]
        # Original order preserved, new metric appended
        self.assertEqual(ordering, [metric_uuid_2, metric_uuid_1, metric_uuid_3])

    def test_update_auto_syncs_ordering_when_saved_metric_added_without_ordering(self):
        """Test that adding a saved metric without sending ordering auto-populates the ordering"""
        saved_metric_uuid = "saved-metric-no-ordering-uuid"
        saved_metric_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Saved Metric",
                "query": {
                    "kind": "ExperimentMetric",
                    "uuid": saved_metric_uuid,
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                },
            },
            format="json",
        )
        self.assertEqual(saved_metric_response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = saved_metric_response.json()["id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-saved-metric-no-ordering",
                "parameters": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Add a saved metric WITHOUT sending ordering - backend should auto-populate
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "primary"}}],
            },
            format="json",
        )

        # Should succeed and the UUID should be in the ordering
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertIn(saved_metric_uuid, update_response.json()["primary_metrics_ordered_uuids"])

    def test_update_removes_saved_metric_uuid_from_ordering_when_removed(self):
        """Test that removing a saved metric also removes its UUID from the ordering array"""
        saved_metric_uuid_1 = "remove-saved-uuid-1"
        saved_metric_uuid_2 = "remove-saved-uuid-2"

        # Create two saved metrics
        saved_metric_response_1 = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Saved Metric 1",
                "query": {
                    "kind": "ExperimentMetric",
                    "uuid": saved_metric_uuid_1,
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                },
            },
            format="json",
        )
        saved_metric_id_1 = saved_metric_response_1.json()["id"]

        saved_metric_response_2 = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Saved Metric 2",
                "query": {
                    "kind": "ExperimentMetric",
                    "uuid": saved_metric_uuid_2,
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageleave"}],
                },
            },
            format="json",
        )
        saved_metric_id_2 = saved_metric_response_2.json()["id"]

        # Create experiment with both saved metrics
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-remove-saved-metric",
                "parameters": None,
                "saved_metrics_ids": [
                    {"id": saved_metric_id_1, "metadata": {"type": "primary"}},
                    {"id": saved_metric_id_2, "metadata": {"type": "primary"}},
                ],
                "primary_metrics_ordered_uuids": [saved_metric_uuid_1, saved_metric_uuid_2],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Remove one saved metric - backend should auto-remove from ordering
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "saved_metrics_ids": [{"id": saved_metric_id_1, "metadata": {"type": "primary"}}],
            },
            format="json",
        )

        # Should succeed, only saved_metric_uuid_1 should remain in ordering
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        ordering = update_response.json()["primary_metrics_ordered_uuids"]
        self.assertIn(saved_metric_uuid_1, ordering)
        self.assertNotIn(saved_metric_uuid_2, ordering)

    def test_update_auto_syncs_secondary_saved_metric_ordering(self):
        """Test that adding a secondary saved metric auto-populates the secondary ordering array"""
        saved_metric_uuid = "secondary-saved-metric-uuid"
        saved_metric_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Secondary Saved Metric",
                "query": {
                    "kind": "ExperimentMetric",
                    "uuid": saved_metric_uuid,
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                },
            },
            format="json",
        )
        self.assertEqual(saved_metric_response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = saved_metric_response.json()["id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-secondary-saved-metric",
                "parameters": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Add a secondary saved metric without ordering
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/",
            {
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "secondary"}}],
            },
            format="json",
        )

        # Should succeed and the UUID should be in the secondary ordering
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertIn(saved_metric_uuid, update_response.json()["secondary_metrics_ordered_uuids"])

    def test_create_auto_syncs_ordering_when_inline_metric_added_without_ordering(self):
        """Test that creating an experiment with metrics but no ordering auto-populates the ordering"""
        metric_uuid = "create-no-ordering-uuid"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Test Experiment",
                "feature_flag_key": "test-create-no-ordering",
                "parameters": None,
                "metrics": [
                    {
                        "uuid": metric_uuid,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    }
                ],
            },
            format="json",
        )

        # Should succeed and the UUID should be in the ordering
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn(metric_uuid, response.json()["primary_metrics_ordered_uuids"])

    def test_create_auto_syncs_ordering_for_secondary_inline_metrics(self):
        """Test that creating an experiment with secondary metrics auto-populates secondary ordering"""
        metric_uuid = "create-secondary-uuid"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Test Experiment",
                "feature_flag_key": "test-create-secondary",
                "parameters": None,
                "metrics_secondary": [
                    {
                        "uuid": metric_uuid,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    }
                ],
            },
            format="json",
        )

        # Should succeed and the UUID should be in the secondary ordering
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn(metric_uuid, response.json()["secondary_metrics_ordered_uuids"])

    def test_create_auto_syncs_ordering_for_saved_metrics(self):
        """Test that creating an experiment with saved metrics auto-populates ordering"""
        saved_metric_uuid = "create-saved-metric-uuid"
        saved_metric_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Saved Metric",
                "query": {
                    "kind": "ExperimentMetric",
                    "uuid": saved_metric_uuid,
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                },
            },
            format="json",
        )
        self.assertEqual(saved_metric_response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = saved_metric_response.json()["id"]

        # Create experiment with saved metric but no ordering
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "test-create-saved-metric",
                "parameters": None,
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "primary"}}],
            },
            format="json",
        )

        # Should succeed and the saved metric UUID should be in the ordering
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn(saved_metric_uuid, response.json()["primary_metrics_ordered_uuids"])

    def test_create_auto_syncs_ordering_for_mixed_metrics(self):
        """Test that creating an experiment with both inline and saved metrics auto-populates ordering"""
        inline_uuid = "create-mixed-inline-uuid"
        saved_metric_uuid = "create-mixed-saved-uuid"

        saved_metric_response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Saved Metric",
                "query": {
                    "kind": "ExperimentMetric",
                    "uuid": saved_metric_uuid,
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                },
            },
            format="json",
        )
        saved_metric_id = saved_metric_response.json()["id"]

        # Create experiment with both inline and saved metrics, no ordering
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "allow_unknown_events": True,
                "name": "Test Experiment",
                "feature_flag_key": "test-create-mixed",
                "parameters": None,
                "metrics": [
                    {
                        "uuid": inline_uuid,
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [{"kind": "EventsNode", "event": "$pageleave"}],
                    }
                ],
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "primary"}}],
            },
            format="json",
        )

        # Should succeed and both UUIDs should be in the ordering
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ordering = response.json()["primary_metrics_ordered_uuids"]
        self.assertIn(inline_uuid, ordering)
        self.assertIn(saved_metric_uuid, ordering)


class TestExperimentParametersFieldMutation(APILicensedTest):
    """
    ExperimentParametersField translates split_percent <-> rollout_percentage at the API
    boundary. Both methods must be pure transformations — mutating caller state would leak
    the alias translation into serializer.initial_data, request.data, activity logs, Sentry
    reports, and any downstream consumer that reads the original input/output.
    """

    def test_to_internal_value_does_not_mutate_input_dict(self):
        from products.experiments.backend.presentation.serializers import ExperimentParametersField

        input_dict = {
            "feature_flag_variants": [
                {"key": "control", "split_percent": 50},
                {"key": "test", "split_percent": 50},
            ]
        }

        ExperimentParametersField().to_internal_value(input_dict)

        # Caller's dict must still have split_percent (not replaced by rollout_percentage)
        assert input_dict == {
            "feature_flag_variants": [
                {"key": "control", "split_percent": 50},
                {"key": "test", "split_percent": 50},
            ]
        }

    def test_to_representation_does_not_mutate_stored_value(self):
        from products.experiments.backend.presentation.serializers import ExperimentParametersField

        stored_value = {
            "feature_flag_variants": [
                {"key": "control", "rollout_percentage": 50},
                {"key": "test", "rollout_percentage": 50},
            ]
        }

        ExperimentParametersField().to_representation(stored_value)

        # Stored value (the model's in-memory parameters dict) must not gain split_percent
        assert stored_value == {
            "feature_flag_variants": [
                {"key": "control", "rollout_percentage": 50},
                {"key": "test", "rollout_percentage": 50},
            ]
        }


class TestExperimentRunningTimeCalculation(_HoistFlagConfigClientMixin, APILicensedTest):
    EXPOSURE_ESTIMATE_CONFIG = {
        "conversionRateInputType": "manual",
        "manualMetricType": "funnel",
        "manualBaselineValue": 5,
        "manualExposureRate": 100,
    }

    def _create_experiment(self, **overrides: Any) -> dict:
        payload: dict[str, Any] = {
            "name": "Running time experiment",
            "feature_flag_key": "running-time-flag",
            "filters": {"events": [{"order": 0, "id": "$pageview"}], "properties": []},
            **overrides,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/experiments/", payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        return response.json()

    def test_create_with_legacy_parameters_does_not_populate_running_time_calculation(self):
        created = self._create_experiment(
            parameters={
                "minimum_detectable_effect": 25,
                "recommended_running_time": 14,
                "recommended_sample_size": 5000,
                "exposure_estimate_config": self.EXPOSURE_ESTIMATE_CONFIG,
            }
        )

        # Legacy calculator keys in `parameters` are no longer mirrored into the canonical field.
        self.assertEqual(created["running_time_calculation"], {})

        experiment = Experiment.objects.get(pk=created["id"])
        self.assertEqual(experiment.running_time_calculation, {})

    def test_create_with_running_time_calculation_does_not_touch_parameters(self):
        created = self._create_experiment(
            running_time_calculation={
                "minimum_detectable_effect": 20,
                "exposure_estimate_config": self.EXPOSURE_ESTIMATE_CONFIG,
            }
        )

        self.assertEqual(
            created["running_time_calculation"],
            {"minimum_detectable_effect": 20, "exposure_estimate_config": self.EXPOSURE_ESTIMATE_CONFIG},
        )
        self.assertNotIn("minimum_detectable_effect", created["parameters"] or {})
        self.assertNotIn("exposure_estimate_config", created["parameters"] or {})

        experiment = Experiment.objects.get(pk=created["id"])
        self.assertEqual(
            experiment.running_time_calculation,
            {"minimum_detectable_effect": 20, "exposure_estimate_config": self.EXPOSURE_ESTIMATE_CONFIG},
        )
        self.assertNotIn("minimum_detectable_effect", experiment.parameters or {})

    def test_update_running_time_calculation_does_not_touch_parameters(self):
        created = self._create_experiment(
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ],
            }
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{created['id']}/",
            {"running_time_calculation": {"minimum_detectable_effect": 10, "recommended_running_time": 7}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        experiment = Experiment.objects.get(pk=created["id"])
        self.assertEqual(
            experiment.running_time_calculation,
            {"minimum_detectable_effect": 10, "recommended_running_time": 7},
        )
        # Calculator keys never leak into `parameters`, and the variants on the flag are untouched.
        self.assertNotIn("minimum_detectable_effect", experiment.parameters or {})
        self.assertNotIn("recommended_running_time", experiment.parameters or {})
        flag = FeatureFlag.objects.get(key="running-time-flag")
        self.assertEqual(len(flag.filters["multivariate"]["variants"]), 2)

    def test_update_running_time_calculation_does_not_touch_feature_flag(self):
        variants = [
            {"key": "control", "rollout_percentage": 34},
            {"key": "test_a", "rollout_percentage": 33},
            {"key": "test_b", "rollout_percentage": 33},
        ]
        created = self._create_experiment(parameters={"feature_flag_variants": variants})
        flag = FeatureFlag.objects.get(key="running-time-flag")
        self.assertEqual(len(flag.filters["multivariate"]["variants"]), 3)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{created['id']}/",
            {"running_time_calculation": {"minimum_detectable_effect": 15}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        flag.refresh_from_db()
        self.assertEqual(len(flag.filters["multivariate"]["variants"]), 3)

    def test_update_parameters_does_not_touch_running_time_calculation(self):
        created = self._create_experiment(
            running_time_calculation={"minimum_detectable_effect": 15},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{created['id']}/",
            {"parameters": {"minimum_detectable_effect": 30, "recommended_sample_size": 1000}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        experiment = Experiment.objects.get(pk=created["id"])
        # The canonical field is independent of legacy `parameters` calculator keys.
        self.assertEqual(experiment.running_time_calculation, {"minimum_detectable_effect": 15})

    def test_running_time_calculation_and_parameters_are_independent(self):
        created = self._create_experiment()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{created['id']}/",
            {
                "parameters": {"minimum_detectable_effect": 99},
                "running_time_calculation": {"minimum_detectable_effect": 11},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        experiment = Experiment.objects.get(pk=created["id"])
        # Each side is stored exactly as sent — no cross-write between them.
        self.assertEqual(experiment.running_time_calculation, {"minimum_detectable_effect": 11})
        assert experiment.parameters is not None
        self.assertEqual(experiment.parameters["minimum_detectable_effect"], 99)

    @parameterized.expand(
        [
            ("unknown_key", {"not_a_real_key": 1}),
            ("non_numeric_mde", {"minimum_detectable_effect": "twenty"}),
            ("boolean_running_time", {"recommended_running_time": True}),
            ("non_object_exposure_config", {"exposure_estimate_config": "manual"}),
        ]
    )
    def test_invalid_running_time_calculation_rejected(self, _name: str, value: dict):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Invalid running time",
                "feature_flag_key": "invalid-running-time-flag",
                "running_time_calculation": value,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestExperimentExcludedVariants(_HoistFlagConfigClientMixin, APILicensedTest):
    THREE_VARIANTS = [
        {"key": "control", "rollout_percentage": 34},
        {"key": "test-1", "rollout_percentage": 33},
        {"key": "test-2", "rollout_percentage": 33},
    ]

    def _create_experiment(self, **overrides: Any) -> dict:
        payload: dict[str, Any] = {
            "name": "Excluded variants experiment",
            "feature_flag_key": "excluded-variants-flag",
            "filters": {"events": [{"order": 0, "id": "$pageview"}], "properties": []},
            **overrides,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/experiments/", payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        return response.json()

    def test_create_with_excluded_variants_writes_only_column(self):
        created = self._create_experiment(
            parameters={"feature_flag_variants": self.THREE_VARIANTS},
            excluded_variants=["test-2"],
        )

        self.assertEqual(created["excluded_variants"], ["test-2"])

        experiment = Experiment.objects.get(pk=created["id"])
        self.assertEqual(experiment.excluded_variants, ["test-2"])
        # No longer mirrored into the deprecated parameters blob
        assert experiment.parameters is not None
        self.assertNotIn("excluded_variants", experiment.parameters)

    def test_update_excluded_variants_does_not_require_feature_flag_variants(self):
        """The headline of the parameters split: excluding a variant no longer requires
        re-sending feature_flag_variants, because validation resolves against the flag."""
        created = self._create_experiment(parameters={"feature_flag_variants": self.THREE_VARIANTS})

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{created['id']}/",
            {"excluded_variants": ["test-2"]},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        experiment = Experiment.objects.get(pk=created["id"])
        self.assertEqual(experiment.excluded_variants, ["test-2"])
        # Only the column is written; the deprecated parameters blob is untouched
        self.assertNotIn("excluded_variants", experiment.parameters or {})
        flag = FeatureFlag.objects.get(key="excluded-variants-flag")
        self.assertEqual(len(flag.filters["multivariate"]["variants"]), 3)

    def test_update_excluded_variants_does_not_touch_feature_flag(self):
        created = self._create_experiment(parameters={"feature_flag_variants": self.THREE_VARIANTS})
        flag = FeatureFlag.objects.get(key="excluded-variants-flag")
        self.assertEqual(len(flag.filters["multivariate"]["variants"]), 3)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{created['id']}/",
            {"excluded_variants": ["test-2"]},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        flag.refresh_from_db()
        self.assertEqual(len(flag.filters["multivariate"]["variants"]), 3)

    @parameterized.expand(
        [
            ("unknown_variant", ["does-not-exist"]),
            ("baseline_excluded", ["control"]),
            ("all_test_variants_excluded", ["test-1", "test-2"]),
        ]
    )
    def test_update_excluded_variants_validates_against_flag_variants(self, _name: str, excluded_variants: list):
        created = self._create_experiment(parameters={"feature_flag_variants": self.THREE_VARIANTS})

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{created['id']}/",
            {"excluded_variants": excluded_variants},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    @parameterized.expand(
        [
            ("non_list", "test-2"),
            ("non_string_element", [123]),
        ]
    )
    def test_invalid_excluded_variants_rejected(self, _name: str, value):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Invalid excluded variants",
                "feature_flag_key": "invalid-excluded-variants-flag",
                "excluded_variants": value,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestCalculateRunningTimeEndpoint(APILicensedTest):
    def _calculate(self, payload: dict[str, Any]):
        return self.client.post(
            f"/api/projects/{self.team.id}/experiments/calculate_running_time/",
            payload,
            format="json",
        )

    @parameterized.expand(
        [
            ("mean_count", {"metric_type": "mean_count", "baseline_value": 4, "minimum_detectable_effect": 5}, 6400),
            (
                "mean_sum_or_avg",
                {"metric_type": "mean_sum_or_avg", "baseline_value": 50, "minimum_detectable_effect": 5},
                3200,
            ),
            ("funnel", {"metric_type": "funnel", "baseline_value": 0.1, "minimum_detectable_effect": 50}, 1152),
        ]
    )
    def test_sample_size_from_baseline_value(self, _name: str, payload: dict, expected_sample_size: int):
        response = self._calculate(payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["recommended_sample_size"], expected_sample_size)

    def test_includes_running_time_when_exposure_rate_given(self):
        response = self._calculate(
            {
                "metric_type": "mean_count",
                "baseline_value": 4,
                "minimum_detectable_effect": 5,
                "exposure_rate_per_day": 100,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        body = response.json()
        self.assertEqual(body["recommended_sample_size"], 6400)
        self.assertEqual(body["recommended_running_time_days"], 64)

    def test_running_time_is_null_without_exposure_rate(self):
        response = self._calculate({"metric_type": "funnel", "baseline_value": 0.1, "minimum_detectable_effect": 50})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertIsNone(response.json()["recommended_running_time_days"])

    def test_ratio_from_baseline_stats(self):
        response = self._calculate(
            {
                "metric_type": "ratio",
                "minimum_detectable_effect": 10,
                "baseline_stats": {
                    "number_of_samples": 10000,
                    "sum": 500000,
                    "sum_squares": 30000000,
                    "denominator_sum": 50000,
                    "denominator_sum_squares": 300000,
                    "numerator_denominator_sum_product": 2600000,
                },
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        body = response.json()
        self.assertAlmostEqual(body["baseline_value"], 10, places=4)
        self.assertAlmostEqual(body["variance"], 32, places=1)
        self.assertEqual(body["recommended_sample_size"], 1024)

    def test_funnel_from_step_counts(self):
        response = self._calculate(
            {
                "metric_type": "funnel",
                "minimum_detectable_effect": 50,
                "baseline_stats": {"number_of_samples": 1000, "sum": 100, "step_counts": [1000, 100]},
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        body = response.json()
        self.assertAlmostEqual(body["baseline_value"], 0.1, places=4)
        self.assertIsNone(body["variance"])
        self.assertEqual(body["recommended_sample_size"], 1152)

    @parameterized.expand(
        [
            ("missing_baseline", {"metric_type": "funnel", "minimum_detectable_effect": 5}),
            ("zero_mde", {"metric_type": "funnel", "baseline_value": 0.1, "minimum_detectable_effect": 0}),
            ("ratio_without_variance", {"metric_type": "ratio", "baseline_value": 10, "minimum_detectable_effect": 10}),
            (
                "ratio_stats_without_denominator_sum",
                {
                    "metric_type": "ratio",
                    "minimum_detectable_effect": 10,
                    "baseline_stats": {"number_of_samples": 10000, "sum": 500000, "sum_squares": 30000000},
                },
            ),
        ]
    )
    def test_invalid_input_rejected(self, _name: str, payload: dict):
        response = self._calculate(payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())


class TestExperimentSerializerSuperset(unittest.TestCase):
    """Structural guard: ExperimentBasicSerializer must stay a subset of ExperimentSerializer.

    ExperimentBasicApi is a structural subset of ExperimentApi in generated frontend types.
    If a field is added to the detail serializer but forgotten in the basic one the superset
    invariant holds — but the reverse (basic grows a field not in detail) would break it, and
    a mismatched read_only/required on a shared field would produce divergent nullability.
    """

    def test_basic_fields_are_subset_of_full_fields(self) -> None:
        from products.experiments.backend.presentation.serializers import (
            ExperimentBasicSerializer,
            ExperimentSerializer,
        )

        basic = ExperimentBasicSerializer()
        full = ExperimentSerializer()
        basic_field_names = set(basic.fields.keys())
        full_field_names = set(full.fields.keys())
        extra = basic_field_names - full_field_names
        self.assertFalse(
            extra,
            f"ExperimentBasicSerializer has fields not present in ExperimentSerializer: {extra}. "
            "ExperimentBasicApi must remain a structural subset of ExperimentApi.",
        )

    def test_shared_fields_have_matching_read_only_and_required(self) -> None:
        from products.experiments.backend.presentation.serializers import (
            ExperimentBasicSerializer,
            ExperimentSerializer,
        )

        basic = ExperimentBasicSerializer()
        full = ExperimentSerializer()
        shared = set(basic.fields.keys()) & set(full.fields.keys())
        mismatches: list[str] = []
        for name in sorted(shared):
            b_field = basic.fields[name]
            f_field = full.fields[name]
            if b_field.read_only != f_field.read_only:
                mismatches.append(f"{name}: read_only basic={b_field.read_only} full={f_field.read_only}")
            if b_field.required != f_field.required:
                mismatches.append(f"{name}: required basic={b_field.required} full={f_field.required}")
        self.assertFalse(
            mismatches,
            "Shared fields have mismatched read_only/required between serializers:\n" + "\n".join(mismatches),
        )


class TestExperimentApiExposureCriteriaParity(unittest.TestCase):
    """Structural guard: the slim API exposure-criteria schema must expose every writable field.

    ``exposure_criteria`` is stored as a plain JSONField, so the backend accepts any field at
    runtime. ``ExperimentApiExposureCriteria`` is the slim type that drives the OpenAPI spec and,
    downstream, the MCP tool / frontend write schema. A field honored at runtime (read from
    ``ExperimentExposureCriteria``) but missing from the slim type is silently stripped by the
    generated client before it ever reaches the API — which is how ``multiple_variant_handling``
    looked settable via ``experiment-get`` yet never saved via ``experiment-update``.
    """

    def test_api_schema_exposes_every_runtime_field(self) -> None:
        from posthog.schema import ExperimentApiExposureCriteria, ExperimentExposureCriteria

        runtime_fields = set(ExperimentExposureCriteria.model_fields)
        api_fields = set(ExperimentApiExposureCriteria.model_fields)
        dropped = runtime_fields - api_fields
        self.assertFalse(
            dropped,
            f"ExperimentApiExposureCriteria omits exposure_criteria fields the runtime honors: {dropped}. "
            "Generated write clients (MCP, frontend) strip these silently — add them to the slim API "
            "type in frontend/src/queries/schema/schema-general.ts and rerun hogli build:schema.",
        )
