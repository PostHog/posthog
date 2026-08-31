"""Canonical, adapter-owned Pulse measurement replay."""

import re
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import isfinite
from typing import Literal, TypedDict, cast

from posthog.dataclasses import frozen

from products.subscriptions.backend.models import OutcomePlan

from .contracts import (
    CanonicalMeasurement,
    MeasurementCandidate,
    MeasurementEvidence,
    OutcomeEvaluation,
    OutcomeReplayInstructionDTO,
)


class MeasurementValidationError(ValueError):
    pass


@frozen
class _MeasurementWindow:
    start: datetime
    end: datetime


_DIRECTIONS = frozenset({"increase", "decrease", "maintain"})
_EXPECTED_CHANGE_TYPES = frozenset({"absolute", "relative_percent"})
_READOUT_WINDOWS = frozenset({3, 7, 14, 28})
_METRIC_ARGUMENTS = frozenset({"name", "date_from", "date_to", "interval", "query_id", "refresh"})
_QUERY_ARGUMENTS = frozenset(
    {
        "aggregation_group_type_index",
        "breakdownFilter",
        "compareFilter",
        "dataColorTheme",
        "dateRange",
        "filterTestAccounts",
        "interval",
        "kind",
        "modifiers",
        "output_format",
        "properties",
        "response",
        "samplingFactor",
        "series",
        "tags",
        "version",
    }
)
_TREND_ARGUMENTS = _QUERY_ARGUMENTS | frozenset({"calendarHeatmapFilter", "conversionGoal", "trendsFilter"})
_FUNNEL_ARGUMENTS = _QUERY_ARGUMENTS | frozenset({"funnelsFilter"})
_SERIES_NODE_ARGUMENTS = frozenset(
    {
        "custom_name",
        "event",
        "fixedProperties",
        "id",
        "kind",
        "math",
        "math_group_type_index",
        "math_hogql",
        "math_multiplier",
        "math_property",
        "math_property_revenue_currency",
        "math_property_type",
        "name",
        "optionalInFunnel",
        "properties",
        "response",
        "version",
    }
)
_FUNNEL_FILTER_ARGUMENTS = frozenset(
    {
        "exclusions",
        "funnelFromStep",
        "funnelOrderType",
        "funnelStepReference",
        "funnelToStep",
        "funnelVizType",
        "funnelWindowInterval",
        "funnelWindowIntervalUnit",
    }
)
_FUNNEL_FILTER_DEFAULTS: dict[str, object] = {
    "exclusions": [],
    "funnelFromStep": None,
    "funnelOrderType": "ordered",
    "funnelStepReference": "total",
    "funnelToStep": None,
    "funnelVizType": "steps",
    "funnelWindowInterval": 14,
    "funnelWindowIntervalUnit": "day",
}
_WRAPPER_DEFAULTS = {
    "query-trends": {"kind", "interval", "properties", "filterTestAccounts"},
    "query-funnel": {"kind", "properties", "filterTestAccounts"},
}
_METRIC_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class _MeasurementSpec(TypedDict):
    tool_name: str
    tool_schema_version: str
    selector: dict[str, str]
    replay_arguments: dict[str, object]
    extraction_kind: str


class _MeasurementAdapter:
    def __init__(
        self,
        *,
        tool_name: str,
        extraction_kind: str,
        allowed_selector_keys: frozenset[str],
        neutral_tolerance: Decimal,
    ) -> None:
        self.tool_name = tool_name
        self.tool_schema_version = "v1"
        self.extraction_kind = extraction_kind
        self.metric_unit: Literal["count"] = "count"
        self.allowed_selector_keys = allowed_selector_keys
        self.neutral_tolerance = neutral_tolerance

    def validate_selector(self, selector: dict[str, str]) -> dict[str, str]:
        if set(selector) - self.allowed_selector_keys or any(not isinstance(value, str) for value in selector.values()):
            raise MeasurementValidationError("Measurement selector is not supported by this adapter.")
        if self.tool_name in {"query-trends", "query-funnel"}:
            value = selector.get("series_index")
            if value is None or not value.isdecimal():
                raise MeasurementValidationError("Series measurements require a numeric series_index selector.")
        elif selector:
            raise MeasurementValidationError("This adapter does not accept a measurement selector.")
        return dict(sorted(selector.items()))

    def canonicalize_arguments(self, arguments: dict[str, object]) -> dict[str, object]:
        copied = _json_object(arguments, message="Measurement arguments must be a JSON object.")
        window = self._window(copied)
        if window.start >= window.end:
            raise MeasurementValidationError("Measurement comparison window is invalid.")
        self._validate_immutable_arguments(copied)
        return copied

    def comparison_arguments(
        self,
        *,
        original: dict[str, object],
        baseline_from: datetime,
        baseline_to: datetime,
        readout_at: datetime | None,
    ) -> dict[str, object]:
        if readout_at is None:
            raise MeasurementValidationError("Measurement readout time is unavailable.")
        if readout_at.tzinfo is None:
            raise MeasurementValidationError("Measurement readout time is invalid.")
        expected_from = readout_at - (baseline_to - baseline_from)
        expected_to = readout_at
        comparison = _json_object(original, message="Measurement arguments must be a JSON object.")
        if self.tool_name == "data-catalog-metric-run":
            comparison["date_from"] = expected_from.isoformat()
            comparison["date_to"] = expected_to.isoformat()
        else:
            date_range = cast(dict[str, object], comparison["dateRange"])
            date_range["date_from"] = expected_from.isoformat()
            date_range["date_to"] = expected_to.isoformat()
        return comparison

    def observed_window(self, arguments: dict[str, object]) -> _MeasurementWindow:
        return self._window(arguments)

    def _window(self, arguments: dict[str, object]) -> _MeasurementWindow:
        if self.tool_name == "data-catalog-metric-run":
            return _window_values(arguments)
        date_range = arguments.get("dateRange")
        if not isinstance(date_range, dict):
            raise MeasurementValidationError("Query measurements require an absolute dateRange.")
        return _window_values(date_range)

    def _validate_immutable_arguments(self, arguments: dict[str, object]) -> None:
        if self.tool_name == "data-catalog-metric-run":
            if set(arguments) - _METRIC_ARGUMENTS or not isinstance(arguments.get("name"), str):
                raise MeasurementValidationError("Metric measurements require the generated name identifier.")
            return
        allowed_arguments = _TREND_ARGUMENTS if self.tool_name == "query-trends" else _FUNNEL_ARGUMENTS
        expected_kind = "TrendsQuery" if self.tool_name == "query-trends" else "FunnelsQuery"
        series = arguments.get("series")
        if (
            set(arguments) - allowed_arguments
            or arguments.get("kind", expected_kind) != expected_kind
            or not isinstance(series, list)
        ):
            raise MeasurementValidationError(f"{expected_kind} measurement arguments are unsupported.")
        unsupported = {
            "aggregation_group_type_index",
            "breakdownFilter",
            "compareFilter",
            "modifiers",
            "response",
            "samplingFactor",
        }
        if self.tool_name == "query-trends":
            unsupported |= {"calendarHeatmapFilter", "conversionGoal", "trendsFilter"}
        if any(arguments.get(key) is not None for key in unsupported):
            raise MeasurementValidationError("Query measurement contains an ambiguous aggregation or comparison.")
        if arguments.get("filterTestAccounts") not in (None, False, True):
            raise MeasurementValidationError("Query measurement test-account policy is invalid.")
        if self.tool_name == "query-trends" and len(series) != 1:
            raise MeasurementValidationError("Trend measurements require exactly one total-count series.")
        if self.tool_name == "query-funnel" and len(series) < 2:
            raise MeasurementValidationError("Funnel measurements require at least two ordered steps.")
        for node in series:
            self._validate_series_node(node)
        if self.tool_name == "query-funnel":
            self._validate_funnel_filter(arguments.get("funnelsFilter"))

    def _validate_series_node(self, value: object) -> None:
        if not isinstance(value, dict) or set(value) - _SERIES_NODE_ARGUMENTS:
            raise MeasurementValidationError("Query measurement series shape is unsupported.")
        kind = value.get("kind")
        if kind == "EventsNode":
            if not isinstance(value.get("event"), str) or not value["event"]:
                raise MeasurementValidationError("Event count measurements require an event identifier.")
        elif kind == "ActionsNode":
            if not isinstance(value.get("id"), int) or isinstance(value.get("id"), bool):
                raise MeasurementValidationError("Action count measurements require an action identifier.")
        else:
            raise MeasurementValidationError("Only event and action count series are supported.")
        if value.get("math") not in (None, "total"):
            raise MeasurementValidationError("Query measurements require total-count series.")
        derived_fields = {
            "math_group_type_index",
            "math_hogql",
            "math_multiplier",
            "math_property",
            "math_property_revenue_currency",
            "math_property_type",
            "response",
        }
        if any(value.get(key) is not None for key in derived_fields):
            raise MeasurementValidationError("Query measurements do not support derived or scaled series.")

    def _validate_funnel_filter(self, value: object) -> None:
        if value is None:
            return
        if not isinstance(value, dict) or set(value) - _FUNNEL_FILTER_ARGUMENTS:
            raise MeasurementValidationError("Funnel measurement settings are unsupported.")
        if value.get("funnelVizType", "steps") not in (None, "steps"):
            raise MeasurementValidationError("Funnel measurements require step-count visualization.")

    def canonical_replay_arguments(self, *, arguments: dict[str, object], result: object) -> dict[str, object]:
        raw_arguments = self.canonicalize_arguments(arguments)
        if self.tool_name not in _WRAPPER_DEFAULTS:
            return raw_arguments
        if not isinstance(result, dict) or not isinstance(result.get("query"), dict):
            raise MeasurementValidationError("Query result shape is unsupported.")
        executed = _json_object(result["query"], message="Query result shape is unsupported.")
        self.canonicalize_arguments(executed)
        raw_query = _json_object(raw_arguments, message="Measurement arguments must be a JSON object.")
        raw_query.pop("output_format", None)
        expected_kind = "TrendsQuery" if self.tool_name == "query-trends" else "FunnelsQuery"
        if executed.get("kind") != expected_kind:
            raise MeasurementValidationError("Query result kind is unsupported.")
        for key, value in raw_query.items():
            if executed.get(key) != value:
                raise MeasurementValidationError("Query result changed measurement arguments.")
        added = set(executed) - set(raw_query)
        if not added <= _WRAPPER_DEFAULTS[self.tool_name] or not self._valid_wrapper_defaults(executed, added):
            raise MeasurementValidationError("Query result widened measurement arguments.")
        return executed

    def _valid_wrapper_defaults(self, executed: dict[str, object], added: set[str]) -> bool:
        if "kind" in added and executed["kind"] != (
            "TrendsQuery" if self.tool_name == "query-trends" else "FunnelsQuery"
        ):
            return False
        if "properties" in added and executed["properties"] != []:
            return False
        if "filterTestAccounts" in added and executed["filterTestAccounts"] is not True:
            return False
        return "interval" not in added or (self.tool_name == "query-trends" and executed["interval"] == "day")

    def extract_value(self, *, result: object, selector: dict[str, str], arguments: dict[str, object]) -> Decimal:
        if self.tool_name == "data-catalog-metric-run":
            if (
                not isinstance(result, dict)
                or result.get("status") != "approved"
                or result.get("is_drifted") is not False
                or result.get("unit") != "count"
                or result.get("kind") != "EventsNode"
            ):
                raise MeasurementValidationError("Metric result shape is unsupported.")
            return _count_at(result.get("results"), 0)
        if not isinstance(result, dict) or result.get("query") != arguments:
            raise MeasurementValidationError("Query result does not match the executed measurement arguments.")
        series = self._selected_series(arguments=arguments, selector=selector)
        results = result.get("results")
        index = int(selector["series_index"])
        if self.tool_name == "query-trends":
            if index != 0 or not isinstance(results, list) or len(results) != 1:
                raise MeasurementValidationError("Trend result must contain one unbroken total-count series.")
            self._validate_trend_result_item(value=results[0], series=series)
        else:
            all_series = arguments["series"]
            if not isinstance(all_series, list) or not isinstance(results, list) or len(results) != len(all_series):
                raise MeasurementValidationError("Funnel result must contain one row for every declared step.")
            for step_index, (step_result, step_series) in enumerate(zip(results, all_series, strict=True)):
                if not isinstance(step_series, dict):
                    raise MeasurementValidationError("Funnel series shape is unsupported.")
                self._validate_funnel_result_item(value=step_result, series=step_series, index=step_index)
        return _count_at(results, index)

    def _validate_trend_result_item(self, *, value: object, series: dict[str, object]) -> None:
        if not isinstance(value, dict) or "breakdown" in value or "breakdown_value" in value:
            raise MeasurementValidationError("Trend result contains an ambiguous breakdown.")
        action = value.get("action")
        if not isinstance(action, dict) or action.get("order") != 0:
            raise MeasurementValidationError("Trend result is not bound to the declared series.")
        self._validate_result_source(value=action, series=series, identifier_key="id")

    def _validate_funnel_result_item(self, *, value: object, series: dict[str, object], index: int) -> None:
        if (
            not isinstance(value, dict)
            or value.get("order") != index
            or "breakdown" in value
            or "breakdown_value" in value
        ):
            raise MeasurementValidationError("Funnel result is not an unbroken ordered step result.")
        self._validate_result_source(value=value, series=series, identifier_key="action_id")
        _count_at([value], 0)

    def _validate_result_source(
        self, *, value: dict[str, object], series: dict[str, object], identifier_key: str
    ) -> None:
        if series["kind"] == "EventsNode":
            expected_type, expected_identifier = "events", series["event"]
        else:
            expected_type, expected_identifier = "actions", series["id"]
        if value.get("type") != expected_type or str(value.get(identifier_key)) != str(expected_identifier):
            raise MeasurementValidationError("Query result is not bound to the declared series.")

    def metric_name(self, *, arguments: dict[str, object], selector: dict[str, str]) -> str:
        if self.tool_name == "data-catalog-metric-run":
            return f"Metric {_metric_identifier(arguments.get('name'))}"
        series = self._selected_series(arguments=arguments, selector=selector)
        index = int(selector["series_index"])
        source_kind = _metric_identifier(series.get("kind"))
        prefix = "Trend" if self.tool_name == "query-trends" else "Funnel"
        return f"{prefix} {source_kind} series {index + 1}"

    def metric_identity(self, *, arguments: dict[str, object], selector: dict[str, str]) -> str:
        if self.tool_name == "data-catalog-metric-run":
            return f"catalog:{_metric_identifier(arguments.get('name'))}"
        self._selected_series(arguments=arguments, selector=selector)
        payload = {
            "tool_name": self.tool_name,
            "series_index": selector["series_index"],
            "query": self._semantic_query(arguments),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        return f"{self.tool_name}:sha256:{sha256(encoded).hexdigest()}"

    def _semantic_query(self, arguments: dict[str, object]) -> dict[str, object]:
        query = _json_object(arguments, message="Measurement arguments must be a JSON object.")
        for key in ("dataColorTheme", "dateRange", "interval", "output_format", "response", "tags"):
            query.pop(key, None)
        if query.get("filterTestAccounts") is None or query.get("filterTestAccounts") is False:
            query.pop("filterTestAccounts", None)
        if query.get("version") is None:
            query.pop("version", None)
        if query.get("properties") is None or query.get("properties") == []:
            query.pop("properties", None)
        else:
            query["properties"] = self._semantic_properties(query["properties"])
        series = query.get("series")
        if not isinstance(series, list):
            raise MeasurementValidationError("Query measurement series shape is unsupported.")
        query["series"] = [self._semantic_series_node(node) for node in series]
        funnel_filter = query.get("funnelsFilter")
        if isinstance(funnel_filter, dict):
            normalized_filter = {
                key: value
                for key, value in funnel_filter.items()
                if key not in _FUNNEL_FILTER_DEFAULTS or value != _FUNNEL_FILTER_DEFAULTS[key]
            }
            normalized_filter.pop("funnelStepReference", None)
            exclusions = normalized_filter.get("exclusions")
            if isinstance(exclusions, list):
                normalized_filter["exclusions"] = sorted(
                    (self._semantic_properties(item) for item in exclusions), key=_semantic_sort_key
                )
            if normalized_filter:
                query["funnelsFilter"] = normalized_filter
            else:
                query.pop("funnelsFilter", None)
        elif funnel_filter is None:
            query.pop("funnelsFilter", None)
        return query

    def _semantic_series_node(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise MeasurementValidationError("Query measurement series shape is unsupported.")
        node = _json_object(value, message="Query measurement series shape is unsupported.")
        for key in ("custom_name", "name", "response"):
            node.pop(key, None)
        for key in (
            "math_group_type_index",
            "math_hogql",
            "math_multiplier",
            "math_property",
            "math_property_revenue_currency",
            "math_property_type",
        ):
            if node.get(key) is None:
                node.pop(key, None)
        if node.get("math") in (None, "total"):
            node.pop("math", None)
        if node.get("optionalInFunnel") is None or node.get("optionalInFunnel") is False:
            node.pop("optionalInFunnel", None)
        if node.get("version") is None:
            node.pop("version", None)
        for key in ("fixedProperties", "properties"):
            if node.get(key) is None:
                node.pop(key, None)
            else:
                node[key] = self._semantic_properties(node[key])
        return node

    def _semantic_properties(self, value: object) -> object:
        if isinstance(value, list):
            normalized = [self._semantic_properties(item) for item in value]
            return sorted(normalized, key=_semantic_sort_key)
        if not isinstance(value, dict):
            return value
        normalized_object = _json_object(value, message="Measurement properties are invalid.")
        normalized_object.pop("label", None)
        group_values = normalized_object.get("values")
        if normalized_object.get("type") in ("AND", "OR") and isinstance(group_values, list):
            normalized_object["values"] = sorted(
                (self._semantic_properties(item) for item in group_values), key=_semantic_sort_key
            )
        property_value = normalized_object.get("value")
        if isinstance(property_value, list) and normalized_object.get("operator") not in ("between", "not_between"):
            normalized_object["value"] = sorted(property_value, key=_semantic_sort_key)
        return normalized_object

    def _selected_series(self, *, arguments: dict[str, object], selector: dict[str, str]) -> dict[str, object]:
        series = arguments.get("series")
        index = int(selector["series_index"])
        if not isinstance(series, list) or index >= len(series) or not isinstance(series[index], dict):
            raise MeasurementValidationError("Measurement series identity is unsupported.")
        return cast(dict[str, object], series[index])


_REGISTRY: dict[tuple[str, str], _MeasurementAdapter] = {
    ("data-catalog-metric-run", "v1"): _MeasurementAdapter(
        tool_name="data-catalog-metric-run",
        extraction_kind="metric_count",
        allowed_selector_keys=frozenset(),
        neutral_tolerance=Decimal("1"),
    ),
    ("query-trends", "v1"): _MeasurementAdapter(
        tool_name="query-trends",
        extraction_kind="trend_count",
        allowed_selector_keys=frozenset({"series_index"}),
        neutral_tolerance=Decimal("1"),
    ),
    ("query-funnel", "v1"): _MeasurementAdapter(
        tool_name="query-funnel",
        extraction_kind="funnel_count",
        allowed_selector_keys=frozenset({"series_index"}),
        neutral_tolerance=Decimal("1"),
    ),
}


def canonicalize_measurement(*, candidate: MeasurementCandidate, evidence: MeasurementEvidence) -> CanonicalMeasurement:
    """Validate same-run evidence and return a replay spec entirely owned by an adapter."""
    if candidate.run_id != evidence.run_id or candidate.baseline_tool_call_id != evidence.tool_call_id:
        raise MeasurementValidationError("Measurement evidence is not bound to this analysis run.")
    if evidence.completed_at is None or evidence.error_class is not None or evidence.result_truncated:
        raise MeasurementValidationError("Measurement evidence did not complete successfully.")
    if candidate.direction not in _DIRECTIONS or candidate.expected_change_type not in _EXPECTED_CHANGE_TYPES:
        raise MeasurementValidationError("Measurement direction or forecast type is invalid.")
    if candidate.readout_after_days not in _READOUT_WINDOWS:
        raise MeasurementValidationError("Measurement readout window is invalid.")
    lower = _finite_decimal(candidate.expected_change_lower)
    upper = _finite_decimal(candidate.expected_change_upper)
    if lower > upper:
        raise MeasurementValidationError("Measurement forecast range is inverted.")
    adapter = _adapter(tool_name=evidence.tool_name, tool_schema_version=evidence.tool_schema_version)
    selector = adapter.validate_selector(candidate.selector)
    arguments = adapter.canonical_replay_arguments(arguments=evidence.arguments, result=evidence.result)
    baseline_window = adapter.observed_window(arguments)
    baseline_value = adapter.extract_value(result=evidence.result, selector=selector, arguments=arguments)
    return CanonicalMeasurement(
        spec={
            "version": 1,
            "adapter_version": "v1",
            "tool_name": adapter.tool_name,
            "tool_schema_version": adapter.tool_schema_version,
            "replay_arguments": arguments,
            "selector": selector,
            "extraction_kind": adapter.extraction_kind,
        },
        metric_name=adapter.metric_name(arguments=arguments, selector=selector),
        metric_unit=adapter.metric_unit,
        baseline_value=baseline_value,
        baseline_from=baseline_window.start,
        baseline_to=baseline_window.end,
    )


def evaluate_measurement(*, plan: OutcomePlan, evidence: MeasurementEvidence) -> OutcomeEvaluation:
    """Evaluate an adapter-derived readout window without trusting model forecasts or arguments."""
    if evidence.error_class is not None:
        return _inconclusive(evidence.error_class)
    try:
        spec = _measurement_spec(plan.measurement_spec)
        adapter = _adapter_for_spec(spec)
        if evidence.tool_name != adapter.tool_name or evidence.tool_schema_version != adapter.tool_schema_version:
            raise MeasurementValidationError("Measurement tool binding changed.")
        if evidence.completed_at is None or evidence.result_truncated:
            raise MeasurementValidationError("Measurement evidence is incomplete.")
        selector = adapter.validate_selector(spec["selector"])
        original_arguments = adapter.canonicalize_arguments(spec["replay_arguments"])
        expected_arguments = adapter.comparison_arguments(
            original=original_arguments,
            baseline_from=plan.baseline_from,
            baseline_to=plan.baseline_to,
            readout_at=plan.next_readout_at,
        )
        observed_arguments = adapter.canonical_replay_arguments(arguments=evidence.arguments, result=evidence.result)
        if observed_arguments != expected_arguments:
            raise MeasurementValidationError("Measurement arguments changed outside the derived comparison window.")
        observed_value = adapter.extract_value(result=evidence.result, selector=selector, arguments=observed_arguments)
        baseline_value = _finite_decimal(plan.baseline_value)
        absolute_delta = observed_value - baseline_value
        relative_delta = None if baseline_value == 0 else absolute_delta / baseline_value * Decimal("100")
        verdict = _verdict(
            direction=plan.source_action.metric_direction, delta=absolute_delta, tolerance=adapter.neutral_tolerance
        )
        observed_window = adapter.observed_window(observed_arguments)
        return OutcomeEvaluation(
            status="measured",
            observed_value=observed_value,
            observed_from=observed_window.start,
            observed_to=observed_window.end,
            absolute_delta=absolute_delta,
            relative_delta=relative_delta,
            verdict=verdict,
        )
    except MeasurementValidationError as error:
        return _inconclusive(_failure_code(error))


def build_outcome_replay_instruction(*, plan: OutcomePlan) -> OutcomeReplayInstructionDTO:
    """Derive the sole permitted comparison call without exposing stored outcome state."""
    spec = _measurement_spec(plan.measurement_spec)
    adapter = _adapter_for_spec(spec)
    selector = adapter.validate_selector(spec["selector"])
    original_arguments = adapter.canonicalize_arguments(spec["replay_arguments"])
    comparison_arguments = adapter.comparison_arguments(
        original=original_arguments,
        baseline_from=plan.baseline_from,
        baseline_to=plan.baseline_to,
        readout_at=plan.next_readout_at,
    )
    return OutcomeReplayInstructionDTO(
        plan_id=plan.id,
        tool_name=adapter.tool_name,
        tool_schema_version=adapter.tool_schema_version,
        comparison_arguments=comparison_arguments,
        selector=selector,
    )


def _adapter(*, tool_name: str, tool_schema_version: str) -> _MeasurementAdapter:
    adapter = _REGISTRY.get((tool_name, tool_schema_version))
    if adapter is None:
        raise MeasurementValidationError("Measurement tool or schema version is unsupported.")
    return adapter


def measurement_metadata(*, specification: object) -> tuple[str, Literal["count"]]:
    """Return the adapter-owned identity and unit for a canonical scalar readout."""
    spec = _measurement_spec(specification)
    adapter = _adapter_for_spec(spec)
    selector = adapter.validate_selector(spec["selector"])
    arguments = adapter.canonicalize_arguments(spec["replay_arguments"])
    return adapter.metric_name(arguments=arguments, selector=selector), adapter.metric_unit


def measurement_identity(*, specification: object) -> str:
    """Return the adapter-owned stable identity used for proposal deduplication."""
    spec = _measurement_spec(specification)
    adapter = _adapter_for_spec(spec)
    selector = adapter.validate_selector(spec["selector"])
    arguments = adapter.canonicalize_arguments(spec["replay_arguments"])
    return adapter.metric_identity(arguments=arguments, selector=selector)


def _adapter_for_spec(spec: _MeasurementSpec) -> _MeasurementAdapter:
    adapter = _adapter(tool_name=spec["tool_name"], tool_schema_version=spec["tool_schema_version"])
    if spec["extraction_kind"] != adapter.extraction_kind:
        raise MeasurementValidationError("Measurement extraction kind is invalid.")
    return adapter


def _window_values(arguments: dict[str, object]) -> _MeasurementWindow:
    return _MeasurementWindow(
        start=_parse_datetime(arguments.get("date_from")),
        end=_parse_datetime(arguments.get("date_to")),
    )


def _count_at(value: object, index: int) -> Decimal:
    if not isinstance(value, list) or index >= len(value) or not isinstance(value[index], dict):
        raise MeasurementValidationError("Measurement result shape is unsupported.")
    count = _finite_decimal(value[index].get("count"))
    if count != count.to_integral_value():
        raise MeasurementValidationError("Measurement count must be an integer.")
    return count


def _metric_identifier(value: object) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise MeasurementValidationError("Measurement metric identity is unsupported.")
    if isinstance(value, float):
        if not isfinite(value):
            raise MeasurementValidationError("Measurement metric identity is unsupported.")
        identifier = str(int(value)) if value.is_integer() else str(value)
    else:
        identifier = str(value)
    if _METRIC_IDENTIFIER.fullmatch(identifier) is None:
        raise MeasurementValidationError("Measurement metric identity is unsupported.")
    return identifier


def _json_object(value: object, *, message: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MeasurementValidationError(message)
    try:
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        decoded = json.loads(serialized, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError) as error:
        raise MeasurementValidationError(message) from error
    if not isinstance(decoded, dict):
        raise MeasurementValidationError(message)
    return decoded


def _semantic_sort_key(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _finite_decimal(value: object) -> Decimal:
    try:
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise MeasurementValidationError("Measurement value is not a decimal.") from error
    if not decimal.is_finite():
        raise MeasurementValidationError("Measurement value must be finite.")
    return decimal


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise MeasurementValidationError("Measurement window values must be ISO timestamps.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise MeasurementValidationError("Measurement window values must be ISO timestamps.") from error
    if parsed.tzinfo is None:
        raise MeasurementValidationError("Measurement window values must include a timezone.")
    return parsed


def _measurement_spec(value: object) -> _MeasurementSpec:
    spec = _json_object(value, message="Measurement specification is invalid.")
    required = {
        "version",
        "adapter_version",
        "tool_name",
        "tool_schema_version",
        "replay_arguments",
        "selector",
        "extraction_kind",
    }
    if set(spec) != required or spec["version"] != 1 or spec["adapter_version"] != "v1":
        raise MeasurementValidationError("Measurement specification is invalid.")
    if (
        not isinstance(spec["tool_name"], str)
        or not isinstance(spec["tool_schema_version"], str)
        or not isinstance(spec["extraction_kind"], str)
    ):
        raise MeasurementValidationError("Measurement specification is invalid.")
    if (
        not isinstance(spec["selector"], dict)
        or not all(isinstance(key, str) and isinstance(item, str) for key, item in spec["selector"].items())
        or not isinstance(spec["replay_arguments"], dict)
    ):
        raise MeasurementValidationError("Measurement specification is invalid.")
    return {
        "tool_name": cast(str, spec["tool_name"]),
        "tool_schema_version": cast(str, spec["tool_schema_version"]),
        "selector": cast(dict[str, str], spec["selector"]),
        "replay_arguments": cast(dict[str, object], spec["replay_arguments"]),
        "extraction_kind": cast(str, spec["extraction_kind"]),
    }


def _verdict(
    *, direction: str | None, delta: Decimal, tolerance: Decimal
) -> Literal["improved", "flat", "regressed", "inconclusive"]:
    if direction == "maintain":
        return "flat" if abs(delta) <= tolerance else "regressed"
    if abs(delta) <= tolerance:
        return "flat"
    if direction == "increase":
        return "improved" if delta > 0 else "regressed"
    if direction == "decrease":
        return "improved" if delta < 0 else "regressed"
    raise MeasurementValidationError("Measurement direction is invalid.")


def _failure_code(error: MeasurementValidationError) -> str:
    if "arguments changed" in str(error) or "executed measurement" in str(error):
        return "measurement_arguments_changed"
    return "measurement_inconclusive"


def _inconclusive(failure_code: str) -> OutcomeEvaluation:
    return OutcomeEvaluation(
        status="inconclusive",
        observed_value=None,
        observed_from=None,
        observed_to=None,
        absolute_delta=None,
        relative_delta=None,
        verdict="inconclusive",
        failure_code=failure_code,
    )
