from typing import Any

from parameterized import parameterized

from products.logs.backend.drop_rule_matching import MAX_DROP_RULE_NAMES, FacetDimension, matching_drop_rule_names
from products.logs.backend.models import LogsExclusionRule

SEV = FacetDimension(field="severity_text")
SVC = FacetDimension(field="service_name")
NS = FacetDimension(resource_attribute="k8s.namespace.name")


def _rule(
    rule_type: str,
    *,
    name: str = "r",
    scope_service: str | None = None,
    config: dict | None = None,
) -> LogsExclusionRule:
    return LogsExclusionRule(
        name=name, rule_type=rule_type, scope_service=scope_service, config=config or {}, enabled=True
    )


def _wrap(leaf: dict) -> dict:
    return {"type": "AND", "values": [{"type": "AND", "values": [leaf]}]}


def _applies(rule: LogsExclusionRule, dimension: FacetDimension, value: str) -> bool:
    return matching_drop_rule_names([rule], dimension, value) == [rule.name]


class TestSeveritySamplingMatching:
    @parameterized.expand(
        [
            ("debug_dropped", "debug", True),
            ("trace_in_debug_bucket", "trace", True),
            ("info_kept", "info", False),
            ("warn_sampled", "warn", True),
            ("error_kept", "error", False),
            ("fatal_in_error_bucket", "fatal", False),
        ]
    )
    def test_severity_facet_is_precise_per_level(self, _name: str, value: str, expected: bool) -> None:
        rule = _rule(
            LogsExclusionRule.RuleType.SEVERITY_SAMPLING,
            config={
                "actions": {
                    "DEBUG": {"type": "drop"},
                    "INFO": {"type": "keep"},
                    "WARN": {"type": "sample", "rate": 0.5},
                    "ERROR": {"type": "keep"},
                }
            },
        )
        assert _applies(rule, SEV, value) is expected

    def test_no_op_rule_never_matches(self) -> None:
        rule = _rule(
            LogsExclusionRule.RuleType.SEVERITY_SAMPLING,
            config={"actions": {"DEBUG": {"type": "keep"}, "INFO": {"type": "keep"}}},
        )
        assert _applies(rule, SEV, "debug") is False
        assert _applies(rule, SVC, "api") is False

    def test_applies_to_every_service_when_any_severity_dropped(self) -> None:
        # On non-severity facets we can't know each line's severity, so a rule that drops *some*
        # severity could drop logs from any service — it surfaces everywhere (matches Services tab).
        rule = _rule(LogsExclusionRule.RuleType.SEVERITY_SAMPLING, config={"actions": {"DEBUG": {"type": "drop"}}})
        assert _applies(rule, SVC, "api") is True
        assert _applies(rule, NS, "prod") is True


class TestScopeAndFilterGroupMatching:
    def test_legacy_scope_service_exact_match(self) -> None:
        rule = _rule(LogsExclusionRule.RuleType.PATH_DROP, scope_service="api")
        assert _applies(rule, SVC, "api") is True
        assert _applies(rule, SVC, "other") is False

    def test_legacy_scope_service_does_not_exclude_other_dimensions(self) -> None:
        # A service-scoped rule still drops some namespace=prod lines (those from `api`), so on the
        # namespace facet it stays visible rather than being provably excluded.
        rule = _rule(LogsExclusionRule.RuleType.PATH_DROP, scope_service="api")
        assert _applies(rule, NS, "prod") is True

    @parameterized.expand([("service_name",), ("service.name",)])
    def test_filter_group_service_leaf(self, key: str) -> None:
        rule = _rule(
            LogsExclusionRule.RuleType.PATH_DROP,
            config={"filter_group": _wrap({"key": key, "operator": "exact", "value": "api"})},
        )
        assert _applies(rule, SVC, "api") is True
        assert _applies(rule, SVC, "other") is False

    def test_filter_group_resource_attribute_leaf(self) -> None:
        rule = _rule(
            LogsExclusionRule.RuleType.PATH_DROP,
            config={
                "filter_group": _wrap(
                    {
                        "key": "k8s.namespace.name",
                        "type": "log_resource_attribute",
                        "operator": "exact",
                        "value": "prod",
                    }
                )
            },
        )
        assert _applies(rule, NS, "prod") is True
        assert _applies(rule, NS, "dev") is False

    def test_unrelated_leaf_is_indeterminate_and_surfaces(self) -> None:
        # A namespace-scoped rule could still drop logs from any service, so it shows on every service.
        rule = _rule(
            LogsExclusionRule.RuleType.PATH_DROP,
            config={
                "filter_group": _wrap(
                    {
                        "key": "k8s.namespace.name",
                        "type": "log_resource_attribute",
                        "operator": "exact",
                        "value": "prod",
                    }
                )
            },
        )
        assert _applies(rule, SVC, "anything") is True

    @parameterized.expand(
        [
            ("none_applies_everywhere", None, "api", True),
            ("service_scoped_match", "api", "api", True),
            ("service_scoped_miss", "api", "other", False),
        ]
    )
    def test_rate_limit_filter_group_scoping(self, _name: str, leaf_value: Any, value: str, expected: bool) -> None:
        config: dict = {"kb_per_second": 100}
        if leaf_value is not None:
            config["filter_group"] = _wrap({"key": "service_name", "operator": "exact", "value": leaf_value})
        rule = _rule(LogsExclusionRule.RuleType.RATE_LIMIT, config=config)
        assert _applies(rule, SVC, value) is expected


class TestMatchingDropRuleNames:
    def test_returns_names_in_order_and_caps(self) -> None:
        rules = [
            _rule(LogsExclusionRule.RuleType.RATE_LIMIT, name=f"rule-{i}", config={"kb_per_second": 1})
            for i in range(MAX_DROP_RULE_NAMES + 5)
        ]
        names = matching_drop_rule_names(rules, SVC, "api")
        assert names == [f"rule-{i}" for i in range(MAX_DROP_RULE_NAMES)]

    def test_only_matching_rules_returned(self) -> None:
        matches = _rule(LogsExclusionRule.RuleType.PATH_DROP, name="match", scope_service="api")
        misses = _rule(LogsExclusionRule.RuleType.PATH_DROP, name="miss", scope_service="other")
        assert matching_drop_rule_names([matches, misses], SVC, "api") == ["match"]
