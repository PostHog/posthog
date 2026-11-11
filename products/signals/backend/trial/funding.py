from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, cast
from uuid import UUID

from posthog.dataclasses import frozen


@frozen
class TrialFunding:
    funding: Literal["trial", "paid", "existing", "operator"]
    grant_id: UUID | None = None
    implementation_allowed: bool = True
    report_pass_key: str = ""

    def as_dict(self) -> dict[str, str | int]:
        return {
            "funding": self.funding,
            "grant_id": str(self.grant_id) if self.grant_id else "",
            "implementation_allowed": self.implementation_allowed,
            "report_pass_key": self.report_pass_key,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object] | None) -> "TrialFunding | None":
        if not value:
            return None
        mode = value["funding"]
        if mode not in {"trial", "paid", "existing", "operator"}:
            raise ValueError("Invalid Self-driving funding mode")
        grant_id = UUID(str(value["grant_id"])) if value.get("grant_id") else None
        if (mode == "trial") != (grant_id is not None):
            raise ValueError("Trial funding must identify its grant")
        return cls(
            funding=cast(Literal["trial", "paid", "existing", "operator"], mode),
            grant_id=grant_id,
            implementation_allowed=value.get("implementation_allowed") is not False,
            report_pass_key=str(value.get("report_pass_key", "")),
        )


direct_report_funding: ContextVar[tuple[int, TrialFunding] | None] = ContextVar("direct_report_funding", default=None)


def direct_report_funding_snapshot(team_id: int) -> dict[str, str | int] | None:
    context = direct_report_funding.get()
    return context[1].as_dict() if context is not None and context[0] == team_id else None


def signal_funding(team_id: int, signal_id: str | None) -> TrialFunding | None:
    from products.signals.backend.models import SignalSpend  # noqa: PLC0415 -- model registration cycle

    if signal_id is None:
        return None
    receipts = SignalSpend.objects.for_team(team_id).filter(signal_id=signal_id, kind=SignalSpend.Kind.AD_HOC)
    snapshot = receipts.values("trial_grant_id").first()
    if snapshot is None:
        return None
    grant_id = snapshot["trial_grant_id"]
    return TrialFunding(funding="trial", grant_id=grant_id) if grant_id else TrialFunding(funding="existing")


@contextmanager
def without_trial_funding(team_id: int) -> Iterator[None]:
    token = direct_report_funding.set((team_id, TrialFunding(funding="existing")))
    try:
        yield
    finally:
        direct_report_funding.reset(token)
