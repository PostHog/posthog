import re
from pathlib import Path

import pytest

from products.warehouse_sources.backend.presentation.views.external_data_schema import (
    ExternalDataSchemaCompactSerializer,
    ExternalDataSchemaSerializer,
)

# Agents follow this section to call a `Completed` schema broken, so it must judge staleness by the
# stamp that moves on every successful sync, not by `last_synced_at`, which stays old on a quiet source.
_SKILL_PATH = Path(__file__).parents[2] / "skills" / "auditing-warehouse-source-health" / "SKILL.md"
_STALENESS_SECTION = re.search(
    r'\*\*Stale but "Completed" schemas:\*\*\n(.*?)\n\*\*', _SKILL_PATH.read_text(), re.DOTALL
)


def test_staleness_section_is_found() -> None:
    assert _STALENESS_SECTION is not None


@pytest.mark.parametrize(
    "required",
    [
        # The field that moves on runs that load no rows.
        "compare `last_checked_at` with `sync_frequency`",
        # Compact rows omit `sync_frequency`, so the comparison needs the full rows.
        "`compact: false`",
        # Null and legacy `last_checked_at` values need the job history before a verdict.
        "system.source_sync_jobs",
    ],
)
def test_staleness_check_does_not_trust_last_synced_at_alone(required: str) -> None:
    assert _STALENESS_SECTION is not None
    assert required in _STALENESS_SECTION.group(1)


def test_staleness_fields_need_the_full_schema_rows() -> None:
    assert {"last_checked_at", "sync_frequency"} <= set(ExternalDataSchemaSerializer.Meta.fields)
    assert "last_checked_at" in ExternalDataSchemaCompactSerializer.Meta.fields
    assert "sync_frequency" not in ExternalDataSchemaCompactSerializer.Meta.fields
