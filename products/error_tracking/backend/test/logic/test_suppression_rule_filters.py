from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import PropertyGroupFilterValue

from products.error_tracking.backend.logic import get_client_safe_filters
from products.error_tracking.backend.rule_bytecode import generate_byte_code

from common.hogvm.python.execute import execute_bytecode


def _leaf(key: str, value: list[str] | str, operator: str = "exact") -> dict:
    return {"key": key, "type": "event", "value": value, "operator": operator}


class TestClientServerFilterConsistency(APIBaseTest):
    """Cross-validate that client-safe filters produce identical results to server bytecode.

    Since _get_client_safe_filters now returns the filters unchanged (or None),
    client-safe rules must match identically on client and server.

    Uses non-array properties ($exception_type, $exception_message) to avoid JSONExtract
    bytecode calls unsupported by the Python HogVM.
    """

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
    def test_client_safe_bytecode_matches_server(
        self, _name: str, filters: dict, cases: list[tuple[dict, bool]]
    ) -> None:
        assert get_client_safe_filters(filters) is not None

        bytecode = generate_byte_code(self.team, PropertyGroupFilterValue(**filters))

        for event_props, expected in cases:
            assert self._eval(bytecode, event_props) == expected, f"Expected {expected} for props {event_props}"
