//! Domain layer (base): the crate's newtyped ids, epochs, instants, and ranges — `RunId`, `ChunkId`,
//! `ClaimEpoch`, `SChunkMs`, `ConditionHash`, `UtcMillis`, `UtcMsRange`. Depends only on `cohort-core`
//! (re-exporting its `DayIdx`); every other domain module builds on these.

use std::borrow::Borrow;
use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};
use sqlx::Type;
use uuid::Uuid;

pub use cohort_core::DayIdx;

#[derive(
    Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize, Type,
)]
#[serde(transparent)]
#[sqlx(transparent)]
pub struct RunId(pub Uuid);

#[derive(
    Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize, Type,
)]
#[serde(transparent)]
#[sqlx(transparent)]
pub struct ChunkId(pub Uuid);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Type)]
#[sqlx(transparent)]
pub struct ClaimEpoch(pub i32);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Type)]
#[sqlx(transparent)]
pub struct Band(pub i16);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Type)]
#[sqlx(transparent)]
pub struct SChunkMs(pub i64);

impl SChunkMs {
    pub const fn as_utc(self) -> UtcMillis {
        UtcMillis::new(self.0)
    }
}

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

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct ConditionHash([u8; 16]);

impl ConditionHash {
    pub fn parse(value: &str) -> Result<Self, ConditionHashError> {
        if value.len() != 16 {
            return Err(ConditionHashError::Length(value.len()));
        }
        if !value.is_ascii() {
            return Err(ConditionHashError::NonAscii);
        }
        let mut bytes = [0; 16];
        bytes.copy_from_slice(value.as_bytes());
        Ok(Self(bytes))
    }

    pub const fn as_bytes(self) -> [u8; 16] {
        self.0
    }

    pub fn as_str(&self) -> &str {
        std::str::from_utf8(&self.0)
            .expect("ASCII by construction: parse() is the only constructor")
    }
}

impl Borrow<[u8; 16]> for ConditionHash {
    fn borrow(&self) -> &[u8; 16] {
        &self.0
    }
}

impl fmt::Display for ConditionHash {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for ConditionHash {
    type Err = ConditionHashError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::parse(value)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum ConditionHashError {
    #[error("conditionHash must be exactly 16 bytes, got {0}")]
    Length(usize),
    #[error("conditionHash must contain only ASCII characters")]
    NonAscii,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn condition_hash_accepts_only_the_catalogs_literal_ascii_shape() {
        let hash = ConditionHash::parse("0123456789abcdef").unwrap();
        assert_eq!(hash.as_str(), "0123456789abcdef");
        assert_eq!(hash.as_bytes(), *b"0123456789abcdef");

        for invalid in ["0123456789abcde", "0123456789abcdefg", "é23456789abcdef"] {
            assert!(
                ConditionHash::parse(invalid).is_err(),
                "accepted {invalid:?}"
            );
        }
    }
}
