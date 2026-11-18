from django.test import SimpleTestCase

from parameterized import parameterized

from products.logs.backend.models import LogsMetricRule
from products.logs.backend.presentation.filter_group_validation import MAX_FILTER_GROUP_LEAF_VALUES
from products.logs.backend.presentation.views.metric_rules_api import LogsMetricRuleSerializer
from products.logs.backend.test.metric_rule_fixtures import VALID_FILTER_GROUP


class TestLogsMetricRuleSerializerValidation(SimpleTestCase):
    def _serializer(self, **overrides):
        data = {
            "name": "API errors",
            "metric_name": "log.api_errors",
            "filter_group": VALID_FILTER_GROUP,
        }
        data.update(overrides)
        return LogsMetricRuleSerializer(data=data)

    @parameterized.expand(
        [
            ("starts_with_digit", "1metric"),
            ("starts_with_dot", ".metric"),
            ("contains_space", "log errors"),
            ("contains_slash", "log/errors"),
            ("empty", ""),
        ]
    )
    def test_rejects_invalid_metric_name(self, _label, metric_name):
        s = self._serializer(metric_name=metric_name)
        assert not s.is_valid()
        assert "metric_name" in s.errors

    @parameterized.expand(
        [
            ("simple", "log_errors"),
            ("dotted", "log.api.errors"),
            ("dashed", "log-errors"),
            ("mixed", "Log.API_errors-2"),
        ]
    )
    def test_accepts_valid_metric_name(self, _label, metric_name):
        s = self._serializer(metric_name=metric_name)
        assert s.is_valid(), s.errors

    def test_rejects_more_than_five_group_by_keys(self):
        s = self._serializer(group_by=[f"attributes.k{i}" for i in range(6)])
        assert not s.is_valid()
        assert "group_by" in s.errors

    @parameterized.expand(
        [
            ("unknown_top_level", ["severity_number"]),
            ("body", ["body"]),
            ("bare_prefix", ["attributes."]),
            ("unprefixed_attribute", ["http.status_code"]),
        ]
    )
    def test_rejects_invalid_group_by_key(self, _label, group_by):
        s = self._serializer(group_by=group_by)
        assert not s.is_valid()
        assert "group_by" in s.errors

    def test_accepts_valid_group_by_keys(self):
        s = self._serializer(
            group_by=["service_name", "severity_text", "attributes.http.status_code", "resource_attributes.k8s.pod"]
        )
        assert s.is_valid(), s.errors

    def test_count_rule_without_value_attribute_is_valid(self):
        s = self._serializer()
        assert s.is_valid(), s.errors
        assert s.validated_data.get("value_attribute") is None

    def test_source_defaults_to_logs(self):
        s = self._serializer()
        assert s.is_valid(), s.errors
        assert s.validated_data.get("source") == LogsMetricRule.RecordSource.LOGS

    def test_span_rule_accepts_span_top_level_group_by_keys(self):
        s = self._serializer(
            source="spans",
            group_by=["service_name", "name", "status_code", "kind", "attributes.http.route"],
        )
        assert s.is_valid(), s.errors

    @parameterized.expand(
        [
            ("severity_text", ["severity_text"]),
            ("event_name", ["event_name"]),
        ]
    )
    def test_span_rule_rejects_log_only_group_by_keys(self, _label, group_by):
        s = self._serializer(source="spans", group_by=group_by)
        assert not s.is_valid()
        assert "group_by" in s.errors

    @parameterized.expand(
        [
            ("name", ["name"]),
            ("status_code", ["status_code"]),
            ("kind", ["kind"]),
        ]
    )
    def test_log_rule_rejects_span_only_group_by_keys(self, _label, group_by):
        s = self._serializer(source="logs", group_by=group_by)
        assert not s.is_valid()
        assert "group_by" in s.errors

    def test_span_rule_accepts_duration_ms_value_attribute(self):
        s = self._serializer(source="spans", value_attribute="duration_ms")
        assert s.is_valid(), s.errors

    def test_log_rule_rejects_duration_ms_value_attribute(self):
        s = self._serializer(source="logs", value_attribute="duration_ms")
        assert not s.is_valid()
        assert "value_attribute" in s.errors

    def test_source_immutable_on_update(self):
        instance = LogsMetricRule(metric_name="span.errors", source=LogsMetricRule.RecordSource.SPANS)
        s = LogsMetricRuleSerializer(instance=instance, data={"source": "logs"}, partial=True)
        assert not s.is_valid()
        assert "source" in s.errors

    def test_full_update_omitting_source_keeps_existing_source(self):
        # A PUT that omits `source` must not overwrite an existing spans rule with the
        # field default (logs) — the record source is immutable and pinned to the instance.
        instance = LogsMetricRule(metric_name="span.errors", source=LogsMetricRule.RecordSource.SPANS)
        s = LogsMetricRuleSerializer(
            instance=instance,
            data={"name": "Renamed", "metric_name": "span.errors", "filter_group": VALID_FILTER_GROUP},
        )
        assert s.is_valid(), s.errors
        assert s.validated_data["source"] == LogsMetricRule.RecordSource.SPANS

    def test_null_filter_group_matches_all_logs(self):
        s = self._serializer(filter_group=None)
        assert s.is_valid(), s.errors

    @parameterized.expand(
        [
            ("not_a_group", {"key": "service.name"}),
            ("list_shape", [{"type": "AND", "values": []}]),
            ("vacuous_group", {"type": "AND", "values": []}),
        ]
    )
    def test_rejects_malformed_filter_group(self, _label, filter_group):
        s = self._serializer(filter_group=filter_group)
        assert not s.is_valid()
        assert "filter_group" in s.errors

    def test_rejects_too_deep_filter_group(self):
        node: dict = {
            "type": "AND",
            "values": [{"key": "service.name", "operator": "exact", "value": "api", "type": "log_attribute"}],
        }
        for _ in range(20):
            node = {"type": "AND", "values": [node]}
        s = self._serializer(filter_group=node)
        assert not s.is_valid()
        assert "filter_group" in s.errors

    def test_rejects_too_many_filter_leaf_values(self):
        # One `exact` leaf with a huge value array counts as a single node, but
        # matchExact scans the whole array per log record — the leaf-value budget
        # bounds that per-record CPU.
        huge = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "service.name",
                            "operator": "exact",
                            "value": [f"svc-{i}" for i in range(MAX_FILTER_GROUP_LEAF_VALUES + 1)],
                            "type": "log_attribute",
                        }
                    ],
                }
            ],
        }
        s = self._serializer(filter_group=huge)
        assert not s.is_valid()
        assert "filter_group" in s.errors

    def test_rejects_oversized_filter_leaf_value(self):
        oversized = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "service.name",
                            "operator": "exact",
                            "value": "x" * 5000,
                            "type": "log_attribute",
                        }
                    ],
                }
            ],
        }
        s = self._serializer(filter_group=oversized)
        assert not s.is_valid()
        assert "filter_group" in s.errors
