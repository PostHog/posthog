//! Tolerant two-stage decode of a seed-topic payload: a cheap kind/schema probe, then the full
//! the full wire type parse only for a supported combination. The consumer's policy is
//! skip-and-count (never wedge a partition): unknown kinds and newer schemas are data for later
//! consumers, and a malformed payload is deterministic bytes that would fail identically on every
//! redelivery.

use serde::Deserialize;

use super::reconcile::{ReconcileTile, RECONCILE_KIND, RECONCILE_SCHEMA_VERSION};
use super::tile::{SeedTile, SCHEMA_VERSION, TILE_KIND};

/// The probe outcome for a supported-or-not payload. `UnknownKind` covers kinds this consumer does
/// not handle; `UnsupportedSchema` covers a known kind at a newer schema version.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DecodedSeed {
    Tile(SeedTile),
    Reconcile(ReconcileTile),
    UnknownKind { kind: String, schema_version: u32 },
    UnsupportedSchema { kind: String, schema_version: u32 },
}

#[derive(Deserialize)]
struct SeedProbe {
    kind: String,
    schema_version: u32,
}

pub fn decode_seed(payload: &[u8]) -> Result<DecodedSeed, serde_json::Error> {
    let probe: SeedProbe = serde_json::from_slice(payload)?;
    match probe.kind.as_str() {
        TILE_KIND if probe.schema_version == SCHEMA_VERSION => {
            Ok(DecodedSeed::Tile(serde_json::from_slice(payload)?))
        }
        RECONCILE_KIND if probe.schema_version == RECONCILE_SCHEMA_VERSION => {
            Ok(DecodedSeed::Reconcile(serde_json::from_slice(payload)?))
        }
        TILE_KIND | RECONCILE_KIND => Ok(DecodedSeed::UnsupportedSchema {
            kind: probe.kind,
            schema_version: probe.schema_version,
        }),
        _ => Ok(DecodedSeed::UnknownKind {
            kind: probe.kind,
            schema_version: probe.schema_version,
        }),
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU32;

    use uuid::Uuid;

    use crate::filters::TeamId;
    use crate::seed::{
        BehavioralShapeHash, ClaimEpoch, ConditionHash, ReconcileTile, RunId, SChunkMs,
    };

    use super::*;

    fn tile_json() -> serde_json::Value {
        serde_json::to_value(SeedTile::new(
            TeamId(2),
            Uuid::from_u128(7),
            ConditionHash::parse("0123456789abcdef").unwrap(),
            NonZeroU32::new(3).unwrap(),
            19,
            SChunkMs(1_700_000_000_000),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        ))
        .unwrap()
    }

    fn reconcile_json() -> serde_json::Value {
        serde_json::to_value(ReconcileTile::new(
            TeamId(2),
            crate::filters::CohortId(42),
            BehavioralShapeHash::parse(
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            )
            .unwrap(),
            RunId(Uuid::nil()),
        ))
        .unwrap()
    }

    #[test]
    fn decode_probes_kind_and_schema_before_the_full_parse() {
        let tile = tile_json();
        let decode = |value: &serde_json::Value| decode_seed(&serde_json::to_vec(value).unwrap());

        assert!(matches!(decode(&tile).unwrap(), DecodedSeed::Tile(_)));

        let reconcile = reconcile_json();
        assert_eq!(
            decode(&reconcile).unwrap(),
            DecodedSeed::Reconcile(serde_json::from_value(reconcile.clone()).unwrap()),
        );

        let mut unknown = tile.clone();
        unknown["kind"] = serde_json::json!("future_control");
        assert_eq!(
            decode(&unknown).unwrap(),
            DecodedSeed::UnknownKind {
                kind: "future_control".to_string(),
                schema_version: 1,
            },
        );

        let mut newer = tile.clone();
        newer["schema_version"] = serde_json::json!(2);
        assert_eq!(
            decode(&newer).unwrap(),
            DecodedSeed::UnsupportedSchema {
                kind: "behavioral_tile".to_string(),
                schema_version: 2,
            }
        );

        let mut newer_reconcile = reconcile.clone();
        newer_reconcile["schema_version"] = serde_json::json!(2);
        newer_reconcile["filters_hash"] = serde_json::json!("");
        assert_eq!(
            decode(&newer_reconcile).unwrap(),
            DecodedSeed::UnsupportedSchema {
                kind: "reconcile".to_string(),
                schema_version: 2,
            },
        );

        // A supported kind/schema with a malformed body is a decode error, not a skip: the probe
        // admits it, the full parse rejects it (zero count here).
        let mut zero_count = tile.clone();
        zero_count["count"] = serde_json::json!(0);
        assert!(decode(&zero_count).is_err());

        let mut empty_hash = reconcile;
        empty_hash["filters_hash"] = serde_json::json!("");
        assert!(decode(&empty_hash).is_err());

        let mut kindless = tile;
        kindless.as_object_mut().unwrap().remove("kind");
        assert!(decode(&kindless).is_err());
        assert!(decode_seed(b"not json").is_err());
    }
}
