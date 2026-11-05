from posthog.test.base import APIBaseTest

from parameterized import parameterized

from products.error_tracking.backend.logic.built_in_filter_definitions import BUILT_IN_FILTERS_BY_KEY
from products.error_tracking.backend.logic.rules import compile_filter_bytecode

from common.hogvm.python.execute import execute_bytecode


def _leaf(key: str, value: list[str] | str, operator: str = "exact") -> dict:
    return {"key": key, "type": "event", "value": value, "operator": operator}


class TestServerFilterEvaluation(APIBaseTest):
    def _eval(self, bytecode: list, event_props: dict) -> bool:
        result = execute_bytecode(bytecode, {"properties": event_props})
        return bool(result.result)

    @parameterized.expand(
        [
            (
                "and_exact_match",
                {
                    "type": "AND",
                    "values": [
                        {"type": "AND", "values": [_leaf("$exception_type", ["TypeError"])]},
                    ],
                },
                [
                    ({"$exception_type": "TypeError"}, True),
                    ({"$exception_type": "RangeError"}, False),
                    ({}, False),
                ],
            ),
            (
                "or_with_negative_operator",
                {
                    "type": "OR",
                    "values": [
                        {"type": "AND", "values": [_leaf("$exception_type", ["TypeError"])]},
                        {"type": "AND", "values": [_leaf("$exception_message", ["expected"], "is_not")]},
                    ],
                },
                [
                    ({"$exception_type": "TypeError"}, True),
                    ({"$exception_message": "unexpected"}, True),
                    ({"$exception_type": "RangeError", "$exception_message": "expected"}, False),
                ],
            ),
            (
                "and_with_icontains",
                {
                    "type": "AND",
                    "values": [
                        {"type": "AND", "values": [_leaf("$exception_type", ["TypeError"])]},
                        {"type": "AND", "values": [_leaf("$exception_message", ["null"], "icontains")]},
                    ],
                },
                [
                    ({"$exception_type": "TypeError", "$exception_message": "Cannot read null"}, True),
                    ({"$exception_type": "TypeError", "$exception_message": "other"}, False),
                    ({"$exception_message": "Cannot read null"}, False),
                ],
            ),
            (
                "or_with_regex",
                {
                    "type": "OR",
                    "values": [
                        {"type": "AND", "values": [_leaf("$exception_type", ["TypeError"])]},
                        {"type": "AND", "values": [_leaf("$exception_message", ".*null.*", "regex")]},
                    ],
                },
                [
                    ({"$exception_type": "TypeError"}, True),
                    ({"$exception_message": "Cannot read null"}, True),
                    ({"$exception_type": "RangeError", "$exception_message": "some error"}, False),
                ],
            ),
        ]
    )
    def test_filter_bytecode_evaluation(self, _name: str, filters: dict, cases: list[tuple[dict, bool]]) -> None:
        bytecode = compile_filter_bytecode(self.team.id, filters)

        for event_props, expected in cases:
            assert self._eval(bytecode, event_props) == expected, f"Expected {expected} for props {event_props}"

    @parameterized.expand(
        [
            (
                "web_crawlers",
                [
                    (
                        {"$raw_user_agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
                        True,
                    ),
                    (
                        {
                            "$raw_user_agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)"
                        },
                        True,
                    ),
                    (
                        {
                            "$raw_user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/120.0.0.0 Safari/537.36"
                        },
                        True,
                    ),
                    (
                        {
                            "$raw_user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
                        },
                        False,
                    ),
                    (
                        {
                            "$raw_user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
                        },
                        False,
                    ),
                    (
                        {
                            "$raw_user_agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot"
                        },
                        False,
                    ),
                    ({"$raw_user_agent": "axios/1.6.0"}, False),
                    ({"$raw_user_agent": ""}, False),
                    ({}, False),
                ],
            ),
            (
                "localhost",
                [
                    ({"$current_url": "http://localhost:3000/dashboard"}, True),
                    ({"$current_url": "https://app.localhost/settings"}, True),
                    ({"$current_url": "http://127.0.0.1:8000"}, True),
                    ({"$current_url": "http://[::1]:5173/"}, True),
                    ({"$current_url": "http://0.0.0.0:8080/"}, True),
                    ({"$current_url": "file:///Users/example/index.html"}, True),
                    ({"$current_url": "HTTP://LOCALHOST"}, True),
                    ({"$current_url": "https://localhost.example.com/"}, False),
                    ({"$current_url": "https://example.com/?next=http://localhost:3000"}, False),
                    ({"$current_url": "http://localhostfoo/"}, False),
                    ({}, False),
                ],
            ),
            (
                "legacy_browsers",
                [
                    ({"$browser": "Internet Explorer", "$browser_version": 11}, True),
                    ({"$browser": "Internet Explorer"}, True),
                    ({"$browser": "Chrome", "$browser_version": 86}, True),
                    ({"$browser": "Chrome", "$browser_version": "86.0.4240.198"}, True),
                    ({"$browser": "Chrome", "$browser_version": 87}, False),
                    ({"$browser": "Chrome", "$browser_version": 120.0}, False),
                    ({"$browser": "Microsoft Edge", "$browser_version": 18}, True),
                    ({"$browser": "Microsoft Edge", "$browser_version": 88}, False),
                    ({"$browser": "Firefox", "$browser_version": 77}, True),
                    ({"$browser": "Firefox", "$browser_version": 78}, False),
                    ({"$browser": "Safari", "$browser_version": 13.1}, True),
                    ({"$browser": "Safari", "$browser_version": 14}, False),
                    ({"$browser": "Mobile Safari", "$browser_version": 9}, True),
                    ({"$browser": "Opera", "$browser_version": 72}, True),
                    ({"$browser": "Opera", "$browser_version": 73}, False),
                    ({"$browser": "Chrome", "$browser_version": "unknown"}, False),
                    ({"$browser": "Chrome"}, False),
                    ({"$browser_version": 10}, False),
                    ({}, False),
                ],
            ),
            (
                "react_hydration_errors",
                [
                    (
                        {
                            "$exception_values": [
                                "Minified React error #418; visit https://react.dev/errors/418?args[]=text for the full message"
                            ]
                        },
                        True,
                    ),
                    (
                        {
                            "$exception_values": [
                                "Minified React error #423; visit https://reactjs.org/docs/error-decoder.html?invariant=423 for the full message"
                            ]
                        },
                        True,
                    ),
                    (
                        {
                            "$exception_values": [
                                "Minified React error #185; visit https://react.dev/errors/185 for the full message"
                            ]
                        },
                        False,
                    ),
                    ({}, False),
                ],
            ),
            (
                "chunk_load_errors",
                [
                    (
                        {"$exception_types": ["ChunkLoadError"], "$exception_values": ["Loading chunk 123 failed."]},
                        True,
                    ),
                    (
                        {
                            "$exception_types": ["TypeError"],
                            "$exception_values": [
                                "Failed to fetch dynamically imported module: https://example.com/assets/index-a1b2c3.js"
                            ],
                        },
                        True,
                    ),
                    (
                        {"$exception_types": ["TypeError"], "$exception_values": ["Importing a module script failed."]},
                        True,
                    ),
                    ({"$exception_types": ["TypeError"], "$exception_values": ["Failed to fetch"]}, False),
                    ({}, False),
                ],
            ),
            (
                "resize_observer_loop",
                [
                    ({"$exception_values": ["ResizeObserver loop completed with undelivered notifications."]}, True),
                    ({"$exception_values": ["ResizeObserver loop limit exceeded"]}, True),
                    ({"$exception_values": ["ResizeObserver is not defined"]}, False),
                    ({}, False),
                ],
            ),
        ]
    )
    def test_built_in_filter_evaluation(self, key: str, cases: list[tuple[dict, bool]]) -> None:
        bytecode = compile_filter_bytecode(self.team.id, BUILT_IN_FILTERS_BY_KEY[key].filters)

        for event_props, expected in cases:
            assert self._eval(bytecode, event_props) == expected, f"Expected {expected} for props {event_props}"
