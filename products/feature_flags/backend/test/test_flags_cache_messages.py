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
    ("fixture_name", "expected_shadow", "expected_source"),
    [
        pytest.param("flags_cache_invalidation_v1.json", False, "edit", id="real_invalidation"),
        pytest.param("flags_cache_invalidation_v1_shadow.json", True, "edit", id="shadow_invalidation"),
        pytest.param("flags_cache_invalidation_v1_refresh.json", False, "refresh", id="refresh_invalidation"),
    ],
)
def test_fixture_round_trip(fixture_name: str, expected_shadow: bool, expected_source: str) -> None:
    raw = (FIXTURE_DIR / fixture_name).read_text()

    parsed = FlagsCacheInvalidation.model_validate_json(raw)
    assert parsed.version == 1
    assert parsed.team_id == 12345
    assert parsed.operation == "invalidate"
    assert parsed.emitted_at == datetime(2026, 4, 23, 10, 37, 0, tzinfo=UTC)
    assert parsed.shadow is expected_shadow
    assert parsed.source == expected_source

    # Reserialize and reparse — proves the schema survives a full round-trip even
    # when Pydantic's datetime output (`+00:00`) differs from the fixture's `Z`.
    serialized = parsed.model_dump_json()
    reparsed = FlagsCacheInvalidation.model_validate_json(serialized)
    assert reparsed == parsed

    # The wire contract, asserted once rather than per field: a serialized message
    # carries exactly the keys its fixture carries, so `shadow=False` and
    # `source="edit"` stay off the wire and a consumer predating either field can
    # still read it. A per-field membership check would pass a third optional
    # field that someone forgot to omit.
    expected_keys = json.loads(raw).keys()
    assert json.loads(serialized).keys() == expected_keys
    # Both pydantic entry points: `_produce_invalidation` serializes with
    # `model_dump(mode="json")`, while the round-trip above uses
    # `model_dump_json()`. A message that leaks `source` is a parse error to a
    # consumer predating the field, and such a message is dropped, not DLQ'd.
    assert parsed.model_dump(mode="json").keys() == expected_keys


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"version": 2}, id="rejects_unknown_version"),
        pytest.param({"operation": "clear"}, id="rejects_unknown_operation"),
        pytest.param({"emitted_at": "2026-04-23T10:37:00"}, id="rejects_naive_datetime"),
        pytest.param({"unknown_field": "oops"}, id="rejects_extra_field"),
        pytest.param({"shadow": 1}, id="rejects_non_bool_shadow"),
        pytest.param({"source": "sweep"}, id="rejects_unknown_source"),
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
