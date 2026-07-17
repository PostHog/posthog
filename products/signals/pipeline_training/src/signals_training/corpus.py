from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .io import JsonObject, parse_epoch, read_jsonl, require_string, require_string_list

BAND_CEILINGS = (1, 2, 4, 8, 16, 32, 64, 128)
BAND_ORDER = tuple(str(value) for value in BAND_CEILINGS) + ("128+",)


def band_of(size: int) -> str:
    for ceiling in BAND_CEILINGS:
        if size <= ceiling:
            return str(ceiling)
    return "128+"


def month_of(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m")


@dataclass(frozen=True)
class Corpus:
    signals: dict[str, JsonObject]
    reports: dict[str, JsonObject]
    report_of: dict[str, str]

    @classmethod
    def load(cls, signals_path: Path, reports_path: Path) -> Corpus:
        signals = {
            require_string(row, "document_id", f"{signals_path}:{line_number}"): row
            for line_number, row in read_jsonl(signals_path)
        }
        reports: dict[str, JsonObject] = {}
        report_of: dict[str, str] = {}
        for line_number, row in read_jsonl(reports_path):
            location = f"{reports_path}:{line_number}"
            report_id = require_string(row, "report_id", location)
            reports[report_id] = row
            for member in require_string_list(row, "member_ids", location, non_empty=True):
                report_of[member] = report_id
        return cls(signals=signals, reports=reports, report_of=report_of)

    def signal_ids(self, report_id: str) -> list[str]:
        row = self.reports[report_id]
        return cast(list[str], row["member_ids"])

    def selected(self, report_ids: set[str]) -> Corpus:
        reports = {report_id: self.reports[report_id] for report_id in sorted(report_ids)}
        members = {member for report_id in reports for member in self.signal_ids(report_id)}
        signals = {document_id: self.signals[document_id] for document_id in members}
        report_of = {document_id: self.report_of[document_id] for document_id in members}
        return Corpus(signals=signals, reports=reports, report_of=report_of)

    def sorted_signals(self) -> list[JsonObject]:
        return sorted(
            self.signals.values(),
            key=lambda row: (
                parse_epoch(row.get("timestamp"), f"signal {row.get('document_id')}.timestamp"),
                str(row.get("document_id")),
            ),
        )

    def sorted_reports(self) -> list[JsonObject]:
        return [self.reports[report_id] for report_id in sorted(self.reports)]


def report_statistics(corpus: Corpus, report_id: str, error_tracking_product: str) -> JsonObject:
    members = corpus.signal_ids(report_id)
    rows = [corpus.signals[member] for member in members]
    products = Counter(str(row["source_product"]) for row in rows)
    timestamps = [parse_epoch(row.get("timestamp"), f"signal {row.get('document_id')}.timestamp") for row in rows]
    size = len(rows)
    error_tracking_count = products[error_tracking_product]
    return {
        "n": size,
        "n_error_tracking": error_tracking_count,
        "n_products": len(products),
        "first_timestamp": min(timestamps),
        "last_timestamp": max(timestamps),
        "error_tracking_only": error_tracking_count == size,
        "heterogeneous": len(products) > 1,
        "band": band_of(size),
        "source_products": dict(sorted(products.items())),
    }


def has_scout_bypass(corpus: Corpus, report_id: str) -> bool:
    for document_id in corpus.signal_ids(report_id):
        signal = corpus.signals[document_id]
        if signal.get("source_product") != "signals_scout":
            continue
        metadata_value = signal.get("metadata", {})
        metadata = metadata_value if isinstance(metadata_value, dict) else {}
        parent = metadata.get("parent_signal_id", signal.get("parent_signal_id"))
        reason = metadata.get("reason", signal.get("reason"))
        rejected = metadata.get("n_rejected", signal.get("n_rejected", 0))
        if (
            (parent is None or parent == "")
            and (reason is None or reason == "")
            and (rejected is None or rejected == 0)
        ):
            return True
    return False
