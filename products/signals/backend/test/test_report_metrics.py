from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from pydantic import ValidationError

from products.signals.backend.report_metrics import (
    MAX_LIVE_METRIC_QUERY_POINTS,
    MAX_LIVE_METRIC_QUERY_SERIES,
    MAX_REPORT_METRICS,
    ReportMetric,
    metric_batch_error,
)
from products.signals.backend.serializers import ReportMetricComparisonSerializer, ReportMetricSerializer


def _affected_users_metric(metric_id: str = "affected-users", role: str = "primary") -> ReportMetric:
    return ReportMetric.model_validate(
        {
            "metric_id": metric_id,
            "title": "Affected users",
            "kind": "affected_users",
            "role": role,
            "value": 17,
            "value_at": datetime(2026, 8, 29, tzinfo=UTC),
            "value_format": "count",
            "unit": "users",
            "query": {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "dateRange": {"date_from": "-30d"},
                    "series": [{"kind": "EventsNode", "event": "$exception", "math": "dau"}],
                    "trendsFilter": {"display": "ActionsBar"},
                },
            },
        }
    )


class TestReportMetric(SimpleTestCase):
    def test_accepts_affected_users_as_a_live_distinct_people_metric(self) -> None:
        metric = _affected_users_metric()

        assert metric.value == 17
        assert metric.query is not None
        assert metric.query["source"]["series"][0]["math"] == "dau"
        assert ReportMetric.model_validate_json(metric.model_dump_json()) == metric

    def test_zero_is_a_valid_measured_count(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        content["value"] = 0
        metric = ReportMetric.model_validate(content)

        assert metric.value == 0

    def test_rejects_fractional_or_negative_count_snapshots(self) -> None:
        for value in (-1, 1.5):
            content = _affected_users_metric().model_dump(mode="json")
            content["value"] = value

            with self.assertRaisesRegex(ValidationError, "non-negative whole number"):
                ReportMetric.model_validate(content)

    def test_rejects_summing_occurrences_as_affected_users(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        content["query"]["source"]["series"][0]["math"] = "total"

        with self.assertRaisesRegex(ValidationError, "math: dau"):
            ReportMetric.model_validate(content)

    def test_live_query_rejects_result_series_multipliers_for_every_metric_kind(self) -> None:
        for source_patch, error in (
            ({"breakdownFilter": {"breakdown": "$browser"}}, "must not use a breakdown"),
            ({"compareFilter": {"compare": True}}, "must not use compare mode"),
            ({"trendsFilter": {"display": "Metric"}}, "Metric display must disable metricShowChange"),
        ):
            with self.subTest(source_patch=source_patch):
                content = _affected_users_metric().model_dump(mode="json")
                content["kind"] = "custom"
                content["query"]["source"].update(source_patch)

                with self.assertRaisesRegex(ValidationError, error):
                    ReportMetric.model_validate(content)

        for trends_filter in (
            {"display": "Metric", "metricShowChange": False},
            {"display": "Metric", "metricSummary": "latest"},
        ):
            with self.subTest(trends_filter=trends_filter):
                content = _affected_users_metric().model_dump(mode="json")
                content["kind"] = "custom"
                content["query"]["source"]["compareFilter"] = {"compare": False}
                content["query"]["source"]["trendsFilter"] = trends_filter
                assert ReportMetric.model_validate(content).query is not None

    def test_rejects_unique_groups_labeled_as_affected_users(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        content["query"]["source"]["series"][0]["math_group_type_index"] = 0

        with self.assertRaisesRegex(ValidationError, "count people, not unique groups"):
            ReportMetric.model_validate(content)

    def test_rejects_series_whose_resource_access_cannot_be_checked(self) -> None:
        unsupported_series = (
            {
                "kind": "DataWarehouseNode",
                "id": "events",
                "id_field": "uuid",
                "table_name": "events",
                "timestamp_field": "timestamp",
                "distinct_id_field": "distinct_id",
                "math": "dau",
            },
            {
                "kind": "GroupNode",
                "operator": "OR",
                "nodes": [{"kind": "EventsNode", "event": "$exception", "math": "total"}],
                "math": "total",
            },
        )

        for series in unsupported_series:
            with self.subTest(kind=series["kind"]):
                content = _affected_users_metric().model_dump(mode="json")
                content["kind"] = "custom"
                content["query"]["source"]["series"] = [series]

                with self.assertRaisesRegex(ValidationError, "only event or action series"):
                    ReportMetric.model_validate(content)

    def test_rejects_series_that_fail_the_canonical_query_schema(self) -> None:
        for series in (
            {"kind": "EventsNode", "event": "$pageview", "math": "dau", "invented_field": True},
            {"kind": "ActionsNode", "math": "dau"},
        ):
            with self.subTest(series=series):
                content = _affected_users_metric().model_dump(mode="json")
                content["query"]["source"]["series"] = [series]

                with self.assertRaisesRegex(ValidationError, "canonical InsightVizNode schema"):
                    ReportMetric.model_validate(content)

    def test_every_live_series_requires_a_canonical_identity(self) -> None:
        for series, error in (
            ({"kind": "EventsNode", "math": "dau"}, "non-empty event name"),
            ({"kind": "EventsNode", "event": " ", "math": "dau"}, "non-empty event name"),
            ({"kind": "ActionsNode", "id": "42", "math": "dau"}, "positive integer action id"),
            ({"kind": "ActionsNode", "id": 0, "math": "dau"}, "positive integer action id"),
            ({"kind": "ActionsNode", "id": -1, "math": "dau"}, "positive integer action id"),
            ({"kind": "ActionsNode", "id": True, "math": "dau"}, "positive integer action id"),
        ):
            with self.subTest(series=series):
                content = _affected_users_metric().model_dump(mode="json")
                content["kind"] = "custom"
                content["query"]["source"]["series"] = [series]

                with self.assertRaisesRegex(ValidationError, error):
                    ReportMetric.model_validate(content)

        for series in (
            {"kind": "EventsNode", "event": "$pageview", "math": "dau"},
            {"kind": "ActionsNode", "id": 42, "math": "dau"},
        ):
            with self.subTest(series=series):
                content = _affected_users_metric().model_dump(mode="json")
                content["query"]["source"]["series"] = [series]

                assert ReportMetric.model_validate(content).query is not None

    def test_rejects_an_unbounded_live_query(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        del content["query"]["source"]["dateRange"]

        with self.assertRaisesRegex(ValidationError, "date_from"):
            ReportMetric.model_validate(content)

    def test_live_query_requires_at_least_one_series(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        content["kind"] = "custom"
        content["query"]["source"]["series"] = []

        with self.assertRaisesRegex(ValidationError, "at least one Trends series"):
            ReportMetric.model_validate(content)

    def test_live_query_requires_a_reasonable_advancing_relative_window(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        content["query"]["source"]["dateRange"]["date_from"] = ["-30d"]
        with self.assertRaisesRegex(ValidationError, "canonical InsightVizNode schema"):
            ReportMetric.model_validate(content)

        for date_from in ("all", "2026-01-01", "-367d", "-13m", "-2y"):
            with self.subTest(date_from=date_from):
                content = _affected_users_metric().model_dump(mode="json")
                content["query"]["source"]["dateRange"]["date_from"] = date_from

                with self.assertRaisesRegex(ValidationError, "relative time window|must not exceed"):
                    ReportMetric.model_validate(content)

        for date_from in ("-8784h", "-366d", "-52w", "-12m", "-1y"):
            with self.subTest(date_from=date_from):
                content = _affected_users_metric().model_dump(mode="json")
                content["query"]["source"]["dateRange"]["date_from"] = date_from

                assert ReportMetric.model_validate(content).query is not None

        content = _affected_users_metric().model_dump(mode="json")
        content["query"]["source"]["dateRange"]["date_to"] = "2026-08-29"
        with self.assertRaisesRegex(ValidationError, "date_to must be empty"):
            ReportMetric.model_validate(content)

    def test_live_query_bounds_estimated_output_points(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        content["kind"] = "custom"
        content["query"]["source"]["interval"] = "hour"
        content["query"]["source"]["dateRange"]["date_from"] = f"-{MAX_LIVE_METRIC_QUERY_POINTS - 1}h"

        assert ReportMetric.model_validate(content).query is not None

        content["query"]["source"]["dateRange"]["date_from"] = f"-{MAX_LIVE_METRIC_QUERY_POINTS}h"
        with self.assertRaisesRegex(ValidationError, f"accept at most {MAX_LIVE_METRIC_QUERY_POINTS}"):
            ReportMetric.model_validate(content)

    def test_live_query_requires_exactly_one_output_series(self) -> None:
        for key, value in (
            (None, None),
            ("formulas", ["A", "B"]),
            ("formulaNodes", [{"formula": "A"}, {"formula": "B"}]),
        ):
            with self.subTest(key=key):
                content = _affected_users_metric().model_dump(mode="json")
                content["kind"] = "custom"
                content["query"]["source"]["series"] *= 2
                if key is not None:
                    content["query"]["source"]["trendsFilter"][key] = value

                with self.assertRaisesRegex(ValidationError, "exactly one output series"):
                    ReportMetric.model_validate(content)

    def test_live_query_allows_bounded_formula_inputs_for_one_output(self) -> None:
        for key, value in (
            ("formula", "A+B+C+D+E+F+G+H+I+J"),
            ("formulas", ["A+B+C+D+E+F+G+H+I+J"]),
            ("formulaNodes", [{"formula": "A+B+C+D+E+F+G+H+I+J"}]),
        ):
            with self.subTest(key=key):
                content = _affected_users_metric().model_dump(mode="json")
                content["kind"] = "custom"
                content["query"]["source"]["series"] *= MAX_LIVE_METRIC_QUERY_SERIES
                content["query"]["source"]["trendsFilter"][key] = value

                assert ReportMetric.model_validate(content).query is not None

        content = _affected_users_metric().model_dump(mode="json")
        content["kind"] = "custom"
        content["query"]["source"]["series"] *= MAX_LIVE_METRIC_QUERY_SERIES + 1
        content["query"]["source"]["trendsFilter"]["formula"] = "A"
        with self.assertRaisesRegex(ValidationError, f"at most {MAX_LIVE_METRIC_QUERY_SERIES} series"):
            ReportMetric.model_validate(content)

    def test_live_query_rejects_formulas_the_trends_runner_cannot_execute(self) -> None:
        for description, trends_formula in (
            ("empty formulas entry", {"formulas": [""]}),
            ("empty formula node", {"formulaNodes": [{"formula": ""}]}),
            ("unknown series letter", {"formula": "B"}),
            ("function call", {"formula": "round(A)"}),
            ("invalid syntax", {"formula": "A +"}),
        ):
            with self.subTest(description=description):
                content = _affected_users_metric().model_dump(mode="json")
                content["kind"] = "custom"
                content["query"]["source"]["trendsFilter"].update(trends_formula)

                with self.assertRaisesRegex(ValidationError, "formula"):
                    ReportMetric.model_validate(content)

    def test_live_query_requires_a_canonical_interval(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        content["query"]["source"]["interval"] = "fortnight"

        with self.assertRaisesRegex(ValidationError, "canonical InsightVizNode schema"):
            ReportMetric.model_validate(content)

    def test_rejects_every_formula_shape_for_affected_users(self) -> None:
        for key, value in (
            ("formula", "A * 100"),
            ("formulas", ["A * 100"]),
            ("formulaNodes", [{"formula": "A * 100"}]),
        ):
            with self.subTest(key=key):
                content = _affected_users_metric().model_dump(mode="json")
                content["query"]["source"].setdefault("trendsFilter", {})[key] = value

                with self.assertRaisesRegex(ValidationError, "must not use a formula"):
                    ReportMetric.model_validate(content)

    def test_rejects_executable_payloads_shared_with_chart_validation(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        content["query"]["source"]["nested"] = {"kind": "HogQuery", "code": "return 1"}

        with self.assertRaisesRegex(ValidationError, "HogQuery"):
            ReportMetric.model_validate(content)

    def test_requires_snapshot_value_and_timestamp_together(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        content["value_at"] = None

        with self.assertRaisesRegex(ValidationError, "value and value_at"):
            ReportMetric.model_validate(content)

    def test_snapshot_timestamp_requires_a_timezone(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        content["value_at"] = "2026-08-29T12:00:00"

        with self.assertRaisesRegex(ValidationError, "must include a timezone"):
            ReportMetric.model_validate(content)

    def test_rejects_a_future_snapshot_timestamp(self) -> None:
        # An author-supplied future time would make every refresh look older than the snapshot and
        # freeze the stale value, so a time past now plus the clock-skew allowance is rejected.
        content = _affected_users_metric().model_dump(mode="json")
        content["value_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()

        with self.assertRaisesRegex(ValidationError, "must not be in the future"):
            ReportMetric.model_validate(content)

    def test_requires_a_live_query_for_every_metric(self) -> None:
        with self.assertRaisesRegex(ValidationError, "Field required"):
            ReportMetric.model_validate(
                {
                    "metric_id": "conversion",
                    "title": "Conversion",
                    "kind": "conversion_rate",
                    "role": "supporting",
                    "value": 34,
                    "value_at": "2026-08-29T12:00:00Z",
                    "value_format": "percentage",
                }
            )

    def test_count_comparison_uses_the_same_whole_number_semantics(self) -> None:
        content = _affected_users_metric().model_dump(mode="json")
        content["comparison"] = {"label": " Previous period ", "value": 16}

        metric = ReportMetric.model_validate(content)
        assert metric.comparison is not None
        assert metric.comparison.label == "Previous period"

        content["comparison"]["value"] = 16.5
        with self.assertRaisesRegex(ValidationError, "count comparison"):
            ReportMetric.model_validate(content)

    def test_rejects_boolean_snapshot_and_comparison_values(self) -> None:
        # Pydantic's lax mode coerces a JSON boolean to a float, so without the guard `true`/`false`
        # would be stored as a 1.0/0.0 measurement. Both value fields must refuse it.
        for boolean in (True, False):
            snapshot = _affected_users_metric().model_dump(mode="json")
            snapshot["value"] = boolean
            with self.assertRaisesRegex(ValidationError, "not a boolean"):
                ReportMetric.model_validate(snapshot)

            comparison = _affected_users_metric().model_dump(mode="json")
            comparison["comparison"] = {"label": "Previous period", "value": boolean}
            with self.assertRaisesRegex(ValidationError, "not a boolean"):
                ReportMetric.model_validate(comparison)

    def test_scaled_and_point_percentage_rates_have_unambiguous_ranges(self) -> None:
        base = {
            "metric_id": "conversion",
            "title": "Conversion",
            "kind": "conversion_rate",
            "role": "supporting",
            "value_at": "2026-08-29T12:00:00Z",
        }

        for value, value_format in ((34, "percentage"), (0.34, "percentage_scaled")):
            query = _affected_users_metric(role="supporting").model_dump(mode="json")["query"]
            query["source"]["trendsFilter"]["aggregationAxisFormat"] = value_format
            assert (
                ReportMetric.model_validate(
                    {**base, "value": value, "value_format": value_format, "query": query}
                ).value
                == value
            )

        for value, value_format in ((101, "percentage"), (1.01, "percentage_scaled")):
            with self.subTest(value=value, value_format=value_format):
                query = _affected_users_metric(role="supporting").model_dump(mode="json")["query"]
                query["source"]["trendsFilter"]["aggregationAxisFormat"] = value_format
                with self.assertRaisesRegex(ValidationError, "rate snapshot"):
                    ReportMetric.model_validate({**base, "value": value, "value_format": value_format, "query": query})

        with self.assertRaisesRegex(ValidationError, "percentage formatting"):
            ReportMetric.model_validate(
                {
                    **base,
                    "value": 0.34,
                    "value_format": "number",
                    "query": _affected_users_metric(role="supporting").query,
                }
            )

    def test_percentage_format_requires_a_matching_query_axis_format(self) -> None:
        for axis_format in (None, "numeric", "percentage_scaled"):
            with self.subTest(axis_format=axis_format):
                query = _affected_users_metric().query
                assert query is not None
                if axis_format is None:
                    query["source"]["trendsFilter"].pop("aggregationAxisFormat", None)
                else:
                    query["source"]["trendsFilter"]["aggregationAxisFormat"] = axis_format

                content = {
                    "metric_id": "conversion",
                    "title": "Conversion",
                    "kind": "conversion_rate",
                    "role": "primary",
                    "value_format": "percentage",
                    "query": query,
                }

                with self.assertRaisesRegex(ValidationError, "aggregationAxisFormat.*matches"):
                    ReportMetric.model_validate(content)

        for value_format in ("percentage", "percentage_scaled"):
            with self.subTest(value_format=value_format):
                query = _affected_users_metric().query
                assert query is not None
                query["source"]["trendsFilter"]["aggregationAxisFormat"] = value_format
                assert (
                    ReportMetric.model_validate(
                        {
                            "metric_id": "conversion",
                            "title": "Conversion",
                            "kind": "conversion_rate",
                            "role": "primary",
                            "value_format": value_format,
                            "query": query,
                        }
                    ).query
                    is not None
                )

    def test_semantic_kinds_require_compatible_formats_and_units(self) -> None:
        base = {
            "metric_id": "semantic",
            "title": "Semantic metric",
            "value": 12,
            "value_at": "2026-08-29T12:00:00Z",
            "query": _affected_users_metric(role="supporting").query,
        }

        for kind in ("affected_sessions", "occurrences"):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValidationError, "must use count formatting"):
                    ReportMetric.model_validate({**base, "kind": kind, "value_format": "number"})

        with self.assertRaisesRegex(ValidationError, "must use `ms` or `s`"):
            ReportMetric.model_validate({**base, "kind": "duration", "value_format": "duration", "unit": "min"})

        with self.assertRaisesRegex(ValidationError, "ISO currency code"):
            ReportMetric.model_validate({**base, "kind": "revenue", "value_format": "currency", "unit": "usd"})

        revenue = ReportMetric.model_validate({**base, "kind": "revenue", "value_format": "currency", "unit": " USD "})
        assert revenue.unit == "USD"


class TestMetricBatchError(SimpleTestCase):
    def test_accepts_one_primary_and_supporting_metrics(self) -> None:
        primary = _affected_users_metric()
        supporting = ReportMetric.model_validate(
            {
                "metric_id": "occurrences",
                "title": "Dead clicks",
                "kind": "occurrences",
                "value": 3912,
                "value_at": "2026-08-29T12:00:00Z",
                "value_format": "count",
                "unit": "clicks",
                "query": _affected_users_metric(role="supporting").query,
            }
        )

        assert metric_batch_error([primary, supporting]) is None

    def test_rejects_duplicate_ids(self) -> None:
        metric = _affected_users_metric(role="supporting")

        assert "duplicate metric_id" in (metric_batch_error([metric, metric]) or "")

    def test_rejects_more_than_the_bounded_metric_count(self) -> None:
        metrics = [
            ReportMetric.model_validate(
                {
                    "metric_id": f"metric-{index}",
                    "title": f"Metric {index}",
                    "kind": "custom",
                    "value": index,
                    "value_at": "2026-08-29T12:00:00Z",
                    "query": _affected_users_metric(role="supporting").query,
                }
            )
            for index in range(MAX_REPORT_METRICS + 1)
        ]

        assert f"at most {MAX_REPORT_METRICS}" in (metric_batch_error(metrics) or "")


class TestReportMetricSerializerRejectsBooleans(SimpleTestCase):
    def test_boolean_value_is_not_coerced_into_a_measurement(self) -> None:
        # DRF's FloatField coerces `true`/`false` to 1.0/0.0, so the write path needs its own guard
        # beyond the pydantic model. Cover both the snapshot value and the comparison value.
        for boolean in (True, False):
            comparison = ReportMetricComparisonSerializer(data={"value": boolean, "label": "Previous period"})
            assert not comparison.is_valid()
            assert comparison.errors["value"][0].code == "invalid"

            metric = ReportMetricSerializer(
                data={
                    "metric_id": "affected-users",
                    "title": "Affected users",
                    "kind": "affected_users",
                    "value": boolean,
                    "query": _affected_users_metric().query,
                }
            )
            assert not metric.is_valid()
            assert metric.errors["value"][0].code == "invalid"
