//! Cascade wire types for the `cohort_cascade_events` topic.
//!
//! [`CascadeMessage`] embeds [`CohortMembershipChange`] via `#[serde(flatten)]` so the inner `change`
//! is produced verbatim to `cohort_membership_changed` while the full message carries the extra
//! cascade fields — one source of truth for the shared keys.

use serde::{Deserialize, Serialize};

use crate::producer::CohortMembershipChange;

/// One `cohort_cascade_events` message: a membership change plus the depth and chain state used to
/// bound and cycle-check cascade re-evaluation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CascadeMessage {
    /// Produced verbatim to `cohort_membership_changed`; flattened into this message's JSON.
    #[serde(flatten)]
    pub change: CohortMembershipChange,
    /// Offset of the triggering input message, carried for replay idempotence. The partition is
    /// implicit in the cascade consumer's assignment.
    pub source_offset: i64,
    /// Hops since the originating flip; `1` for the first cascade, capped at `cohort_cascade_depth_cap`.
    pub depth: u8,
    /// The cohort that initiated this chain; constant across every hop.
    pub originating_cohort_id: i32,
    /// Ordered cohort ids visited in this chain; a hop whose cohort id is already present is dropped
    /// as a cycle.
    pub cascade_chain: Vec<i32>,
}

/// The outcome of a per-hop cascade decision.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CascadeDecision {
    /// Produce `outgoing` to `cohort_cascade_events` and continue the chain.
    Emit { outgoing: CascadeMessage },
    /// Stop the chain here without cascading further.
    Drop { reason: DropReason },
}

/// Why a cascade hop was dropped.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DropReason {
    /// `incoming.depth >= depth_cap`.
    DepthExceeded,
    /// The next cohort id is already in `cascade_chain`.
    CycleDetectedRuntime,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};

    use crate::producer::MembershipStatus;

    const TS: &str = "2026-05-26 12:34:56.789123";

    fn message() -> CascadeMessage {
        CascadeMessage {
            change: CohortMembershipChange {
                team_id: 42,
                cohort_id: 91204,
                person_id: "01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string(),
                last_updated: TS.to_string(),
                status: MembershipStatus::Entered,
            },
            source_offset: 12345,
            depth: 2,
            originating_cohort_id: 91204,
            cascade_chain: vec![91204, 91205],
        }
    }

    #[test]
    fn round_trips_through_json() {
        let msg = message();
        let encoded = serde_json::to_string(&msg).unwrap();
        let decoded: CascadeMessage = serde_json::from_str(&encoded).unwrap();
        assert_eq!(decoded, msg);
    }

    #[test]
    fn flattens_to_exactly_the_nine_keys() {
        let value = serde_json::to_value(message()).unwrap();
        let object = value.as_object().unwrap();

        let mut keys: Vec<&str> = object.keys().map(String::as_str).collect();
        keys.sort_unstable();
        assert_eq!(
            keys,
            vec![
                "cascade_chain",
                "cohort_id",
                "depth",
                "last_updated",
                "originating_cohort_id",
                "person_id",
                "source_offset",
                "status",
                "team_id",
            ],
        );
    }

    #[test]
    fn status_and_chain_serialize_in_their_wire_shapes() {
        let value = serde_json::to_value(message()).unwrap();
        let object = value.as_object().unwrap();
        assert_eq!(object["status"], json!("entered"));
        assert_eq!(object["cascade_chain"], json!([91204, 91205]));
        assert!(object["cascade_chain"]
            .as_array()
            .unwrap()
            .iter()
            .all(Value::is_i64));
    }

    #[test]
    fn left_status_flattens_to_snake_case() {
        let mut msg = message();
        msg.change.status = MembershipStatus::Left;
        let value = serde_json::to_value(msg).unwrap();
        assert_eq!(value["status"], json!("left"));
    }

    #[test]
    fn the_external_five_keys_are_byte_identical_to_serializing_change_alone() {
        // The external keys embedded in the cascade message must equal serializing `change` alone, so
        // the same struct can feed both produces.
        let msg = message();
        let change_only = serde_json::to_value(&msg.change).unwrap();
        let full = serde_json::to_value(&msg).unwrap();
        let full_object = full.as_object().unwrap();

        let extracted: serde_json::Map<String, Value> = change_only
            .as_object()
            .unwrap()
            .keys()
            .map(|key| (key.clone(), full_object[key].clone()))
            .collect();
        assert_eq!(Value::Object(extracted), change_only);
    }
}
