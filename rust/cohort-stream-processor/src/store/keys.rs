//! Typed, partition-prefixed key encoders for the state column families.
//!
//! Keys are fixed-size big-endian so a partition's state is one contiguous `delete_range`.

use uuid::Uuid;

use super::rocks::StoreError;
use crate::stage1::key::{LeafStateKey, Stage1Key};

/// `[partition_id u16][team_id u64][leaf_state_key 16][person_id 16]`.
pub const STAGE1_KEY_LEN: usize = 2 + 8 + 16 + 16;
/// `[partition_id u16][team_id u64][person_id 16]`.
pub const PERSON_INDEX_KEY_LEN: usize = 2 + 8 + 16;
/// `[partition_id u16][team_id u64][cohort_id u64][person_id 16]`.
pub const STAGE2_KEY_LEN: usize = 2 + 8 + 8 + 16;
/// `[partition_id u16][team_id u64][old_person 16][merge_msg_partition u32][merge_msg_offset u64]`.
pub const MERGE_DRAIN_KEY_LEN: usize = 2 + 8 + 16 + 4 + 8;
/// `[partition_id u16][team_id u64][old_person 16]`.
pub const PENDING_TRANSFER_KEY_LEN: usize = 2 + 8 + 16;
/// `[partition_id u16][team_id u64][new_person 16][source_partition u32][source_offset u64]`.
pub const MERGE_APPLIED_KEY_LEN: usize = 2 + 8 + 16 + 4 + 8;
/// `[partition_id u16][team_id u64][person 16]`.
pub const TOMBSTONE_KEY_LEN: usize = 2 + 8 + 16;

/// `cf_person_index` key: a person's Stage 1 leaf states live under this prefix.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct PersonIndexKey {
    pub partition_id: u16,
    pub team_id: u64,
    pub person_id: Uuid,
}

/// `cf_stage2` key: per-`(cohort, person)` membership state.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct Stage2Key {
    pub partition_id: u16,
    pub team_id: u64,
    pub cohort_id: u64,
    pub person_id: Uuid,
}

/// `cf_merge_drains_applied` key: Phase 1 idempotence marker for one merge message.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct MergeDrainKey {
    pub partition_id: u16,
    pub team_id: u64,
    pub old_person: Uuid,
    /// Kafka partition of the merge message.
    pub merge_msg_partition: i32,
    /// Kafka offset of the merge message.
    pub merge_msg_offset: i64,
}

/// `cf_pending_transfers` key: Phase 1 outbox slot for a person's drained state.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct PendingTransferKey {
    pub partition_id: u16,
    pub team_id: u64,
    pub old_person: Uuid,
}

/// `cf_merge_applied` key: Phase 2 idempotence marker, keyed by the triggering merge message's
/// Kafka coordinates (not the transfer message's own) so duplicate transfer copies all short-circuit.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct MergeAppliedKey {
    pub partition_id: u16,
    pub team_id: u64,
    pub new_person: Uuid,
    /// Kafka partition of the triggering merge message.
    pub source_partition: i32,
    /// Kafka offset of the triggering merge message.
    pub source_offset: i64,
}

/// `cf_merge_tombstones` key: redirect marker for a merged-away person.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct TombstoneKey {
    pub partition_id: u16,
    pub team_id: u64,
    pub person: Uuid,
}

impl Stage1Key {
    pub fn encode(&self) -> [u8; STAGE1_KEY_LEN] {
        let mut out = [0u8; STAGE1_KEY_LEN];
        out[0..2].copy_from_slice(&self.partition_id.to_be_bytes());
        out[2..10].copy_from_slice(&self.team_id.to_be_bytes());
        out[10..26].copy_from_slice(&self.leaf_state_key.0);
        out[26..42].copy_from_slice(self.person_id.as_bytes());
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(bytes, STAGE1_KEY_LEN, "stage1")?;
        Ok(Self {
            partition_id: u16::from_be_bytes(array2(&bytes[0..2])),
            team_id: u64::from_be_bytes(array8(&bytes[2..10])),
            leaf_state_key: LeafStateKey(array16(&bytes[10..26])),
            person_id: Uuid::from_bytes(array16(&bytes[26..42])),
        })
    }
}

impl PersonIndexKey {
    pub fn encode(&self) -> [u8; PERSON_INDEX_KEY_LEN] {
        let mut out = [0u8; PERSON_INDEX_KEY_LEN];
        out[0..2].copy_from_slice(&self.partition_id.to_be_bytes());
        out[2..10].copy_from_slice(&self.team_id.to_be_bytes());
        out[10..26].copy_from_slice(self.person_id.as_bytes());
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(bytes, PERSON_INDEX_KEY_LEN, "person_index")?;
        Ok(Self {
            partition_id: u16::from_be_bytes(array2(&bytes[0..2])),
            team_id: u64::from_be_bytes(array8(&bytes[2..10])),
            person_id: Uuid::from_bytes(array16(&bytes[10..26])),
        })
    }
}

impl Stage2Key {
    pub fn encode(&self) -> [u8; STAGE2_KEY_LEN] {
        let mut out = [0u8; STAGE2_KEY_LEN];
        out[0..2].copy_from_slice(&self.partition_id.to_be_bytes());
        out[2..10].copy_from_slice(&self.team_id.to_be_bytes());
        out[10..18].copy_from_slice(&self.cohort_id.to_be_bytes());
        out[18..34].copy_from_slice(self.person_id.as_bytes());
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(bytes, STAGE2_KEY_LEN, "stage2")?;
        Ok(Self {
            partition_id: u16::from_be_bytes(array2(&bytes[0..2])),
            team_id: u64::from_be_bytes(array8(&bytes[2..10])),
            cohort_id: u64::from_be_bytes(array8(&bytes[10..18])),
            person_id: Uuid::from_bytes(array16(&bytes[18..34])),
        })
    }
}

impl MergeDrainKey {
    pub fn encode(&self) -> [u8; MERGE_DRAIN_KEY_LEN] {
        let mut out = [0u8; MERGE_DRAIN_KEY_LEN];
        out[0..2].copy_from_slice(&self.partition_id.to_be_bytes());
        out[2..10].copy_from_slice(&self.team_id.to_be_bytes());
        out[10..26].copy_from_slice(self.old_person.as_bytes());
        out[26..30].copy_from_slice(&(self.merge_msg_partition as u32).to_be_bytes());
        out[30..38].copy_from_slice(&(self.merge_msg_offset as u64).to_be_bytes());
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(bytes, MERGE_DRAIN_KEY_LEN, "merge_drain")?;
        Ok(Self {
            partition_id: u16::from_be_bytes(array2(&bytes[0..2])),
            team_id: u64::from_be_bytes(array8(&bytes[2..10])),
            old_person: Uuid::from_bytes(array16(&bytes[10..26])),
            merge_msg_partition: u32::from_be_bytes(array4(&bytes[26..30])) as i32,
            merge_msg_offset: u64::from_be_bytes(array8(&bytes[30..38])) as i64,
        })
    }
}

impl PendingTransferKey {
    pub fn encode(&self) -> [u8; PENDING_TRANSFER_KEY_LEN] {
        let mut out = [0u8; PENDING_TRANSFER_KEY_LEN];
        out[0..2].copy_from_slice(&self.partition_id.to_be_bytes());
        out[2..10].copy_from_slice(&self.team_id.to_be_bytes());
        out[10..26].copy_from_slice(self.old_person.as_bytes());
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(bytes, PENDING_TRANSFER_KEY_LEN, "pending_transfer")?;
        Ok(Self {
            partition_id: u16::from_be_bytes(array2(&bytes[0..2])),
            team_id: u64::from_be_bytes(array8(&bytes[2..10])),
            old_person: Uuid::from_bytes(array16(&bytes[10..26])),
        })
    }
}

impl MergeAppliedKey {
    pub fn encode(&self) -> [u8; MERGE_APPLIED_KEY_LEN] {
        let mut out = [0u8; MERGE_APPLIED_KEY_LEN];
        out[0..2].copy_from_slice(&self.partition_id.to_be_bytes());
        out[2..10].copy_from_slice(&self.team_id.to_be_bytes());
        out[10..26].copy_from_slice(self.new_person.as_bytes());
        out[26..30].copy_from_slice(&(self.source_partition as u32).to_be_bytes());
        out[30..38].copy_from_slice(&(self.source_offset as u64).to_be_bytes());
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(bytes, MERGE_APPLIED_KEY_LEN, "merge_applied")?;
        Ok(Self {
            partition_id: u16::from_be_bytes(array2(&bytes[0..2])),
            team_id: u64::from_be_bytes(array8(&bytes[2..10])),
            new_person: Uuid::from_bytes(array16(&bytes[10..26])),
            source_partition: u32::from_be_bytes(array4(&bytes[26..30])) as i32,
            source_offset: u64::from_be_bytes(array8(&bytes[30..38])) as i64,
        })
    }
}

impl TombstoneKey {
    pub fn encode(&self) -> [u8; TOMBSTONE_KEY_LEN] {
        let mut out = [0u8; TOMBSTONE_KEY_LEN];
        out[0..2].copy_from_slice(&self.partition_id.to_be_bytes());
        out[2..10].copy_from_slice(&self.team_id.to_be_bytes());
        out[10..26].copy_from_slice(self.person.as_bytes());
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(bytes, TOMBSTONE_KEY_LEN, "tombstone")?;
        Ok(Self {
            partition_id: u16::from_be_bytes(array2(&bytes[0..2])),
            team_id: u64::from_be_bytes(array8(&bytes[2..10])),
            person: Uuid::from_bytes(array16(&bytes[10..26])),
        })
    }
}

pub fn partition_prefix(partition_id: u16) -> [u8; 2] {
    partition_id.to_be_bytes()
}

/// Half-open `[start, end)` byte range covering exactly one partition's keys, for `delete_range`.
pub fn partition_range(partition_id: u16) -> (Vec<u8>, Vec<u8>) {
    let start = partition_id.to_be_bytes().to_vec();
    let end = match partition_id.checked_add(1) {
        Some(next) => next.to_be_bytes().to_vec(),
        None => vec![0xFFu8; STAGE1_KEY_LEN + 1],
    };
    (start, end)
}

fn check_len(bytes: &[u8], expected: usize, kind: &'static str) -> Result<(), StoreError> {
    if bytes.len() == expected {
        Ok(())
    } else {
        Err(StoreError::KeyDecode {
            kind,
            expected,
            actual: bytes.len(),
        })
    }
}

fn array2(s: &[u8]) -> [u8; 2] {
    let mut a = [0u8; 2];
    a.copy_from_slice(s);
    a
}
fn array4(s: &[u8]) -> [u8; 4] {
    let mut a = [0u8; 4];
    a.copy_from_slice(s);
    a
}
fn array8(s: &[u8]) -> [u8; 8] {
    let mut a = [0u8; 8];
    a.copy_from_slice(s);
    a
}
fn array16(s: &[u8]) -> [u8; 16] {
    let mut a = [0u8; 16];
    a.copy_from_slice(s);
    a
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lsk(b: u8) -> LeafStateKey {
        LeafStateKey([b; 16])
    }

    fn person(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn stage1(partition_id: u16, team_id: u64) -> Stage1Key {
        Stage1Key {
            partition_id,
            team_id,
            leaf_state_key: lsk(0xAB),
            person_id: person(1),
        }
    }

    #[test]
    fn encoded_lengths_are_exact() {
        assert_eq!(stage1(1, 2).encode().len(), 42);
        assert_eq!(STAGE1_KEY_LEN, 42);
        assert_eq!(
            PersonIndexKey {
                partition_id: 1,
                team_id: 2,
                person_id: person(3),
            }
            .encode()
            .len(),
            26,
        );
        assert_eq!(PERSON_INDEX_KEY_LEN, 26);
        assert_eq!(
            Stage2Key {
                partition_id: 1,
                team_id: 2,
                cohort_id: 3,
                person_id: person(4),
            }
            .encode()
            .len(),
            34,
        );
        assert_eq!(STAGE2_KEY_LEN, 34);
    }

    #[test]
    fn stage1_round_trips() {
        let key = Stage1Key {
            partition_id: 0xBEEF,
            team_id: 0x0123_4567_89AB_CDEF,
            leaf_state_key: lsk(0x5A),
            person_id: person(0xDEAD_BEEF),
        };
        assert_eq!(Stage1Key::decode(&key.encode()).unwrap(), key);
    }

    #[test]
    fn person_index_round_trips() {
        let key = PersonIndexKey {
            partition_id: 7,
            team_id: 42,
            person_id: person(0xFEED),
        };
        assert_eq!(PersonIndexKey::decode(&key.encode()).unwrap(), key);
    }

    #[test]
    fn stage2_round_trips() {
        let key = Stage2Key {
            partition_id: 7,
            team_id: 42,
            cohort_id: 99,
            person_id: person(0xC0FFEE),
        };
        assert_eq!(Stage2Key::decode(&key.encode()).unwrap(), key);
    }

    #[test]
    fn decode_rejects_wrong_length() {
        let err = Stage1Key::decode(&[0u8; 41]).unwrap_err();
        assert!(
            matches!(
                err,
                StoreError::KeyDecode {
                    kind: "stage1",
                    expected: 42,
                    actual: 41
                }
            ),
            "unexpected error: {err:?}",
        );
    }

    #[test]
    fn big_endian_prefix_orders_by_partition_then_team() {
        assert!(stage1(1, u64::MAX).encode() < stage1(2, 0).encode());
        assert!(stage1(1, 0).encode() < stage1(256, 0).encode());
        assert!(stage1(5, 1).encode() < stage1(5, 2).encode());
        assert!(stage1(5, 1).encode() < stage1(5, u64::from(u32::MAX)).encode());
    }

    #[test]
    fn partition_range_is_the_two_byte_successor() {
        let (start, end) = partition_range(0);
        assert_eq!(start, vec![0x00, 0x00]);
        assert_eq!(end, vec![0x00, 0x01]);

        let (start, end) = partition_range(255);
        assert_eq!(start, vec![0x00, 0xFF]);
        assert_eq!(end, vec![0x01, 0x00]);
    }

    #[test]
    fn partition_range_brackets_every_key_in_the_partition() {
        for p in [0u16, 5, 256, u16::MAX - 1, u16::MAX] {
            let (start, end) = partition_range(p);
            let max_key = Stage1Key {
                partition_id: p,
                team_id: u64::MAX,
                leaf_state_key: lsk(0xFF),
                person_id: person(u128::MAX),
            }
            .encode();
            let min_key = Stage1Key {
                partition_id: p,
                team_id: 0,
                leaf_state_key: lsk(0x00),
                person_id: person(0),
            }
            .encode();
            assert!(start.as_slice() <= min_key.as_slice(), "start>min at p={p}");
            assert!(max_key.as_slice() < end.as_slice(), "max>=end at p={p}");
            if let Some(next) = p.checked_add(1) {
                let next_min = stage1(next, 0).encode();
                assert!(
                    end.as_slice() <= next_min.as_slice(),
                    "end>next_min at p={p}"
                );
            }
        }
    }

    #[test]
    fn max_partition_sentinel_exceeds_the_all_ones_key() {
        let (_start, end) = partition_range(u16::MAX);
        assert!([0xFFu8; STAGE1_KEY_LEN].as_slice() < end.as_slice());
    }

    #[test]
    fn merge_key_lengths_are_exact_and_within_the_stage1_bound() {
        assert_eq!(MERGE_DRAIN_KEY_LEN, 38);
        assert_eq!(PENDING_TRANSFER_KEY_LEN, 26);
        assert_eq!(MERGE_APPLIED_KEY_LEN, 38);
        assert_eq!(TOMBSTONE_KEY_LEN, 26);
        for len in [
            MERGE_DRAIN_KEY_LEN,
            PENDING_TRANSFER_KEY_LEN,
            MERGE_APPLIED_KEY_LEN,
            TOMBSTONE_KEY_LEN,
        ] {
            assert!(len <= STAGE1_KEY_LEN, "{len} exceeds STAGE1_KEY_LEN");
        }

        let drain = MergeDrainKey {
            partition_id: 1,
            team_id: 2,
            old_person: person(3),
            merge_msg_partition: 4,
            merge_msg_offset: 5,
        };
        assert_eq!(drain.encode().len(), MERGE_DRAIN_KEY_LEN);
        assert_eq!(
            PendingTransferKey {
                partition_id: 1,
                team_id: 2,
                old_person: person(3),
            }
            .encode()
            .len(),
            PENDING_TRANSFER_KEY_LEN,
        );
        assert_eq!(
            MergeAppliedKey {
                partition_id: 1,
                team_id: 2,
                new_person: person(3),
                source_partition: 4,
                source_offset: 5,
            }
            .encode()
            .len(),
            MERGE_APPLIED_KEY_LEN,
        );
        assert_eq!(
            TombstoneKey {
                partition_id: 1,
                team_id: 2,
                person: person(3),
            }
            .encode()
            .len(),
            TOMBSTONE_KEY_LEN,
        );
    }

    #[test]
    fn merge_drain_key_round_trips_including_kafka_coords() {
        let key = MergeDrainKey {
            partition_id: 0xBEEF,
            team_id: 0x0123_4567_89AB_CDEF,
            old_person: person(0xDEAD_BEEF),
            merge_msg_partition: 63,
            merge_msg_offset: 0x7FFF_FFFF_FFFF_FFFE,
        };
        assert_eq!(MergeDrainKey::decode(&key.encode()).unwrap(), key);
    }

    #[test]
    fn merge_applied_key_round_trips_including_kafka_coords() {
        let key = MergeAppliedKey {
            partition_id: 7,
            team_id: 42,
            new_person: person(0xC0FFEE),
            source_partition: 17,
            source_offset: 12345,
        };
        assert_eq!(MergeAppliedKey::decode(&key.encode()).unwrap(), key);
    }

    #[test]
    fn pending_transfer_and_tombstone_keys_round_trip() {
        let pending = PendingTransferKey {
            partition_id: 9,
            team_id: 100,
            old_person: person(0xFEED),
        };
        assert_eq!(
            PendingTransferKey::decode(&pending.encode()).unwrap(),
            pending
        );

        let tombstone = TombstoneKey {
            partition_id: 9,
            team_id: 100,
            person: person(0xFACE),
        };
        assert_eq!(
            TombstoneKey::decode(&tombstone.encode()).unwrap(),
            tombstone
        );
    }

    #[test]
    fn merge_drain_decode_rejects_wrong_length() {
        let err = MergeDrainKey::decode(&[0u8; 37]).unwrap_err();
        assert!(
            matches!(
                err,
                StoreError::KeyDecode {
                    kind: "merge_drain",
                    expected: 38,
                    actual: 37
                }
            ),
            "unexpected error: {err:?}",
        );
    }

    #[test]
    fn merge_keys_share_the_partition_prefix_so_delete_range_reclaims_them() {
        for p in [0u16, 5, 256, u16::MAX] {
            let (start, end) = partition_range(p);
            let drain = MergeDrainKey {
                partition_id: p,
                team_id: u64::MAX,
                old_person: person(u128::MAX),
                merge_msg_partition: i32::MAX,
                merge_msg_offset: i64::MAX,
            }
            .encode();
            let tombstone = TombstoneKey {
                partition_id: p,
                team_id: 0,
                person: person(0),
            }
            .encode();
            assert!(
                start.as_slice() <= tombstone.as_slice(),
                "start>min at p={p}"
            );
            assert!(drain.as_slice() < end.as_slice(), "max>=end at p={p}");
        }
    }
}
