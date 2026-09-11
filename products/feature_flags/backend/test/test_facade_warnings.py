from typing import Any, get_args

import pytest

from parameterized import parameterized

from products.feature_flags.backend.facade.warnings import (
    ManagementWarning,
    ManagementWarningCode,
    ManagementWarningWire,
    parse_management_warning,
    serialize_management_warning,
)


class TestManagementWarning:
    @parameterized.expand(
        [
            ("code_only", {}),
            ("detail", {"detail": "The rule order can change traffic."}),
            ("null_attr", {"attr": None}),
            ("field_attr", {"attr": "filters.rules"}),
            ("detail_and_attr", {"detail": "The rule order can change traffic.", "attr": "filters.rules"}),
            ("empty_strings", {"detail": "", "attr": ""}),
        ]
    )
    def test_wire_round_trip(self, _name: str, optional_members: dict[str, object]) -> None:
        for code in get_args(ManagementWarningCode):
            wire = {"code": code, **optional_members}
            warning = parse_management_warning(wire)
            assert serialize_management_warning(warning) == wire
            assert parse_management_warning(serialize_management_warning(warning)) == warning

    @parameterized.expand(
        [
            ("unknown_member", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "extra": True}, "Unknown.*member"),
            ("unknown_code", {"code": "UNKNOWN_WARNING"}, "Unsupported.*code"),
            ("missing_code", {}, "code is required"),
            ("null_code", {"code": None}, "Unsupported.*code"),
            ("number_code", {"code": 1}, "Unsupported.*code"),
            ("bool_code", {"code": True}, "Unsupported.*code"),
            ("list_code", {"code": []}, "Unsupported.*code"),
            ("object_code", {"code": {}}, "Unsupported.*code"),
            ("null_detail", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "detail": None}, "detail must be a string"),
            ("number_detail", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "detail": 2}, "detail must be a string"),
            ("bool_detail", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "detail": False}, "detail must be a string"),
            ("list_detail", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "detail": []}, "detail must be a string"),
            ("object_detail", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "detail": {}}, "detail must be a string"),
            ("number_attr", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "attr": 1}, "attr must be a string or null"),
            ("bool_attr", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "attr": True}, "attr must be a string or null"),
            ("list_attr", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "attr": []}, "attr must be a string or null"),
            ("object_attr", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "attr": {}}, "attr must be a string or null"),
        ]
    )
    def test_invalid_wire_is_rejected(self, _name: str, wire: dict[str, object], message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_management_warning(wire)

    def test_constructed_warning_omits_absent_members(self) -> None:
        wire: ManagementWarningWire = {"code": "RULE_ORDER_CHANGES_TRAFFIC"}
        assert serialize_management_warning(ManagementWarning(code="RULE_ORDER_CHANGES_TRAFFIC")) == wire
        assert serialize_management_warning(ManagementWarning(code="RULE_ORDER_CHANGES_TRAFFIC", attr=None)) == {
            **wire,
            "attr": None,
        }

    @parameterized.expand(
        [
            ("unknown_code", {"code": "UNKNOWN_WARNING"}),
            ("wrong_detail", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "detail": []}),
            ("wrong_attr", {"code": "RULE_ORDER_CHANGES_TRAFFIC", "attr": False}),
        ]
    )
    def test_invalid_construction_is_rejected(self, _name: str, members: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            ManagementWarning(**members)
