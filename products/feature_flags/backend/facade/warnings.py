"""Dormant management warning contracts for feature flag rules v2."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import TYPE_CHECKING, Literal, NotRequired, Protocol, TypedDict, cast, get_args

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from products.feature_flags.backend.facade.config import ConfigV2

ManagementWarningCode = Literal[
    "RULE_ORDER_CHANGES_TRAFFIC",
    "UNREACHABLE_LOWER_RULE",
    "ROLLOUT_MISS_CAN_ENTER_LOWER_RULE",
    "ASSIGNMENT_RESET_CHANGES_TRAFFIC",
    "EXPERIMENT_VALUE_COLLISION",
    "CONCLUSION_EXPANDS_POPULATION",
    "SDK_REMOTE_FALLBACK_REQUIRED",
    "SDK_EXPERIMENT_CONTEXT_MISSING",
    "LEGACY_PROJECTION_LIMITED",
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
        if not isinstance(self.code, str) or self.code not in get_args(ManagementWarningCode):
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


def parse_management_warning(value: Mapping[str, object]) -> ManagementWarning:
    if not isinstance(value, Mapping):
        raise ValueError("Management warning must be an object")
    if value.keys() - {"code", "detail", "attr"}:
        raise ValueError("Unknown management warning member")
    if "code" not in value:
        raise ValueError("Management warning code is required")
    if "detail" in value and value["detail"] is None:
        raise ValueError("Management warning detail must be a string")
    if "attr" in value and value["attr"] is not None and not isinstance(value["attr"], str):
        raise ValueError("Management warning attr must be a string or null")
    # Construction validates the member types and the closed code set.
    return ManagementWarning(
        code=cast(ManagementWarningCode, value["code"]),
        detail=cast(str | None, value.get("detail")),
        attr=cast(str | None | _Absent, value.get("attr", _Absent.VALUE)),
    )


class WarningDetector(Protocol):
    def __call__(self, config: ConfigV2, previous: ConfigV2 | None = None) -> list[ManagementWarning]: ...


class ManagementWarningValidator:
    def __init__(self) -> None:
        self._detectors: list[WarningDetector] = []

    def register(self, detector: WarningDetector) -> None:
        self._detectors.append(detector)

    def __call__(self, config: ConfigV2, previous: ConfigV2 | None = None) -> list[ManagementWarning]:
        return [warning for detector in self._detectors for warning in detector(config, previous)]
