//! Pure protocol decision functions, shared between the coordinator and
//! the stateright model (`personhog-stateright`).
//!
//! The coordinator calls these on state it reads from etcd; the model
//! calls them on checker state. One implementation on both sides means
//! the logic the checker verifies is the logic production runs — the
//! phase-advancement rules cannot drift from their verified form.
//!
//! Every function is a pure predicate over partition-scoped inputs: the
//! caller supplies the acks already filtered to one partition (as
//! `list_*_acks(partition)` returns them).

use std::collections::HashSet;

use crate::types::{
    HandoffState, PodDrainedAck, PodWarmedAck, RegisteredPod, RegisteredRouter, RouterFreezeAck,
};

/// Whether the freeze quorum for `handoff` is met.
///
/// Identity-based: every currently registered router must have acked
/// this partition's freeze. A count comparison would let a stale ack
/// from a departed router (acks are not lease-bound) stand in for a live
/// router that hasn't stashed yet — advancing to Draining while that
/// router still forwards writes to the old owner. Only acks echoing this
/// handoff's id count: an ack left over from a previous handoff of the
/// same partition proves nothing about this one.
///
/// With zero routers there is no traffic to stash, so the freeze quorum
/// is vacuously met. This keeps bootstrap and router-less configurations
/// (e.g. tests exercising only the coordinator+pod) unblocked.
pub fn freeze_quorum_met(
    routers: &[RegisteredRouter],
    freeze_acks: &[RouterFreezeAck],
    handoff: &HandoffState,
) -> bool {
    let acked: HashSet<&str> = freeze_acks
        .iter()
        .filter(|a| a.handoff_id == handoff.handoff_id)
        .map(|a| a.router_name.as_str())
        .collect();
    routers
        .iter()
        .all(|r| acked.contains(r.router_name.as_str()))
}

/// Whether the drain requirement for `handoff` is satisfied.
///
/// "Alive" here means the old owner's etcd registration key still exists
/// (its lease hasn't expired) — not just that it's `Ready`. A `Draining`
/// pod is shutting down gracefully but is still capable of running its
/// handoff handler and writing a `DrainedAck`, and may still have
/// inflight handlers. Bypassing the drain requirement for such a pod
/// would let the coordinator advance to Warming while the old owner is
/// still producing — breaking the protocol's core invariant. Only treat
/// the old owner as drained when its key is genuinely absent, or when it
/// has acked this handoff attempt.
pub fn drain_satisfied(
    registered_pods: &[RegisteredPod],
    drained_acks: &[PodDrainedAck],
    handoff: &HandoffState,
) -> bool {
    match &handoff.old_owner {
        // Defensive: a handoff that reached Draining without an old owner
        // shouldn't exist (Freezing skips Draining when old_owner is
        // None), but if it does, there's nothing to drain.
        None => true,
        Some(name) => {
            let old_owner_present = registered_pods.iter().any(|p| p.pod_name == *name);
            !old_owner_present
                || drained_acks
                    .iter()
                    .any(|a| a.pod_name == *name && a.handoff_id == handoff.handoff_id)
        }
    }
}

/// Whether the new owner has warmed for this handoff attempt.
pub fn warm_satisfied(warmed_acks: &[PodWarmedAck], handoff: &HandoffState) -> bool {
    warmed_acks
        .iter()
        .any(|a| a.pod_name == handoff.new_owner && a.handoff_id == handoff.handoff_id)
}
