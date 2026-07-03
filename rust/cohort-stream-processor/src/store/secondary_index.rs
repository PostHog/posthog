//! `cf_person_index` maintenance via a non-associative RocksDB merge operator.
//!
//! The hot path appends a [`LeafStateKey`] to a person's set without a read, in the same
//! `WriteBatch` as the `cf_stage1` put. Append *and* remove are both needed, so the operator is
//! non-associative (operand format ≠ value format):
//!
//! - **Value** — the set, a sorted, de-duplicated, packed `[u8; 16] × N` (untagged).
//! - **Operand** — a 17-byte `[tag u8][lsk 16]` ([`IndexOp`]); a concatenation of several is itself
//!   a valid operand.
//!
//! Maintained on the hot path even though its only readers are the merge drain (enumerating P_old's
//! leaves on a person merge, [`crate::merge::drain_handler`]) and Stage 2 composition: writing it
//! eagerly gives the non-associative merge operator production bake time on real compaction/flush
//! threads before readers depend on it, and lets readers inherit a fully-built person→leaf-state
//! index with no historical backfill pass.
//!
//! Two correctness rules:
//!
//! 1. **Never panic.** The merge fns run on RocksDB compaction/flush threads; a panic across that
//!    FFI boundary is UB. Every decode is length-checked and skips (with a metric).
//! 2. **Never return `None`.** `None` from `full_merge` signals a *merge failure* (a
//!    `"Merge operator failed"` error on the next read), not a key drop. The empty set therefore
//!    encodes to an empty value, which reads back as "no states" — same as a missing key.
//!
//! Append-present and remove-absent are `BTreeSet` no-ops, so replay is idempotent.

use std::collections::BTreeSet;

use metrics::counter;
use rocksdb::MergeOperands;

use crate::observability::metrics::STORE_MERGE_MALFORMED_TOTAL;
use crate::stage1::key::LeafStateKey;

/// RocksDB treats the operator name as a forward-compat contract: bump `_vN` on any format change.
pub const PERSON_INDEX_MERGE_OPERATOR_NAME: &str = "cf_person_index_merge_v1";

const LSK_LEN: usize = 16;
const OPERAND_LEN: usize = 1 + LSK_LEN;
const TAG_APPEND: u8 = 0;
const TAG_REMOVE: u8 = 1;

/// A mutation of a person's leaf-state set, applied to `cf_person_index` via `merge_cf`.
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum IndexOp {
    Append(LeafStateKey),
    Remove(LeafStateKey),
}

impl IndexOp {
    pub fn encode(&self) -> [u8; OPERAND_LEN] {
        let (tag, lsk) = match self {
            IndexOp::Append(lsk) => (TAG_APPEND, lsk),
            IndexOp::Remove(lsk) => (TAG_REMOVE, lsk),
        };
        let mut out = [0u8; OPERAND_LEN];
        out[0] = tag;
        out[1..].copy_from_slice(&lsk.0);
        out
    }
}

/// Decode a stored `cf_person_index` value into sorted, unique leaf-state keys. Infallible: a
/// trailing partial entry is dropped (with a metric) rather than erroring; empty yields "no states".
pub fn decode_person_index(value: &[u8]) -> Vec<LeafStateKey> {
    decode_packed(value).into_iter().map(LeafStateKey).collect()
}

pub(crate) fn full_merge(
    _key: &[u8],
    existing: Option<&[u8]>,
    operands: &MergeOperands,
) -> Option<Vec<u8>> {
    Some(collapse(existing, operands))
}

/// Concatenate operand logs without a base value. RocksDB only re-feeds the result as another
/// operand (`existing` is always `None`), so a concatenation of valid logs is itself valid.
pub(crate) fn partial_merge(
    _key: &[u8],
    _existing: Option<&[u8]>,
    operands: &MergeOperands,
) -> Option<Vec<u8>> {
    Some(concat_logs(operands))
}

/// Fold `existing` + ordered `operands` into the encoded set. Takes an iterator (not
/// `MergeOperands`) so the tests, which can't construct one, can share it.
fn collapse<'a>(existing: Option<&[u8]>, operands: impl IntoIterator<Item = &'a [u8]>) -> Vec<u8> {
    let mut set: BTreeSet<[u8; LSK_LEN]> = existing
        .map(|bytes| decode_packed(bytes).into_iter().collect())
        .unwrap_or_default();
    for operand in operands {
        apply_operand_log(&mut set, operand);
    }
    encode_set(&set)
}

/// Concatenate operand logs, skipping any not a whole number of entries so one malformed operand
/// can't misalign the rest.
fn concat_logs<'a>(operands: impl IntoIterator<Item = &'a [u8]>) -> Vec<u8> {
    let mut combined = Vec::new();
    for operand in operands {
        if operand.len() % OPERAND_LEN == 0 {
            combined.extend_from_slice(operand);
        } else {
            counter!(STORE_MERGE_MALFORMED_TOTAL, "kind" => "operand_len").increment(1);
        }
    }
    combined
}

fn apply_operand_log(set: &mut BTreeSet<[u8; LSK_LEN]>, log: &[u8]) {
    let mut entries = log.chunks_exact(OPERAND_LEN);
    for entry in &mut entries {
        let [tag, lsk_bytes @ ..] = entry else {
            continue;
        };
        let mut lsk = [0u8; LSK_LEN];
        lsk.copy_from_slice(lsk_bytes);
        match *tag {
            TAG_APPEND => {
                set.insert(lsk);
            }
            TAG_REMOVE => {
                set.remove(&lsk);
            }
            _ => {
                counter!(STORE_MERGE_MALFORMED_TOTAL, "kind" => "operand_tag").increment(1);
            }
        }
    }
    if !entries.remainder().is_empty() {
        counter!(STORE_MERGE_MALFORMED_TOTAL, "kind" => "operand_len").increment(1);
    }
}

fn encode_set(set: &BTreeSet<[u8; LSK_LEN]>) -> Vec<u8> {
    let mut out = Vec::with_capacity(set.len() * LSK_LEN);
    for lsk in set {
        out.extend_from_slice(lsk);
    }
    out
}

/// Decode the packed value into raw 16-byte keys, dropping a trailing partial entry (with a metric).
fn decode_packed(bytes: &[u8]) -> Vec<[u8; LSK_LEN]> {
    let mut out = Vec::with_capacity(bytes.len() / LSK_LEN);
    let mut chunks = bytes.chunks_exact(LSK_LEN);
    for chunk in &mut chunks {
        let mut lsk = [0u8; LSK_LEN];
        lsk.copy_from_slice(chunk);
        out.push(lsk);
    }
    if !chunks.remainder().is_empty() {
        counter!(STORE_MERGE_MALFORMED_TOTAL, "kind" => "base_len").increment(1);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lsk(b: u8) -> LeafStateKey {
        LeafStateKey([b; 16])
    }

    fn append(b: u8) -> [u8; OPERAND_LEN] {
        IndexOp::Append(lsk(b)).encode()
    }

    fn remove(b: u8) -> [u8; OPERAND_LEN] {
        IndexOp::Remove(lsk(b)).encode()
    }

    #[test]
    fn operand_encoding_is_tag_then_key() {
        let a = append(0xAB);
        assert_eq!(a[0], TAG_APPEND);
        assert_eq!(&a[1..], &[0xAB; 16]);

        let r = remove(0xCD);
        assert_eq!(r[0], TAG_REMOVE);
        assert_eq!(&r[1..], &[0xCD; 16]);
    }

    #[test]
    fn append_then_collapse_round_trips_through_decode() {
        let value = collapse(None, [&append(1)[..], &append(2)[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(1), lsk(2)]);
    }

    #[test]
    fn append_then_remove_leaves_the_set_empty() {
        let value = collapse(None, [&append(1)[..], &remove(1)[..]]);
        assert!(value.is_empty());
        assert_eq!(decode_person_index(&value), vec![]);
    }

    /// Removing before the matching append is a no-op, so the key survives.
    #[test]
    fn remove_then_append_keeps_the_key() {
        let value = collapse(None, [&remove(1)[..], &append(1)[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(1)]);
    }

    #[test]
    fn duplicate_appends_are_deduplicated_and_sorted() {
        let value = collapse(None, [&append(2)[..], &append(1)[..], &append(2)[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(1), lsk(2)]);
    }

    #[test]
    fn merge_folds_into_an_existing_base() {
        let base = collapse(None, [&append(1)[..]]);
        let value = collapse(Some(&base), [&append(2)[..], &remove(1)[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(2)]);
    }

    /// `partial_merge` grouping must not change the final set, whatever the grouping.
    #[test]
    fn partial_merge_grouping_is_invariant() {
        let ops: [&[u8]; 3] = [&append(1), &append(2), &remove(1)];
        let direct = collapse(None, ops);

        let fully_grouped = concat_logs(ops);
        assert_eq!(collapse(None, [&fully_grouped[..]]), direct);

        let prefix = concat_logs([ops[0], ops[1]]);
        assert_eq!(collapse(None, [&prefix[..], ops[2]]), direct);
    }

    #[test]
    fn malformed_operand_length_does_not_panic_or_corrupt() {
        let value = collapse(None, [&append(1)[..], &[0u8; 5][..], &append(2)[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(1), lsk(2)]);

        let mut corrupt_base = collapse(None, [&append(9)[..]]);
        corrupt_base.push(0xFF);
        let value = collapse(Some(&corrupt_base), [&append(8)[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(8), lsk(9)]);
    }

    #[test]
    fn unknown_operand_tag_is_skipped() {
        let mut bad = [0u8; OPERAND_LEN];
        bad[0] = 99;
        let value = collapse(None, [&append(1)[..], &bad[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(1)]);
    }

    #[test]
    fn decode_person_index_of_empty_is_empty() {
        assert_eq!(decode_person_index(&[]), vec![]);
    }
}
