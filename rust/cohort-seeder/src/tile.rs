use std::num::NonZeroU32;

use cohort_core::filters::TeamId;
use serde::Serialize;
use uuid::Uuid;

use crate::domain::SeedDomain;
use crate::ids::{ClaimEpoch, ConditionHash, DayIdx, RunId};

const SCHEMA_VERSION: u32 = 1;
const TILE_KIND: &str = "behavioral_tile";

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SeedTile {
    schema_version: u32,
    kind: &'static str,
    team_id: i32,
    person_id: String,
    condition_hash: String,
    day_idx: DayIdx,
    count: u32,
    run_id: String,
    s_chunk_ms: i64,
    claim_epoch: i32,
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
            team_id: team_id.0,
            person_id: person_id.to_string(),
            condition_hash: condition_hash.to_string(),
            day_idx: domain.day(),
            count: count.get(),
            run_id: run_id.0.to_string(),
            s_chunk_ms: domain.s_chunk().0,
            claim_epoch: claim_epoch.0,
        }
    }

    pub fn partition_key(&self) -> String {
        format!("{}:{}", self.team_id, self.person_id)
    }

    pub const fn count(&self) -> u32 {
        self.count
    }

    pub fn person_id(&self) -> &str {
        &self.person_id
    }

    pub fn condition_hash(&self) -> &str {
        &self.condition_hash
    }
}

#[cfg(test)]
mod tests {
    use chrono_tz::UTC;
    use cohort_core::partitioner::{partition_for, COHORT_PARTITION_COUNT};

    use super::*;
    use crate::domain::Boundary;
    use crate::ids::SChunkMs;

    #[test]
    fn tile_wire_contract_and_partition_key_are_fixed_by_construction() {
        let person = Uuid::from_u128(0x0192_8aaa_bbbb_cccc_dddd_eeee_eeee_eeee);
        let boundary = Boundary::new(20 * 86_400_000, UTC);
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
    }
}
