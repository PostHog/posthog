from posthog.test.base import APIBaseTest

from parameterized import parameterized

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
