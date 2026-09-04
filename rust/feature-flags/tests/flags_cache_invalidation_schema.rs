//! Schema contract test for `flags_cache_invalidation` messages.
//!
//! Reads the same on-disk fixture the Python side round-trips
//! (`products/feature_flags/backend/test/test_flags_cache_messages.py`). If the
//! wire schema drifts on either side, one of these tests — or its Python twin —
//! fails the build. The rejection cases mirror Python's `extra="forbid"` model
//! one-for-one.

use chrono::{DateTime, Utc};
use feature_flags::flags::cache_invalidation::{FlagsCacheInvalidation, Operation};
use rstest::rstest;
use serde_json::{json, Value};

const FIXTURE: &str = include_str!("fixtures/flags_cache_invalidation_v1.json");
const SHADOW_FIXTURE: &str = include_str!("fixtures/flags_cache_invalidation_v1_shadow.json");

#[test]
fn fixture_round_trips() {
    let parsed: FlagsCacheInvalidation = serde_json::from_str(FIXTURE).expect("fixture must parse");

    assert_eq!(parsed.version, 1);
    assert_eq!(parsed.team_id, 12345);
    assert_eq!(parsed.operation, Operation::Invalidate);
    // A fixture without the field must read as a real invalidation, so producers
    // predating shadow mode keep exactly today's behavior.
    assert!(!parsed.shadow);
    let expected_emitted_at = "2026-04-23T10:37:00Z"
        .parse::<DateTime<Utc>>()
        .expect("expected timestamp must parse");
    assert_eq!(parsed.emitted_at, expected_emitted_at);

    // Re-serialize and reparse — the struct must survive a full round-trip even
    // though chrono drops the fixture's zero `.000` fractional seconds (both are
    // valid ISO 8601; the schema, not the byte formatting, is the contract).
    let serialized = serde_json::to_string(&parsed).expect("must serialize");
    // `shadow: false` stays off the wire so real invalidations (including DLQ
    // replays) remain byte-compatible with the pre-shadow schema.
    assert!(!serialized.contains("shadow"));
    let reparsed: FlagsCacheInvalidation = serde_json::from_str(&serialized).expect("must reparse");
    assert_eq!(reparsed, parsed);
}

#[test]
fn shadow_fixture_round_trips() {
    let parsed: FlagsCacheInvalidation =
        serde_json::from_str(SHADOW_FIXTURE).expect("shadow fixture must parse");

    assert_eq!(parsed.version, 1);
    assert_eq!(parsed.team_id, 12345);
    assert_eq!(parsed.operation, Operation::Invalidate);
    assert!(parsed.shadow);

    let reparsed: FlagsCacheInvalidation =
        serde_json::from_str(&serde_json::to_string(&parsed).expect("must serialize"))
            .expect("must reparse");
    assert_eq!(reparsed, parsed);
}

#[test]
fn explicit_shadow_false_parses_as_real_invalidation() {
    let mut payload = valid_base();
    payload["shadow"] = json!(false);
    let parsed: FlagsCacheInvalidation =
        serde_json::from_value(payload).expect("explicit shadow: false must parse");
    assert!(!parsed.shadow);
}

fn valid_base() -> Value {
    json!({
        "version": 1,
        "team_id": 12345,
        "operation": "invalidate",
        "emitted_at": "2026-04-23T10:37:00Z",
    })
}

/// Each case mutates one field of `valid_base()` and asserts the payload is
/// rejected — mirroring Python's `extra="forbid"` model one-for-one. Setting a
/// missing key (e.g. `unknown_field`) inserts it, exercising `deny_unknown_fields`.
#[rstest]
#[case::unknown_version("version", json!(2))]
#[case::unknown_operation("operation", json!("clear"))]
#[case::naive_datetime("emitted_at", json!("2026-04-23T10:37:00"))]
#[case::extra_field("unknown_field", json!("oops"))]
#[case::non_bool_shadow("shadow", json!(1))]
fn rejects_invalid_payload(#[case] field: &str, #[case] value: Value) {
    let mut payload = valid_base();
    payload[field] = value;
    assert!(serde_json::from_value::<FlagsCacheInvalidation>(payload).is_err());
}
