//! Wire and column-family value types for the cross-partition merge protocol.
//!
//! - [`PersonMergeEvent`] -- the merge trigger, keyed by P_old.
//! - [`MergeStateTransfer`] -- P_old's packaged per-leaf state, keyed by P_new.
//! - [`PendingTransfer`] -- `cf_pending_transfers` outbox value.
//! - [`Tombstone`] -- `cf_merge_tombstones` value for straggler redirect.
//! - [`DrainStamp`] / [`ApplyStamp`] -- idempotence markers (key presence is the guard).

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::stage1::key::LeafStateKey;
use crate::stage1::state::StatefulRecord;

pub const MERGE_EVENT_SCHEMA_VERSION: u32 = 1;

/// A committed `P_old -> P_new` person merge event.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PersonMergeEvent {
    pub team_id: i32,
    pub old_person_uuid: Uuid,
    pub new_person_uuid: Uuid,
    pub merged_at_ms: i64,
    pub schema_version: u32,
}

/// One leaf of a [`MergeStateTransfer`].
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TransferLeaf {
    /// 16-byte `LeafStateKey` as 32 lowercase hex chars (human-readable on the wire).
    pub leaf_state_key: String,
    pub record: StatefulRecord,
}

impl TransferLeaf {
    pub fn new(leaf_state_key: LeafStateKey, record: StatefulRecord) -> Self {
        Self {
            leaf_state_key: hex_encode(&leaf_state_key.0),
            record,
        }
    }

    /// Decode the hex `leaf_state_key`, or `None` if malformed.
    pub fn decode_leaf_state_key(&self) -> Option<LeafStateKey> {
        hex_decode(&self.leaf_state_key).map(LeafStateKey)
    }
}

/// P_old's packaged state for cross-partition transfer, keyed by P_new.
/// `source_partition`/`source_offset` are the original merge message's coordinates (used for
/// idempotence on the apply side, since duplicate transfers arrive at fresh topic offsets).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MergeStateTransfer {
    pub team_id: i32,
    pub old_person_uuid: Uuid,
    pub new_person_uuid: Uuid,
    pub merged_at_ms: i64,
    pub source_partition: i32,
    pub source_offset: i64,
    pub leaves: Vec<TransferLeaf>,
    /// Cross-partition forward hops taken so far when `new_person_uuid` was itself tombstoned at
    /// apply time (chained merge `A → B → C` where `B → C` drained before `A → B` applied). Bounded
    /// by [`crate::merge::apply_handler::MAX_TRANSFER_FORWARD_HOPS`]. `#[serde(default)]`: a message
    /// without the field decodes to `0`, so the field is JSON-compatible both ways.
    #[serde(default)]
    pub forward_hops: u8,
}

/// Staged transfer in `cf_pending_transfers`. Survives a crash between the drain batch and the
/// produce; the redrive re-produces it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PendingTransfer {
    pub transfer: MergeStateTransfer,
    pub merge_msg_partition: i32,
    pub merge_msg_offset: i64,
}

/// Tombstone value: the person a merged-away P_old's late events redirect to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Tombstone {
    pub new_person: Uuid,
    pub merged_at_ms: i64,
}

/// Drain idempotence marker value (informational; key presence is the guard).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct DrainStamp {
    pub drained_at_ms: i64,
}

/// Apply idempotence marker value.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct ApplyStamp {
    pub applied_at_ms: i64,
}

/// JSON codecs: infallible `encode`, fallible `decode`.
macro_rules! json_codec {
    ($ty:ty) => {
        impl $ty {
            #[doc = "Infallible: this is plain data and always serializes."]
            pub fn encode(&self) -> Vec<u8> {
                serde_json::to_vec(self).expect("merge value is plain data and always serializes")
            }

            #[doc = "Garbage bytes yield an [`Err`], never a panic."]
            pub fn decode(bytes: &[u8]) -> Result<Self, serde_json::Error> {
                serde_json::from_slice(bytes)
            }
        }
    };
}

json_codec!(PersonMergeEvent);
json_codec!(MergeStateTransfer);
json_codec!(PendingTransfer);
json_codec!(Tombstone);
json_codec!(DrainStamp);
json_codec!(ApplyStamp);

/// Encode 16 bytes as 32 lowercase hex chars.
fn hex_encode(bytes: &[u8; 16]) -> String {
    let mut out = String::with_capacity(32);
    for &byte in bytes {
        // `from_digit(_, 16)` is `Some` for any nibble `0..=15`.
        out.push(char::from_digit((byte >> 4) as u32, 16).expect("high nibble < 16"));
        out.push(char::from_digit((byte & 0x0f) as u32, 16).expect("low nibble < 16"));
    }
    out
}

/// Decode exactly 32 hex chars into 16 bytes, or `None` on invalid input.
fn hex_decode(s: &str) -> Option<[u8; 16]> {
    let bytes = s.as_bytes();
    if bytes.len() != 32 {
        return None;
    }
    let mut out = [0u8; 16];
    for (i, slot) in out.iter_mut().enumerate() {
        let hi = (bytes[2 * i] as char).to_digit(16)?;
        let lo = (bytes[2 * i + 1] as char).to_digit(16)?;
        *slot = ((hi << 4) | lo) as u8;
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::stage1::state::{AppliedOffsets, Stage1State};

    fn uuid(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn single_record() -> StatefulRecord {
        StatefulRecord::new(
            Stage1State::BehavioralSingle {
                has_match: true,
                last_event_at_ms: 1_700_000_000_000,
                earliest_eviction_at_ms: i64::MAX,
            },
            AppliedOffsets::default(),
        )
    }

    #[test]
    fn hex_round_trips_every_byte() {
        let key = LeafStateKey([
            0x00, 0x12, 0x34, 0x56, 0x78, 0x9a, 0xbc, 0xde, 0xf0, 0xff, 0x01, 0x02, 0x03, 0x04,
            0x05, 0x06,
        ]);
        let leaf = TransferLeaf::new(key, single_record());
        assert_eq!(leaf.leaf_state_key.len(), 32);
        assert_eq!(
            leaf.leaf_state_key, "00123456789abcdef0ff010203040506",
            "lowercase, two chars per byte, MSB first",
        );
        assert_eq!(leaf.decode_leaf_state_key(), Some(key));
    }

    #[test]
    fn malformed_hex_decodes_to_none_not_panic() {
        let bad_len = TransferLeaf {
            leaf_state_key: "abcd".to_string(),
            record: single_record(),
        };
        assert_eq!(bad_len.decode_leaf_state_key(), None, "wrong length");
        let bad_char = TransferLeaf {
            leaf_state_key: "zz123456789abcdef0ff010203040506".to_string(),
            record: single_record(),
        };
        assert_eq!(bad_char.decode_leaf_state_key(), None, "non-hex char");
    }

    #[test]
    fn person_merge_event_shape_is_pinned() {
        let event = PersonMergeEvent {
            team_id: 42,
            old_person_uuid: uuid(0xAAAA),
            new_person_uuid: uuid(0xBBBB),
            merged_at_ms: 1_716_800_000_000,
            schema_version: MERGE_EVENT_SCHEMA_VERSION,
        };
        let value: serde_json::Value = serde_json::from_slice(&event.encode()).unwrap();
        let object = value.as_object().unwrap();
        let mut keys: Vec<&str> = object.keys().map(String::as_str).collect();
        keys.sort_unstable();
        assert_eq!(
            keys,
            vec![
                "merged_at_ms",
                "new_person_uuid",
                "old_person_uuid",
                "schema_version",
                "team_id",
            ],
        );
        assert_eq!(
            object["old_person_uuid"],
            serde_json::json!(uuid(0xAAAA).to_string())
        );
        assert_eq!(object["schema_version"], serde_json::json!(1));
        assert_eq!(PersonMergeEvent::decode(&event.encode()).unwrap(), event);
    }

    #[test]
    fn merge_state_transfer_carries_records_whole_and_round_trips() {
        let transfer = MergeStateTransfer {
            team_id: 7,
            old_person_uuid: uuid(0xAAAA),
            new_person_uuid: uuid(0xBBBB),
            merged_at_ms: 1_716_800_000_000,
            source_partition: 17,
            source_offset: 12_345,
            leaves: vec![TransferLeaf::new(LeafStateKey([0xAB; 16]), single_record())],
            forward_hops: 0,
        };
        let decoded = MergeStateTransfer::decode(&transfer.encode()).unwrap();
        assert_eq!(decoded, transfer);
        assert_eq!(
            decoded.leaves[0].record,
            single_record(),
            "the leaf's StatefulRecord transfers whole, so redirect_dedup chains for free",
        );
    }

    #[test]
    fn transfer_without_forward_hops_decodes_to_zero_for_wire_compat() {
        // A transfer JSON that omits `forward_hops` must decode to `0` (`#[serde(default)]`).
        let json = serde_json::json!({
            "team_id": 7,
            "old_person_uuid": uuid(0xAAAA).to_string(),
            "new_person_uuid": uuid(0xBBBB).to_string(),
            "merged_at_ms": 1_716_800_000_000_i64,
            "source_partition": 17,
            "source_offset": 12_345,
            "leaves": [],
        });
        let decoded = MergeStateTransfer::decode(&serde_json::to_vec(&json).unwrap()).unwrap();
        assert_eq!(
            decoded.forward_hops, 0,
            "missing forward_hops defaults to 0"
        );
    }

    #[test]
    fn cf_value_types_round_trip() {
        let transfer = MergeStateTransfer {
            team_id: 7,
            old_person_uuid: uuid(0xAAAA),
            new_person_uuid: uuid(0xBBBB),
            merged_at_ms: 1,
            source_partition: 3,
            source_offset: 4,
            leaves: vec![],
            forward_hops: 0,
        };
        let pending = PendingTransfer {
            transfer,
            merge_msg_partition: 9,
            merge_msg_offset: 100,
        };
        assert_eq!(PendingTransfer::decode(&pending.encode()).unwrap(), pending);

        let tombstone = Tombstone {
            new_person: uuid(0xBBBB),
            merged_at_ms: 1_716_800_000_000,
        };
        assert_eq!(Tombstone::decode(&tombstone.encode()).unwrap(), tombstone);

        let drain = DrainStamp {
            drained_at_ms: 1_716_800_000_000,
        };
        assert_eq!(DrainStamp::decode(&drain.encode()).unwrap(), drain);
        let apply = ApplyStamp {
            applied_at_ms: 1_716_800_000_000,
        };
        assert_eq!(ApplyStamp::decode(&apply.encode()).unwrap(), apply);
    }

    #[test]
    fn garbage_bytes_decode_to_err_not_panic() {
        assert!(PersonMergeEvent::decode(b"not json").is_err());
        assert!(MergeStateTransfer::decode(&[]).is_err());
        assert!(Tombstone::decode(b"{}").is_err());
    }
}
