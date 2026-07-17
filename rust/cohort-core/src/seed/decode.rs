//! Tolerant two-stage decode of a seed-topic payload: a cheap kind/schema probe, then the full
//! [`SeedTile`] parse only for a supported combination. The consumer's policy is skip-and-count
//! (never wedge a partition): unknown kinds and newer schemas are data for later slices'
//! consumers, and a malformed payload is deterministic bytes that would fail identically on every
//! redelivery.

use serde::Deserialize;

use super::tile::{SeedTile, SCHEMA_VERSION, TILE_KIND};

/// The probe outcome for a supported-or-not payload. `UnknownKind` covers kinds this consumer
/// does not handle (e.g. a reconcile control tile before its slice ships); `UnsupportedSchema`
/// covers a known kind at a newer schema version.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DecodedSeed {
    Tile(SeedTile),
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
    if probe.kind != TILE_KIND {
        return Ok(DecodedSeed::UnknownKind {
            kind: probe.kind,
            schema_version: probe.schema_version,
        });
    }
    if probe.schema_version != SCHEMA_VERSION {
        return Ok(DecodedSeed::UnsupportedSchema {
            kind: probe.kind,
            schema_version: probe.schema_version,
        });
    }
    Ok(DecodedSeed::Tile(serde_json::from_slice(payload)?))
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroU32;

    use uuid::Uuid;

    use crate::filters::TeamId;
    use crate::seed::{ClaimEpoch, ConditionHash, RunId, SChunkMs};

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

    #[test]
    fn decode_probes_kind_and_schema_before_the_full_parse() {
        let tile = tile_json();
        let decode = |value: &serde_json::Value| decode_seed(&serde_json::to_vec(value).unwrap());

        assert!(matches!(decode(&tile).unwrap(), DecodedSeed::Tile(_)));

        let mut reconcile = tile.clone();
        reconcile["kind"] = serde_json::json!("reconcile");
        assert_eq!(
            decode(&reconcile).unwrap(),
            DecodedSeed::UnknownKind {
                kind: "reconcile".to_string(),
                schema_version: 1,
            }
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

        // A supported kind/schema with a malformed body is a decode error, not a skip: the probe
        // admits it, the full parse rejects it (zero count here).
        let mut zero_count = tile.clone();
        zero_count["count"] = serde_json::json!(0);
        assert!(decode(&zero_count).is_err());

        let mut kindless = tile;
        kindless.as_object_mut().unwrap().remove("kind");
        assert!(decode(&kindless).is_err());
        assert!(decode_seed(b"not json").is_err());
    }
}
