//! Continuous chaos executor for the dev traffic bed.
//!
//! Chaos is part of the bed's normal operation, not a windowed event:
//! the stack is expected to stay correct while pods die under load, and
//! attribution runs through instrumentation — every action lands in
//! `personhog_traffic_chaos_actions_total` with a scenario/target/mode
//! label set and a timestamp gauge, so a violation or latency excursion
//! on the dashboard correlates against exactly what chaos did and when.
//!
//! Scenarios are short sequences, not just single kills, because the
//! interesting compound states are *recovery interrupted by a second
//! failure*: a leader dying while it warms a first victim's partitions,
//! or a freshly elected coordinator dying mid-reconcile. Kill modes
//! split the two protocol recovery paths — a graceful delete walks
//! SIGTERM → drain → handoff, an abrupt delete (grace 0) walks lease
//! expiry → dead-owner handoff → changelog re-warm.
//!
//! Safety model: RBAC is the hard boundary — the harness ServiceAccount
//! holds pod get/list/delete in exactly the personhog namespaces, so no
//! configuration bug can widen the blast radius. Inside that boundary
//! the min-alive guard, evaluated per step at execution time, never
//! takes a target class's last ready pod: chaos degrades the bed, it
//! does not extinguish it. Chaos failures (API errors, vacant
//! elections) are counted and logged, never propagated — a broken chaos
//! loop must not take the traffic it exists to stress.

use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result};
use k8s_openapi::api::core::v1::Pod;
use kube::api::{DeleteParams, ListParams};
use kube::Api;
use metrics::{counter, gauge};
use rand::rngs::StdRng;
use rand::seq::SliceRandom;
use rand::{Rng, SeedableRng};

use assignment_coordination::store::{EtcdStore, StoreConfig};
use personhog_coordination::store::PersonhogStore;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TargetKind {
    Leader,
    Router,
    Writer,
    /// The coordination store itself. Deliberately not part of the
    /// random-draw target pool: only the dedicated `EtcdBounce`
    /// scenario may touch it, under its own quorum guard.
    Etcd,
}

impl TargetKind {
    fn label(self) -> &'static str {
        match self {
            TargetKind::Leader => "leader",
            TargetKind::Router => "router",
            TargetKind::Writer => "writer",
            TargetKind::Etcd => "etcd",
        }
    }
}

#[derive(Debug, Clone)]
pub struct TargetSpec {
    pub kind: TargetKind,
    pub namespace: String,
    /// Label selector for the class's app pods, excluding sidecar
    /// deployments (pgbouncer) that share the namespace.
    pub selector: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum KillMode {
    /// Normal delete: SIGTERM → drain → handoff. The planned-departure
    /// recovery path.
    Graceful,
    /// Grace period zero: lease expiry → dead-owner handoff → re-warm.
    /// The crash recovery path.
    Abrupt,
}

impl KillMode {
    fn label(self) -> &'static str {
        match self {
            KillMode::Graceful => "graceful",
            KillMode::Abrupt => "abrupt",
        }
    }

    fn pick(rng: &mut impl Rng) -> Self {
        if rng.gen_bool(0.5) {
            KillMode::Graceful
        } else {
            KillMode::Abrupt
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Scenario {
    /// One kill of a random target class.
    SingleKill,
    /// A leader and a router killed simultaneously — the node-failure /
    /// AZ-blip analog.
    CrossClassPair,
    /// Kill one target, wait a few seconds, kill another while the
    /// first recovery is mid-flight.
    StaggeredFollowUp,
    /// Kill the pod currently holding the coordinator election.
    CoordinatorKill,
    /// Kill the coordinator, wait for a successor to win the election,
    /// kill that one too — election churn plus orphaned reconciliation.
    CoordinatorDoubleTap,
    /// Abruptly kill one etcd member of a ≥3-member cluster: quorum
    /// survives, state survives (persistent volumes), but every client
    /// stream pinned to that member breaks at once — the coordination
    /// blip that must never restart the fleet. The expected signature
    /// is run-supervisor rebuilds (`run_restarts_total` up) with zero
    /// container restarts, zero handoffs, and zero client-visible
    /// errors.
    EtcdBounce,
}

impl Scenario {
    fn label(self) -> &'static str {
        match self {
            Scenario::SingleKill => "single_kill",
            Scenario::CrossClassPair => "cross_class_pair",
            Scenario::StaggeredFollowUp => "staggered_follow_up",
            Scenario::CoordinatorKill => "coordinator_kill",
            Scenario::CoordinatorDoubleTap => "coordinator_double_tap",
            Scenario::EtcdBounce => "etcd_bounce",
        }
    }

    fn needs_coordinator(self) -> bool {
        matches!(
            self,
            Scenario::CoordinatorKill | Scenario::CoordinatorDoubleTap
        )
    }

    fn needs_etcd_target(self) -> bool {
        matches!(self, Scenario::EtcdBounce)
    }
}

/// Scenario draw weights. Singles dominate so the common case stays the
/// baseline; compounds and coordinator churn are salted in.
const SCENARIO_WEIGHTS: &[(Scenario, u32)] = &[
    (Scenario::SingleKill, 60),
    (Scenario::CrossClassPair, 12),
    (Scenario::StaggeredFollowUp, 12),
    (Scenario::CoordinatorKill, 8),
    (Scenario::CoordinatorDoubleTap, 8),
    (Scenario::EtcdBounce, 8),
];

/// Draw a scenario, excluding coordinator scenarios when no etcd access
/// is configured and the etcd bounce when no etcd target is configured
/// (their weight redistributes over the rest).
fn pick_scenario(rng: &mut impl Rng, coordinator_available: bool, etcd_target: bool) -> Scenario {
    let pool: Vec<(Scenario, u32)> = SCENARIO_WEIGHTS
        .iter()
        .filter(|(s, _)| coordinator_available || !s.needs_coordinator())
        .filter(|(s, _)| etcd_target || !s.needs_etcd_target())
        .copied()
        .collect();
    let total: u32 = pool.iter().map(|(_, w)| w).sum();
    let mut roll = rng.gen_range(0..total);
    for (scenario, weight) in pool {
        if roll < weight {
            return scenario;
        }
        roll -= weight;
    }
    unreachable!("weights cover the full range")
}

/// The min-alive guard: choose a victim only when at least two pods
/// remain that this scenario has not already killed. Subtracting
/// `killed` closes the compound-kill race — a pod deleted moments ago
/// can still report `Ready` before its `deletion_timestamp` propagates,
/// so counting raw readiness would let a staggered or double-tap
/// scenario take a class's last live pod.
fn choose_victim(rng: &mut impl Rng, ready: &[String], killed: &HashSet<String>) -> Option<String> {
    let alive: Vec<&String> = ready.iter().filter(|n| !killed.contains(*n)).collect();
    if alive.len() < 2 {
        return None;
    }
    alive.choose(rng).map(|s| (*s).clone())
}

pub struct ChaosConfig {
    pub interval_min: Duration,
    pub interval_max: Duration,
    pub targets: Vec<TargetSpec>,
    /// etcd endpoints + key prefix of the stack under test. Enables the
    /// coordinator scenarios; without it they are excluded from the draw.
    pub etcd: Option<(String, String)>,
    /// The etcd cluster's own pods. Enables the `EtcdBounce` scenario;
    /// without it that scenario is excluded from the draw. Kept out of
    /// `targets` so the general kill scenarios can never draw etcd —
    /// only the bounce, with its quorum guard, may touch it.
    pub etcd_target: Option<TargetSpec>,
}

pub async fn run(cfg: ChaosConfig, shutdown: Arc<AtomicBool>) {
    let client = match kube::Client::try_default().await {
        Ok(c) => c,
        Err(e) => {
            tracing::error!(error = %e, "chaos disabled: cannot build kube client");
            counter!("personhog_traffic_chaos_skipped_total", "reason" => "kube_client")
                .increment(1);
            // The gauge tracks whether chaos is *running*, not whether it
            // was asked for: a loop that cannot start must not keep
            // reporting itself as enabled while doing nothing.
            gauge!("personhog_traffic_chaos_enabled").set(0.0);
            return;
        }
    };

    let store = match &cfg.etcd {
        Some((endpoints, prefix)) => match connect_store(endpoints, prefix).await {
            Ok(store) => Some(store),
            Err(e) => {
                // Counted, not just logged: coordinator scenarios quietly
                // dropping out of the mix is otherwise indistinguishable
                // from the draw not having reached them yet.
                tracing::error!(error = %e, "coordinator scenarios disabled: etcd unreachable");
                counter!("personhog_traffic_chaos_skipped_total", "reason" => "etcd_unreachable")
                    .increment(1);
                None
            }
        },
        None => None,
    };

    tracing::info!(
        targets = cfg.targets.len(),
        coordinator_scenarios = store.is_some(),
        "chaos executor running"
    );
    // Clamp so a misconfigured range can neither panic `gen_range` (min >
    // max) nor spin (sub-second bounds truncate to a zero-second pause).
    let lo = cfg.interval_min.as_secs().max(1);
    let hi = cfg.interval_max.as_secs().max(lo);
    let mut rng = StdRng::from_entropy();

    loop {
        let pause = rng.gen_range(lo..=hi);
        if sleep_interruptible(Duration::from_secs(pause), &shutdown).await {
            return;
        }

        let scenario = pick_scenario(&mut rng, store.is_some(), cfg.etcd_target.is_some());
        tracing::info!(scenario = scenario.label(), "chaos scenario starting");
        // Pods this scenario has already killed, kept out of every later
        // step's min-alive count regardless of how fast k8s reflects the
        // deletion.
        let mut killed = HashSet::new();
        execute(
            &client,
            &cfg,
            store.as_ref(),
            scenario,
            &mut rng,
            &shutdown,
            &mut killed,
        )
        .await;
    }
}

#[allow(clippy::too_many_arguments)]
async fn execute(
    client: &kube::Client,
    cfg: &ChaosConfig,
    store: Option<&PersonhogStore>,
    scenario: Scenario,
    rng: &mut StdRng,
    shutdown: &Arc<AtomicBool>,
    killed: &mut HashSet<String>,
) {
    match scenario {
        Scenario::SingleKill => {
            if let Some(target) = cfg.targets.choose(rng) {
                kill_one(client, target, KillMode::pick(rng), scenario, rng, killed).await;
            }
        }
        Scenario::CrossClassPair => {
            // Distinct classes have independent min-alive counts, so the
            // two kills run concurrently — each with its own rng and its
            // own killed-set, since a `&mut` cannot be shared across the
            // join. Both sets fold back afterwards so a later step of
            // this scenario still sees everything it killed.
            let leader = cfg.targets.iter().find(|t| t.kind == TargetKind::Leader);
            let router = cfg.targets.iter().find(|t| t.kind == TargetKind::Router);
            if let (Some(leader), Some(router)) = (leader, router) {
                let (lm, rm) = (KillMode::pick(rng), KillMode::pick(rng));
                let (mut rng_l, mut rng_r) = (StdRng::from_entropy(), StdRng::from_entropy());
                let mut killed_l = HashSet::new();
                let mut killed_r = HashSet::new();
                tokio::join!(
                    kill_one(client, leader, lm, scenario, &mut rng_l, &mut killed_l),
                    kill_one(client, router, rm, scenario, &mut rng_r, &mut killed_r),
                );
                killed.extend(killed_l);
                killed.extend(killed_r);
            }
        }
        Scenario::StaggeredFollowUp => {
            let Some(first) = cfg.targets.choose(rng) else {
                return;
            };
            kill_one(client, first, KillMode::pick(rng), scenario, rng, killed).await;
            let gap = Duration::from_secs(rng.gen_range(2..=10));
            if sleep_interruptible(gap, shutdown).await {
                return;
            }
            if let Some(second) = cfg.targets.choose(rng) {
                kill_one(client, second, KillMode::pick(rng), scenario, rng, killed).await;
            }
        }
        Scenario::CoordinatorKill => {
            kill_coordinator(client, cfg, store, scenario, rng, killed).await;
        }
        Scenario::EtcdBounce => {
            let Some(target) = &cfg.etcd_target else {
                return;
            };
            // Quorum guard: only bounce when all three members are
            // ready, so the kill leaves two — a healthy majority. The
            // point is a connection blip, not an availability test;
            // taking etcd below quorum would halt coordination for the
            // whole bed and test nothing this scenario is for.
            let ready = match list_ready(client, target).await {
                Ok(ready) => ready,
                Err(e) => {
                    tracing::warn!(error = %e, namespace = %target.namespace, "listing etcd pods failed");
                    counter!("personhog_traffic_chaos_skipped_total", "reason" => "list_failed")
                        .increment(1);
                    return;
                }
            };
            if ready.len() < 3 {
                counter!("personhog_traffic_chaos_skipped_total", "reason" => "etcd_quorum_guard")
                    .increment(1);
                return;
            }
            // Always abrupt: a graceful etcd shutdown hands off cleanly,
            // but the failure this scenario reproduces is the sudden
            // stream break every client sees when a member vanishes.
            kill_one(client, target, KillMode::Abrupt, scenario, rng, killed).await;
        }
        Scenario::CoordinatorDoubleTap => {
            let Some(first) = kill_coordinator(client, cfg, store, scenario, rng, killed).await
            else {
                return;
            };
            // The successor needs the old election lease to lapse (abrupt
            // kills leave it until TTL) plus a campaign; poll generously.
            let deadline = Duration::from_secs(25);
            let start = Instant::now();
            let successor = loop {
                if shutdown.load(Ordering::SeqCst) {
                    return;
                }
                if start.elapsed() > deadline {
                    break None;
                }
                match resolve_coordinator(store).await {
                    Some(holder) if holder != first => break Some(holder),
                    _ => tokio::time::sleep(Duration::from_millis(500)).await,
                }
            };
            match successor {
                Some(_) => {
                    kill_coordinator(client, cfg, store, scenario, rng, killed).await;
                }
                None => {
                    tracing::warn!("double tap: no successor coordinator within deadline");
                    counter!("personhog_traffic_chaos_skipped_total", "reason" => "no_successor")
                        .increment(1);
                }
            }
        }
    }
}

/// Resolve and kill the current coordinator (a router pod). Returns the
/// holder's pod name when a kill was issued. The router class's
/// min-alive count is enforced here too — a coordinator kill is still a
/// router kill, and the double-tap must not drain the class below one
/// live pod.
async fn kill_coordinator(
    client: &kube::Client,
    cfg: &ChaosConfig,
    store: Option<&PersonhogStore>,
    scenario: Scenario,
    rng: &mut StdRng,
    killed: &mut HashSet<String>,
) -> Option<String> {
    let Some(holder) = resolve_coordinator(store).await else {
        tracing::info!("no coordinator election holder; skipping");
        counter!("personhog_traffic_chaos_skipped_total", "reason" => "no_coordinator")
            .increment(1);
        return None;
    };
    let router = cfg.targets.iter().find(|t| t.kind == TargetKind::Router)?;
    // Distinguishing a failed list from a genuinely thin class matters
    // most at rollout: without the RBAC grant this call 403s, and
    // folding that into the min-alive count would report "not enough
    // pods" for what is really a missing permission.
    let ready = match list_ready(client, router).await {
        Ok(ready) => ready,
        Err(e) => {
            tracing::warn!(error = %e, namespace = %router.namespace, "listing pods failed");
            counter!("personhog_traffic_chaos_skipped_total", "reason" => "list_failed")
                .increment(1);
            return None;
        }
    };
    if ready.is_empty() {
        // etcd named a live coordinator, so a class with no pods means
        // the selector or namespace is wrong, not that the routers are
        // gone. Kept separate from min_alive: they send an operator to
        // different knobs.
        tracing::warn!(namespace = %router.namespace, "no pods matched the router selector");
        counter!("personhog_traffic_chaos_skipped_total", "reason" => "no_targets").increment(1);
        return None;
    }
    let alive = ready.iter().filter(|n| !killed.contains(*n)).count();
    if alive < 2 {
        tracing::info!(alive, "min-alive guard: skipping coordinator kill");
        counter!("personhog_traffic_chaos_skipped_total", "reason" => "min_alive").increment(1);
        return None;
    }
    let mode = KillMode::pick(rng);
    if kill_named(client, router, &holder, mode, scenario).await {
        killed.insert(holder.clone());
        Some(holder)
    } else {
        None
    }
}

async fn resolve_coordinator(store: Option<&PersonhogStore>) -> Option<String> {
    match store?.get_leader().await {
        Ok(Some(leader)) => Some(leader.holder),
        Ok(None) => None,
        Err(e) => {
            tracing::warn!(error = %e, "reading coordinator election failed");
            None
        }
    }
}

/// Kill one randomly chosen ready pod of `target`, honoring the
/// min-alive guard.
async fn kill_one(
    client: &kube::Client,
    target: &TargetSpec,
    mode: KillMode,
    scenario: Scenario,
    rng: &mut impl Rng,
    killed: &mut HashSet<String>,
) {
    let ready = match list_ready(client, target).await {
        Ok(ready) => ready,
        Err(e) => {
            tracing::warn!(error = %e, namespace = %target.namespace, "listing pods failed");
            counter!("personhog_traffic_chaos_skipped_total", "reason" => "list_failed")
                .increment(1);
            return;
        }
    };
    if ready.is_empty() {
        // A class with no ready pods at all is a wrong selector or
        // namespace far more often than a class that is genuinely
        // all-down, and either way it is not the min-alive guard
        // declining to take the last one.
        tracing::warn!(
            target = target.kind.label(),
            namespace = %target.namespace,
            "no pods matched the selector"
        );
        counter!("personhog_traffic_chaos_skipped_total", "reason" => "no_targets").increment(1);
        return;
    }
    let Some(victim) = choose_victim(rng, &ready, killed) else {
        tracing::info!(
            target = target.kind.label(),
            ready = ready.len(),
            "min-alive guard: skipping kill"
        );
        counter!("personhog_traffic_chaos_skipped_total", "reason" => "min_alive").increment(1);
        return;
    };
    if kill_named(client, target, &victim, mode, scenario).await {
        killed.insert(victim);
    }
}

/// Delete a specific pod. Returns whether the delete was accepted.
async fn kill_named(
    client: &kube::Client,
    target: &TargetSpec,
    pod_name: &str,
    mode: KillMode,
    scenario: Scenario,
) -> bool {
    let pods: Api<Pod> = Api::namespaced(client.clone(), &target.namespace);
    let params = match mode {
        KillMode::Graceful => DeleteParams::default(),
        KillMode::Abrupt => DeleteParams {
            grace_period_seconds: Some(0),
            ..DeleteParams::default()
        },
    };
    match pods.delete(pod_name, &params).await {
        Ok(_) => {
            tracing::info!(
                scenario = scenario.label(),
                target = target.kind.label(),
                pod = pod_name,
                mode = mode.label(),
                "chaos kill issued"
            );
            counter!(
                "personhog_traffic_chaos_actions_total",
                "scenario" => scenario.label(),
                "target" => target.kind.label(),
                "mode" => mode.label(),
            )
            .increment(1);
            let now = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64();
            gauge!("personhog_traffic_chaos_last_action_timestamp_seconds").set(now);
            true
        }
        Err(e) => {
            tracing::warn!(error = %e, pod = pod_name, "chaos delete failed");
            counter!("personhog_traffic_chaos_skipped_total", "reason" => "delete_failed")
                .increment(1);
            false
        }
    }
}

/// Ready, non-terminating pod names matching the target's selector.
async fn list_ready(client: &kube::Client, target: &TargetSpec) -> Result<Vec<String>> {
    let pods: Api<Pod> = Api::namespaced(client.clone(), &target.namespace);
    let list = pods
        .list(&ListParams::default().labels(&target.selector))
        .await
        .context("listing pods")?;
    Ok(list
        .items
        .iter()
        .filter(|p| is_ready(p))
        .filter_map(|p| p.metadata.name.clone())
        .collect())
}

fn is_ready(pod: &Pod) -> bool {
    if pod.metadata.deletion_timestamp.is_some() {
        return false;
    }
    pod.status
        .as_ref()
        .and_then(|s| s.conditions.as_ref())
        .map(|conds| {
            conds
                .iter()
                .any(|c| c.type_ == "Ready" && c.status == "True")
        })
        .unwrap_or(false)
}

/// Sleep in one-second slices so shutdown interrupts promptly. Returns
/// true when interrupted.
async fn sleep_interruptible(total: Duration, shutdown: &Arc<AtomicBool>) -> bool {
    let mut remaining = total;
    while !remaining.is_zero() {
        if shutdown.load(Ordering::SeqCst) {
            return true;
        }
        let slice = remaining.min(Duration::from_secs(1));
        tokio::time::sleep(slice).await;
        remaining -= slice;
    }
    shutdown.load(Ordering::SeqCst)
}

async fn connect_store(endpoints: &str, prefix: &str) -> Result<PersonhogStore> {
    let etcd = EtcdStore::connect(StoreConfig {
        endpoints: endpoints.split(',').map(String::from).collect(),
        prefix: prefix.to_string(),
    })
    .await
    .context("connecting to etcd for coordinator resolution")?;
    Ok(PersonhogStore::new(etcd))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::rngs::StdRng;
    use rand::SeedableRng;

    /// Without etcd access the draw must never yield a coordinator
    /// scenario — otherwise every such cycle would burn on a skip.
    #[test]
    fn coordinator_scenarios_excluded_without_etcd() {
        let mut rng = StdRng::seed_from_u64(7);
        for _ in 0..1000 {
            assert!(!pick_scenario(&mut rng, false, false).needs_coordinator());
            assert!(!pick_scenario(&mut rng, false, false).needs_etcd_target());
        }
    }

    /// The min-alive guard: a class with fewer than two live pods
    /// yields no victim, so chaos can never extinguish a class.
    #[test]
    fn min_alive_guard_never_takes_the_last_pod() {
        let mut rng = StdRng::seed_from_u64(7);
        let none = HashSet::new();
        assert!(choose_victim(&mut rng, &[], &none).is_none());
        assert!(choose_victim(&mut rng, &["only-pod".into()], &none).is_none());
        let two = ["a".to_string(), "b".to_string()];
        assert!(choose_victim(&mut rng, &two, &none).is_some());
    }

    /// Pods already killed this scenario are subtracted before the guard,
    /// so a second step can never take the class's last still-live pod
    /// even while the first victim still reports Ready to the API.
    #[test]
    fn min_alive_guard_excludes_already_killed() {
        let mut rng = StdRng::seed_from_u64(7);
        let ready = ["a".to_string(), "b".to_string()];
        let mut killed = HashSet::new();
        killed.insert("a".to_string());
        // Only "b" is live; the guard must refuse rather than pick it.
        assert!(choose_victim(&mut rng, &ready, &killed).is_none());
    }
}
