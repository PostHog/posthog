import json
from dataclasses import dataclass
from typing import IO

from posthog.models import Team

from products.signals.backend.api import emit_signal


@dataclass
class IngestResult:
    success: int
    failed: int
    total: int
    errors: list[str]


def parse_signals_json(f: IO[str]) -> list[list]:
    """Parse a JSONL file of signal rows exported from the embeddings table.

    Each line is a JSON array with columns:
    [0] product, [1] document_type, [2] document_id, [3] timestamp,
    [4] inserted_at, [5] description, [6] metadata json
    """
    rows: list[list] = []
    for _line_num, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            rows.append(row)
        except json.JSONDecodeError:
            pass  # skip malformed lines
    return rows


async def ingest_signals(team: Team, rows: list[list]) -> IngestResult:
    """Emit signals from parsed rows via emit_signal(). Returns an IngestResult summary."""
    success = 0
    failed = 0
    errors: list[str] = []

    for i, row in enumerate(rows):
        try:
            description = row[5]
            metadata = json.loads(row[6]) if isinstance(row[6], str) else row[6]

            await emit_signal(
                team=team,
                source_product=metadata.get("source_product", "unknown"),
                source_type=metadata.get("source_type", "unknown"),
                source_id=metadata.get("source_id", ""),
                description=description,
                weight=metadata.get("weight", 0.5),
                extra=metadata.get("extra"),
            )
            success += 1
        except Exception as e:
            signal_id = row[2] if len(row) > 2 else f"row {i}"
            errors.append(f"Failed to emit signal {signal_id}: {e}")
            failed += 1

    return IngestResult(success=success, failed=failed, total=len(rows), errors=errors)
