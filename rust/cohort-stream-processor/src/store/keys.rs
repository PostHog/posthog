//! Typed, partition-prefixed key encoders for the non-state column families.
//!
//! Keys are fixed-size big-endian so a partition's state is one contiguous `delete_range`. The
//! person-clustered state keys live in [`super::keyspace`]; these are the merge-protocol and Stage 2
//! keys.

use uuid::Uuid;

use super::keyspace::BEHAVIORAL_KEY_LEN;
use super::rocks::StoreError;

/// `[partition_id u16][team_id u64][cohort_id u64][person_id 16]`.
pub const STAGE2_KEY_LEN: usize = 2 + 8 + 8 + 16;
/// `[partition_id u16][team_id u64][cohort_id u64]`.
pub const STAGE2_COHORT_PREFIX_LEN: usize = 2 + 8 + 8;
/// `[partition_id u16][0xFF; 32][dirty discriminant][team_id u64][cohort_id u64]`.
pub const STAGE2_DIRTY_COHORT_PREFIX_LEN: usize = STAGE2_KEY_LEN + 1 + 8 + 8;
/// `[dirty cohort prefix][person_id 16]`.
pub const STAGE2_DIRTY_KEY_LEN: usize = STAGE2_DIRTY_COHORT_PREFIX_LEN + 16;
const STAGE2_DIRTY_DISCRIMINANT: u8 = 1;
/// `[partition_id u16][0xFF; 32][transferred-register discriminant][team_id u64][person_id 16]`.
pub const STAGE2_TRANSFERRED_REGISTER_PERSON_PREFIX_LEN: usize = STAGE2_KEY_LEN + 1 + 8 + 16;
/// `[transferred-register person prefix][cohort_id u64]`.
pub const STAGE2_TRANSFERRED_REGISTER_KEY_LEN: usize =
    STAGE2_TRANSFERRED_REGISTER_PERSON_PREFIX_LEN + 8;
const STAGE2_TRANSFERRED_REGISTER_DISCRIMINANT: u8 = 2;
/// `[partition_id u16][team_id u64][old_person 16][merge_msg_partition u32][merge_msg_offset u64]`.
pub const MERGE_DRAIN_KEY_LEN: usize = 2 + 8 + 16 + 4 + 8;
/// `[partition_id u16][team_id u64][old_person 16]`.
pub const PENDING_TRANSFER_KEY_LEN: usize = 2 + 8 + 16;
/// `[partition_id u16][team_id u64][new_person 16][source_partition u32][source_offset u64]`.
pub const MERGE_APPLIED_KEY_LEN: usize = 2 + 8 + 16 + 4 + 8;
/// `[partition_id u16][team_id u64][person 16]`.
pub const TOMBSTONE_KEY_LEN: usize = 2 + 8 + 16;

/// `cf_stage2` key: per-`(cohort, person)` membership state.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct Stage2Key {
    pub partition_id: u16,
    pub team_id: u64,
    pub cohort_id: u64,
    pub person_id: Uuid,
}

/// Prefix selecting one cohort's membership rows in one partition.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct Stage2CohortPrefix {
    pub partition_id: u16,
    pub team_id: u64,
    pub cohort_id: u64,
}

/// Coalescing mutation marker for one Stage 2 person row.
///
/// Dirty keys sort after every valid [`Stage2Key`] in their partition. Their namespace starts with
/// the partition's maximum 34-byte Stage 2 row, followed by a discriminant below `0xFF`; this keeps
/// them inside the partition range without colliding with a row, including in partition `u16::MAX`.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct Stage2DirtyKey(Stage2Key);

/// Prefix selecting one cohort's dirty-person markers.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct Stage2DirtyPrefix(Stage2CohortPrefix);

/// Catalog-independent inventory for a register received through the merge protocol.
///
/// The primary Stage 2 layout is cohort-first, so a merge drain cannot enumerate one person's rows
/// when its local catalog has not learned the cohort yet. This person-first metadata key closes that
/// gap. Its value carries the source transfer kind and bit plus the exact primary bytes they
/// describe; the primary row remains the receiver's current materialized membership state.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct Stage2TransferredRegisterKey(Stage2Key);

/// Prefix selecting one person's transferred-register inventory entries.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct Stage2TransferredRegisterPersonPrefix {
    pub partition_id: u16,
    pub team_id: u64,
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

    pub fn cohort_prefix(&self) -> Stage2CohortPrefix {
        Stage2CohortPrefix {
            partition_id: self.partition_id,
            team_id: self.team_id,
            cohort_id: self.cohort_id,
        }
    }
}

impl Stage2CohortPrefix {
    pub fn encode(&self) -> [u8; STAGE2_COHORT_PREFIX_LEN] {
        let mut out = [0u8; STAGE2_COHORT_PREFIX_LEN];
        out[0..2].copy_from_slice(&self.partition_id.to_be_bytes());
        out[2..10].copy_from_slice(&self.team_id.to_be_bytes());
        out[10..18].copy_from_slice(&self.cohort_id.to_be_bytes());
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(bytes, STAGE2_COHORT_PREFIX_LEN, "stage2 cohort prefix")?;
        Ok(Self {
            partition_id: u16::from_be_bytes(array2(&bytes[0..2])),
            team_id: u64::from_be_bytes(array8(&bytes[2..10])),
            cohort_id: u64::from_be_bytes(array8(&bytes[10..18])),
        })
    }

    /// Half-open byte range containing the matching [`Stage2Key`] values.
    pub fn range(&self) -> (Vec<u8>, Vec<u8>) {
        let start = self.encode().to_vec();
        let mut end = start.clone();
        for byte in end.iter_mut().rev() {
            if let Some(next) = byte.checked_add(1) {
                *byte = next;
                return (start, end);
            }
            *byte = 0;
        }

        // The maximum valid Stage2 key is 34 bytes of 0xFF, so the same bytes plus one remain a
        // strict exclusive upper bound when the 18-byte prefix itself has no successor.
        (start, vec![0xFF; STAGE2_KEY_LEN + 1])
    }

    pub const fn dirty_prefix(self) -> Stage2DirtyPrefix {
        Stage2DirtyPrefix(self)
    }
}

impl Stage2DirtyKey {
    pub const fn new(key: Stage2Key) -> Self {
        Self(key)
    }

    pub const fn stage2_key(self) -> Stage2Key {
        self.0
    }

    pub fn encode(self) -> [u8; STAGE2_DIRTY_KEY_LEN] {
        let mut out = [0u8; STAGE2_DIRTY_KEY_LEN];
        out[0..2].copy_from_slice(&self.0.partition_id.to_be_bytes());
        out[2..STAGE2_KEY_LEN].fill(0xFF);
        out[STAGE2_KEY_LEN] = STAGE2_DIRTY_DISCRIMINANT;
        out[(STAGE2_KEY_LEN + 1)..(STAGE2_KEY_LEN + 9)]
            .copy_from_slice(&self.0.team_id.to_be_bytes());
        out[(STAGE2_KEY_LEN + 9)..STAGE2_DIRTY_COHORT_PREFIX_LEN]
            .copy_from_slice(&self.0.cohort_id.to_be_bytes());
        out[STAGE2_DIRTY_COHORT_PREFIX_LEN..].copy_from_slice(self.0.person_id.as_bytes());
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(bytes, STAGE2_DIRTY_KEY_LEN, "stage2 dirty")?;
        if bytes[2..STAGE2_KEY_LEN].iter().any(|byte| *byte != 0xFF)
            || bytes[STAGE2_KEY_LEN] != STAGE2_DIRTY_DISCRIMINANT
        {
            return Err(StoreError::UnknownKey {
                kind: "stage2 dirty",
            });
        }
        Ok(Self(Stage2Key {
            partition_id: u16::from_be_bytes(array2(&bytes[0..2])),
            team_id: u64::from_be_bytes(array8(&bytes[(STAGE2_KEY_LEN + 1)..(STAGE2_KEY_LEN + 9)])),
            cohort_id: u64::from_be_bytes(array8(
                &bytes[(STAGE2_KEY_LEN + 9)..STAGE2_DIRTY_COHORT_PREFIX_LEN],
            )),
            person_id: Uuid::from_bytes(array16(&bytes[STAGE2_DIRTY_COHORT_PREFIX_LEN..])),
        }))
    }
}

impl Stage2DirtyPrefix {
    pub fn encode(self) -> [u8; STAGE2_DIRTY_COHORT_PREFIX_LEN] {
        let key = Stage2Key {
            partition_id: self.0.partition_id,
            team_id: self.0.team_id,
            cohort_id: self.0.cohort_id,
            person_id: Uuid::nil(),
        };
        let encoded = Stage2DirtyKey::new(key).encode();
        let mut out = [0u8; STAGE2_DIRTY_COHORT_PREFIX_LEN];
        out.copy_from_slice(&encoded[..STAGE2_DIRTY_COHORT_PREFIX_LEN]);
        out
    }

    pub fn range(self) -> (Vec<u8>, Vec<u8>) {
        let start = self.encode().to_vec();
        let mut end = start.clone();
        for byte in end.iter_mut().rev() {
            if let Some(next) = byte.checked_add(1) {
                *byte = next;
                return (start, end);
            }
            *byte = 0;
        }
        unreachable!("the dirty discriminant has a lexicographic successor")
    }
}

impl From<Stage2Key> for Stage2DirtyKey {
    fn from(value: Stage2Key) -> Self {
        Self::new(value)
    }
}

impl Stage2TransferredRegisterKey {
    pub const fn new(key: Stage2Key) -> Self {
        Self(key)
    }

    pub const fn stage2_key(self) -> Stage2Key {
        self.0
    }

    pub fn encode(self) -> [u8; STAGE2_TRANSFERRED_REGISTER_KEY_LEN] {
        let mut out = [0u8; STAGE2_TRANSFERRED_REGISTER_KEY_LEN];
        out[0..2].copy_from_slice(&self.0.partition_id.to_be_bytes());
        out[2..STAGE2_KEY_LEN].fill(0xFF);
        out[STAGE2_KEY_LEN] = STAGE2_TRANSFERRED_REGISTER_DISCRIMINANT;
        out[(STAGE2_KEY_LEN + 1)..(STAGE2_KEY_LEN + 9)]
            .copy_from_slice(&self.0.team_id.to_be_bytes());
        out[(STAGE2_KEY_LEN + 9)..STAGE2_TRANSFERRED_REGISTER_PERSON_PREFIX_LEN]
            .copy_from_slice(self.0.person_id.as_bytes());
        out[STAGE2_TRANSFERRED_REGISTER_PERSON_PREFIX_LEN..]
            .copy_from_slice(&self.0.cohort_id.to_be_bytes());
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(
            bytes,
            STAGE2_TRANSFERRED_REGISTER_KEY_LEN,
            "stage2 transferred register",
        )?;
        if bytes[2..STAGE2_KEY_LEN].iter().any(|byte| *byte != 0xFF)
            || bytes[STAGE2_KEY_LEN] != STAGE2_TRANSFERRED_REGISTER_DISCRIMINANT
        {
            return Err(StoreError::UnknownKey {
                kind: "stage2 transferred register",
            });
        }
        Ok(Self(Stage2Key {
            partition_id: u16::from_be_bytes(array2(&bytes[0..2])),
            team_id: u64::from_be_bytes(array8(&bytes[(STAGE2_KEY_LEN + 1)..(STAGE2_KEY_LEN + 9)])),
            cohort_id: u64::from_be_bytes(array8(
                &bytes[STAGE2_TRANSFERRED_REGISTER_PERSON_PREFIX_LEN..],
            )),
            person_id: Uuid::from_bytes(array16(
                &bytes[(STAGE2_KEY_LEN + 9)..STAGE2_TRANSFERRED_REGISTER_PERSON_PREFIX_LEN],
            )),
        }))
    }

    pub const fn person_prefix(self) -> Stage2TransferredRegisterPersonPrefix {
        Stage2TransferredRegisterPersonPrefix {
            partition_id: self.0.partition_id,
            team_id: self.0.team_id,
            person_id: self.0.person_id,
        }
    }
}

impl Stage2TransferredRegisterPersonPrefix {
    pub const fn new(partition_id: u16, team_id: u64, person_id: Uuid) -> Self {
        Self {
            partition_id,
            team_id,
            person_id,
        }
    }

    pub fn encode(self) -> [u8; STAGE2_TRANSFERRED_REGISTER_PERSON_PREFIX_LEN] {
        let key = Stage2Key {
            partition_id: self.partition_id,
            team_id: self.team_id,
            cohort_id: 0,
            person_id: self.person_id,
        };
        let encoded = Stage2TransferredRegisterKey::new(key).encode();
        let mut out = [0u8; STAGE2_TRANSFERRED_REGISTER_PERSON_PREFIX_LEN];
        out.copy_from_slice(&encoded[..STAGE2_TRANSFERRED_REGISTER_PERSON_PREFIX_LEN]);
        out
    }

    pub fn range(self) -> (Vec<u8>, Vec<u8>) {
        let start = self.encode().to_vec();
        let mut end = start.clone();
        for byte in end.iter_mut().rev() {
            if let Some(next) = byte.checked_add(1) {
                *byte = next;
                return (start, end);
            }
            *byte = 0;
        }
        unreachable!("the transferred-register discriminant has a lexicographic successor")
    }
}

impl From<Stage2Key> for Stage2TransferredRegisterKey {
    fn from(value: Stage2Key) -> Self {
        Self::new(value)
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
        None => vec![0xFFu8; BEHAVIORAL_KEY_LEN + 1],
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
    use proptest::prelude::*;

    use super::*;
    use crate::stage1::key::LeafStateKey;
    use crate::store::keyspace::BehavioralKey;

    fn person(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn behavioral(partition_id: u16, team_id: u64) -> BehavioralKey {
        BehavioralKey::new(partition_id, team_id, person(1), LeafStateKey([0xAB; 16]))
    }

    #[test]
    fn encoded_lengths_are_exact() {
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
        assert_eq!(
            Stage2CohortPrefix {
                partition_id: 1,
                team_id: 2,
                cohort_id: 3,
            }
            .encode()
            .len(),
            18,
        );
        assert_eq!(STAGE2_COHORT_PREFIX_LEN, 18);
        assert_eq!(
            Stage2DirtyKey::new(Stage2Key {
                partition_id: 1,
                team_id: 2,
                cohort_id: 3,
                person_id: person(4),
            })
            .encode()
            .len(),
            STAGE2_DIRTY_KEY_LEN,
        );
        assert_eq!(STAGE2_DIRTY_KEY_LEN, 67);
        assert_eq!(STAGE2_TRANSFERRED_REGISTER_PERSON_PREFIX_LEN, 59);
        assert_eq!(
            Stage2TransferredRegisterKey::new(Stage2Key {
                partition_id: 1,
                team_id: 2,
                cohort_id: 3,
                person_id: person(4),
            })
            .encode()
            .len(),
            STAGE2_TRANSFERRED_REGISTER_KEY_LEN,
        );
        assert_eq!(STAGE2_TRANSFERRED_REGISTER_KEY_LEN, 67);
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
    fn stage2_decode_rejects_wrong_length() {
        let err = Stage2Key::decode(&[0u8; 33]).unwrap_err();
        assert!(
            matches!(
                err,
                StoreError::KeyDecode {
                    kind: "stage2",
                    expected: 34,
                    actual: 33
                }
            ),
            "unexpected error: {err:?}",
        );
    }

    #[test]
    fn stage2_dirty_key_round_trips_without_colliding_with_a_person_row() {
        let row = Stage2Key {
            partition_id: 7,
            team_id: 42,
            cohort_id: 99,
            person_id: person(123),
        };
        let dirty = Stage2DirtyKey::new(row);
        let encoded = dirty.encode();
        assert_eq!(Stage2DirtyKey::decode(&encoded).unwrap(), dirty);
        assert!(Stage2Key::decode(&encoded).is_err());

        let mut wrong_discriminant = encoded;
        wrong_discriminant[STAGE2_KEY_LEN] = 2;
        assert!(Stage2DirtyKey::decode(&wrong_discriminant).is_err());
    }

    #[test]
    fn stage2_dirty_namespace_sorts_after_rows_and_inside_its_partition() {
        for partition_id in [0, 7, u16::MAX] {
            let row = Stage2Key {
                partition_id,
                team_id: u64::MAX,
                cohort_id: u64::MAX,
                person_id: person(u128::MAX),
            };
            let dirty = Stage2DirtyKey::new(row).encode();
            assert!(row.encode().as_slice() < dirty.as_slice());
            let (partition_start, partition_end) = partition_range(partition_id);
            assert!(partition_start.as_slice() <= dirty.as_slice());
            assert!(dirty.as_slice() < partition_end.as_slice());
        }
    }

    #[test]
    fn transferred_register_key_round_trips_and_groups_by_person() {
        let row = Stage2Key {
            partition_id: 7,
            team_id: 42,
            cohort_id: 99,
            person_id: person(123),
        };
        let inventory = Stage2TransferredRegisterKey::new(row);
        assert_eq!(
            Stage2TransferredRegisterKey::decode(&inventory.encode()).unwrap(),
            inventory,
        );
        assert_eq!(inventory.stage2_key(), row);
        assert_eq!(
            inventory.person_prefix(),
            Stage2TransferredRegisterPersonPrefix::new(7, 42, person(123)),
        );
        assert!(Stage2Key::decode(&inventory.encode()).is_err());
        assert!(Stage2DirtyKey::decode(&inventory.encode()).is_err());
    }

    #[test]
    fn transferred_register_namespace_sorts_after_dirty_and_inside_partition() {
        for partition_id in [0, 7, u16::MAX] {
            let row = Stage2Key {
                partition_id,
                team_id: u64::MAX,
                cohort_id: u64::MAX,
                person_id: person(u128::MAX),
            };
            let dirty = Stage2DirtyKey::new(row).encode();
            let inventory = Stage2TransferredRegisterKey::new(row).encode();
            assert!(row.encode().as_slice() < dirty.as_slice());
            assert!(dirty.as_slice() < inventory.as_slice());
            let (partition_start, partition_end) = partition_range(partition_id);
            assert!(partition_start.as_slice() <= inventory.as_slice());
            assert!(inventory.as_slice() < partition_end.as_slice());
        }
    }

    #[test]
    fn transferred_register_person_prefix_selects_all_and_only_that_person() {
        let prefix = Stage2TransferredRegisterPersonPrefix::new(7, 42, person(9));
        let (start, end) = prefix.range();
        for cohort_id in [0, 1, u64::MAX] {
            let encoded = Stage2TransferredRegisterKey::new(Stage2Key {
                partition_id: 7,
                team_id: 42,
                cohort_id,
                person_id: person(9),
            })
            .encode();
            assert!(start.as_slice() <= encoded.as_slice());
            assert!(encoded.as_slice() < end.as_slice());
        }
        for foreign in [
            Stage2Key {
                partition_id: 8,
                team_id: 42,
                cohort_id: 1,
                person_id: person(9),
            },
            Stage2Key {
                partition_id: 7,
                team_id: 43,
                cohort_id: 1,
                person_id: person(9),
            },
            Stage2Key {
                partition_id: 7,
                team_id: 42,
                cohort_id: 1,
                person_id: person(10),
            },
        ] {
            let encoded = Stage2TransferredRegisterKey::new(foreign).encode();
            assert!(encoded.as_slice() < start.as_slice() || encoded.as_slice() >= end.as_slice());
        }
    }

    #[test]
    fn stage2_dirty_prefix_selects_exactly_one_cohort() {
        let prefix = Stage2CohortPrefix {
            partition_id: 7,
            team_id: 42,
            cohort_id: 99,
        }
        .dirty_prefix();
        let (start, end) = prefix.range();
        for person_id in [0, 1, u128::MAX] {
            let encoded = Stage2DirtyKey::new(Stage2Key {
                partition_id: 7,
                team_id: 42,
                cohort_id: 99,
                person_id: person(person_id),
            })
            .encode();
            assert!(start.as_slice() <= encoded.as_slice());
            assert!(encoded.as_slice() < end.as_slice());
        }
        for foreign in [
            Stage2Key {
                partition_id: 8,
                team_id: 42,
                cohort_id: 99,
                person_id: person(1),
            },
            Stage2Key {
                partition_id: 7,
                team_id: 43,
                cohort_id: 99,
                person_id: person(1),
            },
            Stage2Key {
                partition_id: 7,
                team_id: 42,
                cohort_id: 100,
                person_id: person(1),
            },
        ] {
            let encoded = Stage2DirtyKey::new(foreign).encode();
            assert!(encoded.as_slice() < start.as_slice() || encoded.as_slice() >= end.as_slice());
        }
    }

    proptest! {
        #[test]
        fn stage2_cohort_prefix_range_contains_exactly_matching_keys(
            partition_id in any::<u16>(),
            team_id in any::<u64>(),
            cohort_id in any::<u64>(),
            person_id in any::<u128>(),
            foreign_axis in 0u8..3,
        ) {
            let prefix = Stage2CohortPrefix {
                partition_id,
                team_id,
                cohort_id,
            };
            let (start, end) = prefix.range();
            let matching = Stage2Key {
                partition_id,
                team_id,
                cohort_id,
                person_id: person(person_id),
            }
            .encode();
            prop_assert!(start.as_slice() <= matching.as_slice());
            prop_assert!(matching.as_slice() < end.as_slice());

            let (foreign_partition, foreign_team, foreign_cohort) = match foreign_axis {
                0 => (partition_id.wrapping_add(1), team_id, cohort_id),
                1 => (partition_id, team_id.wrapping_add(1), cohort_id),
                _ => (partition_id, team_id, cohort_id.wrapping_add(1)),
            };
            let foreign = Stage2Key {
                partition_id: foreign_partition,
                team_id: foreign_team,
                cohort_id: foreign_cohort,
                person_id: person(person_id),
            }
            .encode();
            prop_assert!(
                foreign.as_slice() < start.as_slice() || foreign.as_slice() >= end.as_slice()
            );
        }
    }

    #[test]
    fn stage2_cohort_prefix_range_carries_and_bounds_the_all_ones_key() {
        for (prefix, expected_end) in [
            (
                Stage2CohortPrefix {
                    partition_id: 1,
                    team_id: 2,
                    cohort_id: 3,
                },
                Stage2CohortPrefix {
                    partition_id: 1,
                    team_id: 2,
                    cohort_id: 4,
                }
                .encode()
                .to_vec(),
            ),
            (
                Stage2CohortPrefix {
                    partition_id: 1,
                    team_id: 2,
                    cohort_id: u64::MAX,
                },
                Stage2CohortPrefix {
                    partition_id: 1,
                    team_id: 3,
                    cohort_id: 0,
                }
                .encode()
                .to_vec(),
            ),
            (
                Stage2CohortPrefix {
                    partition_id: 1,
                    team_id: u64::MAX,
                    cohort_id: u64::MAX,
                },
                Stage2CohortPrefix {
                    partition_id: 2,
                    team_id: 0,
                    cohort_id: 0,
                }
                .encode()
                .to_vec(),
            ),
        ] {
            assert_eq!(prefix.range().1, expected_end);
        }

        let max_prefix = Stage2CohortPrefix {
            partition_id: u16::MAX,
            team_id: u64::MAX,
            cohort_id: u64::MAX,
        };
        let (start, end) = max_prefix.range();
        assert_eq!(start, vec![0xFF; STAGE2_COHORT_PREFIX_LEN]);
        assert_eq!(end, vec![0xFF; STAGE2_KEY_LEN + 1]);
        assert!(
            Stage2Key {
                partition_id: u16::MAX,
                team_id: u64::MAX,
                cohort_id: u64::MAX,
                person_id: person(u128::MAX),
            }
            .encode()
            .as_slice()
                < end.as_slice(),
        );
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
        // The behavioral key is the longest partition-prefixed state key, so bracketing it (and the
        // stage2 key) proves a partition wipe reclaims the partition's whole state slice.
        for p in [0u16, 5, 256, u16::MAX - 1, u16::MAX] {
            let (start, end) = partition_range(p);
            let max_key =
                BehavioralKey::new(p, u64::MAX, person(u128::MAX), LeafStateKey([0xFF; 16]))
                    .encode();
            let min_key = BehavioralKey::new(p, 0, person(0), LeafStateKey([0x00; 16])).encode();
            assert!(start.as_slice() <= min_key.as_slice(), "start>min at p={p}");
            assert!(max_key.as_slice() < end.as_slice(), "max>=end at p={p}");
            if let Some(next) = p.checked_add(1) {
                let next_min = behavioral(next, 0).encode();
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
        assert!([0xFFu8; BEHAVIORAL_KEY_LEN].as_slice() < end.as_slice());
    }

    #[test]
    fn merge_key_lengths_are_exact_and_within_the_state_key_bound() {
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
            assert!(
                len <= BEHAVIORAL_KEY_LEN,
                "{len} exceeds BEHAVIORAL_KEY_LEN"
            );
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
