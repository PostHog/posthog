//! Wire contract for one partition-targeted reconcile control tile.

use std::fmt;
use std::str::FromStr;

use serde::de::{Deserializer, Error as DeError, Unexpected};
use serde::ser::Serializer;
use serde::{Deserialize, Serialize};

use crate::filters::{CohortId, TeamId};

use super::ids::RunId;

pub(super) const RECONCILE_SCHEMA_VERSION: u32 = 1;
pub(super) const RECONCILE_KIND: &str = "reconcile";

/// The persisted behavioral filter-shape fingerprint that fences a reconcile job from cohort edits.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct BehavioralShapeHash(Box<str>);

impl BehavioralShapeHash {
    pub fn parse(value: &str) -> Result<Self, BehavioralShapeHashError> {
        if value.is_empty() {
            return Err(BehavioralShapeHashError::Empty);
        }
        if value.len() > 64 {
            return Err(BehavioralShapeHashError::TooLong(value.len()));
        }
        if !value.is_ascii() {
            return Err(BehavioralShapeHashError::NonAscii);
        }
        Ok(Self(value.into()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for BehavioralShapeHash {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for BehavioralShapeHash {
    type Err = BehavioralShapeHashError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::parse(value)
    }
}

impl Serialize for BehavioralShapeHash {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for BehavioralShapeHash {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        Self::parse(&value).map_err(|_| {
            DeError::invalid_value(
                Unexpected::Str(&value),
                &"a non-empty ASCII behavioral shape hash of at most 64 bytes",
            )
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum BehavioralShapeHashError {
    #[error("behavioral shape hash must not be empty")]
    Empty,
    #[error("behavioral shape hash must be at most 64 bytes, got {0}")]
    TooLong(usize),
    #[error("behavioral shape hash must contain only ASCII characters")]
    NonAscii,
}

/// A control tile that requests one partition's full current snapshot for one behavioral cohort.
/// Field order is the wire order.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReconcileTile {
    #[serde(deserialize_with = "deserialize_schema_version")]
    schema_version: u32,
    kind: ReconcileKind,
    #[serde(
        serialize_with = "serialize_team_id",
        deserialize_with = "deserialize_team_id"
    )]
    team_id: TeamId,
    #[serde(
        serialize_with = "serialize_cohort_id",
        deserialize_with = "deserialize_cohort_id"
    )]
    cohort_id: CohortId,
    filters_hash: BehavioralShapeHash,
    run_id: RunId,
}

impl ReconcileTile {
    pub fn new(
        team_id: TeamId,
        cohort_id: CohortId,
        filters_hash: BehavioralShapeHash,
        run_id: RunId,
    ) -> Self {
        Self {
            schema_version: RECONCILE_SCHEMA_VERSION,
            kind: ReconcileKind,
            team_id,
            cohort_id,
            filters_hash,
            run_id,
        }
    }

    pub const fn team_id(&self) -> TeamId {
        self.team_id
    }

    pub const fn cohort_id(&self) -> CohortId {
        self.cohort_id
    }

    pub fn filters_hash(&self) -> &BehavioralShapeHash {
        &self.filters_hash
    }

    pub const fn run_id(&self) -> RunId {
        self.run_id
    }
}

/// A zero-sized discriminant proven to be [`RECONCILE_KIND`] during deserialization.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct ReconcileKind;

impl Serialize for ReconcileKind {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(RECONCILE_KIND)
    }
}

impl<'de> Deserialize<'de> for ReconcileKind {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        if value != RECONCILE_KIND {
            return Err(DeError::invalid_value(
                Unexpected::Str(&value),
                &"seed kind \"reconcile\"",
            ));
        }
        Ok(Self)
    }
}

fn serialize_team_id<S: Serializer>(value: &TeamId, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_i32(value.0)
}

fn deserialize_team_id<'de, D: Deserializer<'de>>(deserializer: D) -> Result<TeamId, D::Error> {
    i32::deserialize(deserializer).map(TeamId)
}

fn serialize_cohort_id<S: Serializer>(value: &CohortId, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_i32(value.0)
}

fn deserialize_cohort_id<'de, D: Deserializer<'de>>(deserializer: D) -> Result<CohortId, D::Error> {
    i32::deserialize(deserializer).map(CohortId)
}

fn deserialize_schema_version<'de, D: Deserializer<'de>>(deserializer: D) -> Result<u32, D::Error> {
    let value = u32::deserialize(deserializer)?;
    if value != RECONCILE_SCHEMA_VERSION {
        return Err(DeError::invalid_value(
            Unexpected::Unsigned(u64::from(value)),
            &"reconcile schema version 1",
        ));
    }
    Ok(value)
}

#[cfg(test)]
mod tests {
    use uuid::Uuid;

    use super::*;

    // `extract_behavioral_leaf_shape_hash` for the canonical Python behavioral-leaf fixture.
    const SHA256: &str = "9efcd8a99c5334a19b52f6a7b990e3b862ad116031a0b47481f8bbb09e54a7de";

    fn tile() -> ReconcileTile {
        ReconcileTile::new(
            TeamId(2),
            CohortId(42),
            BehavioralShapeHash::parse(SHA256).unwrap(),
            RunId(Uuid::nil()),
        )
    }

    #[test]
    fn reconcile_wire_contract_is_fixed() {
        let tile = tile();
        assert_eq!(
            serde_json::to_value(&tile).unwrap(),
            serde_json::json!({
                "schema_version": 1,
                "kind": "reconcile",
                "team_id": 2,
                "cohort_id": 42,
                "filters_hash": SHA256,
                "run_id": "00000000-0000-0000-0000-000000000000",
            })
        );
        assert_eq!(
            serde_json::to_string(&tile).unwrap(),
            r#"{"schema_version":1,"kind":"reconcile","team_id":2,"cohort_id":42,"filters_hash":"9efcd8a99c5334a19b52f6a7b990e3b862ad116031a0b47481f8bbb09e54a7de","run_id":"00000000-0000-0000-0000-000000000000"}"#
        );
    }

    #[test]
    fn reconcile_roundtrips_and_rejects_foreign_kind_schema_and_hash() {
        let tile = tile();
        let bytes = serde_json::to_vec(&tile).unwrap();
        assert_eq!(
            serde_json::from_slice::<ReconcileTile>(&bytes).unwrap(),
            tile
        );

        let golden = serde_json::to_value(&tile).unwrap();
        let mut extended = golden.clone();
        extended["future_metadata"] = serde_json::json!({ "source": "scheduler" });
        assert_eq!(
            serde_json::from_value::<ReconcileTile>(extended).unwrap(),
            tile
        );

        for (field, value) in [
            ("kind", serde_json::json!("behavioral_tile")),
            ("schema_version", serde_json::json!(2)),
            ("filters_hash", serde_json::json!("")),
            ("filters_hash", serde_json::json!("x".repeat(65))),
            ("filters_hash", serde_json::json!("non-ascii-é")),
        ] {
            let mut broken = golden.clone();
            broken[field] = value;
            assert!(
                serde_json::from_value::<ReconcileTile>(broken).is_err(),
                "accepted a reconcile tile with mutated {field}",
            );
        }
    }

    #[test]
    fn behavioral_shape_hash_matches_the_persisted_output_bounds() {
        assert_eq!(BehavioralShapeHash::parse(SHA256).unwrap().as_str(), SHA256,);
        assert_eq!(BehavioralShapeHash::parse("a").unwrap().as_str(), "a",);
        assert_eq!(
            BehavioralShapeHash::parse(""),
            Err(BehavioralShapeHashError::Empty),
        );
        assert_eq!(
            BehavioralShapeHash::parse(&"x".repeat(65)),
            Err(BehavioralShapeHashError::TooLong(65)),
        );
        assert_eq!(
            BehavioralShapeHash::parse("é"),
            Err(BehavioralShapeHashError::NonAscii),
        );
    }
}
