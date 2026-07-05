//! Typed keyspaces: the sole constructors of the state column families' keys.
//!
//! A [`Keyspace`] binds a key type to exactly one [`Cf`] and to whether that CF is partition-prefixed,
//! so a key cannot be encoded for the wrong column family and every new CF is forced to declare
//! whether a partition wipe reclaims it (the [`Cf::partitioned`] exhaustive match). The state CFs are
//! person-clustered: [`PersonPrefix`] is the 26-byte `(partition, team, person)` prefix under which a
//! person's rows sort contiguously, and [`BehavioralKey`] appends a 16-byte leaf-state key so one
//! person's leaf rows form one contiguous, prefix-scannable slice.

use uuid::Uuid;

use super::column_families::Cf;
use super::rocks::StoreError;
use crate::stage1::key::LeafStateKey;

/// `[partition_id u16][team_id u64][person_id 16]`. The person-clustered prefix.
pub const PERSON_PREFIX_LEN: usize = 2 + 8 + 16;
/// `[partition_id u16][team_id u64][person_id 16][leaf_state_key 16]`.
pub const BEHAVIORAL_KEY_LEN: usize = PERSON_PREFIX_LEN + 16;

/// The 26-byte person prefix: every state key for one person sorts under it, so a person's rows are
/// one contiguous slice reachable by a prefix scan or reclaimed by a single range delete.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct PersonPrefix {
    pub partition_id: u16,
    pub team_id: u64,
    pub person_id: Uuid,
}

impl PersonPrefix {
    pub fn new(partition_id: u16, team_id: u64, person_id: Uuid) -> Self {
        Self {
            partition_id,
            team_id,
            person_id,
        }
    }

    pub fn encode(&self) -> [u8; PERSON_PREFIX_LEN] {
        let mut out = [0u8; PERSON_PREFIX_LEN];
        out[0..2].copy_from_slice(&self.partition_id.to_be_bytes());
        out[2..10].copy_from_slice(&self.team_id.to_be_bytes());
        out[10..26].copy_from_slice(self.person_id.as_bytes());
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(bytes, PERSON_PREFIX_LEN, "person_prefix")?;
        Ok(Self {
            partition_id: u16::from_be_bytes(array2(&bytes[0..2])),
            team_id: u64::from_be_bytes(array8(&bytes[2..10])),
            person_id: Uuid::from_bytes(array16(&bytes[10..26])),
        })
    }

    /// The behavioral state key for one of this person's leaves.
    pub fn behavioral_key(&self, lsk: LeafStateKey) -> BehavioralKey {
        BehavioralKey { prefix: *self, lsk }
    }

    /// This person's `cf_person_records` key — the 26-byte prefix itself, since there is exactly one
    /// record per person.
    pub fn record_key(&self) -> PersonRecordKey {
        PersonRecordKey(*self)
    }

    /// The half-open byte range `[prefix, prefix-successor)` covering exactly this person's slice of a
    /// person-clustered CF — the unit of prefix iteration and of a single `delete_range_cf`.
    ///
    /// The upper bound is the 26-byte prefix incremented as a big-endian integer: a person's keys are
    /// all `>= prefix` and strictly `< next-prefix`, so incrementing the last non-`0xFF` byte (dropping
    /// the trailing `0xFF` run) yields the smallest key greater than every extension of `prefix`. A
    /// prefix of all `0xFF` bytes (the maximum person on the maximum team of the last partition) has no
    /// shorter successor, so the end is an all-`0xFF` sentinel one byte longer than the longest key that
    /// can start with this prefix (`prefix + 16-byte lsk`), which exceeds every such key.
    pub fn scan_range(&self) -> (Vec<u8>, Vec<u8>) {
        let start = self.encode().to_vec();
        let end = prefix_successor(&start).unwrap_or_else(|| vec![0xFFu8; BEHAVIORAL_KEY_LEN + 1]);
        (start, end)
    }
}

/// `cf_behavioral` key: one person's per-leaf state, keyed person-first so all of a person's leaves
/// sort contiguously under their [`PersonPrefix`].
#[derive(Copy, Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct BehavioralKey {
    pub prefix: PersonPrefix,
    pub lsk: LeafStateKey,
}

impl BehavioralKey {
    pub fn new(partition_id: u16, team_id: u64, person_id: Uuid, lsk: LeafStateKey) -> Self {
        Self {
            prefix: PersonPrefix::new(partition_id, team_id, person_id),
            lsk,
        }
    }

    pub fn partition_id(&self) -> u16 {
        self.prefix.partition_id
    }

    pub fn team_id(&self) -> u64 {
        self.prefix.team_id
    }

    pub fn person_id(&self) -> Uuid {
        self.prefix.person_id
    }

    pub fn lsk(&self) -> LeafStateKey {
        self.lsk
    }

    pub fn encode(&self) -> [u8; BEHAVIORAL_KEY_LEN] {
        let mut out = [0u8; BEHAVIORAL_KEY_LEN];
        out[0..PERSON_PREFIX_LEN].copy_from_slice(&self.prefix.encode());
        out[PERSON_PREFIX_LEN..].copy_from_slice(&self.lsk.0);
        out
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        check_len(bytes, BEHAVIORAL_KEY_LEN, "behavioral")?;
        Ok(Self {
            prefix: PersonPrefix::decode(&bytes[0..PERSON_PREFIX_LEN])?,
            lsk: LeafStateKey(array16(&bytes[PERSON_PREFIX_LEN..])),
        })
    }
}

/// `cf_person_records` key: exactly one record per person, so the key IS the 26-byte
/// [`PersonPrefix`] — no leaf suffix. Byte-identical to the prefix encoding, so it nests inside the
/// same partition range as the behavioral keys and a partition wipe reclaims it.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct PersonRecordKey(pub PersonPrefix);

impl PersonRecordKey {
    pub fn new(partition_id: u16, team_id: u64, person_id: Uuid) -> Self {
        Self(PersonPrefix::new(partition_id, team_id, person_id))
    }

    pub fn encode(&self) -> [u8; PERSON_PREFIX_LEN] {
        self.0.encode()
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        Ok(Self(PersonPrefix::decode(bytes)?))
    }
}

/// `cf_meta` key: a small set of ASCII-literal keys carrying store-wide guards (schema version). Not
/// partition-prefixed, so it is exempt from partition wipes.
#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]
pub struct MetaKey(pub &'static [u8]);

/// `cf_meta[b"schema_version"]` → the store schema version as a big-endian `u32`.
pub const META_SCHEMA_VERSION: MetaKey = MetaKey(b"schema_version");

mod sealed {
    /// Sealed so only this module's keyspaces implement [`super::Keyspace`]; downstream code cannot
    /// bind a new key type to a CF without declaring its partitioning here.
    pub trait Sealed {}
}

/// A typed keyspace: one key type bound to one column family and to whether that CF is partitioned.
///
/// The binding is what stops a key from being written to the wrong CF (the generic
/// `BatchBuilder::put::<K>` / `StagedBatch::put::<K>` route by `K::CF`) and what forces every CF to
/// declare, via [`Cf::partitioned`]'s exhaustive match, whether a partition wipe reclaims it.
pub trait Keyspace: sealed::Sealed {
    /// The column family this keyspace's keys live in.
    const CF: Cf;
    /// Whether keys carry the partition prefix, so a partition wipe's range delete reclaims them.
    const PARTITIONED: bool;
    /// The typed key. `Copy + Send + 'static` so it can be encoded into an owned staged op.
    type Key: Copy + Send + 'static;

    fn encode(key: &Self::Key) -> Vec<u8>;
    fn decode(bytes: &[u8]) -> Result<Self::Key, StoreError>;
}

/// The person-clustered behavioral-state keyspace.
pub struct Behavioral;

impl sealed::Sealed for Behavioral {}

impl Keyspace for Behavioral {
    const CF: Cf = Cf::Behavioral;
    const PARTITIONED: bool = true;
    type Key = BehavioralKey;

    fn encode(key: &BehavioralKey) -> Vec<u8> {
        key.encode().to_vec()
    }

    fn decode(bytes: &[u8]) -> Result<BehavioralKey, StoreError> {
        BehavioralKey::decode(bytes)
    }
}

/// The per-person-record keyspace: one row per person under the 26-byte prefix. Partitioned, so a
/// partition wipe reclaims it via the shared partition range.
pub struct PersonRecords;

impl sealed::Sealed for PersonRecords {}

impl Keyspace for PersonRecords {
    const CF: Cf = Cf::PersonRecords;
    const PARTITIONED: bool = true;
    type Key = PersonRecordKey;

    fn encode(key: &PersonRecordKey) -> Vec<u8> {
        key.encode().to_vec()
    }

    fn decode(bytes: &[u8]) -> Result<PersonRecordKey, StoreError> {
        PersonRecordKey::decode(bytes)
    }
}

/// The store-metadata keyspace. Not partitioned: its ASCII-literal keys are shorter than a partition
/// range's upper bound and would collide with an arbitrary partition's slice, so a partition wipe must
/// never range over it (e.g. `b"sc"` = `0x7363` sits inside partition `29539`'s range).
pub struct Meta;

impl sealed::Sealed for Meta {}

impl Keyspace for Meta {
    const CF: Cf = Cf::Meta;
    const PARTITIONED: bool = false;
    type Key = MetaKey;

    fn encode(key: &MetaKey) -> Vec<u8> {
        key.0.to_vec()
    }

    fn decode(bytes: &[u8]) -> Result<MetaKey, StoreError> {
        // `cf_meta` keys are a closed set of literals; the only one written today is the schema
        // version. Match the known literals so a decode is total, and reject anything else rather than
        // fabricate a `&'static` from runtime bytes.
        if bytes == META_SCHEMA_VERSION.0 {
            Ok(META_SCHEMA_VERSION)
        } else {
            Err(StoreError::KeyDecode {
                kind: "meta",
                expected: META_SCHEMA_VERSION.0.len(),
                actual: bytes.len(),
            })
        }
    }
}

/// The smallest byte string strictly greater than every extension of `prefix`: increment the last
/// byte below `0xFF`, dropping the trailing `0xFF` run. Returns `None` for an all-`0xFF` prefix, which
/// has no such bound — the caller supplies a length-based sentinel that exceeds every key.
fn prefix_successor(prefix: &[u8]) -> Option<Vec<u8>> {
    let mut end = prefix.to_vec();
    while let Some(last) = end.last_mut() {
        if *last == 0xFF {
            end.pop();
        } else {
            *last += 1;
            return Some(end);
        }
    }
    None
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
    use crate::store::keys::partition_range;

    fn lsk(b: u8) -> LeafStateKey {
        LeafStateKey([b; 16])
    }

    fn person(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn behavioral(partition_id: u16, team_id: u64, p: u128, l: u8) -> BehavioralKey {
        BehavioralKey::new(partition_id, team_id, person(p), lsk(l))
    }

    #[test]
    fn encoded_lengths_are_exact() {
        assert_eq!(PERSON_PREFIX_LEN, 26);
        assert_eq!(BEHAVIORAL_KEY_LEN, 42);
        assert_eq!(
            PersonPrefix::new(1, 2, person(3)).encode().len(),
            PERSON_PREFIX_LEN,
        );
        assert_eq!(behavioral(1, 2, 3, 4).encode().len(), BEHAVIORAL_KEY_LEN);
    }

    #[test]
    fn person_prefix_round_trips() {
        let key = PersonPrefix::new(0xBEEF, 0x0123_4567_89AB_CDEF, person(0xDEAD_BEEF));
        assert_eq!(PersonPrefix::decode(&key.encode()).unwrap(), key);
    }

    #[test]
    fn behavioral_key_round_trips() {
        let key = behavioral(0xBEEF, 0x0123_4567_89AB_CDEF, 0xDEAD_BEEF, 0x5A);
        assert_eq!(BehavioralKey::decode(&key.encode()).unwrap(), key);
    }

    #[test]
    fn behavioral_key_accessors_match_the_prefix() {
        let key = behavioral(7, 42, 99, 0xAB);
        assert_eq!(key.partition_id(), 7);
        assert_eq!(key.team_id(), 42);
        assert_eq!(key.person_id(), person(99));
        assert_eq!(key.lsk(), lsk(0xAB));
    }

    #[test]
    fn decode_rejects_wrong_length() {
        let err = BehavioralKey::decode(&[0u8; 41]).unwrap_err();
        assert!(
            matches!(
                err,
                StoreError::KeyDecode {
                    kind: "behavioral",
                    expected: 42,
                    actual: 41,
                }
            ),
            "unexpected error: {err:?}",
        );
    }

    #[test]
    fn behavioral_keys_sort_person_first_then_leaf() {
        // Person clustering: a person's leaves are contiguous; a different person sorts as a block.
        assert!(behavioral(5, 7, 1, 0xFF).encode() < behavioral(5, 7, 2, 0x00).encode());
        // Within one person, leaves sort by lsk.
        assert!(behavioral(5, 7, 1, 0x01).encode() < behavioral(5, 7, 1, 0x02).encode());
        // Partition then team still dominate.
        assert!(
            behavioral(1, u64::MAX, u128::MAX, 0xFF).encode() < behavioral(2, 0, 0, 0x00).encode()
        );
        assert!(behavioral(5, 1, 0, 0x00).encode() < behavioral(5, 2, 0, 0x00).encode());
    }

    #[test]
    fn scan_range_brackets_exactly_one_persons_leaves() {
        let prefix = PersonPrefix::new(5, 7, person(42));
        let (start, end) = prefix.scan_range();

        let min_leaf = prefix.behavioral_key(lsk(0x00)).encode();
        let max_leaf = prefix.behavioral_key(lsk(0xFF)).encode();
        assert!(start.as_slice() <= min_leaf.as_slice());
        assert!(max_leaf.as_slice() < end.as_slice());

        // A neighbouring person's minimum leaf is at or past the end (never inside this person's range).
        let next_person = PersonPrefix::new(5, 7, person(43))
            .behavioral_key(lsk(0x00))
            .encode();
        assert!(end.as_slice() <= next_person.as_slice());
        // The previous person's maximum leaf is strictly below the start.
        let prev_person = PersonPrefix::new(5, 7, person(41))
            .behavioral_key(lsk(0xFF))
            .encode();
        assert!(prev_person.as_slice() < start.as_slice());
    }

    #[test]
    fn scan_range_handles_the_all_ones_prefix() {
        let prefix = PersonPrefix::new(u16::MAX, u64::MAX, person(u128::MAX));
        let (start, end) = prefix.scan_range();
        let max_leaf = prefix.behavioral_key(lsk(0xFF)).encode();
        assert!(start.as_slice() <= max_leaf.as_slice());
        assert!(
            max_leaf.as_slice() < end.as_slice(),
            "sentinel exceeds the all-ones key"
        );
    }

    #[test]
    fn behavioral_keys_share_the_partition_prefix_so_delete_range_reclaims_them() {
        // The person-prefix range nests inside the partition range, so a partition wipe still reclaims
        // every behavioral key in the partition.
        for p in [0u16, 5, 256, u16::MAX] {
            let (start, end) = partition_range(p);
            let max = behavioral(p, u64::MAX, u128::MAX, 0xFF).encode();
            let min = behavioral(p, 0, 0, 0x00).encode();
            assert!(start.as_slice() <= min.as_slice(), "start>min at p={p}");
            assert!(max.as_slice() < end.as_slice(), "max>=end at p={p}");
        }
    }

    #[test]
    fn keyspace_consts_bind_key_types_to_the_right_cf() {
        assert_eq!(Behavioral::CF, Cf::Behavioral);
        assert_eq!(PersonRecords::CF, Cf::PersonRecords);
        assert_eq!(Meta::CF, Cf::Meta);
        // Each keyspace's PARTITIONED const must agree with its CF's `partitioned()` — the exhaustive
        // match `delete_partition` relies on. A drift here would range-delete (or spare) the wrong CF.
        assert_eq!(Behavioral::PARTITIONED, Cf::Behavioral.partitioned());
        assert_eq!(PersonRecords::PARTITIONED, Cf::PersonRecords.partitioned());
        assert_eq!(Meta::PARTITIONED, Cf::Meta.partitioned());
    }

    #[test]
    fn person_record_key_is_byte_identical_to_the_person_prefix() {
        let prefix = PersonPrefix::new(0xBEEF, 0x0123_4567_89AB_CDEF, person(0xDEAD_BEEF));
        let key = prefix.record_key();
        assert_eq!(key.0, prefix);
        assert_eq!(
            key.encode(),
            prefix.encode(),
            "record key encodes as the bare prefix"
        );
        assert_eq!(PersonRecordKey::decode(&key.encode()).unwrap(), key);
        assert_eq!(
            PersonRecordKey::new(0xBEEF, 0x0123_4567_89AB_CDEF, person(0xDEAD_BEEF)),
            key,
        );
    }

    #[test]
    fn person_record_keyspace_encode_matches_the_key_encoder() {
        let key = PersonRecordKey::new(3, 7, person(9));
        assert_eq!(PersonRecords::encode(&key), key.encode().to_vec());
        assert_eq!(
            PersonRecords::decode(&PersonRecords::encode(&key)).unwrap(),
            key
        );
    }

    #[test]
    fn person_record_keys_share_the_partition_prefix_so_delete_range_reclaims_them() {
        // Same nesting property as the behavioral keys: a person-record key sits inside the partition
        // range, so a partition wipe reclaims it too.
        for p in [0u16, 5, 256, u16::MAX] {
            let (start, end) = partition_range(p);
            let max = PersonRecordKey::new(p, u64::MAX, person(u128::MAX)).encode();
            let min = PersonRecordKey::new(p, 0, person(0)).encode();
            assert!(start.as_slice() <= min.as_slice(), "start>min at p={p}");
            assert!(max.as_slice() < end.as_slice(), "max>=end at p={p}");
        }
    }

    #[test]
    fn behavioral_keyspace_encode_matches_the_key_encoder() {
        let key = behavioral(3, 7, 9, 0xAB);
        assert_eq!(Behavioral::encode(&key), key.encode().to_vec());
        assert_eq!(Behavioral::decode(&Behavioral::encode(&key)).unwrap(), key);
    }

    #[test]
    fn meta_keyspace_round_trips_the_known_literal_and_rejects_others() {
        assert_eq!(
            Meta::encode(&META_SCHEMA_VERSION),
            b"schema_version".to_vec()
        );
        assert_eq!(
            Meta::decode(b"schema_version").unwrap(),
            META_SCHEMA_VERSION,
        );
        assert!(Meta::decode(b"unknown").is_err());
    }
}
