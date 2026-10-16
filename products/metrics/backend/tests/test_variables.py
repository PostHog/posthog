import pytest

from parameterized import parameterized

from posthog.schema import (
    MetricsDashboardVariable,
    MetricsDashboardVariableSelection,
    MetricsDashboardVariableSource,
    MetricsFilterOp,
    MetricsQueryFilter,
)

from products.metrics.backend.variables import (
    Variable,
    from_dashboard,
    substitute_filter,
    substitute_promql,
    substitute_sql,
)

ONE = Variable(values=('pro"d',), is_all=False, all_value=None, options=())
MANY = Variable(values=("a.b", "c"), is_all=False, all_value=None, options=())
ALL = Variable(values=("x", "y"), is_all=True, all_value=None, options=())
ALL_WITH_VALUE = Variable(values=(), is_all=True, all_value="api-.*", options=())


@parameterized.expand(
    [
        ("one_value_is_escaped", 'up{env="$env"}', ONE, 'up{env="pro\\"d"}'),
        ("many_values_are_a_regex", 'up{env=~"$env"}', MANY, 'up{env=~"(a\\\\.b|c)"}'),
        ("csv_format", 'up{env=~"${env:csv}"}', MANY, 'up{env=~"a.b,c"}'),
        ("all_matches_everything", 'up{env=~"$env"}', ALL, 'up{env=~".*"}'),
        ("all_value", 'up{env=~"[[env]]"}', ALL_WITH_VALUE, 'up{env=~"api-.*"}'),
        (
            "range_variables_and_regex_groups_stay",
            'label_replace(rate(x{env="$env"}[$__rate_interval]), "a", "$1", "b", "(.*)")',
            ONE,
            'label_replace(rate(x{env="pro\\"d"}[$__rate_interval]), "a", "$1", "b", "(.*)")',
        ),
    ]
)
def test_substitutes_promql(_name: str, expr: str, variable: Variable, expected: str) -> None:
    assert substitute_promql(expr, {"env": variable}) == (expected, [])


def test_promql_reports_unresolved_variables() -> None:
    assert substitute_promql('up{env="$env", job="$job"}', {"env": ONE}) == ('up{env="pro\\"d", job="$job"}', ["job"])


@parameterized.expand(
    [
        ("one_value_is_a_literal", "SELECT 1 WHERE env = $env", ONE, "SELECT 1 WHERE env = 'pro\"d'"),
        ("quoted_reference_is_one_literal", "SELECT 1 WHERE env = '$env'", ONE, "SELECT 1 WHERE env = 'pro\"d'"),
        ("many_values_are_a_tuple", "SELECT 1 WHERE env IN ${env}", MANY, "SELECT 1 WHERE env IN ('a.b', 'c')"),
        ("all_is_the_loaded_options", "SELECT 1 WHERE env IN $env", ALL, "SELECT 1 WHERE env IN ('x', 'y')"),
        ("field_names_stay", "SELECT properties.$env, $environment", ONE, "SELECT properties.$env, $environment"),
    ]
)
def test_substitutes_sql_values_as_literals(_name: str, sql: str, variable: Variable, expected: str) -> None:
    assert substitute_sql(sql, {"env": variable}) == expected


def test_sql_value_cannot_break_out_of_its_literal() -> None:
    injected = Variable(values=("x' OR 1=1 --",), is_all=False, all_value=None, options=())
    assert substitute_sql("SELECT 1 WHERE env = $env", {"env": injected}) == ("SELECT 1 WHERE env = 'x\\' OR 1=1 --'")


@parameterized.expand(
    [
        ("one_value", MetricsFilterOp.EQ, "$env", ONE, (MetricsFilterOp.EQ, 'pro"d')),
        (
            "many_values_become_an_anchored_regex",
            MetricsFilterOp.EQ,
            "$env",
            MANY,
            (MetricsFilterOp.REGEX, "^(?:a\\.b|c)$"),
        ),
        ("negated_many_values", MetricsFilterOp.NEQ, "${env}", MANY, (MetricsFilterOp.NOT_REGEX, "^(?:a\\.b|c)$")),
        ("all_drops_the_filter", MetricsFilterOp.EQ, "$env", ALL, None),
        ("negated_all_matches_nothing", MetricsFilterOp.NEQ, "$env", ALL, (MetricsFilterOp.NOT_REGEX, ".*")),
        ("all_value", MetricsFilterOp.EQ, "$env", ALL_WITH_VALUE, (MetricsFilterOp.REGEX, "api-.*")),
        ("inside_a_regex", MetricsFilterOp.REGEX, "^$env-.*", MANY, (MetricsFilterOp.REGEX, "^(?:a\\.b|c)-.*")),
        ("all_inside_a_regex", MetricsFilterOp.REGEX, "^$env$", ALL, (MetricsFilterOp.REGEX, "^.*$")),
    ]
)
def test_substitutes_builder_filters(
    _name: str,
    op: MetricsFilterOp,
    value: str,
    variable: Variable,
    expected: tuple[MetricsFilterOp, str] | None,
) -> None:
    substituted, unresolved = substitute_filter(MetricsQueryFilter(key="env", op=op, value=value), {"env": variable})
    assert unresolved == []
    assert (None if substituted is None else (substituted.op, substituted.value)) == expected


@pytest.mark.parametrize("include_all", [True, False])
def test_all_needs_include_all(include_all: bool) -> None:
    definition = MetricsDashboardVariable(
        name="env",
        source=MetricsDashboardVariableSource.CUSTOM,
        includeAll=include_all,
        current=MetricsDashboardVariableSelection(values=["a"], all=True),
    )
    assert from_dashboard([definition])["env"].is_all is include_all
