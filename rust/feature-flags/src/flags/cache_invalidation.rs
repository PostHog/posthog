//! Wire schema for `flags_cache_invalidation` Kafka messages.
//!
//! Producer: Django signal handlers in `products/feature_flags/backend/flags_cache.py`.
//! Consumer: the `flags-cache-builder` binary in this crate.
//!
//! The fixture at `rust/feature-flags/tests/fixtures/flags_cache_invalidation_v1.json`
//! is the contract. Both this crate and the Python side round-trip against that same
//! on-disk file (`products/feature_flags/backend/test/test_flags_cache_messages.py`),
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

/// The only operation v1 carries: "team X changed, rebuild its cache". The
/// consumer always reads fresh DB state at build time, so the message is a
/// trigger, not a payload (see the architecture doc, "team_id only").
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum Operation {
    #[default]
    Invalidate,
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
}

impl FlagsCacheInvalidation {
    /// Construct a v1 invalidation for `team_id` stamped at `emitted_at`.
    pub fn new(team_id: TeamId, emitted_at: DateTime<Utc>) -> Self {
        Self {
            version: 1,
            team_id,
            operation: Operation::Invalidate,
            emitted_at,
        }
    }
}

fn version_1() -> u8 {
    1
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
