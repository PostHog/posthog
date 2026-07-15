//! Domain layer: `SeedTile`, the wire-frozen produced unit — typed fields with serialize helpers that
//! emit exactly today's JSON primitives. Depends on `ids`, `window`, and `cohort-core`.

use std::num::NonZeroU32;

use cohort_core::filters::TeamId;
use serde::{Serialize, Serializer};
use uuid::Uuid;

use super::ids::{ClaimEpoch, ConditionHash, DayIdx, RunId, SChunkMs};
use super::window::SeedDomain;

const SCHEMA_VERSION: u32 = 1;
const TILE_KIND: &str = "behavioral_tile";

/// The wire tile produced to `cohort_stream_seed_events`. Fields are typed, but the `serialize_with`
/// helpers emit exactly the primitives the consumer froze; the golden test in this module is the
/// byte-level regression gate.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SeedTile {
    schema_version: u32,
    kind: &'static str,
    #[serde(serialize_with = "serialize_team_id")]
    team_id: TeamId,
    #[serde(serialize_with = "serialize_uuid")]
    person_id: Uuid,
    #[serde(serialize_with = "serialize_condition_hash")]
    condition_hash: ConditionHash,
    day_idx: DayIdx,
    #[serde(serialize_with = "serialize_count")]
    count: NonZeroU32,
    #[serde(serialize_with = "serialize_run_id")]
    run_id: RunId,
    #[serde(serialize_with = "serialize_s_chunk_ms")]
    s_chunk_ms: SChunkMs,
    #[serde(serialize_with = "serialize_claim_epoch")]
    claim_epoch: ClaimEpoch,
}

impl SeedTile {
    pub(crate) fn new(
        team_id: TeamId,
        person_id: Uuid,
        condition_hash: ConditionHash,
        count: NonZeroU32,
        domain: &SeedDomain,
        run_id: RunId,
        claim_epoch: ClaimEpoch,
    ) -> Self {
        Self {
            schema_version: SCHEMA_VERSION,
            kind: TILE_KIND,
            team_id,
            person_id,
            condition_hash,
            day_idx: domain.day(),
            count,
            run_id,
            s_chunk_ms: domain.s_chunk(),
            claim_epoch,
        }
    }

    pub fn partition_key(&self) -> String {
        format!("{}:{}", self.team_id.0, self.person_id)
    }

    pub const fn count(&self) -> u32 {
        self.count.get()
    }

    pub const fn person_id(&self) -> Uuid {
        self.person_id
    }

    pub const fn condition_hash(&self) -> ConditionHash {
        self.condition_hash
    }
}

fn serialize_team_id<S: Serializer>(value: &TeamId, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_i32(value.0)
}

fn serialize_uuid<S: Serializer>(value: &Uuid, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_str(&value.to_string())
}

fn serialize_condition_hash<S: Serializer>(
    value: &ConditionHash,
    serializer: S,
) -> Result<S::Ok, S::Error> {
    serializer.serialize_str(value.as_str())
}

fn serialize_count<S: Serializer>(value: &NonZeroU32, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_u32(value.get())
}

fn serialize_run_id<S: Serializer>(value: &RunId, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_str(&value.0.to_string())
}

fn serialize_s_chunk_ms<S: Serializer>(value: &SChunkMs, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_i64(value.0)
}

fn serialize_claim_epoch<S: Serializer>(
    value: &ClaimEpoch,
    serializer: S,
) -> Result<S::Ok, S::Error> {
    serializer.serialize_i32(value.0)
}

#[cfg(test)]
mod tests {
    use chrono_tz::UTC;
    use cohort_core::partitioner::{partition_for, COHORT_PARTITION_COUNT};

    use super::*;
    use crate::domain::{Boundary, SChunkMs, UtcMillis};

    #[test]
    fn tile_wire_contract_and_partition_key_are_fixed_by_construction() {
        let person = Uuid::from_u128(0x0192_8aaa_bbbb_cccc_dddd_eeee_eeee_eeee);
        let boundary = Boundary::new(UtcMillis::new(20 * 86_400_000), UTC);
        let domain = SeedDomain::new(19, boundary, UTC, SChunkMs(1_700_000_000_000)).unwrap();
        let tile = SeedTile::new(
            TeamId(2),
            person,
            ConditionHash::parse("0123456789abcdef").unwrap(),
            NonZeroU32::new(3).unwrap(),
            &domain,
            RunId(Uuid::nil()),
            ClaimEpoch(7),
        );

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
}
