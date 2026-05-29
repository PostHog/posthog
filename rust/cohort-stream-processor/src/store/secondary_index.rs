//! `cf_person_index` maintenance via a non-associative RocksDB merge operator (TDD §2.5:301).
//!
//! The hot path appends a [`LeafStateKey`] to a person's leaf-state set **without a read**, in
//! the same `WriteBatch` as the `cf_stage1` put. Both append *and* remove are required, so the
//! operator cannot be associative (operand format ≠ value format):
//!
//! - **Value** — the person's set, a sorted, de-duplicated, packed `[u8; 16] × N` (untagged).
//! - **Operand** — a 17-byte `[tag u8][lsk 16]` ([`IndexOp`]); a `partial_merge` may concatenate
//!   several into one longer log, which is itself a valid operand.
//!
//! ### Two invariants this module is built around
//!
//! 1. **Never panic.** The merge fns run on RocksDB compaction/flush threads; a panic across the
//!    FFI boundary is undefined behavior. Every decode is length-checked and skips (with a
//!    metric) rather than indexing or unwrapping.
//! 2. **Never return `None`.** Returning `None` from `full_merge` signals a *merge failure* to
//!    RocksDB — it surfaces a `"Merge operator failed"` error on the next read, **not** a key
//!    drop (verified against `rocksdb-0.24.0` `tests/test_merge_operator.rs::failed_merge_test`).
//!    The empty set therefore encodes to an empty value, which reads back as "no states" — the
//!    same observable result a missing key gives the migration read.
//!
//! Append-present and remove-absent are natural `BTreeSet` no-ops, so replay is idempotent.

use std::collections::BTreeSet;

use metrics::counter;
use rocksdb::MergeOperands;

use crate::observability::metrics::STORE_MERGE_MALFORMED_TOTAL;
use crate::stage1::key::LeafStateKey;

/// On-disk name of the operator. RocksDB treats the name as a forward-compatibility contract,
/// so bumping the set/operand format means bumping the `_vN` suffix.
pub const PERSON_INDEX_MERGE_OPERATOR_NAME: &str = "cf_person_index_merge_v1";

const LSK_LEN: usize = 16;
/// `[tag u8][lsk 16]`.
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
    /// Encode to the fixed 17-byte operand. Allocation-free.
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

/// Decode a stored `cf_person_index` value into the person's leaf-state keys (sorted, unique).
///
/// Defensive and infallible, mirroring the merge fns: a trailing partial entry is dropped with
/// a metric rather than erroring the read path. A missing key (empty slice) yields an empty
/// vec — "no states".
pub fn decode_person_index(value: &[u8]) -> Vec<LeafStateKey> {
    decode_packed(value).into_iter().map(LeafStateKey).collect()
}

/// `full_merge`: fold the base value and the ordered operand logs into the final set.
pub(crate) fn full_merge(
    _key: &[u8],
    existing: Option<&[u8]>,
    operands: &MergeOperands,
) -> Option<Vec<u8>> {
    Some(collapse(existing, operands))
}

/// `partial_merge`: concatenate operand logs without the base value. RocksDB only ever re-feeds
/// the result as another operand (`existing` is always `None` here —
/// `rocksdb-0.24.0` `merge_operator.rs:151`), so a concatenation of valid 17-byte logs is itself
/// a valid operand.
pub(crate) fn partial_merge(
    _key: &[u8],
    _existing: Option<&[u8]>,
    operands: &MergeOperands,
) -> Option<Vec<u8>> {
    Some(concat_logs(operands))
}

/// Fold `existing` + ordered `operands` into the encoded set. Shared by [`full_merge`] and the
/// unit tests (which can't construct a `MergeOperands`, whose constructor is private).
fn collapse<'a>(existing: Option<&[u8]>, operands: impl IntoIterator<Item = &'a [u8]>) -> Vec<u8> {
    let mut set: BTreeSet<[u8; LSK_LEN]> = existing
        .map(|bytes| decode_packed(bytes).into_iter().collect())
        .unwrap_or_default();
    for operand in operands {
        apply_operand_log(&mut set, operand);
    }
    encode_set(&set)
}

/// Concatenate the operand logs, skipping any whose length isn't a whole number of 17-byte
/// entries (so one malformed operand can't misalign the entries of the others).
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

/// Apply a 17-byte-entry operand log to the set in iteration order.
fn apply_operand_log(set: &mut BTreeSet<[u8; LSK_LEN]>, log: &[u8]) {
    let mut entries = log.chunks_exact(OPERAND_LEN);
    for entry in &mut entries {
        // `chunks_exact(OPERAND_LEN)` yields exactly `OPERAND_LEN` bytes; the `else` arm is
        // therefore unreachable, but keeps the decode panic-free by construction.
        let [tag, lsk_bytes @ ..] = entry else {
            continue;
        };
        let mut lsk = [0u8; LSK_LEN];
        lsk.copy_from_slice(lsk_bytes); // `lsk_bytes` is exactly LSK_LEN (OPERAND_LEN - 1).
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

/// Decode the packed value into raw 16-byte keys, dropping a trailing partial entry (with a
/// metric). Returns entries in stored order — which [`encode_set`] keeps sorted and unique.
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

    /// Order matters: removing before the matching append is a no-op, so the key survives.
    #[test]
    fn remove_then_append_keeps_the_key() {
        let value = collapse(None, [&remove(1)[..], &append(1)[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(1)]);
    }

    #[test]
    fn duplicate_appends_are_deduplicated_and_sorted() {
        // Feed out of order with a dup; expect sorted, unique output.
        let value = collapse(None, [&append(2)[..], &append(1)[..], &append(2)[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(1), lsk(2)]);
    }

    #[test]
    fn merge_folds_into_an_existing_base() {
        let base = collapse(None, [&append(1)[..]]);
        let value = collapse(Some(&base), [&append(2)[..], &remove(1)[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(2)]);
    }

    /// `partial_merge` grouping must not change the final set: collapsing the concatenated log
    /// yields the same result as collapsing the operands one by one (full and partial grouping).
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
        // A short operand and a base with a trailing partial entry are both skipped, leaving the
        // well-formed appends intact.
        let value = collapse(None, [&append(1)[..], &[0u8; 5][..], &append(2)[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(1), lsk(2)]);

        let mut corrupt_base = collapse(None, [&append(9)[..]]);
        corrupt_base.push(0xFF); // trailing partial 16-byte entry
        let value = collapse(Some(&corrupt_base), [&append(8)[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(8), lsk(9)]);
    }

    #[test]
    fn unknown_operand_tag_is_skipped() {
        let mut bad = [0u8; OPERAND_LEN];
        bad[0] = 99; // neither append nor remove
        let value = collapse(None, [&append(1)[..], &bad[..]]);
        assert_eq!(decode_person_index(&value), vec![lsk(1)]);
    }

    #[test]
    fn decode_person_index_of_empty_is_empty() {
        assert_eq!(decode_person_index(&[]), vec![]);
    }
}
