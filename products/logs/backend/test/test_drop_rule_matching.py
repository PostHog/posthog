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

    def test_severity_rule_does_not_target_other_facets(self) -> None:
        # A severity rule explicitly targets only severity levels — it must not light up every
        # service / namespace value just because those logs might include a dropped severity.
        rule = _rule(LogsExclusionRule.RuleType.SEVERITY_SAMPLING, config={"actions": {"DEBUG": {"type": "drop"}}})
        assert _applies(rule, SVC, "api") is False
        assert _applies(rule, NS, "prod") is False


class TestScopeAndFilterGroupMatching:
    def test_legacy_scope_service_exact_match(self) -> None:
        rule = _rule(LogsExclusionRule.RuleType.PATH_DROP, scope_service="api")
        assert _applies(rule, SVC, "api") is True
        assert _applies(rule, SVC, "other") is False

    def test_legacy_scope_service_does_not_target_other_dimensions(self) -> None:
        # A rule scoped only to a service does not explicitly target any namespace, so it must not
        # surface on the namespace facet.
        rule = _rule(LogsExclusionRule.RuleType.PATH_DROP, scope_service="api")
        assert _applies(rule, NS, "prod") is False

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

    def test_other_dimension_leaf_does_not_surface_on_this_facet(self) -> None:
        # A namespace-scoped rule names no service, so it must not appear on the service facet.
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
        assert _applies(rule, SVC, "anything") is False

    @parameterized.expand([(SVC, "api"), (SEV, "error"), (NS, "prod")])
    def test_message_only_rule_targets_no_facet(self, dimension: FacetDimension, value: str) -> None:
        # The reported bug: a rule that filters only on the log message must not light up every facet.
        rule = _rule(
            LogsExclusionRule.RuleType.PATH_DROP,
            config={"filter_group": _wrap({"key": "message", "type": "log", "operator": "icontains", "value": "boom"})},
        )
        assert _applies(rule, dimension, value) is False

    def test_compound_rule_surfaces_on_the_dimension_it_names(self) -> None:
        # `service=envoy AND status=422`: the status leaf is on a non-facet dimension and is ignored,
        # so the rule still surfaces on the `envoy` service value (and only that one).
        rule = _rule(
            LogsExclusionRule.RuleType.PATH_DROP,
            config={
                "filter_group": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "service_name", "operator": "exact", "value": "envoy"},
                                {
                                    "key": "http.status_code",
                                    "type": "log_attribute",
                                    "operator": "exact",
                                    "value": "422",
                                },
                            ],
                        }
                    ],
                }
            },
        )
        assert _applies(rule, SVC, "envoy") is True
        assert _applies(rule, SVC, "api") is False

    @parameterized.expand(
        [
            ("unscoped_targets_nothing", None, "api", False),
            ("service_scoped_match", "api", "api", True),
            ("service_scoped_miss", "api", "other", False),
        ]
    )
    def test_rate_limit_filter_group_scoping(self, _name: str, leaf_value: Any, value: str, expected: bool) -> None:
        # An unscoped rate limit names no dimension, so it surfaces on no facet value.
        config: dict = {"kb_per_second": 100}
        if leaf_value is not None:
            config["filter_group"] = _wrap({"key": "service_name", "operator": "exact", "value": leaf_value})
        rule = _rule(LogsExclusionRule.RuleType.RATE_LIMIT, config=config)
        assert _applies(rule, SVC, value) is expected


class TestMatchingDropRuleNames:
    def test_returns_names_in_order_and_caps(self) -> None:
        rules = [
            _rule(LogsExclusionRule.RuleType.PATH_DROP, name=f"rule-{i}", scope_service="api")
            for i in range(MAX_DROP_RULE_NAMES + 5)
        ]
        names = matching_drop_rule_names(rules, SVC, "api")
        assert names == [f"rule-{i}" for i in range(MAX_DROP_RULE_NAMES)]

    def test_only_matching_rules_returned(self) -> None:
        matches = _rule(LogsExclusionRule.RuleType.PATH_DROP, name="match", scope_service="api")
        misses = _rule(LogsExclusionRule.RuleType.PATH_DROP, name="miss", scope_service="other")
        assert matching_drop_rule_names([matches, misses], SVC, "api") == ["match"]
