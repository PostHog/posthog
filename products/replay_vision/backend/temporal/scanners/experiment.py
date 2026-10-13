"""Experiment scanner: a summarizer that watches one experiment's exposed sessions.

The type is the summarizer with experiment context: the prompt names the experiment, the change
under test, and the session's variant, so the summary can speak to the change rather than guess
at it. Which sessions it watches comes from `experiment_id`/`variants` in the scanner config,
never from the persisted recordings query (see `ReplayScanner.experiment_scope`).
"""

from typing import Any, ClassVar, Literal

from pydantic import Field

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.scanners.base import BaseScannerOutput
from products.replay_vision.backend.temporal.scanners.summarizer import SummarizerOutput, SummarizerScanner


class ExperimentOutput(SummarizerOutput, frozen=True):
    """Persisted output: the summarizer's shape under its own discriminator, so search and the
    summary readers work unchanged. The session's variant is not model output; the workflow
    stores it beside `model_output` in `scanner_result`."""

    scanner_type: Literal[ScannerType.EXPERIMENT] = ScannerType.EXPERIMENT  # type: ignore[assignment]


class ExperimentScanner(SummarizerScanner, frozen=True):
    scanner_type: Literal[ScannerType.EXPERIMENT] = ScannerType.EXPERIMENT  # type: ignore[assignment]
    core_step_template: ClassVar[str] = "experiment_step.jinja"
    output_cls: ClassVar[type[BaseScannerOutput]] = ExperimentOutput
    experiment_id: int = Field(ge=1, description="The experiment this scanner watches.")
    variants: list[str] | None = Field(
        default=None,
        min_length=1,
        description="Variant keys to watch; null means every variant.",
    )
    balance_variants: bool = Field(
        default=True,
        description="Sample each watched variant about evenly instead of proportionally to rollout.",
    )
    # Lifecycle intent, not scan config, so model dumps leave it out. The launch receiver clears
    # it from the stored config before the first scan.
    start_on_launch: bool = Field(
        default=False,
        exclude=True,
        description="Saved disabled on a draft experiment; turned on when the experiment launches.",
    )
    # Scan-time context rather than persisted config, injected per scan by the apply workflow
    # (like the classifier's `known_freeform_tags`). `exclude=True` keeps both out of dumps, so
    # they can never leak into a stored scanner_config or snapshot.
    experiment_context: dict[str, Any] | None = Field(default=None, exclude=True)
    session_variant: str | None = Field(default=None, exclude=True)
    session_fields: ClassVar[frozenset[str]] = SummarizerScanner.session_fields | {
        "experiment_context",
        "session_variant",
    }

    def prompt_context(self) -> dict[str, Any]:
        return {
            **super().prompt_context(),
            "experiment": self.experiment_context,
            "session_variant": self.session_variant,
        }
