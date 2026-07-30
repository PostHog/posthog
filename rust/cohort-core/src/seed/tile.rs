//! `SeedTile`, the wire-frozen unit produced to `cohort_stream_seed_events` and applied by the
//! stream processor — typed private fields, a total constructor, and serde that emits exactly the
//! frozen JSON primitives. The golden test in this module is the byte-level regression gate.

use std::num::NonZeroU32;

use serde::de::{Deserializer, Error as DeError, Unexpected};
use serde::ser::Serializer;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::bucket_tz::DayIdx;
use crate::filters::TeamId;

use super::ids::{ClaimEpoch, ConditionHash, RunId, SChunkMs};

pub(super) const SCHEMA_VERSION: u32 = 1;
pub(super) const TILE_KIND: &str = "behavioral_tile";

/// One `(person, condition, day)` absolute count. Field order is the wire order; new fields must
/// be appended and skipped at their absent-equivalent value (`redirect_hops`) so older payloads
/// keep parsing and seeder-produced bytes stay frozen.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SeedTile {
    #[serde(deserialize_with = "deserialize_schema_version")]
    schema_version: u32,
    kind: TileKind,
    #[serde(
        serialize_with = "serialize_team_id",
        deserialize_with = "deserialize_team_id"
    )]
    team_id: TeamId,
    person_id: Uuid,
    #[serde(
        serialize_with = "serialize_condition_hash",
        deserialize_with = "deserialize_condition_hash"
    )]
    condition_hash: ConditionHash,
    day_idx: DayIdx,
    count: NonZeroU32,
    run_id: RunId,
    s_chunk_ms: SChunkMs,
    claim_epoch: ClaimEpoch,
    /// Times this tile has been re-produced to a merge survivor's partition. Absent on the wire at
    /// 0, so tiles the seeder emits are byte-identical to the pre-field contract.
    #[serde(default, skip_serializing_if = "hops_are_zero")]
    redirect_hops: u8,
}

impl SeedTile {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        team_id: TeamId,
        person_id: Uuid,
        condition_hash: ConditionHash,
        count: NonZeroU32,
        day_idx: DayIdx,
        s_chunk_ms: SChunkMs,
        run_id: RunId,
        claim_epoch: ClaimEpoch,
    ) -> Self {
        Self {
            schema_version: SCHEMA_VERSION,
            kind: TileKind,
            team_id,
            person_id,
            condition_hash,
            day_idx,
            count,
            run_id,
            s_chunk_ms,
            claim_epoch,
            redirect_hops: 0,
        }
    }

    /// The tile re-keyed to a merge survivor, or `None` once `cap` hops are exhausted — an
    /// over-cap re-produce is unrepresentable, so the caller must handle the cap arm explicitly.
    /// `s_chunk_ms` rides verbatim: the fence re-checks at the target partition against the
    /// original scan instant.
    #[must_use]
    pub fn rekeyed_to(&self, survivor: Uuid, cap: u8) -> Option<Self> {
        let redirect_hops = self
            .redirect_hops
            .checked_add(1)
            .filter(|hops| *hops <= cap)?;
        Some(Self {
            person_id: survivor,
            redirect_hops,
            ..self.clone()
        })
    }

    pub fn partition_key(&self) -> String {
        format!("{}:{}", self.team_id.0, self.person_id)
    }

    pub const fn team_id(&self) -> TeamId {
        self.team_id
    }

    pub const fn person_id(&self) -> Uuid {
        self.person_id
    }

    pub const fn condition_hash(&self) -> ConditionHash {
        self.condition_hash
    }

    pub const fn day_idx(&self) -> DayIdx {
        self.day_idx
    }

    pub const fn count(&self) -> u32 {
        self.count.get()
    }

    /// The count with its non-zero proof intact, for consumers whose merge math relies on it.
    pub const fn count_nonzero(&self) -> NonZeroU32 {
        self.count
    }

    pub const fn run_id(&self) -> RunId {
        self.run_id
    }

    pub const fn s_chunk_ms(&self) -> SChunkMs {
        self.s_chunk_ms
    }

    pub const fn claim_epoch(&self) -> ClaimEpoch {
        self.claim_epoch
    }

    pub const fn redirect_hops(&self) -> u8 {
        self.redirect_hops
    }
}

/// The `kind` discriminant, zero-sized and proven to be [`TILE_KIND`] by parse — a borrowed
/// `&'static str` field would force `Deserialize<'static>` on the whole tile.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct TileKind;

impl Serialize for TileKind {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(TILE_KIND)
    }
}

impl<'de> Deserialize<'de> for TileKind {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        if value != TILE_KIND {
            return Err(DeError::invalid_value(
                Unexpected::Str(&value),
                &"seed kind \"behavioral_tile\"",
            ));
        }
        Ok(Self)
    }
}

fn hops_are_zero(hops: &u8) -> bool {
    *hops == 0
}

fn serialize_team_id<S: Serializer>(value: &TeamId, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_i32(value.0)
}

fn deserialize_team_id<'de, D: Deserializer<'de>>(deserializer: D) -> Result<TeamId, D::Error> {
    i32::deserialize(deserializer).map(TeamId)
}

fn serialize_condition_hash<S: Serializer>(
    value: &ConditionHash,
    serializer: S,
) -> Result<S::Ok, S::Error> {
    serializer.serialize_str(value.as_str())
}

fn deserialize_condition_hash<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<ConditionHash, D::Error> {
    let value = String::deserialize(deserializer)?;
    ConditionHash::parse(&value)
        .map_err(|_| DeError::invalid_value(Unexpected::Str(&value), &"a 16-byte ASCII hash"))
}

fn deserialize_schema_version<'de, D: Deserializer<'de>>(deserializer: D) -> Result<u32, D::Error> {
    let value = u32::deserialize(deserializer)?;
    if value != SCHEMA_VERSION {
        return Err(DeError::invalid_value(
            Unexpected::Unsigned(u64::from(value)),
            &"seed tile schema version 1",
        ));
    }
    Ok(value)
}

#[cfg(test)]
mod tests {
    use crate::partitioner::{partition_for, COHORT_PARTITION_COUNT};

    use super::*;

    fn tile() -> SeedTile {
        SeedTile::new(
            TeamId(2),
            Uuid::from_u128(0x0192_8aaa_bbbb_cccc_dddd_eeee_eeee_eeee),
            ConditionHash::parse("0123456789abcdef").unwrap(),
            NonZeroU32::new(3).unwrap(),
            19,
            SChunkMs(1_700_000_000_000),
            RunId(Uuid::nil()),
            ClaimEpoch(7),
        )
    }

    #[test]
    fn tile_wire_contract_and_partition_key_are_fixed_by_construction() {
        let tile = tile();
        assert_eq!(
            tile.partition_key(),
            "2:01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        );
        assert_eq!(
            partition_for(&tile.partition_key(), COHORT_PARTITION_COUNT),
            58
        );
        assert_eq!(
            serde_json::to_value(&tile).unwrap(),
            serde_json::json!({
                "schema_version": 1,
                "kind": "behavioral_tile",
                "team_id": 2,
                "person_id": "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "condition_hash": "0123456789abcdef",
                "day_idx": 19,
                "count": 3,
                "run_id": "00000000-0000-0000-0000-000000000000",
                "s_chunk_ms": 1_700_000_000_000_i64,
                "claim_epoch": 7,
            })
        );
        assert_eq!(
            serde_json::to_string(&tile).unwrap(),
            r#"{"schema_version":1,"kind":"behavioral_tile","team_id":2,"person_id":"01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee","condition_hash":"0123456789abcdef","day_idx":19,"count":3,"run_id":"00000000-0000-0000-0000-000000000000","s_chunk_ms":1700000000000,"claim_epoch":7}"#
        );
    }

    #[test]
    fn tile_roundtrips_and_rejects_foreign_kind_schema_and_zero_count() {
        let tile = tile();
        let bytes = serde_json::to_vec(&tile).unwrap();
        assert_eq!(serde_json::from_slice::<SeedTile>(&bytes).unwrap(), tile);

        let golden = serde_json::to_value(&tile).unwrap();
        for (field, value) in [
            ("kind", serde_json::json!("reconcile")),
            ("schema_version", serde_json::json!(2)),
            ("count", serde_json::json!(0)),
            ("condition_hash", serde_json::json!("too-short")),
        ] {
            let mut broken = golden.clone();
            broken[field] = value;
            assert!(
                serde_json::from_value::<SeedTile>(broken).is_err(),
                "accepted a tile with mutated {field}"
            );
        }
    }

    #[test]
    fn redirect_hops_are_absent_at_zero_and_roundtrip_when_set() {
        let tile = tile();
        assert!(!serde_json::to_string(&tile)
            .unwrap()
            .contains("redirect_hops"));

        let hopped = tile
            .rekeyed_to(Uuid::from_u128(1), 3)
            .and_then(|tile| tile.rekeyed_to(Uuid::from_u128(2), 3))
            .and_then(|tile| tile.rekeyed_to(Uuid::from_u128(3), 3))
            .unwrap();
        assert_eq!(hopped.redirect_hops(), 3);
        let encoded = serde_json::to_string(&hopped).unwrap();
        assert!(encoded.contains(r#""redirect_hops":3"#));
        assert_eq!(serde_json::from_str::<SeedTile>(&encoded).unwrap(), hopped);
    }

    #[test]
    fn rekeyed_to_swaps_the_person_rides_s_chunk_verbatim_and_exhausts_at_the_cap() {
        let tile = tile();
        let survivor = Uuid::from_u128(0xdead_beef);
        let rekeyed = tile.rekeyed_to(survivor, 2).unwrap();
        assert_eq!(rekeyed.person_id(), survivor);
        assert_eq!(rekeyed.redirect_hops(), 1);
        assert_eq!(rekeyed.s_chunk_ms(), tile.s_chunk_ms());
        assert_eq!(rekeyed.team_id(), tile.team_id());
        assert_eq!(rekeyed.condition_hash(), tile.condition_hash());
        assert_eq!(rekeyed.day_idx(), tile.day_idx());
        assert_eq!(rekeyed.count(), tile.count());
        assert_eq!(rekeyed.run_id(), tile.run_id());
        assert_eq!(rekeyed.claim_epoch(), tile.claim_epoch());

        let at_cap = rekeyed.rekeyed_to(survivor, 2).unwrap();
        assert_eq!(at_cap.redirect_hops(), 2);
        assert!(at_cap.rekeyed_to(survivor, 2).is_none());
        assert!(tile.rekeyed_to(survivor, 0).is_none());
    }
}
