//! Wire and column-family value types for the cross-partition merge protocol.
//!
//! - [`PersonMergeEvent`] -- the merge trigger, keyed by P_old.
//! - [`MergeStateTransfer`] -- P_old's packaged per-leaf state, keyed by P_new.
//! - [`PendingTransfer`] -- `cf_pending_transfers` outbox value.
//! - [`Tombstone`] -- `cf_merge_tombstones` value for straggler redirect.
//! - [`DrainStamp`] / [`ApplyStamp`] -- idempotence markers (key presence is the guard).

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::filters::reverse_index::TeamFilters;
use crate::filters::CohortId;
use crate::stage1::key::LeafStateKey;
use crate::stage1::person_record::PersonDedup;
use crate::stage1::state::{StateVariant, StatefulRecord};

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

/// One persisted membership register carried alongside P_old's leaf state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransferMembershipRegister {
    pub cohort_id: i32,
    pub in_cohort: bool,
    /// Enough source semantics for a receiver to materialize the scan register without consulting
    /// a potentially older or not-yet-loaded filter catalog.
    #[serde(default)]
    pub kind: TransferMembershipRegisterKind,
}

/// Source semantics for a transferred membership register.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TransferMembershipRegisterKind {
    SingleLeafBehavioral,
    SingleLeafPersonProperty,
    #[default]
    Composable,
}

/// Persisted source provenance for a merge-carried register. The local Stage 2 row may use a
/// conservative bit from the receiver's current catalog shape; this value keeps the original wire
/// bit and kind available for another catalogless hop.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct TransferredRegisterProvenance {
    pub kind: TransferMembershipRegisterKind,
    pub in_cohort: bool,
    expected_primary: Vec<u8>,
}

impl TransferredRegisterProvenance {
    pub fn new(register: TransferMembershipRegister, expected_primary: &[u8]) -> Self {
        Self {
            kind: register.kind,
            in_cohort: register.in_cohort,
            expected_primary: expected_primary.to_vec(),
        }
    }

    pub fn encode(&self) -> Vec<u8> {
        let mut encoded = Vec::with_capacity(2 + self.expected_primary.len());
        encoded.push(self.kind.encode()[0]);
        encoded.push(self.in_cohort as u8);
        encoded.extend_from_slice(&self.expected_primary);
        encoded
    }

    pub fn decode(bytes: &[u8]) -> Option<Self> {
        let [kind, in_cohort, expected_primary @ ..] = bytes else {
            return None;
        };
        Some(Self {
            kind: TransferMembershipRegisterKind::decode(&[*kind])?,
            in_cohort: match *in_cohort {
                0 => false,
                1 => true,
                _ => return None,
            },
            expected_primary: expected_primary.to_vec(),
        })
    }

    pub fn matches_primary(&self, primary: &[u8]) -> bool {
        self.expected_primary == primary
    }
}

impl TransferMembershipRegisterKind {
    /// The safe initial value for a missing survivor register. Behavioral single-leaf state carries
    /// its exact bit; person-property and composable state must be recomputed for the survivor.
    pub const fn materialized_bit(self, transferred_bit: bool) -> bool {
        match self {
            Self::SingleLeafBehavioral => transferred_bit,
            Self::SingleLeafPersonProperty | Self::Composable => false,
        }
    }

    /// Compact persisted form used by the catalog-independent Stage 2 transfer inventory.
    pub const fn encode(self) -> [u8; 1] {
        [match self {
            Self::SingleLeafBehavioral => 1,
            Self::SingleLeafPersonProperty => 2,
            Self::Composable => 3,
        }]
    }

    pub fn decode(bytes: &[u8]) -> Option<Self> {
        match bytes {
            [1] => Some(Self::SingleLeafBehavioral),
            [2] => Some(Self::SingleLeafPersonProperty),
            [3] => Some(Self::Composable),
            _ => None,
        }
    }

    /// Derive the register semantics from one catalog snapshot. `None` means the cohort does not
    /// currently register membership.
    pub(crate) fn from_filters(filters: &TeamFilters, cohort_id: CohortId) -> Option<Self> {
        match filters.eligibility.get(&cohort_id)? {
            crate::stage2::CohortEligibility::SingleLeaf(lsk) => {
                Some(match filters.by_lsk.get(lsk).map(|meta| meta.variant) {
                    Some(StateVariant::PersonProperty) => Self::SingleLeafPersonProperty,
                    Some(
                        StateVariant::BehavioralSingle
                        | StateVariant::BehavioralDailyBuckets
                        | StateVariant::BehavioralCompressedHistory,
                    ) => Self::SingleLeafBehavioral,
                    None => Self::Composable,
                })
            }
            crate::stage2::CohortEligibility::Stage2Composable
            | crate::stage2::CohortEligibility::Stage2ComposableRef => Some(Self::Composable),
            crate::stage2::CohortEligibility::Excluded(_) => None,
        }
    }
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
    /// P_old's materialized behavioral membership rows. Carrying these preserves the reconcile scan
    /// domain when no leaf transition recreates a composable row, and across catalog refreshes
    /// between drain and apply. An apply uses them only to fill a missing survivor register;
    /// post-merge evaluation remains authoritative.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub membership_registers: Vec<TransferMembershipRegister>,
    /// Cross-partition forward hops taken so far when `new_person_uuid` was itself tombstoned at
    /// apply time (chained merge `A → B → C` where `B → C` drained before `A → B` applied). Bounded
    /// by [`crate::merge::apply_handler::MAX_TRANSFER_FORWARD_HOPS`]. `#[serde(default)]`: a message
    /// without the field decodes to `0`, so the field is JSON-compatible both ways.
    #[serde(default)]
    pub forward_hops: u8,
    /// P_old's person-record replay-dedup, carried so a straggler routed to P_new after the merge
    /// deduplicates against P_old's high-water marks. Only the offsets travel — never P_old's matched
    /// set, fingerprints, or stamp; P_new re-evaluates the person lazily. `#[serde(default,
    /// skip_serializing_if)]`: wire-compatible both ways, and a person with no record contributes no
    /// field.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub person_dedup: Option<PersonDedup>,
}

impl MergeStateTransfer {
    /// Whether applying this transfer can change survivor state.
    pub fn has_payload(&self) -> bool {
        !self.leaves.is_empty()
            || !self.membership_registers.is_empty()
            || self.person_dedup.is_some()
    }
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
    use std::collections::BTreeMap;

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
    fn membership_register_kind_inventory_codec_is_closed() {
        for kind in [
            TransferMembershipRegisterKind::SingleLeafBehavioral,
            TransferMembershipRegisterKind::SingleLeafPersonProperty,
            TransferMembershipRegisterKind::Composable,
        ] {
            assert_eq!(
                TransferMembershipRegisterKind::decode(&kind.encode()),
                Some(kind)
            );
        }
        assert_eq!(TransferMembershipRegisterKind::decode(&[]), None);
        assert_eq!(TransferMembershipRegisterKind::decode(&[0]), None);
        assert_eq!(TransferMembershipRegisterKind::decode(&[1, 2]), None);
    }

    #[test]
    fn transferred_register_provenance_codec_preserves_kind_and_bit() {
        for provenance in [
            TransferredRegisterProvenance::new(
                TransferMembershipRegister {
                    cohort_id: 1,
                    in_cohort: true,
                    kind: TransferMembershipRegisterKind::SingleLeafBehavioral,
                },
                b"primary-a",
            ),
            TransferredRegisterProvenance::new(
                TransferMembershipRegister {
                    cohort_id: 1,
                    in_cohort: false,
                    kind: TransferMembershipRegisterKind::SingleLeafPersonProperty,
                },
                b"primary-b",
            ),
            TransferredRegisterProvenance::new(
                TransferMembershipRegister {
                    cohort_id: 1,
                    in_cohort: true,
                    kind: TransferMembershipRegisterKind::Composable,
                },
                b"primary-c",
            ),
        ] {
            assert_eq!(
                TransferredRegisterProvenance::decode(&provenance.encode()),
                Some(provenance.clone()),
            );
            assert!(provenance.matches_primary(&provenance.expected_primary));
        }
        assert_eq!(TransferredRegisterProvenance::decode(&[1]), None);
        assert_eq!(TransferredRegisterProvenance::decode(&[1, 2]), None);
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
            membership_registers: vec![TransferMembershipRegister {
                cohort_id: 9,
                in_cohort: false,
                kind: TransferMembershipRegisterKind::Composable,
            }],
            forward_hops: 0,

            person_dedup: None,
        };
        let decoded = MergeStateTransfer::decode(&transfer.encode()).unwrap();
        assert_eq!(decoded, transfer);
        let wire: serde_json::Value = serde_json::from_slice(&transfer.encode()).unwrap();
        assert_eq!(
            wire["membership_registers"][0]["kind"],
            serde_json::json!("composable"),
            "the self-describing register kind is pinned on the wire",
        );
        assert_eq!(
            decoded.leaves[0].record,
            single_record(),
            "the leaf's StatefulRecord transfers whole, so redirect_dedup chains for free",
        );
        assert_eq!(decoded.membership_registers, transfer.membership_registers);
        assert!(decoded.has_payload());
    }

    #[test]
    fn register_only_transfer_is_not_empty() {
        let transfer = MergeStateTransfer {
            team_id: 7,
            old_person_uuid: uuid(0xAAAA),
            new_person_uuid: uuid(0xBBBB),
            merged_at_ms: 1,
            source_partition: 3,
            source_offset: 4,
            leaves: vec![],
            membership_registers: vec![TransferMembershipRegister {
                cohort_id: 9,
                in_cohort: false,
                kind: TransferMembershipRegisterKind::SingleLeafBehavioral,
            }],
            forward_hops: 0,
            person_dedup: None,
        };

        assert!(transfer.has_payload());
    }

    #[test]
    fn transfer_round_trips_a_non_empty_person_dedup() {
        // Every other round-trip sets `person_dedup: None`. `PersonDedup.redirect_dedup` carries
        // `#[serde(default, skip_serializing_if = "BTreeMap::is_empty")]`; a non-empty round-trip is
        // what guards that derive. If it silently dropped the field, the None-only tests would all
        // still pass, so assert the offsets survive the wire whole.
        let mut redirect_dedup = BTreeMap::new();
        redirect_dedup.insert(
            uuid(0xCCCC),
            AppliedOffsets::from_sorted_entries(vec![(3, 300)]),
        );
        let transfer = MergeStateTransfer {
            team_id: 7,
            old_person_uuid: uuid(0xAAAA),
            new_person_uuid: uuid(0xBBBB),
            merged_at_ms: 1_716_800_000_000,
            source_partition: 17,
            source_offset: 12_345,
            leaves: vec![],
            membership_registers: vec![],
            forward_hops: 0,
            person_dedup: Some(PersonDedup {
                applied_offsets: AppliedOffsets::from_sorted_entries(vec![(1, 100), (2, 200)]),
                redirect_dedup,
            }),
        };
        let decoded = MergeStateTransfer::decode(&transfer.encode()).unwrap();
        assert_eq!(
            decoded, transfer,
            "a non-empty person_dedup (direct + redirect offsets) survives the wire round-trip",
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
        assert!(
            decoded.membership_registers.is_empty(),
            "older transfers default to no carried register rows",
        );
    }

    #[test]
    fn transfer_tolerates_unknown_fields_so_a_new_sender_cannot_poison_an_old_receiver() {
        // A sender may add fields to the transfer wire; a receiver that does not know them must
        // ignore them, not reject the whole message. This pins the absence of
        // `#[serde(deny_unknown_fields)]` on MergeStateTransfer — adding it would silently drop every
        // cross-partition merge whose transfer carries an unknown field.
        let json = serde_json::json!({
            "team_id": 7,
            "old_person_uuid": uuid(0xAAAA).to_string(),
            "new_person_uuid": uuid(0xBBBB).to_string(),
            "merged_at_ms": 1_716_800_000_000_i64,
            "source_partition": 17,
            "source_offset": 12_345,
            "leaves": [],
            "membership_registers": [{ "cohort_id": 9, "in_cohort": false, "kind": "composable" }],
            "some_future_field": { "added": "by a newer sender" },
        });
        let decoded = MergeStateTransfer::decode(&serde_json::to_vec(&json).unwrap())
            .expect("an unknown extra field must not fail the decode");
        assert_eq!(
            decoded.membership_registers,
            vec![TransferMembershipRegister {
                cohort_id: 9,
                in_cohort: false,
                kind: TransferMembershipRegisterKind::Composable,
            }],
            "the known additive field still round-trips alongside the ignored unknown one",
        );
    }

    #[test]
    fn register_without_kind_defaults_to_safe_composable_semantics() {
        let register: TransferMembershipRegister = serde_json::from_value(serde_json::json!({
            "cohort_id": 9,
            "in_cohort": true,
        }))
        .unwrap();
        assert_eq!(register.kind, TransferMembershipRegisterKind::Composable);
        assert!(!register.kind.materialized_bit(register.in_cohort));
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
            membership_registers: vec![],
            forward_hops: 0,

            person_dedup: None,
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
