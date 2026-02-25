import pytest

from parameterized import parameterized

from products.endpoints.backend.query_handlers import (
    _HANDLER_REGISTRY,
    FunnelsQueryHandler,
    HogQLQueryHandler,
    LifecycleQueryHandler,
    PathsQueryHandler,
    QueryKindHandler,
    RetentionQueryHandler,
    StickinessQueryHandler,
    TrendsQueryHandler,
    _get_single_breakdown_info,
    _get_single_breakdown_property,
    get_query_handler,
)


class TestGetQueryHandler:
    @parameterized.expand(
        [
            ("HogQLQuery", HogQLQueryHandler),
            ("TrendsQuery", TrendsQueryHandler),
            ("FunnelsQuery", FunnelsQueryHandler),
            ("RetentionQuery", RetentionQueryHandler),
            ("LifecycleQuery", LifecycleQueryHandler),
            ("StickinessQuery", StickinessQueryHandler),
            ("PathsQuery", PathsQueryHandler),
        ]
    )
    def test_factory_returns_correct_handler(self, kind, expected_class):
        assert isinstance(get_query_handler(kind), expected_class)

    def test_factory_raises_for_unknown_kind(self):
        with pytest.raises(ValueError, match="Unknown query kind"):
            get_query_handler("UnknownQuery")

    def test_factory_raises_for_none(self):
        with pytest.raises(ValueError, match="Unknown query kind"):
            get_query_handler(None)

    def test_factory_returns_same_instance_for_same_kind(self):
        assert get_query_handler("HogQLQuery") is get_query_handler("HogQLQuery")

    def test_registry_contains_all_expected_kinds(self):
        expected = {
            "HogQLQuery",
            "TrendsQuery",
            "FunnelsQuery",
            "RetentionQuery",
            "LifecycleQuery",
            "StickinessQuery",
            "PathsQuery",
        }
        assert set(_HANDLER_REGISTRY.keys()) == expected


class TestQueryKindHandlerConstants:
    @parameterized.expand(
        [
            ("TrendsQuery", True, "breakdown_value"),
            ("FunnelsQuery", True, "final_prop"),
            ("RetentionQuery", True, "breakdown_value"),
            ("LifecycleQuery", False, None),
            ("StickinessQuery", False, None),
            ("PathsQuery", False, None),
            ("HogQLQuery", False, None),
        ]
    )
    def test_breakdown_constants(self, kind, expected_supports, expected_column):
        handler = get_query_handler(kind)
        assert handler.SUPPORTS_BREAKDOWN == expected_supports
        assert handler.BREAKDOWN_COLUMN == expected_column

    @parameterized.expand(
        [
            ("HogQLQuery", True),
            ("TrendsQuery", False),
            ("FunnelsQuery", False),
            ("RetentionQuery", False),
            ("LifecycleQuery", False),
            ("StickinessQuery", False),
            ("PathsQuery", False),
        ]
    )
    def test_supports_pagination(self, kind, expected):
        assert get_query_handler(kind).SUPPORTS_PAGINATION == expected

    @parameterized.expand(
        [
            ("HogQLQuery", False),
            ("TrendsQuery", True),
            ("FunnelsQuery", True),
            ("RetentionQuery", True),
            ("LifecycleQuery", True),
            ("StickinessQuery", True),
            ("PathsQuery", True),
        ]
    )
    def test_accepts_filters_override(self, kind, expected):
        assert get_query_handler(kind).ACCEPTS_FILTERS_OVERRIDE == expected


class TestBreakdownFilterConditions:
    @parameterized.expand(
        [
            ("TrendsQuery", "Chrome", "breakdown_value"),
            ("RetentionQuery", "Chrome", "breakdown_value"),
            ("FunnelsQuery", "Chrome", "final_prop"),
        ]
    )
    def test_breakdown_condition_uses_correct_column(self, kind, value, expected_col):
        from posthog.hogql import ast

        handler = get_query_handler(kind)
        condition = handler.build_breakdown_filter_condition(value)
        assert condition is not None
        assert isinstance(condition, ast.Call)
        assert condition.name == "has"
        assert isinstance(condition.args[0], ast.Field)
        assert condition.args[0].chain == [expected_col]
        assert isinstance(condition.args[1], ast.Constant)
        assert condition.args[1].value == value

    @parameterized.expand(["LifecycleQuery", "StickinessQuery", "PathsQuery", "HogQLQuery"])
    def test_non_breakdown_types_return_none(self, kind):
        handler = get_query_handler(kind)
        assert handler.build_breakdown_filter_condition("val") is None


class TestHogQLHandlerGetAllowedVariables:
    @parameterized.expand(
        [
            (
                "with_variables",
                {
                    "kind": "HogQLQuery",
                    "variables": {"id1": {"code_name": "event_name"}, "id2": {"code_name": "cohort"}},
                },
                False,
                {"event_name", "cohort"},
            ),
            (
                "empty_variables",
                {"kind": "HogQLQuery", "variables": {}},
                False,
                set(),
            ),
            (
                "no_variables_key",
                {"kind": "HogQLQuery"},
                False,
                set(),
            ),
            (
                "variable_missing_code_name",
                {"kind": "HogQLQuery", "variables": {"id1": {}}},
                False,
                set(),
            ),
        ]
    )
    def test_allowed_variables(self, _name, query, is_materialized, expected):
        handler = HogQLQueryHandler()
        result = handler.get_allowed_variables(query, is_materialized, version=None)
        assert result == expected


class TestInsightHandlerGetAllowedVariables:
    @parameterized.expand(
        [
            (
                "trends_non_mat_with_breakdown",
                "TrendsQuery",
                {"breakdownFilter": {"breakdowns": [{"property": "$browser", "type": "event"}]}},
                False,
                {"$browser", "date_from", "date_to"},
            ),
            (
                "trends_materialized_with_breakdown",
                "TrendsQuery",
                {"breakdownFilter": {"breakdowns": [{"property": "$browser", "type": "event"}]}},
                True,
                {"$browser"},
            ),
            (
                "trends_non_mat_no_breakdown",
                "TrendsQuery",
                {},
                False,
                {"date_from", "date_to"},
            ),
            (
                "lifecycle_non_mat",
                "LifecycleQuery",
                {},
                False,
                {"date_from", "date_to"},
            ),
            (
                "lifecycle_materialized",
                "LifecycleQuery",
                {},
                True,
                set(),
            ),
        ]
    )
    def test_allowed_variables(self, _name, kind, query, is_materialized, expected):
        handler = get_query_handler(kind)
        result = handler.get_allowed_variables(query, is_materialized, version=None)
        assert result == expected


class TestInsightHandlerRequiredVariablesForMaterialized:
    @parameterized.expand(
        [
            (
                "trends_with_breakdown",
                "TrendsQuery",
                {"breakdownFilter": {"breakdowns": [{"property": "$browser", "type": "event"}]}},
                {"$browser"},
            ),
            (
                "trends_no_breakdown",
                "TrendsQuery",
                {},
                set(),
            ),
            (
                "trends_multi_breakdown_returns_none",
                "TrendsQuery",
                {"breakdownFilter": {"breakdowns": [{"property": "$browser"}, {"property": "$os"}]}},
                set(),
            ),
            (
                "lifecycle",
                "LifecycleQuery",
                {},
                set(),
            ),
            (
                "stickiness",
                "StickinessQuery",
                {},
                set(),
            ),
            (
                "paths",
                "PathsQuery",
                {},
                set(),
            ),
        ]
    )
    def test_required_variables_for_materialized(self, _name, kind, query, expected):
        handler = get_query_handler(kind)
        result = handler.get_required_variables_for_materialized(query, version=None)
        assert result == expected


class TestCanMaterialize:
    @parameterized.expand(
        [
            ("hogql_empty_query", "HogQLQuery", {"query": ""}, False),
            ("hogql_no_query_key", "HogQLQuery", {}, False),
            ("hogql_invalid_query_type", "HogQLQuery", {"query": 123}, False),
            ("hogql_valid_query", "HogQLQuery", {"query": "SELECT 1"}, True),
            ("trends_no_breakdown", "TrendsQuery", {}, True),
            (
                "trends_single_breakdown",
                "TrendsQuery",
                {"breakdownFilter": {"breakdowns": [{"property": "$browser"}]}},
                True,
            ),
            (
                "trends_multi_breakdown",
                "TrendsQuery",
                {"breakdownFilter": {"breakdowns": [{"property": "$browser"}, {"property": "$os"}]}},
                False,
            ),
            ("lifecycle_any_query", "LifecycleQuery", {}, True),
        ]
    )
    def test_can_materialize(self, _name, kind, query, expected_can):
        handler = get_query_handler(kind)
        can_mat, reason = handler.can_materialize(query)
        assert can_mat == expected_can
        if not expected_can:
            assert reason


class TestCanUseMaterialized:
    @parameterized.expand(
        [
            ("no_variables_always_ok", "TrendsQuery", {}, None, True),
            (
                "trends_with_valid_breakdown_var",
                "TrendsQuery",
                {"breakdownFilter": {"breakdowns": [{"property": "$browser", "type": "event"}]}},
                {"$browser": "Chrome"},
                True,
            ),
            (
                "trends_with_unknown_var",
                "TrendsQuery",
                {"breakdownFilter": {"breakdowns": [{"property": "$browser", "type": "event"}]}},
                {"$os": "Mac"},
                False,
            ),
            (
                "trends_with_no_breakdown_but_vars",
                "TrendsQuery",
                {},
                {"$browser": "Chrome"},
                False,
            ),
            (
                "lifecycle_with_any_variable_is_false",
                "LifecycleQuery",
                {},
                {"date_from": "-7d"},
                False,
            ),
        ]
    )
    def test_can_use_materialized(self, _name, kind, query, request_variables, expected):
        handler = get_query_handler(kind)
        result = handler.can_use_materialized(query, version=None, request_variables=request_variables)
        assert result == expected


class TestValidateFiltersOverride:
    def test_hogql_raises_validation_error(self):
        from rest_framework.exceptions import ValidationError

        handler = HogQLQueryHandler()
        with pytest.raises(ValidationError):
            handler.validate_filters_override("HogQLQuery")

    @parameterized.expand(
        ["TrendsQuery", "FunnelsQuery", "RetentionQuery", "LifecycleQuery", "StickinessQuery", "PathsQuery"]
    )
    def test_insight_types_do_not_raise(self, kind):
        handler = get_query_handler(kind)
        handler.validate_filters_override(kind)  # should not raise


class TestGetSingleBreakdownProperty:
    @parameterized.expand(
        [
            ("legacy_format", {"breakdown": "$browser", "breakdown_type": "event"}, "$browser"),
            ("new_format_single", {"breakdowns": [{"property": "$browser", "type": "event"}]}, "$browser"),
            ("new_format_multiple", {"breakdowns": [{"property": "$browser"}, {"property": "$os"}]}, None),
            ("empty", {}, None),
        ]
    )
    def test_extracts_property(self, _name, breakdown_filter, expected):
        assert _get_single_breakdown_property(breakdown_filter) == expected


class TestGetSingleBreakdownInfo:
    @parameterized.expand(
        [
            ("legacy_format", {"breakdown": "$browser", "breakdown_type": "event"}, ("$browser", "event")),
            ("legacy_default_type", {"breakdown": "$browser"}, ("$browser", "event")),
            ("new_format_single", {"breakdowns": [{"property": "$browser", "type": "group"}]}, ("$browser", "group")),
            ("new_format_multiple", {"breakdowns": [{"property": "$browser"}, {"property": "$os"}]}, None),
            ("empty", {}, None),
        ]
    )
    def test_extracts_info(self, _name, breakdown_filter, expected):
        assert _get_single_breakdown_info(breakdown_filter) == expected


class TestBaseHandlerDefaults:
    """Verify QueryKindHandler base class returns safe defaults for everything."""

    def test_get_allowed_variables_returns_empty_set(self):
        handler = QueryKindHandler()
        assert handler.get_allowed_variables({}, False, None) == set()

    def test_get_required_variables_returns_empty_set(self):
        assert QueryKindHandler().get_required_variables_for_materialized({}, None) == set()

    def test_build_breakdown_filter_condition_returns_none(self):
        assert QueryKindHandler().build_breakdown_filter_condition("val") is None

    def test_build_materialized_select_columns_returns_star(self):
        from posthog.hogql import ast

        cols = QueryKindHandler().build_materialized_select_columns({}, None, None)
        assert len(cols) == 1
        assert isinstance(cols[0], ast.Field)
        assert cols[0].chain == ["*"]

    def test_get_original_limit_returns_none(self):
        assert QueryKindHandler().get_original_limit({}, None) is None

    def test_can_use_materialized_returns_true(self):
        assert QueryKindHandler().can_use_materialized({}, None, None) is True

    def test_can_materialize_returns_true(self):
        ok, reason = QueryKindHandler().can_materialize({})
        assert ok is True
        assert reason == ""

    def test_validate_filters_override_does_not_raise(self):
        QueryKindHandler().validate_filters_override("AnyKind")  # no-op

    def test_resolve_inline_overrides_returns_empty(self):
        overrides = QueryKindHandler().resolve_inline_overrides({}, None, None)
        assert overrides.variables_override is None
        assert overrides.filters_override is None
        assert overrides.deprecation_headers is None
