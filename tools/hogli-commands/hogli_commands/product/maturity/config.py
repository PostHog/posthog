"""Load migration_config.json to count models still to move."""

from __future__ import annotations

import json
from pathlib import Path

_MIGRATION_CONFIG = (
    Path(__file__).parent.parent.parent.parent
    / ".agents"
    / "skills"
    / "product-model-migration"
    / "migration_config.json"
)

_SKILL_DIR_CONFIG = Path.home() / ".claude" / "skills" / "product-model-migration" / "migration_config.json"


def _load_migration_config() -> dict:
    """Load migration_config.json (best-effort)."""
    for config_path in (_MIGRATION_CONFIG, _SKILL_DIR_CONFIG):
        if config_path.exists():
            try:
                return json.loads(config_path.read_text())
            except (json.JSONDecodeError, KeyError):
                continue
    return {}


def _load_model_assignments() -> dict[str, int]:
    """Load product -> count of models still to move from migration_config.json.

    Only counts entries that are not yet done — done/skip entries have already
    been moved and their models live in products/.
    """
    config = _load_migration_config()
    counts: dict[str, int] = {}
    for entry in config.get("migrations", []):
        status = entry.get("status", "")
        if status in ("done", "skip"):
            continue
        name = entry["name"]
        n = len(entry.get("model_names", [])) + len(entry.get("ee_models", []))
        if n > 0:
            counts[name] = n
    return counts
