"""What a run compared against in the baseline ledger, frozen on the run when it completes.

The record lives in `run.metadata["baseline"]` and names the mode it was made in. Every other
module reads and writes it through `BaselineRecord`, never through the raw key.
"""

from __future__ import annotations

from uuid import UUID

from posthog.dataclasses import frozen

from ..facade.enums import BaselineMode
from ..models import Run

METADATA_KEY = "baseline"


@frozen
class OverlayEntry:
    content_hash: str
    approval_id: UUID
    pr_number: int
    # The ledger's hash for the identifier when the run resolved, empty when absent. An approval
    # made on this run records it as its ledger base, so a landing after the run cannot move it.
    ledger_hash: str

    def to_json(self) -> dict[str, object]:
        return {
            "hash": self.content_hash,
            "approval_id": str(self.approval_id),
            "pr_number": self.pr_number,
            "ledger_hash": self.ledger_hash,
        }

    @classmethod
    def from_json(cls, data: dict) -> OverlayEntry:
        return cls(
            content_hash=str(data["hash"]),
            approval_id=UUID(str(data["approval_id"])),
            pr_number=int(data["pr_number"]),
            ledger_hash=str(data["ledger_hash"]),
        )


@frozen
class ShadowDifference:
    identifier: str
    yaml_verdict: str
    ledger_verdict: str

    def to_json(self) -> dict[str, object]:
        return {"identifier": self.identifier, "yaml": self.yaml_verdict, "ledger": self.ledger_verdict}

    @classmethod
    def from_json(cls, data: dict) -> ShadowDifference:
        return cls(
            identifier=str(data["identifier"]), yaml_verdict=str(data["yaml"]), ledger_verdict=str(data["ledger"])
        )


@frozen
class ShadowComparison:
    """How the ledger verdict of a shadow-mode run differs from the YAML verdict that decided it.

    Pair keys read `<yaml verdict>/<ledger verdict>`.
    """

    pairs: dict[str, int]
    pairs_without_quarantined: dict[str, int]
    yaml_only_removed: tuple[str, ...]
    ledger_only_removed: tuple[str, ...]
    # None when the record's lists were truncated, because the cut lists cannot decide the gate.
    gate_differs: bool | None
    sample: tuple[ShadowDifference, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "pairs": dict(self.pairs),
            "pairs_without_quarantined": dict(self.pairs_without_quarantined),
            "yaml_only_removed": list(self.yaml_only_removed),
            "ledger_only_removed": list(self.ledger_only_removed),
            "gate_differs": self.gate_differs,
            "sample": [difference.to_json() for difference in self.sample],
        }

    @classmethod
    def from_json(cls, data: dict) -> ShadowComparison:
        return cls(
            pairs={str(pair): int(count) for pair, count in data["pairs"].items()},
            pairs_without_quarantined={
                str(pair): int(count) for pair, count in data["pairs_without_quarantined"].items()
            },
            yaml_only_removed=tuple(str(identifier) for identifier in data["yaml_only_removed"]),
            ledger_only_removed=tuple(str(identifier) for identifier in data["ledger_only_removed"]),
            gate_differs=None if data["gate_differs"] is None else bool(data["gate_differs"]),
            sample=tuple(ShadowDifference.from_json(difference) for difference in data["sample"]),
        )


@frozen
class BaselineRecord:
    # In shadow mode the YAML decided the run, and the record also holds what the ledger would have done.
    mode: BaselineMode
    merge_base_sha: str
    position: int
    clamped_to_seed: bool
    containment_complete: bool
    overlay: dict[str, OverlayEntry]
    # Every applicable candidate, also the ones the overlay dropped, because evidence and landing
    # read this list.
    candidate_approval_ids: tuple[UUID, ...]
    conflicts: dict[str, tuple[int, ...]]
    second_candidates: dict[str, str]
    differences: dict[str, str] | None = None
    differences_truncated: bool = False
    ledger_removed: tuple[str, ...] | None = None
    ledger_removed_truncated: bool = False
    comparison: ShadowComparison | None = None
    unavailable_reason: str = ""

    @classmethod
    def unavailable(cls, mode: BaselineMode, reason: str) -> BaselineRecord:
        return cls(
            mode=mode,
            merge_base_sha="",
            position=0,
            clamped_to_seed=False,
            containment_complete=False,
            overlay={},
            candidate_approval_ids=(),
            conflicts={},
            second_candidates={},
            unavailable_reason=reason,
        )

    def to_json(self) -> dict[str, object]:
        if self.unavailable_reason:
            return {"mode": str(self.mode), "unavailable": self.unavailable_reason}
        data: dict[str, object] = {
            "mode": str(self.mode),
            "merge_base_sha": self.merge_base_sha,
            "position": self.position,
            "clamped_to_seed": self.clamped_to_seed,
            "containment_complete": self.containment_complete,
            "overlay": {identifier: entry.to_json() for identifier, entry in self.overlay.items()},
            "candidate_approval_ids": [str(approval_id) for approval_id in self.candidate_approval_ids],
            "conflicts": {identifier: list(pr_numbers) for identifier, pr_numbers in self.conflicts.items()},
            "second_candidates": dict(self.second_candidates),
        }
        if self.differences is not None:
            data["differences"] = dict(self.differences)
            data["differences_truncated"] = self.differences_truncated
        if self.ledger_removed is not None:
            data["ledger_removed"] = list(self.ledger_removed)
            data["ledger_removed_truncated"] = self.ledger_removed_truncated
        if self.comparison is not None:
            data["comparison"] = self.comparison.to_json()
        return data

    @classmethod
    def from_json(cls, data: object) -> BaselineRecord | None:
        """The record, or None when `data` is not one."""
        if not isinstance(data, dict):
            return None
        try:
            mode = BaselineMode(data["mode"])
            if "unavailable" in data:
                return cls.unavailable(mode, str(data["unavailable"]))
            differences = data.get("differences")
            ledger_removed = data.get("ledger_removed")
            comparison = data.get("comparison")
            return cls(
                mode=mode,
                merge_base_sha=str(data["merge_base_sha"]),
                position=int(data["position"]),
                clamped_to_seed=bool(data["clamped_to_seed"]),
                containment_complete=bool(data["containment_complete"]),
                overlay={
                    str(identifier): OverlayEntry.from_json(entry) for identifier, entry in data["overlay"].items()
                },
                candidate_approval_ids=tuple(UUID(str(approval_id)) for approval_id in data["candidate_approval_ids"]),
                conflicts={
                    str(identifier): tuple(int(pr_number) for pr_number in pr_numbers)
                    for identifier, pr_numbers in data["conflicts"].items()
                },
                second_candidates={
                    str(identifier): str(content_hash) for identifier, content_hash in data["second_candidates"].items()
                },
                differences=(
                    {str(identifier): str(content_hash) for identifier, content_hash in differences.items()}
                    if isinstance(differences, dict)
                    else None
                ),
                differences_truncated=bool(data.get("differences_truncated", False)),
                ledger_removed=tuple(str(identifier) for identifier in ledger_removed)
                if isinstance(ledger_removed, list)
                else None,
                ledger_removed_truncated=bool(data.get("ledger_removed_truncated", False)),
                comparison=ShadowComparison.from_json(comparison) if isinstance(comparison, dict) else None,
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            return None


def record_for_run(run: Run) -> BaselineRecord | None:
    """The run's record, or None when it has none or the ledger side was unavailable."""
    metadata = run.metadata if isinstance(run.metadata, dict) else {}
    record = BaselineRecord.from_json(metadata.get(METADATA_KEY))
    if record is None or record.unavailable_reason:
        return None
    return record
