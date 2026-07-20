//! Worker pool discovery.
//!
//! The [`WorkerRegistry`] owns worker membership and health; this module is the
//! source that drives it. Two providers implement [`WorkerDiscovery`]:
//!
//! - [`StaticDiscovery`] — a fixed list from `WORKER_ADDRESSES` (the co-located
//!   sidecar). Applies the set once; no background task.
//! - [`EndpointSliceDiscovery`] — subscribes to the shared EndpointSlice
//!   membership watch ([`k8s_awareness::watch_service_members`]) and keeps the
//!   registry in sync as worker pods join/leave (the separately-deployed pool).
//!
//! Routing stays client-side in the dispatcher; discovery only supplies the
//! member list. A departed worker is marked *draining* (it keeps finishing
//! in-flight work) rather than removed outright; the reaper in `main` removes it
//! from the registry and transport once it has drained or timed out.

use std::collections::HashSet;
use std::net::SocketAddr;
use std::str::FromStr;
use std::sync::Arc;

use kube::Client;
use metrics::gauge;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::worker_registry::{WorkerId, WorkerRegistry};

/// How the worker pool is discovered.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum DiscoveryMode {
    /// Fixed list from `WORKER_ADDRESSES` (co-located sidecar).
    #[default]
    Static,
    /// Watch a Kubernetes Service's EndpointSlices (separate worker deployment).
    EndpointSlice,
}

impl FromStr for DiscoveryMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "static" => Ok(DiscoveryMode::Static),
            "endpointslice" | "endpoint-slice" | "endpoint_slice" => {
                Ok(DiscoveryMode::EndpointSlice)
            }
            other => Err(format!(
                "unknown worker discovery mode '{other}' (expected 'static' or 'endpointslice')"
            )),
        }
    }
}

/// A source of worker-pool membership. `start` applies the initial set to the
/// registry and, for dynamic sources, spawns a task that keeps it in sync until
/// `cancel` fires; it returns the task handle (None for static sources).
pub trait WorkerDiscovery: Send {
    fn start(
        self: Box<Self>,
        registry: Arc<WorkerRegistry>,
        cancel: CancellationToken,
    ) -> Option<JoinHandle<()>>;
}

/// Reconcile the registry to a desired worker set: add workers that are new and
/// re-admit any that rejoined, and mark departed workers as draining (they keep
/// finishing in-flight work; the reaper removes them once drained or timed out).
/// Public so integration tests can drive membership changes the same way the
/// discovery providers do.
pub fn reconcile_membership(registry: &WorkerRegistry, desired: &HashSet<WorkerId>) {
    let current: HashSet<WorkerId> = registry.workers().into_iter().collect();

    for worker in desired.difference(&current) {
        registry.add_worker(worker.clone());
    }
    // Re-admit any desired worker that was draining (rejoined the pool).
    for worker in desired.intersection(&current) {
        if registry.is_draining(worker) {
            registry.add_worker(worker.clone());
        }
    }
    for worker in current.difference(desired) {
        registry.start_draining(worker);
    }

    gauge!("ingestion_consumer_discovery_workers").set(desired.len() as f64);
}

fn addr_to_worker(addr: SocketAddr) -> WorkerId {
    WorkerId::from(format!("http://{addr}").as_str())
}

/// Fixed worker list from configuration.
pub struct StaticDiscovery {
    urls: Vec<String>,
}

impl StaticDiscovery {
    pub fn new(urls: Vec<String>) -> Self {
        Self { urls }
    }
}

impl WorkerDiscovery for StaticDiscovery {
    fn start(
        self: Box<Self>,
        registry: Arc<WorkerRegistry>,
        _cancel: CancellationToken,
    ) -> Option<JoinHandle<()>> {
        let desired: HashSet<WorkerId> = self
            .urls
            .iter()
            .map(|u| WorkerId::from(u.as_str()))
            .collect();
        reconcile_membership(&registry, &desired);
        None
    }
}

/// Subscribes to the shared EndpointSlice membership watch for the worker
/// Service and reconciles the registry as worker pods become ready / leave.
pub struct EndpointSliceDiscovery {
    client: Client,
    namespace: String,
    service_name: String,
    port: u16,
}

impl EndpointSliceDiscovery {
    pub fn new(client: Client, namespace: String, service_name: String, port: u16) -> Self {
        Self {
            client,
            namespace,
            service_name,
            port,
        }
    }

    async fn run(self, registry: Arc<WorkerRegistry>, cancel: CancellationToken) {
        info!(
            service = %self.service_name,
            namespace = %self.namespace,
            port = self.port,
            "starting EndpointSlice worker discovery"
        );

        let (mut members, _watch_task) = k8s_awareness::watch_service_members(
            self.client,
            self.namespace,
            self.service_name,
            cancel.clone(),
        );

        loop {
            tokio::select! {
                _ = cancel.cancelled() => {
                    info!("EndpointSlice discovery cancelled");
                    return;
                }
                changed = members.changed() => {
                    if changed.is_err() {
                        // The watch task only exits on cancellation, so a
                        // closed channel means shutdown is underway.
                        warn!("EndpointSlice membership watch closed");
                        return;
                    }
                    let desired: HashSet<WorkerId> = members
                        .borrow_and_update()
                        .iter()
                        .map(|ip| addr_to_worker(SocketAddr::new(*ip, self.port)))
                        .collect();
                    reconcile_membership(&registry, &desired);
                }
            }
        }
    }
}

impl WorkerDiscovery for EndpointSliceDiscovery {
    fn start(
        self: Box<Self>,
        registry: Arc<WorkerRegistry>,
        cancel: CancellationToken,
    ) -> Option<JoinHandle<()>> {
        let this = *self;
        Some(tokio::spawn(
            async move { this.run(registry, cancel).await },
        ))
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;
    use crate::worker_registry::WorkerRegistryConfig;

    // ---- mode parsing ----

    #[test]
    fn test_discovery_mode_parses_known_values() {
        assert_eq!("static".parse(), Ok(DiscoveryMode::Static));
        assert_eq!("endpointslice".parse(), Ok(DiscoveryMode::EndpointSlice));
        assert_eq!("endpoint-slice".parse(), Ok(DiscoveryMode::EndpointSlice));
        assert_eq!("  EndpointSlice ".parse(), Ok(DiscoveryMode::EndpointSlice));
    }

    #[test]
    fn test_discovery_mode_rejects_unknown_and_defaults_static() {
        assert!("dns".parse::<DiscoveryMode>().is_err());
        assert_eq!(DiscoveryMode::default(), DiscoveryMode::Static);
    }

    // ---- reconcile_membership ----

    fn worker(ip: &str, port: u16) -> WorkerId {
        WorkerId::from(format!("http://{ip}:{port}").as_str())
    }

    fn test_registry() -> WorkerRegistry {
        WorkerRegistry::new(
            &[],
            WorkerRegistryConfig {
                probe_interval: Duration::from_millis(50),
                dead_declaration: Duration::from_millis(100),
                passive_window: Duration::from_millis(500),
                passive_error_threshold: 0.5,
                passive_min_samples: 5,
                degraded_hold: Duration::from_millis(50),
                min_state_duration: Duration::ZERO,
                probe_failure_threshold: 2,
                drain_timeout: Duration::from_secs(5),
            },
        )
    }

    fn sorted_routable(registry: &WorkerRegistry) -> Vec<String> {
        let mut got: Vec<String> = registry
            .healthy_workers()
            .iter()
            .map(|w| w.to_string())
            .collect();
        got.sort();
        got
    }

    #[test]
    fn test_reconcile_adds_workers_and_drains_departures() {
        let registry = test_registry();

        reconcile_membership(
            &registry,
            &HashSet::from([worker("10.0.0.1", 9001), worker("10.0.0.2", 9001)]),
        );
        assert_eq!(
            sorted_routable(&registry),
            vec!["http://10.0.0.1:9001", "http://10.0.0.2:9001"]
        );

        // Reconcile to a new set: .1 departs (→ draining, still present but not
        // routable), .3 joins, .2 stays.
        reconcile_membership(
            &registry,
            &HashSet::from([worker("10.0.0.2", 9001), worker("10.0.0.3", 9001)]),
        );
        assert_eq!(
            sorted_routable(&registry),
            vec!["http://10.0.0.2:9001", "http://10.0.0.3:9001"],
            "departed worker must no longer be routable"
        );
        assert!(
            registry.is_draining("http://10.0.0.1:9001"),
            "departed worker must be draining, not hard-removed"
        );
    }

    #[test]
    fn test_reconcile_readmits_a_rejoined_draining_worker() {
        let registry = test_registry();
        reconcile_membership(&registry, &HashSet::from([worker("10.0.0.1", 9001)]));
        // .1 departs → draining.
        reconcile_membership(&registry, &HashSet::new());
        assert!(registry.is_draining("http://10.0.0.1:9001"));
        // .1 rejoins → draining cleared, routable again.
        reconcile_membership(&registry, &HashSet::from([worker("10.0.0.1", 9001)]));
        assert!(!registry.is_draining("http://10.0.0.1:9001"));
        assert_eq!(sorted_routable(&registry), vec!["http://10.0.0.1:9001"]);
    }

    #[test]
    fn test_static_discovery_populates_registry() {
        let registry = Arc::new(test_registry());

        let discovery = Box::new(StaticDiscovery::new(vec![
            "http://w:1".to_string(),
            "http://w:2".to_string(),
        ]));
        let handle = discovery.start(Arc::clone(&registry), CancellationToken::new());

        assert!(handle.is_none(), "static discovery spawns no task");
        assert_eq!(registry.worker_count(), 2);
    }
}
