//! Producer schema contract test for `hypercache:ready:feature_flags:*` signals.
//!
//! This crate is a PRODUCER of the cache-ready signal (via the flags-cache-builder
//! binary); Django emits the byte-identical shape. The fixture at
//! `rust/feature-flags/tests/fixtures/hypercache_ready_v1.json` is the
//! cross-language contract, and this test is strict: a struct built from the
//! fixture's values must serialize back to the exact fixture shape, and the
//! constructor must stamp `written_at` with the microsecond + `Z` byte shape
//! Django also emits.
//!
//! The gateway's `HintV1` consumer is deliberately lenient (see
//! `feature_flags::flags::hypercache_ready`); strictness lives only on this
//! producer side (plan §3.1 asymmetry).

use chrono::{DateTime, SecondsFormat, Utc};
use feature_flags::flags::hypercache_ready::HypercacheReadySignal;
use serde_json::Value;

const FIXTURE: &str = include_str!("fixtures/hypercache_ready_v1.json");

#[test]
fn hypercache_ready_fixture_serializes_value_equal() {
    let fixture: Value = serde_json::from_str(FIXTURE).expect("fixture must parse as JSON");
    // A struct built from the fixture's values must serialize back to the exact
    // fixture shape — the strict producer contract, catching any field drift.
    let parsed: HypercacheReadySignal =
        serde_json::from_str(FIXTURE).expect("fixture must parse into the producer struct");
    let reserialized = serde_json::to_value(&parsed).expect("producer struct must serialize");
    assert_eq!(
        reserialized, fixture,
        "producer output drifted from the fixture contract"
    );
}

#[test]
fn hypercache_ready_constructor_fills_static_fields_and_micros_z() {
    let signal = HypercacheReadySignal::new(123, "0123456789abcdef".to_string());
    assert_eq!(signal.v, 1);
    assert_eq!(signal.team_id, 123);
    assert_eq!(signal.namespace, "feature_flags");
    assert_eq!(signal.value, "flags.json");
    assert_eq!(signal.etag, "0123456789abcdef");

    // Parse-then-reserialize with Micros + Z: equality proves `written_at` is
    // exactly the microsecond + `Z` byte shape the fixture (and Django) use — a
    // stray milli/nano precision or missing fraction would not round-trip.
    let parsed: DateTime<Utc> = signal
        .written_at
        .parse()
        .expect("written_at must parse as an aware UTC datetime");
    assert_eq!(
        parsed.to_rfc3339_opts(SecondsFormat::Micros, true),
        signal.written_at,
        "written_at is not exactly RFC 3339 microseconds + Z"
    );
}

#[test]
fn hypercache_ready_channel_targets_flags_json() {
    assert_eq!(
        HypercacheReadySignal::channel(),
        "hypercache:ready:feature_flags:flags.json"
    );
}
