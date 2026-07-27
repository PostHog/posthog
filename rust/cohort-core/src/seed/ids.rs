//! The seed contract's newtyped ids: `RunId`, `ClaimEpoch`, `SChunkMs`, and `ConditionHash`. They
//! ride the [`super::tile::SeedTile`] wire and the seeder's PostgreSQL ledger (hence the `sqlx`
//! derives), so both ends resolve them to the same types.

use std::borrow::Borrow;
use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};
use sqlx::Type;
use uuid::Uuid;

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
pub struct ClaimEpoch(pub i32);

/// The chunk's scan instant (epoch ms, UTC): the arrival upper bound of the tile's domain and the
/// consumer's fence input. Rides re-keyed tiles verbatim.
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize, Type,
)]
#[serde(transparent)]
#[sqlx(transparent)]
pub struct SChunkMs(pub i64);

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
