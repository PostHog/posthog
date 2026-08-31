"""Fixtures bind adapters to generated MCP schemas and their repository result contracts.

Schemas: services/mcp/tests/unit/__snapshots__/tool-schemas/{data-catalog-metric-run,
query-trends,query-funnel}.json. Results: products/data_catalog/backend/presentation/
serializers.py and services/mcp/src/tools/query-wrapper-factory.ts.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast
from uuid import uuid4

import pytest

from django.test import SimpleTestCase

from products.subscriptions.backend.models import OutcomePlan
from products.subscriptions.backend.pulse.contracts import (
    CanonicalMeasurement,
    MeasurementCandidate,
    MeasurementEvidence,
)
from products.subscriptions.backend.pulse.measurements import (
    MeasurementValidationError,
    canonicalize_measurement,
    evaluate_measurement,
    measurement_identity,
    measurement_metadata,
)
from products.subscriptions.backend.pulse.services import stable_action_key

RUN_ID = uuid4()
WINDOW_START = "2026-01-01T00:00:00+00:00"
WINDOW_END = "2026-01-08T00:00:00+00:00"
READOUT_AT = datetime(2026, 1, 15, tzinfo=UTC)
_ROOT = Path(__file__).parents[5]


def candidate(
    *,
    tool_call_id: str,
    selector: dict[str, str] | None = None,
    direction: Literal["increase", "decrease", "maintain"] = "increase",
) -> MeasurementCandidate:
    return MeasurementCandidate(
        run_id=RUN_ID,
        baseline_tool_call_id=tool_call_id,
        metric_name="Checkout completion",
        metric_unit="percent",
        direction=direction,
        expected_change_type="absolute",
        expected_change_lower=Decimal("1"),
        expected_change_upper=Decimal("5"),
        readout_after_days=7,
        selector=selector or {},
    )


def evidence(
    *, tool_name: str, arguments: dict[str, object], result: object, schema: str = "v1"
) -> MeasurementEvidence:
    return MeasurementEvidence(
        run_id=RUN_ID,
        tool_call_id="baseline",
        tool_name=tool_name,
        tool_schema_version=schema,
        arguments=arguments,
        result=result,
        completed_at=datetime(2026, 1, 8, tzinfo=UTC),
    )


def metric_arguments(start: str = WINDOW_START, end: str = WINDOW_END) -> dict[str, object]:
    return {"name": "checkout-completion", "date_from": start, "date_to": end, "interval": "day"}


def query_arguments(tool_name: str, start: str = WINDOW_START, end: str = WINDOW_END) -> dict[str, object]:
    series = [{"kind": "EventsNode", "event": "purchase"}]
    if tool_name == "query-funnel":
        series = [{"kind": "EventsNode", "event": "checkout_started"}, *series]
    return {
        "series": series,
        "dateRange": {"date_from": start, "date_to": end},
        "output_format": "json",
    }


def wrapper_result(
    tool_name: str, arguments: dict[str, object], count: str, *, project_test_filter: bool | None = None
) -> dict[str, object]:
    query = dict(arguments)
    query.pop("output_format", None)
    query["kind"] = "TrendsQuery" if tool_name == "query-trends" else "FunnelsQuery"
    query.setdefault("properties", [])
    if project_test_filter is not None:
        query.setdefault("filterTestAccounts", project_test_filter)
    if tool_name == "query-trends":
        query.setdefault("interval", "day")
    series = query["series"]
    assert isinstance(series, list)
    results: list[dict[str, object]] = []
    if tool_name == "query-trends":
        node = series[0]
        assert isinstance(node, dict)
        identifier = node["event"] if node["kind"] == "EventsNode" else node["id"]
        results.append(
            {
                "action": {
                    "id": identifier,
                    "type": "events" if node["kind"] == "EventsNode" else "actions",
                    "order": 0,
                    "name": str(identifier),
                    "custom_name": None,
                    "math": None,
                    "math_property": None,
                    "properties": {},
                },
                "label": str(identifier),
                "count": count,
                "data": [],
                "labels": [],
                "days": [],
            }
        )
    else:
        for index, node in enumerate(series):
            assert isinstance(node, dict)
            identifier = node["event"] if node["kind"] == "EventsNode" else node["id"]
            results.append(
                {
                    "action_id": identifier,
                    "name": str(identifier),
                    "custom_name": None,
                    "order": index,
                    "people": [],
                    "count": count,
                    "type": "events" if node["kind"] == "EventsNode" else "actions",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                }
            )
    return {"query": query, "results": results}


@pytest.mark.parametrize(
    ("tool_name", "schema_file", "required", "arguments", "result", "selector", "baseline"),
    [
        (
            "data-catalog-metric-run",
            "data-catalog-metric-run.json",
            {"name"},
            metric_arguments(),
            {
                "status": "approved",
                "is_drifted": False,
                "unit": "count",
                "kind": "EventsNode",
                "results": [{"count": "12"}],
            },
            {},
            Decimal("12"),
        ),
        (
            "query-trends",
            "query-trends.json",
            {"series"},
            query_arguments("query-trends"),
            wrapper_result("query-trends", query_arguments("query-trends"), "34"),
            {"series_index": "0"},
            Decimal("34"),
        ),
        (
            "query-funnel",
            "query-funnel.json",
            {"series"},
            query_arguments("query-funnel"),
            wrapper_result("query-funnel", query_arguments("query-funnel"), "45"),
            {"series_index": "0"},
            Decimal("45"),
        ),
    ],
)
def test_canonicalizes_schema_derived_arguments_and_successful_result_shapes(
    tool_name: str,
    schema_file: str,
    required: set[str],
    arguments: dict[str, object],
    result: dict[str, object],
    selector: dict[str, str],
    baseline: Decimal,
) -> None:
    schema = json.loads((_ROOT / "services/mcp/tests/unit/__snapshots__/tool-schemas" / schema_file).read_text())
    assert required <= set(schema["required"])
    if tool_name == "data-catalog-metric-run":
        assert "name" in schema["properties"]
    else:
        assert "dateRange" in schema["properties"]
    canonical = canonicalize_measurement(
        candidate=candidate(tool_call_id="baseline", selector=selector),
        evidence=evidence(tool_name=tool_name, arguments=arguments, result=result),
    )
    assert canonical.baseline_value == baseline
    assert canonical.baseline_from.isoformat() == WINDOW_START
    expected_arguments = result["query"] if tool_name.startswith("query-") else arguments
    assert canonical.spec["replay_arguments"] == expected_arguments


class TestMeasurementValidation(SimpleTestCase):
    def test_distinct_event_series_have_distinct_proposal_metric_identities(self) -> None:
        measurements: list[CanonicalMeasurement] = []
        for event_name in ("$pageview", "purchase"):
            arguments = query_arguments("query-trends")
            series = arguments["series"]
            assert isinstance(series, list) and isinstance(series[0], dict)
            cast(dict[str, object], series[0])["event"] = event_name
            measurements.append(
                canonicalize_measurement(
                    candidate=candidate(tool_call_id="baseline", selector={"series_index": "0"}),
                    evidence=evidence(
                        tool_name="query-trends",
                        arguments=arguments,
                        result=wrapper_result("query-trends", arguments, "12"),
                    ),
                )
            )

        identities = [measurement_identity(specification=item.spec) for item in measurements]
        assert identities[0] != identities[1]
        proposal_keys = {
            stable_action_key(kind="recommendation", normalized_target={"area": "checkout"}, metric_name=identity)
            for identity in identities
        }
        assert len(proposal_keys) == 2

    def test_query_identity_tracks_scalar_filters_and_complete_funnel_but_not_labels(self) -> None:
        def identity(tool_name: str, arguments: dict[str, object], selector: dict[str, str]) -> str:
            canonical = canonicalize_measurement(
                candidate=candidate(tool_call_id="baseline", selector=selector),
                evidence=evidence(
                    tool_name=tool_name,
                    arguments=arguments,
                    result=wrapper_result(tool_name, arguments, "12"),
                ),
            )
            return measurement_identity(specification=canonical.spec)

        country_us = query_arguments("query-trends")
        country_us["properties"] = [{"key": "country", "value": "US", "type": "event"}]
        country_nl = query_arguments("query-trends")
        country_nl["properties"] = [{"key": "country", "value": "NL", "type": "event"}]
        assert identity("query-trends", country_us, {"series_index": "0"}) != identity(
            "query-trends", country_nl, {"series_index": "0"}
        )

        filters_a = query_arguments("query-trends")
        filters_a["properties"] = [
            {"key": "country", "value": ["US", "NL"], "type": "event", "operator": "exact"},
            {"key": "browser", "value": "Chrome", "type": "event"},
        ]
        filters_b = query_arguments("query-trends")
        filters_b["properties"] = [
            {"key": "browser", "value": "Chrome", "type": "event"},
            {"key": "country", "value": ["NL", "US"], "type": "event", "operator": "exact"},
        ]
        assert identity("query-trends", filters_a, {"series_index": "0"}) == identity(
            "query-trends", filters_b, {"series_index": "0"}
        )

        label_a = query_arguments("query-trends")
        label_b = query_arguments("query-trends")
        for arguments, label in ((label_a, "Purchases"), (label_b, "Orders")):
            series = arguments["series"]
            assert isinstance(series, list) and isinstance(series[0], dict)
            series_node = cast(dict[str, object], series[0])
            series_node["custom_name"] = label
            series_node["name"] = label
        assert identity("query-trends", label_a, {"series_index": "0"}) == identity(
            "query-trends", label_b, {"series_index": "0"}
        )

        first_funnel = query_arguments("query-funnel")
        second_funnel = query_arguments("query-funnel")
        second_series = second_funnel["series"]
        assert isinstance(second_series, list) and isinstance(second_series[0], dict)
        cast(dict[str, object], second_series[0])["event"] = "product_viewed"
        assert identity("query-funnel", first_funnel, {"series_index": "1"}) != identity(
            "query-funnel", second_funnel, {"series_index": "1"}
        )

        total_reference = query_arguments("query-funnel")
        total_reference["funnelsFilter"] = {"funnelVizType": "steps", "funnelStepReference": "total"}
        previous_reference = query_arguments("query-funnel")
        previous_reference["funnelsFilter"] = {"funnelVizType": "steps", "funnelStepReference": "previous"}
        assert identity("query-funnel", total_reference, {"series_index": "1"}) == identity(
            "query-funnel", previous_reference, {"series_index": "1"}
        )

        exclusions = [
            {
                "kind": "EventsNode",
                "event": "payment_failed",
                "funnelFromStep": 0,
                "funnelToStep": 1,
            },
            {
                "kind": "EventsNode",
                "event": "checkout_abandoned",
                "funnelFromStep": 0,
                "funnelToStep": 1,
            },
        ]
        exclusions_a = query_arguments("query-funnel")
        exclusions_a["funnelsFilter"] = {"funnelVizType": "steps", "exclusions": exclusions}
        exclusions_b = query_arguments("query-funnel")
        exclusions_b["funnelsFilter"] = {"funnelVizType": "steps", "exclusions": list(reversed(exclusions))}
        assert identity("query-funnel", exclusions_a, {"series_index": "1"}) == identity(
            "query-funnel", exclusions_b, {"series_index": "1"}
        )

    def test_rejects_derived_broken_down_and_nonstep_query_counts(self) -> None:
        trend_mutations: tuple[dict[str, object], ...] = (
            {"breakdownFilter": {"breakdown": "country", "breakdown_type": "event"}},
            {"compareFilter": {"compare": True}},
        )
        for mutation in trend_mutations:
            arguments = {**query_arguments("query-trends"), **mutation}
            with self.subTest(trend_mutation=mutation), self.assertRaises(MeasurementValidationError):
                canonicalize_measurement(
                    candidate=candidate(tool_call_id="baseline", selector={"series_index": "0"}),
                    evidence=evidence(
                        tool_name="query-trends",
                        arguments=arguments,
                        result=wrapper_result("query-trends", arguments, "12"),
                    ),
                )

        scaled = query_arguments("query-trends")
        scaled_series = scaled["series"]
        assert isinstance(scaled_series, list) and isinstance(scaled_series[0], dict)
        cast(dict[str, object], scaled_series[0])["math_multiplier"] = 2
        with self.assertRaises(MeasurementValidationError):
            canonicalize_measurement(
                candidate=candidate(tool_call_id="baseline", selector={"series_index": "0"}),
                evidence=evidence(
                    tool_name="query-trends",
                    arguments=scaled,
                    result=wrapper_result("query-trends", scaled, "24"),
                ),
            )

        multi_series = query_arguments("query-trends")
        multi_series_values = multi_series["series"]
        assert isinstance(multi_series_values, list)
        multi_series_values.append({"kind": "EventsNode", "event": "$pageview"})
        with self.assertRaises(MeasurementValidationError):
            canonicalize_measurement(
                candidate=candidate(tool_call_id="baseline", selector={"series_index": "0"}),
                evidence=evidence(
                    tool_name="query-trends",
                    arguments=multi_series,
                    result=wrapper_result("query-trends", multi_series, "12"),
                ),
            )

        funnel = query_arguments("query-funnel")
        funnel["funnelsFilter"] = {"funnelVizType": "time_to_convert"}
        with self.assertRaises(MeasurementValidationError):
            canonicalize_measurement(
                candidate=candidate(tool_call_id="baseline", selector={"series_index": "1"}),
                evidence=evidence(
                    tool_name="query-funnel",
                    arguments=funnel,
                    result=wrapper_result("query-funnel", funnel, "12"),
                ),
            )

    def test_rejects_production_shaped_breakdown_results(self) -> None:
        arguments = query_arguments("query-trends")
        result = wrapper_result("query-trends", arguments, "12")
        results = result["results"]
        assert isinstance(results, list) and isinstance(results[0], dict)
        cast(dict[str, object], results[0])["breakdown_value"] = "US"

        with self.assertRaises(MeasurementValidationError):
            canonicalize_measurement(
                candidate=candidate(tool_call_id="baseline", selector={"series_index": "0"}),
                evidence=evidence(tool_name="query-trends", arguments=arguments, result=result),
            )

    def test_rejects_noncount_catalog_units_and_fractional_counts(self) -> None:
        for unit, count in (("percent", "12"), ("count", "12.5")):
            with self.subTest(unit=unit, count=count), self.assertRaises(MeasurementValidationError):
                canonicalize_measurement(
                    candidate=candidate(tool_call_id="baseline"),
                    evidence=evidence(
                        tool_name="data-catalog-metric-run",
                        arguments=metric_arguments(),
                        result={
                            "status": "approved",
                            "is_drifted": False,
                            "unit": unit,
                            "kind": "EventsNode",
                            "results": [{"count": count}],
                        },
                    ),
                )

    def test_rejects_missing_adapter_metric_identity(self) -> None:
        arguments = query_arguments("query-trends")
        arguments["series"] = [{}]

        with self.assertRaises(MeasurementValidationError):
            canonicalize_measurement(
                candidate=candidate(tool_call_id="baseline", selector={"series_index": "0"}),
                evidence=evidence(
                    tool_name="query-trends",
                    arguments=arguments,
                    result={"query": arguments, "results": []},
                ),
            )

    def test_adapter_owns_the_count_metric_metadata(self) -> None:
        canonical = canonicalize_measurement(
            candidate=candidate(tool_call_id="baseline"),
            evidence=evidence(
                tool_name="data-catalog-metric-run",
                arguments=metric_arguments(),
                result={
                    "status": "approved",
                    "is_drifted": False,
                    "unit": "count",
                    "kind": "EventsNode",
                    "results": [{"count": "12"}],
                },
            ),
        )

        assert canonical.metric_name == "Metric checkout-completion"
        assert canonical.metric_unit == "count"
        assert measurement_metadata(specification=canonical.spec) == ("Metric checkout-completion", "count")

    def test_rejects_model_paths_unknown_selectors_and_nonfinite_json_anywhere(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(MeasurementValidationError):
                canonicalize_measurement(
                    candidate=candidate(tool_call_id="baseline"),
                    evidence=evidence(
                        tool_name="data-catalog-metric-run",
                        arguments={**metric_arguments(), "query_id": value},
                        result={
                            "status": "approved",
                            "is_drifted": False,
                            "unit": "count",
                            "kind": "EventsNode",
                            "results": [{"count": "1"}],
                        },
                    ),
                )
        with self.assertRaises(MeasurementValidationError):
            canonicalize_measurement(
                candidate=candidate(tool_call_id="baseline", selector={"json_path": "$.results"}),
                evidence=evidence(
                    tool_name="query-trends",
                    arguments=query_arguments("query-trends"),
                    result=wrapper_result("query-trends", query_arguments("query-trends"), "1"),
                ),
            )

    def test_rejects_relative_ranges_and_stale_identifiers(self) -> None:
        with self.assertRaises(MeasurementValidationError):
            canonicalize_measurement(
                candidate=candidate(tool_call_id="baseline"),
                evidence=evidence(
                    tool_name="query-funnel", arguments={"series": [], "dateRange": {"date_from": "-7d"}}, result={}
                ),
            )
        with self.assertRaises(MeasurementValidationError):
            canonicalize_measurement(
                candidate=candidate(tool_call_id="baseline"),
                evidence=evidence(
                    tool_name="data-catalog-metric-run",
                    arguments={"metric_id": "old", "date_from": WINDOW_START, "date_to": WINDOW_END},
                    result={},
                ),
            )

    def test_accepts_only_wrapper_defaults_and_persists_the_trusted_executed_query(self) -> None:
        for tool_name in ("query-trends", "query-funnel"):
            with self.subTest(tool_name=tool_name):
                raw = query_arguments(tool_name)
                result = wrapper_result(tool_name, raw, "34", project_test_filter=True)

                canonical = canonicalize_measurement(
                    candidate=candidate(tool_call_id="baseline", selector={"series_index": "0"}),
                    evidence=evidence(tool_name=tool_name, arguments=raw, result=result),
                )

                replay_arguments = canonical.spec["replay_arguments"]
                assert isinstance(replay_arguments, dict)
                assert replay_arguments == result["query"]
                assert replay_arguments["filterTestAccounts"] is True
                if tool_name == "query-trends":
                    assert replay_arguments["interval"] == "day"
                assert replay_arguments["properties"] == []

    def test_rejects_wrapper_result_widening_or_changes(self) -> None:
        for mutation in (
            {"kind": "FunnelsQuery"},
            {"series": [{"kind": "EventsNode", "event": "other"}]},
            {"dateRange": {"date_from": WINDOW_START, "date_to": "2026-01-09T00:00:00+00:00"}},
            {"properties": [{"key": "email", "value": "x", "type": "person"}]},
            {"filterTestAccounts": False},
            {"unexpected": "widening"},
        ):
            with self.subTest(mutation=mutation):
                raw = query_arguments("query-trends")
                result = wrapper_result("query-trends", raw, "34")
                query = result["query"]
                assert isinstance(query, dict)
                query.update(mutation)

                with self.assertRaises(MeasurementValidationError):
                    canonicalize_measurement(
                        candidate=candidate(tool_call_id="baseline", selector={"series_index": "0"}),
                        evidence=evidence(tool_name="query-trends", arguments=raw, result=result),
                    )


class TestMeasurementEvaluation(SimpleTestCase):
    def _plan(
        self,
        canonical: CanonicalMeasurement,
        baseline: Decimal,
        direction: Literal["increase", "decrease", "maintain"] = "increase",
    ) -> OutcomePlan:
        return cast(
            OutcomePlan,
            SimpleNamespace(
                measurement_spec=canonical.spec,
                baseline_value=baseline,
                baseline_from=canonical.baseline_from,
                baseline_to=canonical.baseline_to,
                next_readout_at=READOUT_AT,
                source_action=SimpleNamespace(metric_direction=direction),
            ),
        )

    def test_requires_the_full_adapter_derived_window_and_immutable_arguments(self) -> None:
        canonical = canonicalize_measurement(
            candidate=candidate(tool_call_id="baseline"),
            evidence=evidence(
                tool_name="data-catalog-metric-run",
                arguments=metric_arguments(),
                result={
                    "status": "approved",
                    "is_drifted": False,
                    "unit": "count",
                    "kind": "EventsNode",
                    "results": [{"count": "10"}],
                },
            ),
        )
        plan = self._plan(canonical, Decimal("10"))
        expected = metric_arguments("2026-01-08T00:00:00+00:00", "2026-01-15T00:00:00+00:00")
        good = evaluate_measurement(
            plan=plan,
            evidence=evidence(
                tool_name="data-catalog-metric-run",
                arguments=expected,
                result={
                    "status": "approved",
                    "is_drifted": False,
                    "unit": "count",
                    "kind": "EventsNode",
                    "results": [{"count": "15"}],
                },
            ),
        )
        arbitrary = evaluate_measurement(
            plan=plan,
            evidence=evidence(
                tool_name="data-catalog-metric-run",
                arguments=metric_arguments("2026-01-10T00:00:00+00:00", "2026-01-15T00:00:00+00:00"),
                result={
                    "status": "approved",
                    "is_drifted": False,
                    "unit": "count",
                    "kind": "EventsNode",
                    "results": [{"count": "15"}],
                },
            ),
        )
        assert good.verdict == "improved"
        assert arbitrary.failure_code == "measurement_arguments_changed"

    def test_nested_date_range_replay_and_zero_baseline_are_canonical(self) -> None:
        baseline_args = query_arguments("query-trends")
        canonical = canonicalize_measurement(
            candidate=candidate(tool_call_id="baseline", selector={"series_index": "0"}),
            evidence=evidence(
                tool_name="query-trends",
                arguments=baseline_args,
                result=wrapper_result("query-trends", baseline_args, "0"),
            ),
        )
        observed_args = query_arguments("query-trends", "2026-01-08T00:00:00+00:00", "2026-01-15T00:00:00+00:00")
        evaluation = evaluate_measurement(
            plan=self._plan(canonical, Decimal("0")),
            evidence=evidence(
                tool_name="query-trends",
                arguments=observed_args,
                result=wrapper_result("query-trends", observed_args, "5"),
            ),
        )
        assert evaluation.relative_delta is None
        assert evaluation.verdict == "improved"

    def test_readout_requires_the_full_canonical_executed_query(self) -> None:
        baseline_args = query_arguments("query-trends")
        canonical = canonicalize_measurement(
            candidate=candidate(tool_call_id="baseline", selector={"series_index": "0"}),
            evidence=evidence(
                tool_name="query-trends",
                arguments=baseline_args,
                result=wrapper_result("query-trends", baseline_args, "10", project_test_filter=True),
            ),
        )
        observed_args = query_arguments("query-trends", "2026-01-08T00:00:00+00:00", "2026-01-15T00:00:00+00:00")
        evaluation = evaluate_measurement(
            plan=self._plan(canonical, Decimal("10")),
            evidence=evidence(
                tool_name="query-trends",
                arguments=observed_args,
                result=wrapper_result("query-trends", observed_args, "12"),
            ),
        )

        assert evaluation.status == "inconclusive"
        assert evaluation.failure_code == "measurement_arguments_changed"

    def test_maintain_uses_adapter_tolerance(self) -> None:
        canonical = canonicalize_measurement(
            candidate=candidate(tool_call_id="baseline", direction="maintain"),
            evidence=evidence(
                tool_name="data-catalog-metric-run",
                arguments=metric_arguments(),
                result={
                    "status": "approved",
                    "is_drifted": False,
                    "unit": "count",
                    "kind": "EventsNode",
                    "results": [{"count": "100"}],
                },
            ),
        )
        evaluation = evaluate_measurement(
            plan=self._plan(canonical, Decimal("100"), "maintain"),
            evidence=evidence(
                tool_name="data-catalog-metric-run",
                arguments=metric_arguments("2026-01-08T00:00:00+00:00", "2026-01-15T00:00:00+00:00"),
                result={
                    "status": "approved",
                    "is_drifted": False,
                    "unit": "count",
                    "kind": "EventsNode",
                    "results": [{"count": "101"}],
                },
            ),
        )
        assert evaluation.verdict == "flat"
