from typing import Any

import pytest

from parameterized import parameterized

from products.logs.backend.services_query_runner import rule_could_apply_to_service


def _wrap(inner: dict) -> dict:
    """Mirror the outer-AND envelope the drop-rules UI emits."""
    return {"type": "AND", "values": [inner]}


def _leaf(key: str, operator: str, value: Any) -> dict:
    return {"key": key, "operator": operator, "value": value, "type": "log_resource_attribute"}


class TestRuleCouldApplyToService:
    """
    Unit tests for the three-valued evaluator that backs the Services tab's
    `active_rules` list. The Node ingestion worker remains the source of truth
    for actual per-record drop decisions; this helper only filters the display
    list so a rule scoped via `filter_group` to one service doesn't appear on
    every service's row.
    """

    def test_empty_or_missing_filter_group_applies_to_every_service(self) -> None:
        assert rule_could_apply_to_service(None, "api") is True
        assert rule_could_apply_to_service({}, "api") is True
        assert rule_could_apply_to_service({"type": "AND", "values": []}, "api") is True

    def test_exact_service_name_match(self) -> None:
        rule = _wrap({"type": "AND", "values": [_leaf("service.name", "exact", "api")]})
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "other") is False

    def test_underscore_key_matches_dotted_key(self) -> None:
        # The Node consumer treats `service_name` and `service.name` as aliases;
        # services-page evaluation should too, so the UI's choice of key doesn't
        # silently change the display semantics.
        rule = _wrap({"type": "AND", "values": [_leaf("service_name", "exact", "api")]})
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "other") is False

    @parameterized.expand(
        [
            ("icontains_match", "icontains", "ap", "api", True),
            ("icontains_no_match", "icontains", "redis", "api", False),
            ("not_icontains_match", "not_icontains", "redis", "api", True),
            ("not_icontains_excludes", "not_icontains", "ap", "api", False),
            ("regex_anchor_match", "regex", "^api$", "api", True),
            ("regex_prefix_match", "regex", "^api", "api-v2", True),
            ("regex_no_match", "regex", "^kafka", "api", False),
            ("not_regex_match", "not_regex", "^kafka", "api", True),
            ("in_list_match", "in", ["api", "kafka"], "api", True),
            ("in_list_no_match", "in", ["redis", "kafka"], "api", False),
            ("not_in_match", "not_in", ["redis", "kafka"], "api", True),
            ("not_in_excludes", "not_in", ["api", "kafka"], "api", False),
            ("is_set_with_value", "is_set", None, "api", True),
            ("is_set_blank", "is_set", None, "", False),
            ("is_not_set_with_value", "is_not_set", None, "api", False),
            ("is_not_set_blank", "is_not_set", None, "", True),
            ("invalid_regex_never_matches", "regex", "[unclosed", "api", False),
            ("invalid_not_regex_is_indeterminate", "not_regex", "[unclosed", "api", True),
        ]
    )
    def test_service_leaf_operators(
        self, _label: str, operator: str, value: Any, service_name: str, expected: bool
    ) -> None:
        rule = _wrap({"type": "AND", "values": [_leaf("service.name", operator, value)]})
        assert rule_could_apply_to_service(rule, service_name) is expected

    def test_non_service_leaf_is_indeterminate(self) -> None:
        # A rule scoped only by attributes can match some logs on any service —
        # we can't know without seeing the row. Keep the rule visible.
        rule = _wrap({"type": "AND", "values": [_leaf("severity_text", "exact", "error")]})
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "anything") is True

    def test_and_excludes_when_service_predicate_fails(self) -> None:
        # `service.name = api AND severity = error` → for `other` the service
        # predicate is FALSE, so the AND is FALSE regardless of severity.
        rule = _wrap(
            {
                "type": "AND",
                "values": [
                    _leaf("service.name", "exact", "api"),
                    _leaf("severity_text", "exact", "error"),
                ],
            }
        )
        assert rule_could_apply_to_service(rule, "api") is True  # might apply (error subset)
        assert rule_could_apply_to_service(rule, "other") is False  # cannot apply

    def test_or_keeps_rule_visible_when_one_branch_indeterminate(self) -> None:
        # `service.name = api OR severity = error` → on `other`, service branch
        # is FALSE but severity branch is INDETERMINATE → INDETERMINATE → keep.
        rule = _wrap(
            {
                "type": "OR",
                "values": [
                    _leaf("service.name", "exact", "api"),
                    _leaf("severity_text", "exact", "error"),
                ],
            }
        )
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "other") is True  # error logs of `other` would match

    def test_or_all_service_predicates_resolve_negatively(self) -> None:
        # `service.name = api OR service.name = kafka` → on `redis`, both branches
        # FALSE, OR = FALSE, rule excluded.
        rule = _wrap(
            {
                "type": "OR",
                "values": [
                    _leaf("service.name", "exact", "api"),
                    _leaf("service.name", "exact", "kafka"),
                ],
            }
        )
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "kafka") is True
        assert rule_could_apply_to_service(rule, "redis") is False

    def test_nested_groups(self) -> None:
        # `service.name = api AND (severity = error OR severity = fatal)` —
        # the inner OR is INDETERMINATE (severity unknown), AND with TRUE service
        # match yields INDETERMINATE → keep on `api`. On `other`, the outer AND
        # short-circuits to FALSE.
        rule = _wrap(
            {
                "type": "AND",
                "values": [
                    _leaf("service.name", "exact", "api"),
                    {
                        "type": "OR",
                        "values": [
                            _leaf("severity_text", "exact", "error"),
                            _leaf("severity_text", "exact", "fatal"),
                        ],
                    },
                ],
            }
        )
        assert rule_could_apply_to_service(rule, "api") is True
        assert rule_could_apply_to_service(rule, "other") is False

    def test_malformed_node_falls_back_to_indeterminate(self) -> None:
        # Conservative default: anything we can't parse keeps the rule visible.
        assert rule_could_apply_to_service({"type": "AND", "values": ["oops"]}, "api") is True
        assert rule_could_apply_to_service({"not_a_group": True}, "api") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
