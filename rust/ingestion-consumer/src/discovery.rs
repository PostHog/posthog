//! Worker pool discovery.
//!
//! The [`WorkerRegistry`] owns worker membership and health; this module is the
//! source that drives it. Two providers implement [`WorkerDiscovery`]:
//!
//! - [`StaticDiscovery`] — a fixed list from `WORKER_ADDRESSES` (the co-located
//!   sidecar). Applies the set once; no background task.
//! - [`EndpointSliceDiscovery`] — watches a Kubernetes Service's EndpointSlices
//!   and keeps the registry in sync as worker pods join/leave (the
//!   separately-deployed pool). Adapted from personhog-router's discovery, but
//!   reconciles the registry directly instead of feeding a Tower balancer.
//!
//! Routing stays client-side in the dispatcher; discovery only supplies the
//! member list. A departed worker is marked *draining* (it keeps finishing
//! in-flight work) rather than removed outright; the reaper in `main` removes it
//! from the registry and transport once it has drained or timed out.

use std::collections::{HashMap, HashSet};
use std::net::{IpAddr, SocketAddr};
use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;

use futures::StreamExt;
use k8s_openapi::api::discovery::v1::EndpointSlice;
use kube::api::Api;
use kube::runtime::watcher::{self, Config as WatcherConfig, Event};
use kube::Client;
use metrics::{counter, gauge};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::worker_registry::{WorkerId, WorkerRegistry};

/// Pause before re-listing after the watcher stream closes, so a persistently
/// failing watcher degrades to a slow retry rather than a hot loop.
const WATCHER_RESTART_BACKOFF: Duration = Duration::from_secs(1);

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

/// Parse an EndpointSlice into the set of ready socket addresses. An endpoint is
/// ready when `conditions.ready` is true or absent (per the K8s spec); endpoints
/// with `ready = false` (e.g. draining pods) and unparseable addresses are skipped.
fn extract_ready_addrs(slice: &EndpointSlice, port: u16) -> HashSet<SocketAddr> {
    let mut addrs = HashSet::new();
    for endpoint in slice.endpoints.iter() {
        let ready = endpoint
            .conditions
            .as_ref()
            .and_then(|c| c.ready)
            .unwrap_or(true);
        if !ready {
            continue;
        }
        for addr_str in &endpoint.addresses {
            if let Ok(ip) = addr_str.parse::<IpAddr>() {
                addrs.insert(SocketAddr::new(ip, port));
            }
        }
    }
    addrs
}

fn addr_to_worker(addr: SocketAddr) -> WorkerId {
    WorkerId::from(format!("http://{addr}").as_str())
}

fn slice_key(slice: &EndpointSlice) -> String {
    slice
        .metadata
        .name
        .clone()
        .or_else(|| slice.metadata.uid.clone())
        .unwrap_or_else(|| "unknown".to_string())
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

/// Watches a Kubernetes Service's EndpointSlices and reconciles the registry as
/// worker pods become ready / leave.
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
        let api: Api<EndpointSlice> = Api::namespaced(self.client.clone(), &self.namespace);
        let label_selector = format!("kubernetes.io/service-name={}", self.service_name);

        info!(
            service = %self.service_name,
            namespace = %self.namespace,
            port = self.port,
            "starting EndpointSlice worker discovery"
        );

        // Ready addresses per slice name, so one slice changing doesn't clobber
        // addresses contributed by other slices. Kept across watcher restarts:
        // a fresh watcher re-lists from `Init`, which clears and repopulates it.
        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();

        // The `kube` watcher reconnects internally on errors, so a `None` only
        // surfaces when the stream is definitively closed. Re-enter the watcher
        // rather than leaving the worker pool frozen until the pod restarts.
        loop {
            let config = WatcherConfig::default().labels(&label_selector);
            let stream = watcher::watcher(api.clone(), config);
            tokio::pin!(stream);

            loop {
                tokio::select! {
                    _ = cancel.cancelled() => {
                        info!("EndpointSlice discovery cancelled");
                        return;
                    }
                    item = stream.next() => {
                        match item {
                            Some(Ok(event)) => {
                                if let Some(desired) = Self::apply_event(event, &mut slices, self.port) {
                                    reconcile_membership(&registry, &desired);
                                }
                            }
                            Some(Err(e)) => {
                                warn!(error = %e, "EndpointSlice watcher error, stream will retry");
                                counter!("ingestion_consumer_discovery_errors_total").increment(1);
                            }
                            None => {
                                warn!("EndpointSlice watcher stream ended, restarting");
                                counter!("ingestion_consumer_discovery_errors_total").increment(1);
                                break;
                            }
                        }
                    }
                }
            }

            // Brief pause before re-listing, so a persistently-closing stream
            // can't become a hot reconnect loop.
            tokio::select! {
                _ = cancel.cancelled() => {
                    info!("EndpointSlice discovery cancelled");
                    return;
                }
                _ = tokio::time::sleep(WATCHER_RESTART_BACKOFF) => {}
            }
        }
    }

    /// Apply a watch event to the per-slice state, returning the desired worker
    /// set to reconcile — or `None` when no reconcile is needed (the `Init`
    /// re-list start, where we keep serving the current set until `InitDone`).
    fn apply_event(
        event: Event<EndpointSlice>,
        slices: &mut HashMap<String, HashSet<SocketAddr>>,
        port: u16,
    ) -> Option<HashSet<WorkerId>> {
        match event {
            Event::Apply(slice) | Event::InitApply(slice) => {
                slices.insert(slice_key(&slice), extract_ready_addrs(&slice, port));
            }
            Event::Delete(slice) => {
                slices.remove(&slice_key(&slice));
            }
            // Re-list starting: clear slice state but DON'T reconcile, so the
            // registry keeps serving the current workers until InitDone.
            Event::Init => {
                slices.clear();
                return None;
            }
            Event::InitDone => {}
        }

        Some(
            slices
                .values()
                .flatten()
                .copied()
                .map(addr_to_worker)
                .collect(),
        )
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

    use k8s_openapi::api::discovery::v1::{Endpoint as K8sEndpoint, EndpointConditions};
    use k8s_openapi::apimachinery::pkg::apis::meta::v1::ObjectMeta;

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

    // ---- extract_ready_addrs ----

    fn endpoint(addresses: &[&str], ready: Option<bool>) -> K8sEndpoint {
        K8sEndpoint {
            addresses: addresses.iter().map(|s| s.to_string()).collect(),
            conditions: ready.map(|r| EndpointConditions {
                ready: Some(r),
                ..Default::default()
            }),
            ..Default::default()
        }
    }

    fn slice(name: &str, endpoints: Vec<K8sEndpoint>) -> EndpointSlice {
        EndpointSlice {
            metadata: ObjectMeta {
                name: Some(name.to_string()),
                ..Default::default()
            },
            address_type: "IPv4".to_string(),
            endpoints,
            ports: None,
        }
    }

    fn sock(s: &str, port: u16) -> SocketAddr {
        SocketAddr::new(s.parse().unwrap(), port)
    }

    #[test]
    fn test_extract_ready_addrs_includes_ready_and_nil_conditions() {
        let s = slice(
            "s1",
            vec![
                endpoint(&["10.0.0.1"], Some(true)),
                endpoint(&["10.0.0.2"], Some(false)),
                endpoint(&["10.0.0.3"], None),
            ],
        );
        assert_eq!(
            extract_ready_addrs(&s, 9001),
            HashSet::from([sock("10.0.0.1", 9001), sock("10.0.0.3", 9001)])
        );
    }

    #[test]
    fn test_extract_ready_addrs_skips_unparseable() {
        let s = slice("s1", vec![endpoint(&["not-an-ip", "10.0.0.5"], None)]);
        assert_eq!(
            extract_ready_addrs(&s, 9001),
            HashSet::from([sock("10.0.0.5", 9001)])
        );
    }

    // ---- apply_event ----

    fn worker(ip: &str, port: u16) -> WorkerId {
        WorkerId::from(format!("http://{ip}:{port}").as_str())
    }

    #[test]
    fn test_apply_event_apply_and_delete() {
        let mut slices = HashMap::new();

        let desired = EndpointSliceDiscovery::apply_event(
            Event::Apply(slice("s1", vec![endpoint(&["10.0.0.1"], Some(true))])),
            &mut slices,
            9001,
        )
        .unwrap();
        assert_eq!(desired, HashSet::from([worker("10.0.0.1", 9001)]));

        let desired = EndpointSliceDiscovery::apply_event(
            Event::Delete(slice("s1", vec![])),
            &mut slices,
            9001,
        )
        .unwrap();
        assert!(desired.is_empty());
    }

    #[test]
    fn test_apply_event_init_keeps_serving_until_init_done() {
        let mut slices = HashMap::new();
        EndpointSliceDiscovery::apply_event(
            Event::Apply(slice("s1", vec![endpoint(&["10.0.0.1"], Some(true))])),
            &mut slices,
            9001,
        );

        // Init returns None — caller must NOT reconcile (keep serving current set).
        assert!(EndpointSliceDiscovery::apply_event(Event::Init, &mut slices, 9001).is_none());
        assert!(slices.is_empty());

        // Re-list with a different pod, then InitDone reconciles to the new set.
        EndpointSliceDiscovery::apply_event(
            Event::InitApply(slice("s1", vec![endpoint(&["10.0.0.9"], Some(true))])),
            &mut slices,
            9001,
        );
        let desired =
            EndpointSliceDiscovery::apply_event(Event::InitDone, &mut slices, 9001).unwrap();
        assert_eq!(desired, HashSet::from([worker("10.0.0.9", 9001)]));
    }

    #[test]
    fn test_apply_event_aggregates_across_slices() {
        let mut slices = HashMap::new();
        EndpointSliceDiscovery::apply_event(
            Event::Apply(slice("s1", vec![endpoint(&["10.0.0.1"], Some(true))])),
            &mut slices,
            9001,
        );
        let desired = EndpointSliceDiscovery::apply_event(
            Event::Apply(slice("s2", vec![endpoint(&["10.0.0.2"], Some(true))])),
            &mut slices,
            9001,
        )
        .unwrap();
        assert_eq!(
            desired,
            HashSet::from([worker("10.0.0.1", 9001), worker("10.0.0.2", 9001)])
        );
    }

    // ---- reconcile_membership ----

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
