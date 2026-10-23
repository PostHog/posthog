from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.facade.contracts import SentryMigrationFit, SentryMigrationRateLimit
from products.error_tracking.backend.logic.rules import compile_filter_bytecode
from products.error_tracking.backend.logic.sentry_migration.client import SentryProjectConfig, SentryRateLimit
from products.error_tracking.backend.logic.sentry_migration.plan import SentryMigrationPlanner

from common.hogvm.python.execute import execute_bytecode


def _config(**overrides: object) -> SentryProjectConfig:
    defaults: dict[str, object] = {
        "error_message_globs": (),
        "release_globs": (),
        "blocked_ips": (),
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
    return SentryMigrationPlanner(existing_suppression_filters=[], project_rate_limit=None)


CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
)


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
            (
                "localhost",
                {"localhost": True},
                [
                    ({"$current_url": "http://localhost:3000/settings"}, True),
                    ({"$current_url": "http://127.0.0.1/"}, True),
                    ({"$current_url": "http://app.localhost"}, True),
                    ({"$current_url": "file:///Users/someone/index.html"}, True),
                    ({"$current_url": "https://localhost.example.com/"}, False),
                    ({"$current_url": "https://app.example.com/?next=http://localhost"}, False),
                    ({}, False),
                ],
            ),
            (
                "web_crawlers",
                {"web_crawlers": True},
                [
                    (
                        {"$raw_user_agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
                        True,
                    ),
                    (
                        {
                            "$raw_user_agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2)"
                        },
                        True,
                    ),
                    ({"$raw_user_agent": "Slackbot 1.0 (+https://api.slack.com/robots)"}, False),
                    ({"$raw_user_agent": CHROME_UA}, False),
                    ({}, False),
                ],
            ),
            (
                "legacy_safari",
                {"legacy_browsers": ("safari",)},
                [
                    ({"$browser": "Mobile Safari", "$browser_version": 15.4}, True),
                    ({"$browser": "Safari", "$browser_version": 16}, False),
                    ({"$browser": "Chrome", "$browser_version": 100}, False),
                    ({"$browser": "Safari"}, False),
                ],
            ),
            (
                "legacy_internet_explorer",
                {"legacy_browsers": ("ie",)},
                [
                    ({"$browser": "Internet Explorer", "$browser_version": 11}, True),
                    ({"$browser": "Microsoft Edge", "$browser_version": 11}, False),
                ],
            ),
            (
                "react_hydration_errors",
                {"react_hydration_errors": True},
                [
                    (
                        {
                            "$exception_values": [
                                "Minified React error #418; visit https://react.dev/errors/418?args[]="
                            ]
                        },
                        True,
                    ),
                    (
                        {
                            "$exception_values": [
                                "https://reactjs.org/docs/error-decoder.html?invariant=425 for details"
                            ]
                        },
                        True,
                    ),
                    ({"$exception_values": ["Minified React error #310; visit https://react.dev/errors/310"]}, False),
                ],
            ),
            (
                "chunk_load_errors",
                {"chunk_load_errors": True},
                [
                    ({"$exception_types": ["ChunkLoadError"], "$exception_values": ["Loading chunk 5 failed."]}, True),
                    (
                        {
                            "$exception_types": ["Error"],
                            "$exception_values": ["Uncaught (in promise): ChunkLoadError: Loading chunk 5 failed."],
                        },
                        True,
                    ),
                    ({"$exception_types": ["Error"], "$exception_values": ["Loading CSS failed"]}, False),
                ],
            ),
            (
                "browser_extension_messages",
                {"browser_extensions": True},
                [
                    ({"$exception_values": ["Extension context invalidated."]}, True),
                    ({"$exception_values": ["Cannot redefine property: ethereum"]}, True),
                    ({"$exception_values": ["Cannot read properties of undefined"]}, False),
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

    @parameterized.expand(
        [
            ("all_old_ie_subfilters_merge", ("ie_pre_9", "ie9", "ie10", "ie11"), ["Internet Explorer, all versions"]),
            ("disjoint_ie_ranges", ("ie_pre_9", "ie11"), ["Internet Explorer 8 and older", "Internet Explorer 11"]),
            ("new_key_covers_deprecated_one", ("safari", "safari_pre_6"), ["Safari 15 and older"]),
            (
                "default_table",
                ("default",),
                [
                    "Internet Explorer 9 and older",
                    "Safari 5 and older",
                    "Opera 14 and older",
                    "Opera Mini 7 and older",
                    "Android browser 3 and older",
                ],
            ),
            ("unknown_subfilter", ("netscape",), []),
        ]
    )
    def test_legacy_browser_subfilters_become_one_rule_per_range(
        self, _name: str, subfilters: tuple[str, ...], expected_values: list[str]
    ) -> None:
        items = _planner().build(_config(legacy_browsers=subfilters))

        assert [item.sentry_value for item in items] == expected_values
        assert len({item.id for item in items}) == len(items)
