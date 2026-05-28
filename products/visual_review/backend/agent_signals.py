"""Signal extraction for the agent reviewer.

Builds a compact, JSON-serializable view of a ``RunSnapshot`` so the LLM
reviewer can reason over diff metrics without needing the full ORM
instance — and without us shipping image bytes to the model. The actual
verdict comes from ``agent_reviewer``; this module is pure data prep.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .diff_metadata import DiffMetadata

AGENT_NAME = "claude-haiku-4-5"


@dataclass(frozen=True)
class SnapshotSignals:
    """Minimal slice of a snapshot the reviewer needs to decide.

    Kept Django-free and JSON-dumpable so it can be sent straight to the
    LLM as the user-message payload. Field names are reviewer-facing —
    the model sees them verbatim, so they need to read clearly.
    """

    identifier: str
    result: str
    diff_percentage: float | None
    ssim_score: float | None
    change_kind: str
    size_mismatch: bool
    cluster_count: int
    largest_cluster_area: int
    image_area: int
    is_quarantined: bool

    def to_dict(self) -> dict:
        return asdict(self)


def signals_from_snapshot(snapshot) -> SnapshotSignals:
    """Build a SnapshotSignals from a RunSnapshot model instance."""
    parsed = DiffMetadata.model_validate(snapshot.diff_metadata or {})
    cluster_items = parsed.cluster_summary.items if parsed.cluster_summary else []
    cluster_count = parsed.cluster_summary.total if parsed.cluster_summary else 0
    largest_cluster_area = max(
        (c.bbox[2] * c.bbox[3] for c in cluster_items),
        default=0,
    )
    current = snapshot.current_artifact
    image_area = (current.width or 0) * (current.height or 0) if current is not None else 0

    return SnapshotSignals(
        identifier=snapshot.identifier,
        result=snapshot.result,
        diff_percentage=snapshot.diff_percentage,
        ssim_score=snapshot.ssim_score,
        change_kind=snapshot.change_kind or "",
        size_mismatch=parsed.size_mismatch,
        cluster_count=cluster_count,
        largest_cluster_area=largest_cluster_area,
        image_area=image_area,
        is_quarantined=snapshot.is_quarantined,
    )
