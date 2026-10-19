import pytest

from parameterized import parameterized

from posthog.schema import (
    MetricsDashboardVariable,
    MetricsDashboardVariableSelection,
    MetricsDashboardVariableSource,
    MetricsFilterOp,
    MetricsQueryFilter,
)

from posthog.hogql import ast

from products.metrics.backend.variable_options import apply_regex, re2_pattern
from products.metrics.backend.variables import (
    Variable,
    from_dashboard,
    sql_referenced_names,
    substitute_filter,
    substitute_promql,
    substitute_sql,
)

ONE = Variable(values=('pro"d',), is_all=False, all_value=None, options=())
MANY = Variable(values=("a.b", "c"), is_all=False, all_value=None, options=())
ALL = Variable(values=("x", "y"), is_all=True, all_value=None, options=())
ALL_WITH_VALUE = Variable(values=(), is_all=True, all_value="api-.*", options=())
DOTTED = Variable(values=("10.0.0.1",), is_all=False, all_value=None, options=())
INJECTED = Variable(values=("' OR 1=1 --",), is_all=False, all_value=None, options=())
QUOTED = Variable(values=("api'worker\nnext",), is_all=False, all_value=None, options=())


@parameterized.expand(
    [
        ("one_value_is_escaped", 'up{env="$env"}', ONE, 'up{env="pro\\"d"}'),
        ("many_values_are_a_regex", 'up{env=~"$env"}', MANY, 'up{env=~"(a\\\\.b|c)"}'),
        ("one_value_in_a_regex_matcher_is_escaped", 'up{env=~"$env"}', DOTTED, 'up{env=~"10\\\\.0\\\\.0\\\\.1"}'),
        ("single_quotes_and_newlines", "up{env='$env'}", QUOTED, "up{env='api\\'worker\\nnext'}"),
        ("double_quotes_keep_single_quotes", 'up{env="$env"}', QUOTED, 'up{env="api\'worker\\nnext"}'),
        ("single_quoted_regex_matcher", "up{env=~'$env'}", DOTTED, "up{env=~'10\\\\.0\\\\.0\\\\.1'}"),
        (
            "quote_in_a_comment_does_not_change_the_string",
            'up{ # don\'t filter\n env="$env"}',
            ONE,
            'up{ # don\'t filter\n env="pro\\"d"}',
        ),
        ("reference_in_a_comment_stays", "up # $env\n", ONE, "up # $env\n"),
        ("csv_format", 'up{env=~"${env:csv}"}', MANY, 'up{env=~"a.b,c"}'),
        ("csv_format_is_escaped", 'up{env=~"${env:csv}"}', ONE, 'up{env=~"pro\\"d"}'),
        ("all_matches_everything", 'up{env=~"$env"}', ALL, 'up{env=~".*"}'),
        ("all_value", 'up{env=~"[[env]]"}', ALL_WITH_VALUE, 'up{env=~"api-.*"}'),
        (
            "all_value_as_written",
            "up{env=~`$env`}",
            Variable(values=(), is_all=True, all_value="api\\..*", options=(), all_value_as_written=True),
            "up{env=~`api\\..*`}",
        ),
        (
            "all_value_is_escaped",
            'up{env=~"$env"}',
            Variable(values=(), is_all=True, all_value='api\\."x', options=()),
            'up{env=~"api\\\\.\\"x"}',
        ),
        (
            "range_variables_and_regex_groups_stay",
            'label_replace(rate(x{env="$env"}[$__rate_interval]), "a", "$1", "b", "(.*)")',
            ONE,
            'label_replace(rate(x{env="pro\\"d"}[$__rate_interval]), "a", "$1", "b", "(.*)")',
        ),
        ("escaped_dollar_in_a_matcher", 'up{c=~"\\\\$env", env="$env"}', ONE, 'up{c=~"\\\\$env", env="pro\\"d"}'),
        ("escaped_backslash_in_an_equality_matcher", 'up{c="C:\\\\$env"}', DOTTED, 'up{c="C:\\\\10.0.0.1"}'),
        ("escaped_dollar_in_a_raw_string", "up{c=~`\\$env`}", ONE, "up{c=~`\\$env`}"),
        (
            "named_regex_groups_stay",
            'label_replace(up, "dst", "$name", "src", "(?P<name>.*)")',
            ONE,
            'label_replace(up, "dst", "$name", "src", "(?P<name>.*)")',
        ),
    ]
)
def test_substitutes_promql(_name: str, expr: str, variable: Variable, expected: str) -> None:
    substitution = substitute_promql(expr, {"env": variable})
    assert (substitution.text, substitution.unresolved) == (expected, ())


@parameterized.expand(
    [
        ("label_replace_replacement", 'label_replace(up, "dst", "$name", "src", "(?P<name>.*)")', ()),
        ("label_join_separator", 'label_join(up, "dst", "$separator", "job", "env")', ("separator",)),
        ("label_replace_regex_escape", 'label_replace(up, "dst", "matched", "src", "prefix\\\\$USD")', ()),
        ("matcher", 'up{job="$job"}', ("job",)),
    ]
)
def test_only_label_replace_replacements_keep_undefined_names(_name: str, expr: str, unresolved: tuple[str]) -> None:
    assert substitute_promql(expr, {}).unresolved == unresolved


def test_promql_reports_unresolved_variables_and_keeps_the_named_ones() -> None:
    substitution = substitute_promql('up{env="$env", job="$job", zone="$zone"}', {"env": ONE}, keep={"zone"})
    assert (substitution.text, substitution.unresolved) == ('up{env="pro\\"d", job="$job", zone="$zone"}', ("job",))


@parameterized.expand(
    [
        ("one_value_is_a_constant", "SELECT 1 WHERE env = $env", ONE, ast.Constant(value='pro"d')),
        ("quoted_reference_is_one_constant", "SELECT 1 WHERE env = '$env'", ONE, ast.Constant(value='pro"d')),
        (
            "injected_value_stays_a_constant",
            "SELECT 1 WHERE env = '${env}'",
            INJECTED,
            ast.Constant(value="' OR 1=1 --"),
        ),
        (
            "many_values_are_a_tuple",
            "SELECT 1 WHERE env IN ${env}",
            MANY,
            ast.Tuple(exprs=[ast.Constant(value="a.b"), ast.Constant(value="c")]),
        ),
        (
            "all_is_its_values",
            "SELECT 1 WHERE env IN $env",
            ALL,
            ast.Tuple(exprs=[ast.Constant(value="x"), ast.Constant(value="y")]),
        ),
    ]
)
def test_sql_references_become_placeholders(_name: str, sql: str, variable: Variable, expected: ast.Expr) -> None:
    substitution = substitute_sql(sql, {"env": variable})
    assert substitution.sql.endswith("{metric_variable_env}")
    assert substitution.placeholders == {"metric_variable_env": expected}


@parameterized.expand(
    [
        ("field_names", "SELECT properties.$env, $environment FROM t"),
        ("comments", "SELECT 1 -- $env\n/* $env */ // $env\n# $env"),
        ("other_strings", "SELECT '$1', \"$env\""),
        ("nested_arrays", "SELECT [[env]]"),
    ]
)
def test_sql_text_that_is_not_a_reference_stays(_name: str, sql: str) -> None:
    substitution = substitute_sql(sql, {"env": ONE})
    assert (substitution.sql, substitution.placeholders) == (sql, {})


def test_sql_references_in_comments_are_not_dependencies() -> None:
    assert sql_referenced_names("SELECT 1 -- $job\rWHERE env IN $env /* $zone */ AND x = 'a-$region'") == [
        "env",
        "region",
    ]


def test_sql_time_aliases_become_the_date_placeholders() -> None:
    substitution = substitute_sql(
        "SELECT 1 WHERE t >= $__from AND t < '${__to}' GROUP BY $__interval, $__interval_seconds", {}
    )
    assert (substitution.sql, substitution.placeholders, substitution.unresolved) == (
        "SELECT 1 WHERE t >= {date_from} AND t < {date_to} GROUP BY {interval}, {interval_seconds}",
        {},
        (),
    )


def test_sql_quoted_reference_without_a_selection_is_reported() -> None:
    assert substitute_sql("SELECT 1 WHERE job = '$job'", {"env": ONE}).unresolved == ("job",)


def test_sql_reference_inside_a_longer_string_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"\$env is inside a string"):
        substitute_sql("SELECT 1 WHERE env = 'prefix-$env'", {"env": INJECTED})


@parameterized.expand(
    [
        ("one_value", MetricsFilterOp.EQ, "$env", ONE, (MetricsFilterOp.EQ, 'pro"d')),
        (
            "one_value_in_a_regex_filter",
            MetricsFilterOp.REGEX,
            "$env",
            DOTTED,
            (MetricsFilterOp.REGEX, "^(?:10\\.0\\.0\\.1)$"),
        ),
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
        ("whitespace_around_a_reference", MetricsFilterOp.EQ, " $env ", ONE, (MetricsFilterOp.EQ, ' pro"d ')),
        (
            "escaped_dollar_in_a_regex",
            MetricsFilterOp.REGEX,
            "\\$env-$env",
            ONE,
            (MetricsFilterOp.REGEX, '\\$env-(?:pro"d)'),
        ),
    ]
)
def test_substitutes_builder_filters(
    _name: str,
    op: MetricsFilterOp,
    value: str,
    variable: Variable,
    expected: tuple[MetricsFilterOp, str] | None,
) -> None:
    substitution = substitute_filter(MetricsQueryFilter(key="env", op=op, value=value), {"env": variable})
    assert substitution.unresolved == ()
    result = substitution.filter
    assert (None if result is None else (result.op, result.value)) == expected


@pytest.mark.parametrize("include_all", [True, False])
def test_all_needs_include_all(include_all: bool) -> None:
    definition = MetricsDashboardVariable(
        name="env",
        source=MetricsDashboardVariableSource.CUSTOM,
        includeAll=include_all,
        current=MetricsDashboardVariableSelection(values=["a"], all=True),
    )
    assert from_dashboard([definition])["env"].is_all is include_all


@parameterized.expand(
    [
        ("plain", "^api", "^api"),
        ("slashes", "/api-(.*)/", "api-(.*)"),
        ("flags_become_inline", "/API-(.*)/ig", "(?i)API-(.*)"),
    ]
)
def test_re2_pattern(_name: str, regex: str, expected: str) -> None:
    assert re2_pattern(regex) == expected


@parameterized.expand(
    [
        ("filter", "^api", ["api-1", "web-1"], ["api-1"]),
        ("numbered_group", "/api-(.*)/", ["api-1", "web-1"], ["1"]),
        ("named_group", "api-(?<value>.*)", ["api-1"], ["1"]),
        ("non_capturing_group", "api-(?:1|2)", ["api-1", "api-3"], ["api-1"]),
        ("flags", "/API-(.*)/i", ["api-1"], ["1"]),
        ("dot_matches_a_newline", "^api.*$", ["api\nworker"], ["api\nworker"]),
        ("empty_option_without_a_group", ".*", ["", "api"], ["", "api"]),
    ]
)
def test_apply_regex(_name: str, regex: str, options: list[str], expected: list[str]) -> None:
    assert apply_regex(options, regex) == expected


def test_apply_regex_reads_long_options_in_one_pass() -> None:
    assert apply_regex(['up{instance="api", ' + "x" * 10_000_000 + "}"], 'instance="([^"]+)"') == ["api"]
