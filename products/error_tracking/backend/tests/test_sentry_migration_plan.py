from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.facade.contracts import SentryMigrationFit, SentryMigrationRateLimit
from products.error_tracking.backend.logic.rules import compile_filter_bytecode
from products.error_tracking.backend.logic.sentry_migration.client import (
    MAX_FILTER_PATTERNS,
    SentryApiError,
    SentryProjectConfig,
    SentryRateLimit,
    parse_project_config,
)
from products.error_tracking.backend.logic.sentry_migration.plan import MAX_PATTERN_LENGTH, SentryMigrationPlanner

from common.hogvm.python.execute import execute_bytecode


def _config(**overrides: object) -> SentryProjectConfig:
    defaults: dict[str, object] = {
        "error_message_globs": (),
        "release_globs": (),
        "ip_filter": False,
        "browser_extensions": False,
        "localhost": False,
        "web_crawlers": False,
        "legacy_browsers": (),
        "react_hydration_errors": False,
        "chunk_load_errors": False,
        "rate_limits": (),
    }
    return SentryProjectConfig(**{**defaults, **overrides})  # type: ignore[arg-type]


def _planner() -> SentryMigrationPlanner:
    return SentryMigrationPlanner(existing_suppression_filters=[], enabled_built_in_filters=[], project_rate_limit=None)


class TestSentryMigrationRuleMatching(BaseTest):
    @parameterized.expand(
        [
            (
                "contains_glob",
                {"error_message_globs": ("*ResizeObserver loop*",)},
                [
                    (
                        {"$exception_types": ["Error"], "$exception_values": ["ResizeObserver loop limit exceeded"]},
                        True,
                    ),
                    ({"$exception_types": ["Error"], "$exception_values": ["resizeobserver LOOP completed"]}, True),
                    ({"$exception_types": ["Error"], "$exception_values": ["Something else"]}, False),
                ],
            ),
            (
                "underscore_in_contains_glob_stays_literal",
                {"error_message_globs": ("*user_id*",)},
                [
                    ({"$exception_types": ["Error"], "$exception_values": ["unknown user_id"]}, True),
                    ({"$exception_types": ["Error"], "$exception_values": ["unknown userXid"]}, False),
                ],
            ),
            (
                "type_prefixed_glob",
                {"error_message_globs": ("TypeError: Failed to fetch*",)},
                [
                    (
                        {"$exception_types": ["TypeError"], "$exception_values": ["Failed to fetch (api.example.com)"]},
                        True,
                    ),
                    (
                        {"$exception_types": ["Error"], "$exception_values": ["Failed to fetch (api.example.com)"]},
                        False,
                    ),
                    ({"$exception_types": ["TypeError"], "$exception_values": ["Load failed"]}, False),
                ],
            ),
            (
                "type_prefix_ignores_case",
                {"error_message_globs": ("typeerror: failed to fetch*",)},
                [
                    (
                        {"$exception_types": ["TypeError"], "$exception_values": ["Failed to fetch (api.example.com)"]},
                        True,
                    ),
                    ({"$exception_types": ["RangeError"], "$exception_values": ["Failed to fetch"]}, False),
                ],
            ),
            (
                "character_class",
                {"error_message_globs": ("*code [45]??*",)},
                [
                    ({"$exception_types": ["Error"], "$exception_values": ["Request failed with code 404"]}, True),
                    ({"$exception_types": ["Error"], "$exception_values": ["Request failed with code 304"]}, False),
                ],
            ),
            (
                "negated_character_class_with_range",
                {"error_message_globs": ("status [!0-3]*",)},
                [
                    ({"$exception_types": ["Error"], "$exception_values": ["status 503"]}, True),
                    ({"$exception_types": ["Error"], "$exception_values": ["status 204"]}, False),
                ],
            ),
            (
                "glob_matching_type_only",
                {"error_message_globs": ("ChunkLoadError*",)},
                [
                    ({"$exception_types": ["ChunkLoadError"], "$exception_values": ["Loading chunk 7 failed"]}, True),
                    ({"$exception_types": ["Error"], "$exception_values": ["Loading chunk 7 failed"]}, False),
                ],
            ),
            (
                "alternatives_and_single_character_wildcard",
                {"error_message_globs": ("{Network,Fetch} error ?",)},
                [
                    ({"$exception_types": ["Error"], "$exception_values": ["fetch error 5"]}, True),
                    ({"$exception_types": ["Error"], "$exception_values": ["Network error 12"]}, False),
                    ({"$exception_types": ["Error"], "$exception_values": ["Socket error 5"]}, False),
                ],
            ),
            (
                "unclosed_delimiters_after_closed_ones_stay_literal",
                {"error_message_globs": ("{Network,Fetch} code [45]* {retry [] [later",)},
                [
                    ({"$exception_types": ["Error"], "$exception_values": ["Fetch code 404 {retry [] [later"]}, True),
                    ({"$exception_types": ["Error"], "$exception_values": ["Fetch code 304 {retry [] [later"]}, False),
                    ({"$exception_types": ["Error"], "$exception_values": ["Fetch code 404 retry later"]}, False),
                ],
            ),
            (
                "regex_metacharacters_stay_literal",
                {"error_message_globs": ("Price (USD) is $5.00",)},
                [
                    ({"$exception_types": ["Error"], "$exception_values": ["Price (USD) is $5.00"]}, True),
                    ({"$exception_types": ["Error"], "$exception_values": ["Price USD is $5x00"]}, False),
                ],
            ),
            (
                "wildcard_spans_newlines",
                {"error_message_globs": ("Render failed*at Component",)},
                [
                    (
                        {"$exception_types": ["Error"], "$exception_values": ["Render failed\n  in App\nat Component"]},
                        True,
                    ),
                ],
            ),
            (
                "release_with_package_name",
                {"release_globs": ("my-app@1.2.*",)},
                [
                    ({"$app_version": "1.2.3"}, True),
                    ({"$app_version": "1.3.0"}, False),
                    ({}, False),
                ],
            ),
        ]
    )
    def test_converted_rule_matches_what_sentry_filtered(
        self, _name: str, config_overrides: dict, cases: list[tuple[dict, bool]]
    ) -> None:
        items = _planner().build(_config(**config_overrides))
        assert len(items) == 1
        filters = items[0].suppression_rule_filters
        assert filters is not None
        bytecode = compile_filter_bytecode(self.team.id, filters)

        for event_props, expected in cases:
            matched = bool(execute_bytecode(bytecode, {"properties": event_props}).result)
            assert matched == expected, f"Expected {expected} for {event_props}"


class TestSentryMigrationPlanConversion(SimpleTestCase):
    @parameterized.expand(
        [
            ("hourly_window", 1000, 3600, 1000, 60, SentryMigrationFit.GOOD),
            ("one_minute_window", 100, 60, 1500, 15, SentryMigrationFit.PARTIAL),
            ("daily_window", 10000, 86400, 417, 60, SentryMigrationFit.PARTIAL),
            ("tiny_daily_limit", 1, 86400, 1, 60, SentryMigrationFit.PARTIAL),
            ("twenty_minute_window", 200, 1200, 150, 15, SentryMigrationFit.PARTIAL),
            ("too_large_for_posthog", 3_000_000, 1, None, None, SentryMigrationFit.UNSUPPORTED),
        ]
    )
    def test_rate_limit_window_converts_to_a_supported_bucket(
        self,
        _name: str,
        count: int,
        window_seconds: int,
        expected_value: int | None,
        expected_bucket_minutes: int | None,
        expected_fit: SentryMigrationFit,
    ) -> None:
        rate_limit = SentryRateLimit(key_label="Default", key_id="abc", count=count, window_seconds=window_seconds)
        [item] = _planner().build(_config(rate_limits=(rate_limit,)))

        expected_rate_limit = (
            SentryMigrationRateLimit(value=expected_value, bucket_size_minutes=expected_bucket_minutes)
            if expected_value is not None and expected_bucket_minutes is not None
            else None
        )
        assert item.rate_limit == expected_rate_limit
        assert item.fit == expected_fit

    @parameterized.expand([("error_message", "error_message_globs"), ("release", "release_globs")])
    def test_pattern_too_long_to_import_is_listed_without_a_rule(self, _name: str, config_key: str) -> None:
        glob = "*" + "{[" * MAX_PATTERN_LENGTH

        [item] = _planner().build(_config(**{config_key: (glob,)}))

        assert item.fit == SentryMigrationFit.UNSUPPORTED
        assert item.suppression_rule_filters is None
        assert len(item.sentry_value) < len(glob)

    @parameterized.expand([("error_messages", "filters:error_messages"), ("releases", "filters:releases")])
    def test_more_filters_than_posthog_imports_fail_the_preview(self, _name: str, option: str) -> None:
        patterns = "\n".join(f"pattern {number}" for number in range(MAX_FILTER_PATTERNS + 1))

        with self.assertRaisesRegex(SentryApiError, "PostHog can import up to"):
            parse_project_config(details={"options": {option: patterns}}, filters=[], keys=[])

    @parameterized.expand(
        [
            ("localhost", {"localhost": True}, "On", "localhost", SentryMigrationFit.PARTIAL),
            ("web_crawlers", {"web_crawlers": True}, "On", "web_crawlers", SentryMigrationFit.PARTIAL),
            (
                "react_hydration_errors",
                {"react_hydration_errors": True},
                "On",
                "react_hydration_errors",
                SentryMigrationFit.GOOD,
            ),
            ("chunk_load_errors", {"chunk_load_errors": True}, "On", "chunk_load_errors", SentryMigrationFit.PARTIAL),
            (
                "legacy_browsers",
                {"legacy_browsers": ("ie11", "safari_pre_6", "netscape")},
                "Internet Explorer 11, Safari 5 and older, netscape",
                "legacy_browsers",
                SentryMigrationFit.PARTIAL,
            ),
            ("browser_extensions", {"browser_extensions": True}, "On", None, SentryMigrationFit.UNSUPPORTED),
            ("ip_filter", {"ip_filter": True}, "On", None, SentryMigrationFit.UNSUPPORTED),
        ]
    )
    def test_inbound_filters_turn_on_the_matching_automatic_rule(
        self,
        _name: str,
        config_overrides: dict,
        expected_value: str,
        expected_key: str | None,
        expected_fit: SentryMigrationFit,
    ) -> None:
        planner = SentryMigrationPlanner(
            existing_suppression_filters=[], enabled_built_in_filters=["localhost"], project_rate_limit=None
        )

        [item] = planner.build(_config(**config_overrides))

        assert item.sentry_value == expected_value
        assert (item.built_in_filter.key if item.built_in_filter else None) == expected_key
        assert item.fit == expected_fit
        assert item.suppression_rule_filters is None
        assert item.already_in_posthog == (expected_key == "localhost")
