from typing import cast, get_args

import pytest

from parameterized import parameterized

from products.feature_flags.backend.facade.config import ConfigV2, parse_v2_config
from products.feature_flags.backend.facade.warnings import (
    ManagementWarning,
    ManagementWarningCode,
    ManagementWarningValidator,
    ManagementWarningWire,
    WarningDetector,
    parse_management_warning,
    serialize_management_warning,
)


class TestManagementWarning:
    def test_codes_match_management_warning_schema(self) -> None:
        assert set(get_args(ManagementWarningCode)) == {
            "RULE_ORDER_CHANGES_TRAFFIC",
            "UNREACHABLE_LOWER_RULE",
            "ROLLOUT_MISS_CAN_ENTER_LOWER_RULE",
            "ASSIGNMENT_RESET_CHANGES_TRAFFIC",
            "EXPERIMENT_VALUE_COLLISION",
            "CONCLUSION_EXPANDS_POPULATION",
            "SDK_REMOTE_FALLBACK_REQUIRED",
            "SDK_EXPERIMENT_CONTEXT_MISSING",
            "LEGACY_PROJECTION_LIMITED",
        }

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
    def test_invalid_construction_is_rejected(self, _name: str, members: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            ManagementWarning(**cast(ManagementWarningWire, members))


class TestManagementWarningValidator:
    def test_no_registered_detectors(self) -> None:
        config = parse_v2_config({"version": 2, "return_type": "boolean", "default_value": False, "rules": []})
        validator: WarningDetector = ManagementWarningValidator()
        assert validator(config) == []

    @parameterized.expand([("without_previous", False), ("with_previous", True)])
    def test_detectors_receive_configs_and_preserve_warning_order(self, _name: str, with_previous: bool) -> None:
        config = parse_v2_config({"version": 2, "return_type": "boolean", "default_value": False, "rules": []})
        previous = (
            parse_v2_config({"version": 2, "return_type": "boolean", "default_value": True, "rules": []})
            if with_previous
            else None
        )
        first_warning = ManagementWarning(code="RULE_ORDER_CHANGES_TRAFFIC")
        second_warning = ManagementWarning(code="UNREACHABLE_LOWER_RULE")
        third_warning = ManagementWarning(code="ASSIGNMENT_RESET_CHANGES_TRAFFIC")
        received: list[str] = []

        def first(config: ConfigV2, previous: ConfigV2 | None = None) -> list[ManagementWarning]:
            assert config is expected_config
            assert previous is expected_previous
            received.append("first")
            return [first_warning, second_warning]

        def second(config: ConfigV2, previous: ConfigV2 | None = None) -> list[ManagementWarning]:
            assert config is expected_config
            assert previous is expected_previous
            received.append("second")
            return [third_warning, first_warning]

        expected_config = config
        expected_previous = previous
        validator = ManagementWarningValidator()
        validator.register(first)
        validator.register(second)

        assert validator(config, previous) == [first_warning, second_warning, third_warning, first_warning]
        assert received == ["first", "second"]
        assert ManagementWarningValidator()(config, previous) == []
