from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import JsonValue

type RubricDocument = dict[str, JsonValue]


class ScoutRubricReader(Protocol):
    def read(self, *, config_id: UUID, skill_name: str) -> RubricDocument: ...


class MockScoutRubricReader:
    def read(self, *, config_id: UUID, skill_name: str) -> RubricDocument:
        fixture = Path(__file__).resolve().parent.parent / "fixtures" / "mock-scout-rubric.json"
        document: JsonValue = json.loads(fixture.read_text())
        if not isinstance(document, dict):
            raise ValueError("The mock rubric must be a JSON object.")
        return {**document, "config_id": str(config_id), "skill_name": skill_name}


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a mock scout rubric for comparison development.")
    parser.add_argument("--config-id", type=UUID, required=True)
    parser.add_argument("--skill-name", required=True)
    args = parser.parse_args()
    reader: ScoutRubricReader = MockScoutRubricReader()
    document = reader.read(config_id=args.config_id, skill_name=args.skill_name)
    sys.stdout.write(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    main()
