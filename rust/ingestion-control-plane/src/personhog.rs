//! Personhog topology view: one consistent etcd snapshot of the
//! coordination prefix, interpreted with the same types and pure
//! predicates the coordinator itself runs (`personhog-coordination`), so
//! the diagnostics cannot drift from the protocol.

use std::collections::HashMap;
use std::time::Duration;

use chrono::{DateTime, Utc};
use etcd_client::{Client, GetOptions};
use personhog_coordination::protocol::{
    drain_satisfied, freeze_quorum_met, missing_freeze_ackers, past_phase_deadline, warm_satisfied,
};
use personhog_coordination::types::{
    HandoffPhase, HandoffState, LeaderInfo, PartitionAssignment, PodDrainedAck, PodStatus,
    PodWarmedAck, RegisteredPod, RegisteredRouter, RouterFreezeAck,
};
use serde::Serialize;

/// A `Complete` handoff older than this without cleanup suggests the
/// coordinator is not running its cleanup pass.
const COMPLETE_CLEANUP_GRACE: Duration = Duration::from_secs(60);

pub struct Deadlines {
    pub handoff: Duration,
    pub warming: Duration,
}

/// One raw key-value from the coordination prefix, as fetched.
pub struct RawKv {
    pub key: String,
    pub value: Vec<u8>,
    pub lease: i64,
}

/// The freeze-quorum membership a handoff requires, from the same
/// snapshot. `None` — nothing recorded, or a reference whose record is
/// absent — is the coordinator's own fallback: require every live
/// router.
fn resolve_quorum<'a>(
    quorums: &'a HashMap<String, Vec<String>>,
    handoff: &'a HandoffState,
) -> Option<&'a [String]> {
    match &handoff.freeze_quorum_ref {
        Some(id) => quorums.get(id).map(Vec::as_slice),
        None => handoff.freeze_quorum.as_deref(),
    }
}

/// The coordination prefix, parsed into records. Unparseable or unknown
/// keys are carried as findings instead of failing the snapshot — an ops
/// tool must render a broken keyspace, not error on it.
#[derive(Default)]
pub struct RawSnapshot {
    pub pods: Vec<(RegisteredPod, i64)>,
    pub routers: Vec<(RegisteredRouter, i64)>,
    pub assignments: Vec<PartitionAssignment>,
    pub handoffs: Vec<HandoffState>,
    /// Freeze-quorum membership by record id, so a handoff that refers
    /// to one can be judged from the same snapshot.
    pub freeze_quorums: HashMap<String, Vec<String>>,
    pub freeze_acks: Vec<RouterFreezeAck>,
    pub drained_acks: Vec<PodDrainedAck>,
    pub warmed_acks: Vec<PodWarmedAck>,
    pub leader: Option<(LeaderInfo, i64)>,
    pub total_partitions: Option<u32>,
    pub parse_errors: Vec<String>,
    pub unknown_keys: Vec<String>,
    pub revision: i64,
}

pub fn parse_snapshot(kvs: &[RawKv], prefix: &str, revision: i64) -> RawSnapshot {
    let mut snapshot = RawSnapshot {
        revision,
        ..RawSnapshot::default()
    };

    fn parse<T: serde::de::DeserializeOwned>(kv: &RawKv, errors: &mut Vec<String>) -> Option<T> {
        match serde_json::from_slice(&kv.value) {
            Ok(value) => Some(value),
            Err(e) => {
                errors.push(format!("unparseable record at {}: {e}", kv.key));
                None
            }
        }
    }

    for kv in kvs {
        let Some(suffix) = kv.key.strip_prefix(prefix) else {
            snapshot.unknown_keys.push(kv.key.clone());
            continue;
        };
        let errors = &mut snapshot.parse_errors;
        if suffix.starts_with("pods/") {
            if let Some(pod) = parse::<RegisteredPod>(kv, errors) {
                snapshot.pods.push((pod, kv.lease));
            }
        } else if suffix.starts_with("routers/") {
            if let Some(router) = parse::<RegisteredRouter>(kv, errors) {
                snapshot.routers.push((router, kv.lease));
            }
        } else if suffix.starts_with("assignments/") {
            if let Some(assignment) = parse::<PartitionAssignment>(kv, errors) {
                snapshot.assignments.push(assignment);
            }
        } else if suffix.starts_with("handoffs/") {
            if let Some(handoff) = parse::<HandoffState>(kv, errors) {
                snapshot.handoffs.push(handoff);
            }
        } else if let Some(id) = suffix.strip_prefix("freeze_quorums/") {
            if let Some(members) = parse::<Vec<String>>(kv, errors) {
                snapshot.freeze_quorums.insert(id.to_string(), members);
            }
        } else if suffix.starts_with("freeze_acks/") {
            if let Some(ack) = parse::<RouterFreezeAck>(kv, errors) {
                snapshot.freeze_acks.push(ack);
            }
        } else if suffix.starts_with("drained_acks/") {
            if let Some(ack) = parse::<PodDrainedAck>(kv, errors) {
                snapshot.drained_acks.push(ack);
            }
        } else if suffix.starts_with("warmed_acks/") {
            if let Some(ack) = parse::<PodWarmedAck>(kv, errors) {
                snapshot.warmed_acks.push(ack);
            }
        } else if suffix == "coordinator/leader" {
            if let Some(leader) = parse::<LeaderInfo>(kv, errors) {
                snapshot.leader = Some((leader, kv.lease));
            }
        } else if suffix == "config/total_partitions" {
            match std::str::from_utf8(&kv.value)
                .ok()
                .and_then(|s| s.parse::<u32>().ok())
            {
                Some(count) => snapshot.total_partitions = Some(count),
                None => errors.push(format!("invalid total_partitions at {}", kv.key)),
            }
        } else {
            snapshot.unknown_keys.push(kv.key.clone());
        }
    }
    snapshot
}

#[derive(Serialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Error,
    Warning,
    Info,
}

#[derive(Serialize, Debug)]
pub struct Issue {
    pub severity: Severity,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub partition: Option<u32>,
    pub summary: String,
}

#[derive(Serialize)]
pub struct LeaderView {
    pub holder: String,
    pub lease_id: i64,
    pub lease_ttl_secs: Option<i64>,
}

#[derive(Serialize)]
pub struct PodView {
    pub pod_name: String,
    pub status: String,
    pub registered_at: i64,
    pub last_heartbeat: i64,
    pub advertise_address: Option<String>,
    pub lease_ttl_secs: Option<i64>,
    pub partitions: Vec<u32>,
}

#[derive(Serialize)]
pub struct RouterView {
    pub router_name: String,
    pub registered_at: i64,
    pub last_heartbeat: i64,
    pub lease_ttl_secs: Option<i64>,
}

#[derive(Serialize)]
pub struct HandoffView {
    pub old_owner: Option<String>,
    pub new_owner: String,
    pub phase: HandoffPhase,
    pub handoff_id: String,
    pub started_at: i64,
    pub phase_age_secs: Option<i64>,
    pub past_deadline: bool,
    /// What the protocol is currently waiting for, in operator terms.
    pub waiting_on: Option<String>,
    pub missing_freeze_ackers: Vec<String>,
    pub old_owner_registered: Option<bool>,
    pub new_owner_registered: bool,
}

#[derive(Serialize)]
pub struct PartitionView {
    pub partition: u32,
    pub owner: Option<String>,
    pub owner_registered: Option<bool>,
    pub advertise_address: Option<String>,
    pub handoff: Option<HandoffView>,
}

#[derive(Serialize)]
pub struct TopologyView {
    pub fetched_at: DateTime<Utc>,
    pub revision: i64,
    pub prefix: String,
    pub total_partitions: Option<u32>,
    pub leader: Option<LeaderView>,
    pub pods: Vec<PodView>,
    pub routers: Vec<RouterView>,
    pub partitions: Vec<PartitionView>,
    pub issues: Vec<Issue>,
}

fn phase_age_secs(handoff: &HandoffState, now_ms: i64) -> Option<i64> {
    let entered_ms = if handoff.phase_entered_at_ms > 0 {
        handoff.phase_entered_at_ms
    } else if handoff.started_at > 0 {
        handoff.started_at.saturating_mul(1000)
    } else {
        return None;
    };
    Some(now_ms.saturating_sub(entered_ms) / 1000)
}

/// What a non-terminal handoff is waiting for, using the coordinator's
/// own advance predicates. A phase whose predicate is already satisfied
/// is waiting on the coordinator itself — the signal that distinguishes
/// a stuck participant from a stuck coordinator.
fn waiting_on(
    handoff: &HandoffState,
    routers: &[RegisteredRouter],
    pods: &[RegisteredPod],
    freeze_acks: &[RouterFreezeAck],
    drained_acks: &[PodDrainedAck],
    warmed_acks: &[PodWarmedAck],
    quorum: Option<&[String]>,
) -> Option<String> {
    match handoff.phase {
        HandoffPhase::Freezing => {
            if freeze_quorum_met(routers, freeze_acks, handoff, quorum) {
                Some("freeze quorum met; waiting on the coordinator to advance".to_string())
            } else {
                let missing = missing_freeze_ackers(routers, freeze_acks, handoff, quorum);
                Some(format!(
                    "waiting on freeze acks from {}",
                    missing.join(", ")
                ))
            }
        }
        HandoffPhase::Draining => {
            if drain_satisfied(pods, drained_acks, handoff) {
                Some("drain satisfied; waiting on the coordinator to advance".to_string())
            } else {
                let owner = handoff.old_owner.as_deref().unwrap_or("?");
                Some(format!("waiting on a drained ack from old owner {owner}"))
            }
        }
        HandoffPhase::Warming => {
            if warm_satisfied(warmed_acks, handoff) {
                Some("warmed; waiting on the coordinator to complete".to_string())
            } else {
                Some(format!(
                    "waiting on a warmed ack from new owner {}",
                    handoff.new_owner
                ))
            }
        }
        HandoffPhase::Complete => None,
    }
}

pub fn derive_view(
    raw: RawSnapshot,
    lease_ttls: &HashMap<i64, i64>,
    prefix: &str,
    now_ms: i64,
    deadlines: &Deadlines,
) -> TopologyView {
    let mut issues: Vec<Issue> = Vec::new();

    for error in &raw.parse_errors {
        issues.push(Issue {
            severity: Severity::Error,
            partition: None,
            summary: error.clone(),
        });
    }
    if !raw.unknown_keys.is_empty() {
        issues.push(Issue {
            severity: Severity::Info,
            partition: None,
            summary: format!(
                "{} key(s) under the prefix outside the known layout: {}",
                raw.unknown_keys.len(),
                raw.unknown_keys.join(", ")
            ),
        });
    }

    if raw.total_partitions.is_none() {
        issues.push(Issue {
            severity: Severity::Error,
            partition: None,
            summary: "config/total_partitions is missing: the coordinator cannot plan, and \
                      leaders and routers fail at startup"
                .to_string(),
        });
    }
    if raw.leader.is_none() && (!raw.pods.is_empty() || !raw.routers.is_empty()) {
        issues.push(Issue {
            severity: Severity::Warning,
            partition: None,
            summary: "no coordinator leader is elected".to_string(),
        });
    }

    let pods: Vec<RegisteredPod> = raw.pods.iter().map(|(p, _)| p.clone()).collect();
    let routers: Vec<RegisteredRouter> = raw.routers.iter().map(|(r, _)| r.clone()).collect();
    let pod_registered = |name: &str| pods.iter().any(|p| p.pod_name == name);

    for (pod, _) in &raw.pods {
        if pod.status == PodStatus::Draining {
            issues.push(Issue {
                severity: Severity::Info,
                partition: None,
                summary: format!("pod {} is draining", pod.pod_name),
            });
        }
    }

    let assignments_by_partition: HashMap<u32, &PartitionAssignment> =
        raw.assignments.iter().map(|a| (a.partition, a)).collect();
    let handoffs_by_partition: HashMap<u32, &HandoffState> =
        raw.handoffs.iter().map(|h| (h.partition, h)).collect();

    // Partitions worth a row: everything under the configured count, plus
    // anything that has state anyway (misconfiguration shows itself).
    let mut partition_ids: Vec<u32> = (0..raw.total_partitions.unwrap_or(0)).collect();
    for partition in assignments_by_partition
        .keys()
        .chain(handoffs_by_partition.keys())
    {
        if !partition_ids.contains(partition) {
            partition_ids.push(*partition);
        }
    }
    partition_ids.sort_unstable();

    let mut partitions: Vec<PartitionView> = Vec::with_capacity(partition_ids.len());
    for partition in partition_ids {
        let assignment = assignments_by_partition.get(&partition);
        let handoff = handoffs_by_partition.get(&partition);

        if let Some(total) = raw.total_partitions {
            if partition >= total && (assignment.is_some() || handoff.is_some()) {
                issues.push(Issue {
                    severity: Severity::Warning,
                    partition: Some(partition),
                    summary: format!(
                        "partition {partition} has state but total_partitions is {total}"
                    ),
                });
            }
            if partition < total && assignment.is_none() && handoff.is_none() {
                issues.push(Issue {
                    severity: Severity::Warning,
                    partition: Some(partition),
                    summary: format!("partition {partition} has no assignment and no handoff"),
                });
            }
        }

        let owner_registered = assignment.map(|a| pod_registered(&a.owner));
        if let (Some(assignment), Some(false), None) = (assignment, owner_registered, handoff) {
            issues.push(Issue {
                severity: Severity::Error,
                partition: Some(partition),
                summary: format!(
                    "partition {partition} owner {} is not registered and no handoff is \
                     replanning it",
                    assignment.owner
                ),
            });
        }

        let freeze_acks: Vec<RouterFreezeAck> = raw
            .freeze_acks
            .iter()
            .filter(|a| a.partition == partition)
            .cloned()
            .collect();
        let drained_acks: Vec<PodDrainedAck> = raw
            .drained_acks
            .iter()
            .filter(|a| a.partition == partition)
            .cloned()
            .collect();
        let warmed_acks: Vec<PodWarmedAck> = raw
            .warmed_acks
            .iter()
            .filter(|a| a.partition == partition)
            .cloned()
            .collect();

        // Acks not matching the live handoff attempt are inert by design
        // (quorum checks correlate by handoff_id); surface them so an
        // operator doesn't mistake them for progress.
        let current_id = handoff.map(|h| h.handoff_id.as_str());
        let stale_acks = freeze_acks
            .iter()
            .map(|a| a.handoff_id.as_str())
            .chain(drained_acks.iter().map(|a| a.handoff_id.as_str()))
            .chain(warmed_acks.iter().map(|a| a.handoff_id.as_str()))
            .filter(|id| Some(*id) != current_id)
            .count();
        if stale_acks > 0 {
            issues.push(Issue {
                severity: Severity::Info,
                partition: Some(partition),
                summary: format!(
                    "partition {partition} has {stale_acks} ack(s) for another handoff attempt \
                     (inert; cleaned up with the record)"
                ),
            });
        }

        let handoff_view = handoff.map(|h| {
            let past_deadline =
                past_phase_deadline(h, now_ms, deadlines.handoff, deadlines.warming);
            let age = phase_age_secs(h, now_ms);
            let waiting = waiting_on(
                h,
                &routers,
                &pods,
                &freeze_acks,
                &drained_acks,
                &warmed_acks,
                resolve_quorum(&raw.freeze_quorums, h),
            );
            let new_owner_registered = pod_registered(&h.new_owner);

            if past_deadline {
                issues.push(Issue {
                    severity: Severity::Error,
                    partition: Some(partition),
                    summary: format!(
                        "handoff for partition {partition} is past its {:?} deadline ({}): {}",
                        h.phase,
                        age.map(|secs| format!("{secs}s in phase"))
                            .unwrap_or_else(|| "age unknown".to_string()),
                        waiting.as_deref().unwrap_or("unknown wait")
                    ),
                });
            }
            if h.phase != HandoffPhase::Complete && !new_owner_registered {
                issues.push(Issue {
                    severity: Severity::Warning,
                    partition: Some(partition),
                    summary: format!(
                        "handoff for partition {partition} targets unregistered pod {}; the \
                         planner will cancel or replace it",
                        h.new_owner
                    ),
                });
            }
            if h.phase == HandoffPhase::Complete
                && age.is_some_and(|secs| secs > COMPLETE_CLEANUP_GRACE.as_secs() as i64)
            {
                issues.push(Issue {
                    severity: Severity::Warning,
                    partition: Some(partition),
                    summary: format!(
                        "completed handoff for partition {partition} has not been cleaned up; \
                         the coordinator may not be running"
                    ),
                });
            }

            HandoffView {
                old_owner: h.old_owner.clone(),
                new_owner: h.new_owner.clone(),
                phase: h.phase,
                handoff_id: h.handoff_id.clone(),
                started_at: h.started_at,
                phase_age_secs: age,
                past_deadline,
                waiting_on: waiting,
                missing_freeze_ackers: missing_freeze_ackers(
                    &routers,
                    &freeze_acks,
                    h,
                    resolve_quorum(&raw.freeze_quorums, h),
                ),
                old_owner_registered: h.old_owner.as_deref().map(pod_registered),
                new_owner_registered,
            }
        });

        partitions.push(PartitionView {
            partition,
            owner: assignment.map(|a| a.owner.clone()),
            owner_registered,
            advertise_address: assignment.and_then(|a| a.advertise_address.clone()),
            handoff: handoff_view,
        });
    }

    let mut pod_partitions: HashMap<&str, Vec<u32>> = HashMap::new();
    for assignment in &raw.assignments {
        pod_partitions
            .entry(assignment.owner.as_str())
            .or_default()
            .push(assignment.partition);
    }

    let severity_rank = |severity: Severity| match severity {
        Severity::Error => 0,
        Severity::Warning => 1,
        Severity::Info => 2,
    };
    issues.sort_by_key(|issue| (severity_rank(issue.severity), issue.partition));

    TopologyView {
        fetched_at: Utc::now(),
        revision: raw.revision,
        prefix: prefix.to_string(),
        total_partitions: raw.total_partitions,
        leader: raw.leader.as_ref().map(|(leader, _)| LeaderView {
            holder: leader.holder.clone(),
            lease_id: leader.lease_id,
            lease_ttl_secs: lease_ttls.get(&leader.lease_id).copied(),
        }),
        pods: raw
            .pods
            .iter()
            .map(|(pod, lease)| {
                let mut partitions = pod_partitions
                    .get(pod.pod_name.as_str())
                    .cloned()
                    .unwrap_or_default();
                partitions.sort_unstable();
                PodView {
                    pod_name: pod.pod_name.clone(),
                    status: format!("{:?}", pod.status),
                    registered_at: pod.registered_at,
                    last_heartbeat: pod.last_heartbeat,
                    advertise_address: pod.advertise_address.clone(),
                    lease_ttl_secs: lease_ttls.get(lease).copied(),
                    partitions,
                }
            })
            .collect(),
        routers: raw
            .routers
            .iter()
            .map(|(router, lease)| RouterView {
                router_name: router.router_name.clone(),
                registered_at: router.registered_at,
                last_heartbeat: router.last_heartbeat,
                lease_ttl_secs: lease_ttls.get(lease).copied(),
            })
            .collect(),
        partitions,
        issues,
    }
}

/// The lease ids the view wants remaining TTLs for.
pub fn lease_ids(raw: &RawSnapshot) -> Vec<i64> {
    let mut ids: Vec<i64> = raw
        .pods
        .iter()
        .map(|(_, lease)| *lease)
        .chain(raw.routers.iter().map(|(_, lease)| *lease))
        .chain(raw.leader.iter().map(|(_, lease)| *lease))
        .filter(|lease| *lease != 0)
        .collect();
    ids.sort_unstable();
    ids.dedup();
    ids
}

pub async fn fetch_topology(
    client: &Client,
    prefix: &str,
    deadlines: &Deadlines,
) -> anyhow::Result<TopologyView> {
    let resp = client
        .clone()
        .get(prefix, Some(GetOptions::new().with_prefix()))
        .await?;
    let revision = resp.header().map(|h| h.revision()).unwrap_or(0);
    let kvs: Vec<RawKv> = resp
        .kvs()
        .iter()
        .map(|kv| RawKv {
            key: String::from_utf8_lossy(kv.key()).into_owned(),
            value: kv.value().to_vec(),
            lease: kv.lease(),
        })
        .collect();
    let raw = parse_snapshot(&kvs, prefix, revision);

    let mut lease_ttls: HashMap<i64, i64> = HashMap::new();
    for lease in lease_ids(&raw) {
        // A lease can expire between the snapshot and this lookup; the
        // view just shows no TTL for it.
        if let Ok(lease_info) = client.clone().lease_time_to_live(lease, None).await {
            if lease_info.ttl() >= 0 {
                lease_ttls.insert(lease, lease_info.ttl());
            }
        }
    }

    Ok(derive_view(
        raw,
        &lease_ttls,
        prefix,
        Utc::now().timestamp_millis(),
        deadlines,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    const PREFIX: &str = "/personhog/";

    fn deadlines() -> Deadlines {
        Deadlines {
            handoff: Duration::from_secs(120),
            warming: Duration::from_secs(1800),
        }
    }

    fn kv(suffix: &str, value: serde_json::Value, lease: i64) -> RawKv {
        RawKv {
            key: format!("{PREFIX}{suffix}"),
            value: serde_json::to_vec(&value).unwrap(),
            lease,
        }
    }

    fn pod_kv(name: &str) -> RawKv {
        kv(
            &format!("pods/{name}"),
            serde_json::json!({
                "pod_name": name,
                "status": "Ready",
                "registered_at": 100,
                "last_heartbeat": 200,
            }),
            7,
        )
    }

    fn router_kv(name: &str) -> RawKv {
        kv(
            &format!("routers/{name}"),
            serde_json::json!({
                "router_name": name,
                "registered_at": 100,
                "last_heartbeat": 200,
            }),
            8,
        )
    }

    fn assignment_kv(partition: u32, owner: &str) -> RawKv {
        kv(
            &format!("assignments/{partition}"),
            serde_json::json!({
                "partition": partition,
                "owner": owner,
                "status": "Active",
            }),
            0,
        )
    }

    fn handoff_kv(
        partition: u32,
        phase: &str,
        old_owner: Option<&str>,
        new_owner: &str,
        quorum: &[&str],
        phase_entered_at_ms: i64,
    ) -> RawKv {
        kv(
            &format!("handoffs/{partition}"),
            serde_json::json!({
                "partition": partition,
                "old_owner": old_owner,
                "new_owner": new_owner,
                "phase": phase,
                "started_at": 1,
                "handoff_id": "hid-1",
                "freeze_quorum": quorum,
                "phase_entered_at_ms": phase_entered_at_ms,
            }),
            0,
        )
    }

    fn total_partitions_kv(count: u32) -> RawKv {
        RawKv {
            key: format!("{PREFIX}config/total_partitions"),
            value: count.to_string().into_bytes(),
            lease: 0,
        }
    }

    fn view(kvs: &[RawKv], now_ms: i64) -> TopologyView {
        let raw = parse_snapshot(kvs, PREFIX, 42);
        derive_view(raw, &HashMap::new(), PREFIX, now_ms, &deadlines())
    }

    fn issue_summaries(view: &TopologyView, severity: Severity) -> Vec<&str> {
        view.issues
            .iter()
            .filter(|issue| issue.severity == severity)
            .map(|issue| issue.summary.as_str())
            .collect()
    }

    #[test]
    fn a_stuck_freezing_handoff_names_the_missing_router() {
        let kvs = vec![
            total_partitions_kv(1),
            pod_kv("pod-a"),
            pod_kv("pod-b"),
            router_kv("router-0"),
            router_kv("router-1"),
            assignment_kv(0, "pod-a"),
            handoff_kv(
                0,
                "Freezing",
                Some("pod-a"),
                "pod-b",
                &["router-0", "router-1"],
                1_000,
            ),
            kv(
                "freeze_acks/0/router-0",
                serde_json::json!({
                    "router_name": "router-0",
                    "partition": 0,
                    "acked_at": 2,
                    "handoff_id": "hid-1",
                }),
                0,
            ),
        ];
        // 10 minutes in phase: past the 120s Freezing deadline.
        let topology = view(&kvs, 601_000);

        let handoff = topology.partitions[0].handoff.as_ref().unwrap();
        assert!(handoff.past_deadline);
        assert_eq!(handoff.missing_freeze_ackers, vec!["router-1"]);
        assert!(handoff
            .waiting_on
            .as_ref()
            .unwrap()
            .contains("waiting on freeze acks from router-1"));
        assert!(issue_summaries(&topology, Severity::Error)
            .iter()
            .any(|s| s.contains("past its Freezing deadline")));
    }

    #[test]
    fn a_satisfied_phase_points_at_the_coordinator() {
        let kvs = vec![
            total_partitions_kv(1),
            pod_kv("pod-b"),
            assignment_kv(0, "pod-b"),
            // Draining with a dead old owner: drain is vacuously satisfied,
            // so the wait is on the coordinator itself.
            handoff_kv(0, "Draining", Some("pod-gone"), "pod-b", &[], 1_000),
        ];
        let topology = view(&kvs, 10_000);

        let handoff = topology.partitions[0].handoff.as_ref().unwrap();
        assert_eq!(
            handoff.waiting_on.as_deref(),
            Some("drain satisfied; waiting on the coordinator to advance")
        );
    }

    #[test]
    fn a_dead_owner_without_a_handoff_is_an_error_and_with_one_is_not() {
        let kvs = vec![
            total_partitions_kv(2),
            pod_kv("pod-b"),
            assignment_kv(0, "pod-gone"),
            assignment_kv(1, "pod-gone"),
            handoff_kv(1, "Warming", Some("pod-gone"), "pod-b", &[], 9_000),
        ];
        let topology = view(&kvs, 10_000);

        let errors = issue_summaries(&topology, Severity::Error);
        assert!(errors
            .iter()
            .any(|s| s.contains("partition 0 owner pod-gone")));
        assert!(!errors.iter().any(|s| s.contains("partition 1 owner")));
    }

    #[test]
    fn a_lingering_complete_handoff_flags_the_coordinator() {
        let kvs = vec![
            total_partitions_kv(1),
            pod_kv("pod-b"),
            assignment_kv(0, "pod-b"),
            handoff_kv(0, "Complete", None, "pod-b", &[], 1_000),
        ];
        let topology = view(&kvs, 601_000);

        assert!(issue_summaries(&topology, Severity::Warning)
            .iter()
            .any(|s| s.contains("has not been cleaned up")));
        // Complete is terminal: never past deadline.
        assert!(
            !topology.partitions[0]
                .handoff
                .as_ref()
                .unwrap()
                .past_deadline
        );
    }

    #[test]
    fn unassigned_and_out_of_range_partitions_are_flagged() {
        let kvs = vec![
            total_partitions_kv(2),
            pod_kv("pod-a"),
            assignment_kv(0, "pod-a"),
            assignment_kv(5, "pod-a"),
        ];
        let topology = view(&kvs, 10_000);

        let warnings = issue_summaries(&topology, Severity::Warning);
        assert!(warnings
            .iter()
            .any(|s| s.contains("partition 1 has no assignment and no handoff")));
        assert!(warnings
            .iter()
            .any(|s| s.contains("partition 5 has state but total_partitions is 2")));
        // The out-of-range partition still renders a row.
        assert!(topology.partitions.iter().any(|p| p.partition == 5));
    }

    #[test]
    fn stale_acks_are_inert_info_and_matching_acks_are_not() {
        let kvs = vec![
            total_partitions_kv(1),
            pod_kv("pod-a"),
            pod_kv("pod-b"),
            router_kv("router-0"),
            assignment_kv(0, "pod-a"),
            handoff_kv(0, "Freezing", Some("pod-a"), "pod-b", &["router-0"], 9_000),
            kv(
                "freeze_acks/0/router-0",
                serde_json::json!({
                    "router_name": "router-0",
                    "partition": 0,
                    "acked_at": 2,
                    "handoff_id": "a-previous-attempt",
                }),
                0,
            ),
        ];
        let topology = view(&kvs, 10_000);

        assert!(issue_summaries(&topology, Severity::Info)
            .iter()
            .any(|s| s.contains("ack(s) for another handoff attempt")));
        // The stale ack must not satisfy the quorum.
        let handoff = topology.partitions[0].handoff.as_ref().unwrap();
        assert_eq!(handoff.missing_freeze_ackers, vec!["router-0"]);
    }

    #[test]
    fn missing_total_partitions_is_an_error_without_unassigned_noise() {
        let kvs = vec![pod_kv("pod-a"), assignment_kv(0, "pod-a")];
        let topology = view(&kvs, 10_000);

        assert!(issue_summaries(&topology, Severity::Error)
            .iter()
            .any(|s| s.contains("config/total_partitions is missing")));
        assert!(!issue_summaries(&topology, Severity::Warning)
            .iter()
            .any(|s| s.contains("no assignment")));
    }

    #[test]
    fn a_dead_new_owner_warns_and_unparseable_records_surface() {
        let mut kvs = vec![
            total_partitions_kv(1),
            pod_kv("pod-a"),
            assignment_kv(0, "pod-a"),
            handoff_kv(0, "Warming", Some("pod-a"), "pod-gone", &[], 9_000),
        ];
        kvs.push(RawKv {
            key: format!("{PREFIX}pods/broken"),
            value: b"not json".to_vec(),
            lease: 0,
        });
        let topology = view(&kvs, 10_000);

        assert!(issue_summaries(&topology, Severity::Warning)
            .iter()
            .any(|s| s.contains("targets unregistered pod pod-gone")));
        assert!(issue_summaries(&topology, Severity::Error)
            .iter()
            .any(|s| s.contains("unparseable record at /personhog/pods/broken")));
    }

    #[test]
    fn pods_carry_their_assigned_partitions_and_lease_ttls() {
        let kvs = vec![
            total_partitions_kv(2),
            pod_kv("pod-a"),
            assignment_kv(1, "pod-a"),
            assignment_kv(0, "pod-a"),
        ];
        let raw = parse_snapshot(&kvs, PREFIX, 42);
        let ttls = HashMap::from([(7, 21)]);
        let topology = derive_view(raw, &ttls, PREFIX, 10_000, &deadlines());

        assert_eq!(topology.pods[0].partitions, vec![0, 1]);
        assert_eq!(topology.pods[0].lease_ttl_secs, Some(21));
        assert_eq!(topology.revision, 42);
    }
}
