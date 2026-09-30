//! Schema contract test for `flags_cache_invalidation` messages.
//!
//! Reads the same on-disk fixture the Python side round-trips
//! (`products/feature_flags/backend/test/test_flags_cache_messages.py`). If the
//! wire schema drifts on either side, one of these tests — or its Python twin —
//! fails the build. The rejection cases mirror Python's `extra="forbid"` model
//! one-for-one.

use chrono::{DateTime, Utc};
use feature_flags::flags::cache_invalidation::{FlagsCacheInvalidation, Operation, Source};
use rstest::rstest;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;

const FIXTURE: &str = include_str!("fixtures/flags_cache_invalidation_v1.json");
const SHADOW_FIXTURE: &str = include_str!("fixtures/flags_cache_invalidation_v1_shadow.json");
const REFRESH_FIXTURE: &str = include_str!("fixtures/flags_cache_invalidation_v1_refresh.json");

/// Each fixture parses to the values it declares, survives a re-serialize and
/// reparse, and comes back out with exactly the key set it went in with.
///
/// That last assertion is the wire contract, and it is written once rather than
/// per field: `shadow: false` and `source: edit` are the defaults, they stay off
/// the wire, and a consumer predating either field must still read every message
/// an edit produces. A per-field membership check would pass a fourth optional
/// field that someone forgot to omit.
#[rstest]
#[case::edit(FIXTURE, false, Source::Edit)]
#[case::shadow(SHADOW_FIXTURE, true, Source::Edit)]
#[case::refresh(REFRESH_FIXTURE, false, Source::Refresh)]
fn fixture_round_trips(
    #[case] fixture: &str,
    #[case] expected_shadow: bool,
    #[case] expected_source: Source,
) {
    let parsed: FlagsCacheInvalidation = serde_json::from_str(fixture).expect("fixture must parse");

    assert_eq!(parsed.version, 1);
    assert_eq!(parsed.team_id, 12345);
    assert_eq!(parsed.operation, Operation::Invalidate);
    assert_eq!(parsed.shadow, expected_shadow);
    assert_eq!(parsed.source, expected_source);
    let expected_emitted_at = "2026-04-23T10:37:00Z"
        .parse::<DateTime<Utc>>()
        .expect("expected timestamp must parse");
    assert_eq!(parsed.emitted_at, expected_emitted_at);

    // Re-serialize and reparse — the struct must survive a full round-trip even
    // though chrono drops the fixture's zero `.000` fractional seconds (both are
    // valid ISO 8601; the schema, not the byte formatting, is the contract).
    let serialized = serde_json::to_string(&parsed).expect("must serialize");
    assert_eq!(key_set(&serialized), key_set(fixture));
    let reparsed: FlagsCacheInvalidation = serde_json::from_str(&serialized).expect("must reparse");
    assert_eq!(reparsed, parsed);
}

/// The top-level field names of a JSON object, for comparing a serialized
/// message against the fixture it came from.
fn key_set(json: &str) -> BTreeSet<String> {
    serde_json::from_str::<Map<String, Value>>(json)
        .expect("must be a JSON object")
        .into_iter()
        .map(|(key, _)| key)
        .collect()
}

/// An explicitly written default parses back to that default, so a producer that
/// spells one out is read the same as one that omits it.
#[rstest]
#[case::shadow("shadow", json!(false))]
#[case::source("source", json!("edit"))]
fn explicit_default_parses_as_the_default(#[case] field: &str, #[case] value: Value) {
    let mut payload = valid_base();
    payload[field] = value;
    let parsed: FlagsCacheInvalidation =
        serde_json::from_value(payload).expect("explicit default must parse");

    let omitted: FlagsCacheInvalidation =
        serde_json::from_value(valid_base()).expect("base must parse");
    assert_eq!(parsed, omitted);
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
#[case::unknown_source("source", json!("sweep"))]
fn rejects_invalid_payload(#[case] field: &str, #[case] value: Value) {
    let mut payload = valid_base();
    payload[field] = value;
    assert!(serde_json::from_value::<FlagsCacheInvalidation>(payload).is_err());
}
