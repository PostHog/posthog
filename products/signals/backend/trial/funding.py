from collections.abc import Mapping
from contextvars import ContextVar
from typing import Literal, cast
from uuid import UUID

from posthog.dataclasses import frozen


@frozen
class TrialFunding:
    funding: Literal["trial", "paid", "existing"]
    grant_id: UUID | None = None
    policy_version: int = 1
    report_pass_key: str = ""

    def as_dict(self) -> dict[str, str | int]:
        return {
            "funding": self.funding,
            "grant_id": str(self.grant_id) if self.grant_id else "",
            "policy_version": self.policy_version,
            "report_pass_key": self.report_pass_key,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object] | None) -> "TrialFunding | None":
        if not value:
            return None
        mode = value["funding"]
        if mode not in {"trial", "paid", "existing"}:
            raise ValueError("Invalid Self-driving funding mode")
        grant_id = UUID(str(value["grant_id"])) if value.get("grant_id") else None
        if (mode == "trial") != (grant_id is not None):
            raise ValueError("Trial funding must identify its grant")
        return cls(
            funding=cast(Literal["trial", "paid", "existing"], mode),
            grant_id=grant_id,
            policy_version=int(str(value["policy_version"])),
            report_pass_key=str(value.get("report_pass_key", "")),
        )


direct_report_funding: ContextVar[tuple[int, TrialFunding] | None] = ContextVar("direct_report_funding", default=None)
