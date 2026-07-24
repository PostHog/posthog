//! Domain layer (base): the crate's newtyped ids, epochs, instants, and ranges. The ids that ride
//! the seed wire — `RunId`, `ClaimEpoch`, `SChunkMs`, `ConditionHash` — live in
//! `cohort_core::seed` (the processor consumes them too) and are re-exported here; the
//! seeder-internal `ChunkId`, `Band`, `UtcMillis`, and `UtcMsRange` are defined below. Every other
//! domain module builds on these.

use serde::{Deserialize, Serialize};
use sqlx::Type;
use uuid::Uuid;

pub use cohort_core::seed::{ClaimEpoch, ConditionHash, ConditionHashError, RunId, SChunkMs};
pub use cohort_core::DayIdx;

#[derive(
    Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize, Type,
)]
#[serde(transparent)]
#[sqlx(transparent)]
pub struct ChunkId(pub Uuid);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Type)]
#[sqlx(transparent)]
pub struct Band(pub i16);

/// Epoch milliseconds (UTC): the crate's single instant type. Unwrap to `i64` only at cohort-core
/// calls, SQL rendering, and serde boundaries.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct UtcMillis(i64);

impl UtcMillis {
    pub const fn new(value: i64) -> Self {
        Self(value)
    }

    pub const fn as_i64(self) -> i64 {
        self.0
    }
}

/// A half-open `[start, end)` window of epoch milliseconds. The `start <= end` invariant is proven
/// by [`UtcMsRange::new`], so consumers never re-check it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UtcMsRange {
    start: UtcMillis,
    end: UtcMillis,
}

impl UtcMsRange {
    pub fn new(start: UtcMillis, end: UtcMillis) -> Result<Self, UtcRangeError> {
        if start.0 > end.0 {
            return Err(UtcRangeError {
                start: start.0,
                end: end.0,
            });
        }
        Ok(Self { start, end })
    }

    pub const fn start(self) -> UtcMillis {
        self.start
    }

    pub const fn end(self) -> UtcMillis {
        self.end
    }

    pub const fn is_empty(self) -> bool {
        self.start.0 == self.end.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("UTC range start {start} exceeds end {end}")]
pub struct UtcRangeError {
    pub start: i64,
    pub end: i64,
}
