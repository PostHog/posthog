"""Dormant management warning contracts for feature flag rules v2."""

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal, NotRequired, TypedDict, get_args

from posthog.dataclasses import frozen

ManagementWarningCode = Literal[
    "RULE_ORDER_CHANGES_TRAFFIC",
    "UNREACHABLE_LOWER_RULE",
    "ROLLOUT_MISS_CAN_ENTER_LOWER_RULE",
    "ASSIGNMENT_RESET_CHANGES_TRAFFIC",
    "CONCLUSION_EXPANDS_POPULATION",
]


class _Absent(Enum):
    VALUE = "absent"


class ManagementWarningWire(TypedDict):
    code: ManagementWarningCode
    detail: NotRequired[str]
    attr: NotRequired[str | None]


@frozen
class ManagementWarning:
    code: ManagementWarningCode
    detail: str | None = None
    # A sentinel preserves an omitted attr separately from an explicit wire null.
    attr: str | None | _Absent = _Absent.VALUE

    def __post_init__(self) -> None:
        if self.code not in get_args(ManagementWarningCode):
            raise ValueError("Unsupported management warning code")
        if self.detail is not None and not isinstance(self.detail, str):
            raise ValueError("Management warning detail must be a string")
        if self.attr is not _Absent.VALUE and self.attr is not None and not isinstance(self.attr, str):
            raise ValueError("Management warning attr must be a string or null")


def serialize_management_warning(warning: ManagementWarning) -> ManagementWarningWire:
    result: ManagementWarningWire = {"code": warning.code}
    if warning.detail is not None:
        result["detail"] = warning.detail
    if not isinstance(warning.attr, _Absent):
        result["attr"] = warning.attr
    return result


def parse_management_warning(value: Mapping[str, Any]) -> ManagementWarning:
    if not isinstance(value, Mapping):
        raise ValueError("Management warning must be an object")
    if value.keys() - {"code", "detail", "attr"}:
        raise ValueError("Unknown management warning member")
    if "code" not in value:
        raise ValueError("Management warning code is required")
    # The DTO reads a None detail as omitted, so an explicit wire null must be rejected here.
    if "detail" in value and value["detail"] is None:
        raise ValueError("Management warning detail must be a string")
    # Construction validates the member types and the closed code set.
    return ManagementWarning(code=value["code"], detail=value.get("detail"), attr=value.get("attr", _Absent.VALUE))
