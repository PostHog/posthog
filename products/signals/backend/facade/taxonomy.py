"""Signal taxonomy and value types that other products pass to and receive from signals."""

from typing import TYPE_CHECKING

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.enums import ReportPriority, SignalSourceProduct, SignalSourceType

if TYPE_CHECKING:
    from products.signals.backend.contracts import SignalRemediation

__all__ = [
    "ArtefactAttribution",
    "ReportPriority",
    "SignalRemediation",
    "SignalSourceProduct",
    "SignalSourceType",
]


def __getattr__(name: str) -> type["SignalRemediation"]:
    if name != "SignalRemediation":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from products.signals.backend.contracts import (
        SignalRemediation,  # noqa: PLC0415 - keeps payload schemas off Django startup
    )

    globals()[name] = SignalRemediation
    return SignalRemediation
