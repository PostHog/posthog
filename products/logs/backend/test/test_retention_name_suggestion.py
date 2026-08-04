from unittest.mock import MagicMock, patch

from products.logs.backend.retention_name_suggestion import (
    MAX_LEAF_VALUES_RENDERED,
    describe_filter_group,
    suggest_retention_rule_name,
)


def _leaf(key="service.name", operator="exact", value="api"):
    return {"key": key, "type": "log_resource_attribute", "operator": operator, "value": value}


def _group(node_type, values):
    return {"type": node_type, "values": values}


class TestDescribeFilterGroup:
    def test_single_leaf(self):
        assert describe_filter_group(_leaf()) == "service.name exact api"

    def test_wrapped_envelope_collapses_to_inner_predicate(self):
        # The form stores `{AND, values: [innerGroup]}` — a single predicate shouldn't gain parentheses.
        wrapped = _group("AND", [_group("AND", [_leaf()])])
        assert describe_filter_group(wrapped) == "service.name exact api"

    def test_nested_or_is_parenthesised(self):
        nested = _group(
            "AND",
            [
                _leaf(),
                _group("OR", [_leaf("level", value="error"), _leaf("level", value="warn")]),
            ],
        )
        assert describe_filter_group(nested) == "service.name exact api AND (level exact error OR level exact warn)"

    def test_list_value_is_truncated(self):
        values = [f"svc-{i}" for i in range(MAX_LEAF_VALUES_RENDERED + 5)]
        described = describe_filter_group(_leaf(operator="in", value=values))
        assert described == f"service.name in {', '.join(values[:MAX_LEAF_VALUES_RENDERED])}"

    def test_leaf_without_value_renders_key_and_operator(self):
        assert describe_filter_group(_leaf(operator="is_set", value=None)) == "service.name is_set"

    def test_leaf_without_operator_defaults_to_exact(self):
        assert describe_filter_group({"key": "service.name", "value": "api"}) == "service.name exact api"

    def test_depth_cap_stops_recursion(self):
        node = _leaf()
        for _ in range(12):
            node = _group("AND", [node])
        assert describe_filter_group(node) == ""

    def test_non_dict_input(self):
        assert describe_filter_group(["not", "a", "group"]) == ""
        assert describe_filter_group(None) == ""

    def test_empty_group(self):
        assert describe_filter_group(_group("AND", [_group("AND", [])])) == ""


class TestSuggestRetentionRuleName:
    def _patched_client(self, content):
        client = MagicMock()
        client.complete.return_value = MagicMock(content=content)
        return patch("products.ai_observability.backend.llm.client.Client", return_value=client)

    def test_returns_generated_name(self):
        with self._patched_client("Keep api logs for 30 days"):
            name = suggest_retention_rule_name(30, _leaf(), distinct_id="user-1")
        assert name == "Keep api logs for 30 days"

    def test_strips_prefix_and_quotes(self):
        with self._patched_client('  Name: "Keep api logs for 14 days"  '):
            name = suggest_retention_rule_name(14, _leaf(), distinct_id="user-1")
        assert name == "Keep api logs for 14 days"

    def test_truncates_long_name(self):
        with self._patched_client("x" * 200):
            name = suggest_retention_rule_name(14, _leaf(), distinct_id="user-1")
        assert len(name) == 60

    def test_too_short_name_is_dropped(self):
        with self._patched_client("ok"):
            assert suggest_retention_rule_name(14, _leaf(), distinct_id="user-1") == ""

    def test_no_llm_call_for_empty_filter_group(self):
        with self._patched_client("Keep api logs") as mock_client:
            assert suggest_retention_rule_name(14, _group("AND", []), distinct_id="user-1") == ""
        mock_client.assert_not_called()

    def test_client_failure_returns_blank(self):
        client = MagicMock()
        client.complete.side_effect = RuntimeError("provider down")
        with patch("products.ai_observability.backend.llm.client.Client", return_value=client):
            assert suggest_retention_rule_name(14, _leaf(), distinct_id="user-1") == ""
