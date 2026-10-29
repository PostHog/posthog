from types import SimpleNamespace
from typing import Any

from django.test import SimpleTestCase

from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.resource_transfer.experiment import ExperimentVisitor
from products.experiments.backend.resource_transfer.experiment_holdout import ExperimentHoldoutVisitor
from products.experiments.backend.resource_transfer.experiment_payload import (
    collect_cohort_and_action_ids_from_experiment_json,
)
from products.experiments.backend.resource_transfer.experiment_saved_metric import ExperimentSavedMetricVisitor


def _experiment_like_resource(**overrides):
    base: dict[str, Any] = {
        "filters": {},
        "parameters": {},
        "metrics": [],
        "metrics_secondary": [],
        "exposure_criteria": {},
        "stats_config": {},
        "scheduling_config": {},
        "variants": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestExperimentPayloadDynamicEdgeExtraction(SimpleTestCase):
    def test_collect_ids_from_nested_metrics_with_query(self) -> None:
        resource = _experiment_like_resource(
            metrics=[
                {
                    "uuid": "m1",
                    "query": {
                        "source": {
                            "series": [{"kind": "ActionsNode", "id": 501}],
                            "properties": [{"key": "id", "value": 600, "type": "cohort"}],
                        }
                    },
                }
            ],
        )
        collected = collect_cohort_and_action_ids_from_experiment_json(resource)
        assert collected.cohort_ids == {600}
        assert collected.action_ids == {501}

    def test_collect_ids_from_filters_and_parameters_keys(self) -> None:
        # Top-level experiment ``filters`` often mirrors insight shapes nested under keys;
        # the walker picks up cohorts when it sees a dict with a ``filters`` key.
        resource = _experiment_like_resource(
            filters={
                "nested": {
                    "filters": {"properties": [{"key": "id", "value": 111, "type": "cohort"}]},
                }
            },
            parameters={
                "query": {
                    "source": {
                        "series": [{"kind": "ActionsNode", "id": 222}],
                    }
                }
            },
        )
        collected = collect_cohort_and_action_ids_from_experiment_json(resource)
        assert 111 in collected.cohort_ids
        assert 222 in collected.action_ids


class TestExperimentVisitorDynamicEdges(SimpleTestCase):
    def test_dynamic_edges_match_experiment_json_extraction(self) -> None:
        exp = _experiment_like_resource(
            metrics=[
                {
                    "query": {
                        "source": {
                            "series": [{"kind": "ActionsNode", "id": 777}],
                        }
                    }
                }
            ],
        )
        edges = ExperimentVisitor.get_dynamic_edges(exp)
        by_model_pk = {(e.target_model, e.target_primary_key) for e in edges}
        assert (Action, 777) in by_model_pk
        assert any(e.name == "json_action:777" for e in edges)


class TestExperimentHoldoutVisitorDynamicEdges(SimpleTestCase):
    def test_dynamic_edges_from_filters_list_properties(self) -> None:
        holdout = SimpleNamespace(
            filters=[
                {
                    "properties": [
                        {"key": "id", "value": 55, "type": "cohort"},
                    ]
                }
            ]
        )
        edges = ExperimentHoldoutVisitor.get_dynamic_edges(holdout)
        assert len(edges) == 1
        assert edges[0].target_model is Cohort
        assert edges[0].target_primary_key == 55
        assert edges[0].name == "cohort:55"


class TestExperimentSavedMetricVisitorDynamicEdges(SimpleTestCase):
    def test_dynamic_edges_from_query_uses_insight_extraction(self) -> None:
        metric = SimpleNamespace(
            query={
                "source": {
                    "series": [{"kind": "ActionsNode", "id": 888}],
                    "properties": [{"key": "id", "value": 999, "type": "cohort"}],
                }
            }
        )
        edges = ExperimentSavedMetricVisitor.get_dynamic_edges(metric)
        by_model_pk = {(e.target_model, e.target_primary_key) for e in edges}
        assert (Action, 888) in by_model_pk
        assert (Cohort, 999) in by_model_pk

    def test_non_dict_query_returns_no_edges(self) -> None:
        metric = SimpleNamespace(query=None)
        assert ExperimentSavedMetricVisitor.get_dynamic_edges(metric) == []

        metric_list = SimpleNamespace(query=[])
        assert ExperimentSavedMetricVisitor.get_dynamic_edges(metric_list) == []
