//! Wire schema for `hypercache:ready:feature_flags:*` cache-ready signals — the
//! realtime-flags "hint" fast path, published after a HyperCache write so the
//! streaming gateway can wake subscribers without waiting for its ETag sweep.
//!
//! This is the PRODUCER side. The `flags-cache-builder` binary emits this struct
//! after a successful `flags.json` build; Django's `HyperCache` emits a
//! byte-identical shape after its own writes. The fixture at
//! `rust/feature-flags/tests/fixtures/hypercache_ready_v1.json` is the
//! cross-language contract, and the strict producer schema test round-trips
//! against it (`rust/feature-flags/tests/hypercache_ready_schema.rs`).
//!
//! The CONSUMER — the `flags-stream-gateway`'s `HintV1` subscriber — is
//! deliberately lenient (it tolerates unknown fields): the hint is at-most-once
//! and sweep-backed, so an additive schema change must not blank out the fast
//! path during a rolling deploy. Strictness therefore lives only here, on the
//! producer's output shape (plan §3.1 asymmetry).

use chrono::{SecondsFormat, Utc};
use common_types::TeamId;
use serde::{Deserialize, Serialize};

/// HyperCache namespace the flags caches live under (mirrors
/// `cache_writer::HYPERCACHE_NAMESPACE`, restated so the wire contract stays local).
const NAMESPACE: &str = "feature_flags";
/// HyperCache value name for the remote-eval cache the builder writes.
const VALUE: &str = "flags.json";
/// Pub/sub channel the gateway subscribes to for `flags.json` cache-ready hints.
const READY_CHANNEL: &str = "hypercache:ready:feature_flags:flags.json";

/// A cache-ready signal for one team's `flags.json` snapshot.
///
/// `written_at` is a pre-formatted RFC 3339 UTC string with microsecond precision
/// and a `Z` suffix (e.g. `2026-07-26T12:00:00.123456Z`) — the shape Django emits
/// for sub-second timestamps (pydantic drops the fraction entirely at a whole
/// second, where chrono emits `.000000Z`; consumers parse both). It is kept as a
/// `String` so the producer output is stable and never silently re-formatted by a
/// chrono round-trip.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HypercacheReadySignal {
    /// Schema version. Always 1.
    pub v: u32,
    pub team_id: TeamId,
    /// Always `"feature_flags"`.
    pub namespace: String,
    /// Always `"flags.json"`.
    pub value: String,
    /// The freshly written HyperCache content hash (16 lowercase hex chars).
    pub etag: String,
    /// RFC 3339 UTC, microseconds + `Z`. See the struct doc.
    pub written_at: String,
}

impl HypercacheReadySignal {
    /// Build a v1 signal for `team_id`/`etag`, stamping `written_at` at now with
    /// the microsecond + `Z` shape Django also produces.
    pub fn new(team_id: TeamId, etag: String) -> Self {
        Self {
            v: 1,
            team_id,
            namespace: NAMESPACE.to_string(),
            value: VALUE.to_string(),
            etag,
            written_at: Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true),
        }
    }

    /// The pub/sub channel `flags.json` cache-ready signals are published on.
    pub const fn channel() -> &'static str {
        READY_CHANNEL
    }
}
