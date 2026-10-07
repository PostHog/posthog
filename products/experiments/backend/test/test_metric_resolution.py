import uuid
from typing import Any

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from products.experiments.backend.metric_resolution import (
    find_metric_dict,
    resolve_experiment_metrics,
    resolve_saved_metric_definition,
    scheduled_metric_definitions,
)
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.feature_flags.backend.models.feature_flag import FeatureFlag


@pytest.mark.django_db(transaction=True)
class TestMetricResolution(BaseTest):
    def _experiment(self, metrics: list[dict] | None = None, metrics_secondary: list[dict] | None = None) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=f"flag-{uuid.uuid4().hex[:8]}",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        return Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="exp",
            metrics=metrics or [],
            metrics_secondary=metrics_secondary or [],
        )

    def _attach_saved(self, experiment: Experiment, query: dict, metadata: dict | None = None) -> None:
        saved = ExperimentSavedMetric.objects.create(team=self.team, name="saved", query=query)
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved, metadata=metadata or {})

    def test_inline_metric_takes_precedence_over_saved_with_same_uuid(self):
        shared_uuid = str(uuid.uuid4())
        inline = {"uuid": shared_uuid, "metric_type": "funnel", "source": "inline"}
        experiment = self._experiment(metrics=[inline])
        self._attach_saved(experiment, {"uuid": shared_uuid, "metric_type": "funnel", "source": "saved"})

        resolved = find_metric_dict(experiment, shared_uuid)
        assert resolved is not None
        assert resolved["source"] == "inline"

    def test_resolution_order_and_roles(self):
        primary = {"uuid": str(uuid.uuid4()), "metric_type": "mean"}
        secondary = {"uuid": str(uuid.uuid4()), "metric_type": "mean"}
        experiment = self._experiment(metrics=[primary], metrics_secondary=[secondary])
        saved_secondary_uuid = str(uuid.uuid4())
        saved_untyped_uuid = str(uuid.uuid4())
        self._attach_saved(experiment, {"uuid": saved_secondary_uuid, "metric_type": "mean"}, {"type": "secondary"})
        self._attach_saved(experiment, {"uuid": saved_untyped_uuid, "metric_type": "mean"})

        assert [(m.uuid, m.role) for m in resolve_experiment_metrics(experiment)] == [
            (primary["uuid"], "primary"),
            (secondary["uuid"], "secondary"),
            (saved_secondary_uuid, "secondary"),
            (saved_untyped_uuid, "primary"),
        ]

    def test_prefetched_links_resolve_without_queries(self):
        saved_uuid = str(uuid.uuid4())
        breakdowns = [{"property": "$browser", "type": "event"}]
        self._attach_saved(
            self._experiment(),
            {"uuid": saved_uuid, "metric_type": "mean"},
            {"breakdowns": breakdowns, "breakdown_limit": 3},
        )
        experiment = Experiment.objects.prefetch_related("experimenttosavedmetric_set__saved_metric").get(
            team=self.team
        )

        with self.assertNumQueries(0):
            definitions = scheduled_metric_definitions(experiment)

        assert definitions[saved_uuid]["breakdownFilter"] == {"breakdowns": breakdowns, "breakdown_limit": 3}

    def test_saved_metric_breakdowns_merged_from_link_metadata(self):
        experiment = self._experiment()
        saved_uuid = str(uuid.uuid4())
        breakdowns = [{"property": "$browser", "type": "event"}]
        self._attach_saved(
            experiment,
            {"uuid": saved_uuid, "metric_type": "funnel", "breakdownFilter": {"breakdown_limit": 5}},
            metadata={"breakdowns": breakdowns},
        )

        resolved = find_metric_dict(experiment, saved_uuid)
        assert resolved is not None
        assert resolved["breakdownFilter"] == {"breakdown_limit": 5, "breakdowns": breakdowns}

    def test_saved_metric_without_metadata_gets_empty_breakdowns(self):
        experiment = self._experiment()
        saved_uuid = str(uuid.uuid4())
        self._attach_saved(experiment, {"uuid": saved_uuid, "metric_type": "funnel"})

        resolved = find_metric_dict(experiment, saved_uuid)
        assert resolved is not None
        assert resolved["breakdownFilter"] == {"breakdowns": []}

    def test_unschedulable_metrics_are_excluded(self):
        experiment = self._experiment(
            metrics=[
                {"metric_type": "funnel"},
                {"uuid": str(uuid.uuid4())},
                {"uuid": str(uuid.uuid4()), "kind": "ExperimentTrendsQuery"},
            ]
        )
        self._attach_saved(experiment, {"metric_type": "funnel"})
        self._attach_saved(experiment, {"uuid": str(uuid.uuid4())})
        assert scheduled_metric_definitions(experiment) == {}


_FUNNEL_WITH_SAVED_OVERRIDES: dict[str, Any] = {
    "uuid": "saved-funnel",
    "metric_type": "funnel",
    "breakdownAttributionType": "step",
    "breakdownAttributionValue": 2,
    "breakdownFilter": {"breakdown_limit": 5, "breakdowns": [{"property": "$os", "type": "event"}]},
}


@parameterized.expand(
    [
        (
            "omitted_overrides_keep_saved_values_but_not_saved_breakdowns",
            _FUNNEL_WITH_SAVED_OVERRIDES,
            {"type": "primary"},
            {"breakdownAttributionType": "step", "breakdownAttributionValue": 2},
            {"breakdown_limit": 5, "breakdowns": []},
        ),
        (
            "null_overrides_count_as_omitted",
            _FUNNEL_WITH_SAVED_OVERRIDES,
            {"breakdownAttributionType": None, "breakdownAttributionValue": None, "breakdown_limit": None},
            {"breakdownAttributionType": "step", "breakdownAttributionValue": 2},
            {"breakdown_limit": 5, "breakdowns": []},
        ),
        (
            "link_values_replace_saved_values",
            _FUNNEL_WITH_SAVED_OVERRIDES,
            {
                "breakdownAttributionType": "last_touch",
                "breakdown_limit": 20,
                "breakdowns": [{"property": "$browser", "type": "event"}],
            },
            {"breakdownAttributionType": "last_touch"},
            {"breakdown_limit": 20, "breakdowns": [{"property": "$browser", "type": "event"}]},
        ),
        (
            "attribution_step_zero_is_explicit",
            _FUNNEL_WITH_SAVED_OVERRIDES,
            {
                "breakdownAttributionType": "step",
                "breakdownAttributionValue": 0,
                "breakdowns": [{"property": "$browser", "type": "event"}],
            },
            {"breakdownAttributionType": "step", "breakdownAttributionValue": 0},
            {"breakdown_limit": 5, "breakdowns": [{"property": "$browser", "type": "event"}]},
        ),
        (
            "attribution_on_a_mean_metric_is_ignored",
            {"uuid": "saved-mean", "metric_type": "mean"},
            {
                "breakdownAttributionType": "last_touch",
                "breakdownAttributionValue": 1,
                "breakdowns": [{"property": "$browser", "type": "event"}],
            },
            {},
            {"breakdowns": [{"property": "$browser", "type": "event"}]},
        ),
        (
            "limit_and_attribution_without_link_breakdowns_are_ignored",
            _FUNNEL_WITH_SAVED_OVERRIDES,
            {"breakdownAttributionType": "last_touch", "breakdown_limit": 20, "breakdowns": []},
            {"breakdownAttributionType": "step", "breakdownAttributionValue": 2},
            {"breakdown_limit": 5, "breakdowns": []},
        ),
    ]
)
def test_saved_metric_override_precedence(
    _name: str,
    saved_query: dict[str, Any],
    metadata: dict[str, Any],
    expected_attribution: dict[str, Any],
    expected_breakdown_filter: dict[str, Any],
) -> None:
    resolved = resolve_saved_metric_definition(saved_query, metadata)

    attribution = {
        key: resolved[key] for key in ("breakdownAttributionType", "breakdownAttributionValue") if key in resolved
    }
    assert attribution == expected_attribution
    assert resolved["breakdownFilter"] == expected_breakdown_filter
    assert resolved["uuid"] == saved_query["uuid"]
