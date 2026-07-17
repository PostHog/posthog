import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from django.conf import settings

from pydantic import ValidationError

from products.feature_flags.backend.flags_cache_messages import FlagsCacheInvalidation

# Both this test and the Rust consumer's round-trip test (PR 2) read this
# fixture; if it moves, both fail.
FIXTURE_PATH = (
    Path(settings.BASE_DIR) / "rust" / "feature-flags" / "tests" / "fixtures" / "flags_cache_invalidation_v1.json"
)


def test_fixture_round_trip() -> None:
    raw = FIXTURE_PATH.read_text()

    parsed = FlagsCacheInvalidation.model_validate_json(raw)
    assert parsed.version == 1
    assert parsed.team_id == 12345
    assert parsed.operation == "invalidate"
    assert parsed.emitted_at == datetime(2026, 4, 23, 10, 37, 0, tzinfo=UTC)

    # Reserialize and reparse — proves the schema survives a full round-trip even
    # when Pydantic's datetime output (`+00:00`) differs from the fixture's `Z`.
    reparsed = FlagsCacheInvalidation.model_validate_json(parsed.model_dump_json())
    assert reparsed == parsed


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"version": 2}, id="rejects_unknown_version"),
        pytest.param({"operation": "clear"}, id="rejects_unknown_operation"),
        pytest.param({"emitted_at": "2026-04-23T10:37:00"}, id="rejects_naive_datetime"),
        pytest.param({"unknown_field": "oops"}, id="rejects_extra_field"),
    ],
)
def test_rejects_invalid_payload(overrides: dict) -> None:
    base = {
        "version": 1,
        "team_id": 12345,
        "operation": "invalidate",
        "emitted_at": "2026-04-23T10:37:00Z",
    }
    with pytest.raises(ValidationError):
        FlagsCacheInvalidation.model_validate_json(json.dumps({**base, **overrides}))
