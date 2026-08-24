from contextlib import contextmanager

from unittest.mock import MagicMock, patch

from django.test import override_settings

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
    @contextmanager
    def _patched_client(self, content=None, *, error=None, api_key="sk-test"):
        """Patch the OpenAI client and the API key together — the suggestion no-ops without a key."""
        client = MagicMock()
        if error is not None:
            client.chat.completions.create.side_effect = error
        else:
            client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content=content))]
            )
        with override_settings(OPENAI_API_KEY=api_key):
            with patch("products.logs.backend.retention_name_suggestion.OpenAI", return_value=client) as mock_client:
                yield mock_client

    def _suggest(self, retention_days=14, filter_group=None):
        return suggest_retention_rule_name(
            retention_days,
            _leaf() if filter_group is None else filter_group,
            distinct_id="user-1",
            team_id=1,
        )

    def test_returns_generated_name(self):
        with self._patched_client("Keep api logs for 30 days"):
            assert self._suggest(retention_days=30) == "Keep api logs for 30 days"

    def test_strips_prefix_and_quotes(self):
        with self._patched_client('  Name: "Keep api logs for 14 days"  '):
            assert self._suggest() == "Keep api logs for 14 days"

    def test_truncates_long_name(self):
        with self._patched_client("x" * 200):
            assert len(self._suggest()) == 60

    def test_too_short_name_is_dropped(self):
        with self._patched_client("ok"):
            assert self._suggest() == ""

    def test_no_llm_call_for_empty_filter_group(self):
        with self._patched_client("Keep api logs") as mock_client:
            assert self._suggest(filter_group=_group("AND", [])) == ""
        mock_client.assert_not_called()

    def test_client_failure_returns_blank(self):
        with self._patched_client(error=RuntimeError("provider down")):
            assert self._suggest() == ""

    def test_no_llm_call_when_key_is_unconfigured(self):
        # Self-hosted instances without a key degrade quietly rather than erroring per keystroke.
        with self._patched_client("Keep api logs for 14 days", api_key="") as mock_client:
            assert self._suggest() == ""
        mock_client.assert_not_called()
