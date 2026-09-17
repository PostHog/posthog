//! Wire schema for `flags_cache_invalidation` Kafka messages.
//!
//! Producer: Django signal handlers in `products/feature_flags/backend/flags_cache.py`.
//! Consumer: the `flags-cache-builder` binary in this crate.
//!
//! The fixtures at `rust/feature-flags/tests/fixtures/flags_cache_invalidation_v1.json`,
//! `flags_cache_invalidation_v1_shadow.json` and
//! `flags_cache_invalidation_v1_refresh.json` are the contract. Both this crate and
//! the Python side round-trip against the same on-disk files
//! (`products/feature_flags/backend/test/test_flags_cache_messages.py`),
//! so a schema drift on either side fails CI. The Rust struct mirrors the Python
//! model's strictness field-for-field: unknown fields rejected, only `version: 1`,
//! only `operation: "invalidate"`, and a timezone-aware `emitted_at`.
//!
//! Bumping `version` requires running both producers (old + new) and both consumers
//! (old + new) in parallel during the migration — do not bump it without a written
//! rollout plan.

use chrono::{DateTime, Utc};
use common_types::TeamId;
use serde::{Deserialize, Deserializer, Serialize};
use strum::EnumIter;

/// The only operation v1 carries: "team X changed, rebuild its cache". The
/// consumer always reads fresh DB state at build time, so the message is a
/// trigger, not a payload (see the architecture doc, "team_id only").
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum Operation {
    #[default]
    Invalidate,
}

/// What raised the invalidation. `Edit` is a flag change reaching a signal
/// handler; `Refresh` is the hourly expiry sweep asking for a rebuild before the
/// entry's TTL runs out. The consumer builds both identically — the value exists
/// so a build, a failure and an end-to-end latency can be attributed to the path
/// that caused them. Without it the sweep's volume buries the edit path, which
/// is the one with a serve-latency expectation.
///
/// `EnumIter` is derived so `precreate_counters` iterates it: a new variant
/// cannot reach a metric without also being pre-created at zero.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default, EnumIter)]
#[serde(rename_all = "snake_case")]
pub enum Source {
    #[default]
    Edit,
    Refresh,
}

impl Source {
    pub fn as_label(&self) -> &'static str {
        match self {
            Source::Edit => "edit",
            Source::Refresh => "refresh",
        }
    }

    fn is_edit(&self) -> bool {
        matches!(self, Source::Edit)
    }
}

/// A single cache-invalidation message. `serde(deny_unknown_fields)` plus the
/// `Operation` enum (no catch-all variant) and the `version == 1` guard make this
/// reject exactly what the Python `extra="forbid"` model rejects.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FlagsCacheInvalidation {
    #[serde(deserialize_with = "deserialize_version_1", default = "version_1")]
    pub version: u8,
    pub team_id: TeamId,
    #[serde(default)]
    pub operation: Operation,
    /// ISO 8601, UTC. `DateTime<Utc>` requires an explicit offset, so a naive
    /// timestamp (no `Z`/offset) is rejected — matching Python's `AwareDatetime`.
    pub emitted_at: DateTime<Utc>,
    /// Shadow invalidation: the consumer builds the payload as usual but never
    /// writes it — instead it diffs the build against the live cache entry and
    /// records the result (parity telemetry for teams Celery still owns and
    /// serve-writes). Absent or `false` means a real invalidation, so producers
    /// predating this field are unaffected. `skip_serializing_if` keeps `false`
    /// off the wire, so serialized real invalidations (including DLQ replays)
    /// stay byte-compatible with pre-shadow consumers and Python's
    /// `extra="forbid"` model.
    #[serde(default, skip_serializing_if = "is_false")]
    pub shadow: bool,
    /// Which producer raised this. Absent means `edit`, and `edit` is kept off
    /// the wire, so a consumer that predates the field still reads every message
    /// an edit produces — the same compatibility contract `shadow` has.
    ///
    /// The consequence for rollout: `deny_unknown_fields` makes a message carrying
    /// `source` a parse error to an older consumer, which counts it, logs it,
    /// stores the offset and drops it. There is no DLQ record, so nothing can be
    /// replayed — the team stays stale until the verifier repairs it. Nothing may
    /// emit `refresh` in a region until the builder deployed there understands it.
    #[serde(default, skip_serializing_if = "Source::is_edit")]
    pub source: Source,
}

impl FlagsCacheInvalidation {
    /// Construct a v1 invalidation for `team_id`, stamped at `emitted_at` and
    /// attributed to `source`.
    pub fn new(team_id: TeamId, emitted_at: DateTime<Utc>, source: Source) -> Self {
        Self {
            version: 1,
            team_id,
            operation: Operation::Invalidate,
            emitted_at,
            shadow: false,
            source,
        }
    }
}

fn version_1() -> u8 {
    1
}

fn is_false(value: &bool) -> bool {
    !*value
}

/// Reject any `version` other than 1. A future schema change bumps this
/// deliberately, alongside the dual-producer/dual-consumer rollout the module
/// docs call for.
fn deserialize_version_1<'de, D>(deserializer: D) -> Result<u8, D::Error>
where
    D: Deserializer<'de>,
{
    let version = u8::deserialize(deserializer)?;
    if version != 1 {
        return Err(serde::de::Error::custom(format!(
            "unsupported flags_cache_invalidation schema version: {version} (expected 1)"
        )));
    }
    Ok(version)
}
