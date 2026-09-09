import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from django.conf import settings

from pydantic import ValidationError

from products.feature_flags.backend.flags_cache_messages import FlagsCacheInvalidation

# Both this test and the Rust consumer's round-trip test read these fixtures; if
# they move, both fail.
FIXTURE_DIR = Path(settings.BASE_DIR) / "rust" / "feature-flags" / "tests" / "fixtures"


@pytest.mark.parametrize(
    ("fixture_name", "expected_shadow"),
    [
        pytest.param("flags_cache_invalidation_v1.json", False, id="real_invalidation"),
        pytest.param("flags_cache_invalidation_v1_shadow.json", True, id="shadow_invalidation"),
    ],
)
def test_fixture_round_trip(fixture_name: str, expected_shadow: bool) -> None:
    raw = (FIXTURE_DIR / fixture_name).read_text()

    parsed = FlagsCacheInvalidation.model_validate_json(raw)
    assert parsed.version == 1
    assert parsed.team_id == 12345
    assert parsed.operation == "invalidate"
    assert parsed.emitted_at == datetime(2026, 4, 23, 10, 37, 0, tzinfo=UTC)
    assert parsed.shadow is expected_shadow

    # Reserialize and reparse — proves the schema survives a full round-trip even
    # when Pydantic's datetime output (`+00:00`) differs from the fixture's `Z`.
    serialized = parsed.model_dump_json()
    reparsed = FlagsCacheInvalidation.model_validate_json(serialized)
    assert reparsed == parsed

    # `shadow=False` must stay off the wire, so a real invalidation keeps exactly
    # the v1 key set and any consumer that predates the field can still read it.
    assert ("shadow" in json.loads(serialized)) is expected_shadow


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"version": 2}, id="rejects_unknown_version"),
        pytest.param({"operation": "clear"}, id="rejects_unknown_operation"),
        pytest.param({"emitted_at": "2026-04-23T10:37:00"}, id="rejects_naive_datetime"),
        pytest.param({"unknown_field": "oops"}, id="rejects_extra_field"),
        pytest.param({"shadow": 1}, id="rejects_non_bool_shadow"),
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
