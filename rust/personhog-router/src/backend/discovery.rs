use std::collections::{HashMap, HashSet};
use std::net::{IpAddr, SocketAddr};
use std::time::Duration;

use futures::StreamExt;
use k8s_openapi::api::discovery::v1::EndpointSlice;
use kube::api::Api;
use kube::runtime::watcher::{self, Config as WatcherConfig, Event};
use kube::Client;
use tokio::sync::mpsc::Sender;
use tokio::sync::watch;
use tokio_util::sync::CancellationToken;
use tonic::transport::{Channel, Endpoint};
use tower::discover::Change;
use tracing::{info, warn};

const DISCOVERY_CHANNEL_BUFFER: usize = 64;

pub struct EndpointConfig {
    pub timeout: Duration,
    pub connect_timeout: Duration,
    pub keepalive_interval: Option<Duration>,
    pub keepalive_timeout: Option<Duration>,
}

pub struct EndpointDiscovery {
    client: Client,
    namespace: String,
    service_name: String,
    port: u16,
    endpoint_config: EndpointConfig,
    tx: Sender<Change<SocketAddr, Endpoint>>,
    ready_tx: watch::Sender<bool>,
    cancel: CancellationToken,
}

/// Handle for callers to check whether discovery has completed its initial
/// list and has at least one endpoint available.
#[derive(Clone)]
pub struct DiscoveryReadiness {
    rx: watch::Receiver<bool>,
}

impl DiscoveryReadiness {
    pub fn is_ready(&self) -> bool {
        *self.rx.borrow()
    }

    pub async fn wait_until_ready(&mut self) {
        while !*self.rx.borrow_and_update() {
            if self.rx.changed().await.is_err() {
                break;
            }
        }
    }
}

/// Parses an EndpointSlice and returns the set of ready socket addresses.
///
/// An endpoint is considered ready when `conditions.ready` is `true` or when
/// `conditions` is absent entirely (the K8s spec treats a nil ready field as
/// "assume ready").  Endpoints with `ready = false` are skipped.  Address
/// strings that fail IP parsing are also skipped silently.
pub fn extract_ready_addrs(slice: &EndpointSlice, port: u16) -> HashSet<SocketAddr> {
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

impl EndpointDiscovery {
    pub fn new(
        client: Client,
        namespace: String,
        service_name: String,
        port: u16,
        endpoint_config: EndpointConfig,
        cancel: CancellationToken,
    ) -> (Channel, DiscoveryReadiness, Self) {
        let (channel, tx) = Channel::balance_channel::<SocketAddr>(DISCOVERY_CHANNEL_BUFFER);
        let (ready_tx, ready_rx) = watch::channel(false);

        let discovery = Self {
            client,
            namespace,
            service_name,
            port,
            endpoint_config,
            tx,
            ready_tx,
            cancel,
        };

        (channel, DiscoveryReadiness { rx: ready_rx }, discovery)
    }

    /// Constructor for unit tests: accepts a pre-built sender so tests can
    /// observe the change stream without needing a real K8s client or tonic
    /// balance channel.
    #[cfg(test)]
    pub(crate) fn new_for_test(
        port: u16,
        tx: Sender<Change<SocketAddr, Endpoint>>,
    ) -> (Self, DiscoveryReadiness) {
        let (ready_tx, ready_rx) = watch::channel(false);
        let discovery = Self {
            // Safety: this client is never used in tests — `run()` is not
            // called. The dummy URL keeps construction from panicking.
            client: kube::Client::try_from(kube::Config::new(
                "http://localhost:8080".parse().expect("valid test URL"),
            ))
            .expect("kube client"),
            namespace: "test".to_string(),
            service_name: "test-service".to_string(),
            port,
            endpoint_config: EndpointConfig {
                timeout: Duration::from_secs(5),
                connect_timeout: Duration::from_secs(2),
                keepalive_interval: None,
                keepalive_timeout: None,
            },
            tx,
            ready_tx,
            cancel: CancellationToken::new(),
        };
        (discovery, DiscoveryReadiness { rx: ready_rx })
    }

    pub async fn run(self) {
        let api: Api<EndpointSlice> = Api::namespaced(self.client.clone(), &self.namespace);
        let label_selector = format!("kubernetes.io/service-name={}", self.service_name);
        let config = WatcherConfig::default().labels(&label_selector);

        info!(
            service = %self.service_name,
            namespace = %self.namespace,
            port = self.port,
            "starting EndpointSlice discovery"
        );

        let stream = watcher::watcher(api, config);
        tokio::pin!(stream);

        // Track addrs per slice name so we can correctly reconcile when one
        // slice changes without clobbering addrs from other slices.
        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        let mut active_addrs: HashSet<SocketAddr> = HashSet::new();

        loop {
            tokio::select! {
                _ = self.cancel.cancelled() => {
                    info!("endpoint discovery cancelled");
                    break;
                }
                item = stream.next() => {
                    match item {
                        Some(Ok(event)) => {
                            self.handle_event(event, &mut slices, &mut active_addrs).await;
                        }
                        Some(Err(e)) => {
                            warn!(error = %e, "EndpointSlice watcher error, stream will retry");
                            metrics::counter!("personhog_router_discovery_errors_total").increment(1);
                        }
                        None => {
                            warn!("EndpointSlice watcher stream ended unexpectedly");
                            metrics::counter!("personhog_router_discovery_stream_terminated_total").increment(1);
                            break;
                        }
                    }
                }
            }
        }
    }

    async fn handle_event(
        &self,
        event: Event<EndpointSlice>,
        slices: &mut HashMap<String, HashSet<SocketAddr>>,
        active_addrs: &mut HashSet<SocketAddr>,
    ) {
        match event {
            Event::Apply(slice) | Event::InitApply(slice) => {
                let slice_key = slice
                    .metadata
                    .name
                    .clone()
                    .or_else(|| slice.metadata.uid.clone())
                    .unwrap_or_else(|| "unknown".to_string());
                let new_addrs = extract_ready_addrs(&slice, self.port);
                slices.insert(slice_key, new_addrs);
                self.sync_active(slices, active_addrs).await;
            }
            Event::Delete(slice) => {
                let slice_key = slice
                    .metadata
                    .name
                    .or_else(|| slice.metadata.uid.clone())
                    .unwrap_or_else(|| "unknown".to_string());
                slices.remove(&slice_key);
                self.sync_active(slices, active_addrs).await;
            }
            Event::Init => {
                // Clear the slice map but keep active_addrs intact so the
                // balancer continues serving on stale endpoints during the
                // re-list. InitApply events will rebuild `slices`, and
                // InitDone will reconcile against `active_addrs`.
                slices.clear();
            }
            Event::InitDone => {
                self.sync_active(slices, active_addrs).await;
            }
        }
    }

    async fn sync_active(
        &self,
        slices: &HashMap<String, HashSet<SocketAddr>>,
        active_addrs: &mut HashSet<SocketAddr>,
    ) {
        let desired: HashSet<SocketAddr> = slices.values().flatten().copied().collect();

        for addr in desired.difference(active_addrs) {
            let endpoint = self.build_endpoint(*addr);
            if self.tx.send(Change::Insert(*addr, endpoint)).await.is_ok() {
                metrics::counter!("personhog_router_discovery_updates_total", "action" => "insert")
                    .increment(1);
            }
        }

        for addr in active_addrs.difference(&desired) {
            if self.tx.send(Change::Remove(*addr)).await.is_ok() {
                metrics::counter!("personhog_router_discovery_updates_total", "action" => "remove")
                    .increment(1);
            }
        }

        *active_addrs = desired;
        let count = active_addrs.len();
        metrics::gauge!("personhog_router_discovery_endpoints_active").set(count as f64);
        let _ = self.ready_tx.send(count > 0);
    }

    fn build_endpoint(&self, addr: SocketAddr) -> Endpoint {
        let mut ep = Endpoint::from_shared(format!("http://{addr}"))
            .expect("valid endpoint URL")
            .timeout(self.endpoint_config.timeout)
            .connect_timeout(self.endpoint_config.connect_timeout)
            .tcp_nodelay(true);

        if let Some(interval) = self.endpoint_config.keepalive_interval {
            ep = ep
                .http2_keep_alive_interval(interval)
                .keep_alive_while_idle(true);
        }
        if let Some(timeout) = self.endpoint_config.keepalive_timeout {
            ep = ep.keep_alive_timeout(timeout);
        }

        ep
    }
}

#[cfg(test)]
mod tests {
    use std::collections::{HashMap, HashSet};
    use std::net::SocketAddr;

    use k8s_openapi::api::discovery::v1::EndpointSlice;
    use k8s_openapi::api::discovery::v1::{Endpoint as K8sEndpoint, EndpointConditions};
    use k8s_openapi::apimachinery::pkg::apis::meta::v1::ObjectMeta;
    use kube::runtime::watcher::Event;
    use tokio::sync::mpsc;
    use tonic::transport::Endpoint;
    use tower::discover::Change;

    use super::{extract_ready_addrs, EndpointDiscovery};

    // ── helpers ──────────────────────────────────────────────────────────────

    fn make_endpoint_with_conditions(addresses: Vec<&str>, ready: Option<bool>) -> K8sEndpoint {
        K8sEndpoint {
            addresses: addresses.into_iter().map(str::to_string).collect(),
            conditions: ready.map(|r| EndpointConditions {
                ready: Some(r),
                ..Default::default()
            }),
            ..Default::default()
        }
    }

    fn make_endpoint_no_conditions(addresses: Vec<&str>) -> K8sEndpoint {
        K8sEndpoint {
            addresses: addresses.into_iter().map(str::to_string).collect(),
            conditions: None,
            ..Default::default()
        }
    }

    fn make_slice(name: &str, endpoints: Vec<K8sEndpoint>) -> EndpointSlice {
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

    fn addr(ip: &str, port: u16) -> SocketAddr {
        format!("{ip}:{port}").parse().unwrap()
    }

    /// Drain all pending messages from the receiver without blocking.
    fn drain_changes(
        rx: &mut mpsc::Receiver<Change<SocketAddr, Endpoint>>,
    ) -> Vec<Change<SocketAddr, Endpoint>> {
        let mut out = Vec::new();
        while let Ok(msg) = rx.try_recv() {
            out.push(msg);
        }
        out
    }

    fn inserted_addrs(changes: &[Change<SocketAddr, Endpoint>]) -> HashSet<SocketAddr> {
        changes
            .iter()
            .filter_map(|c| match c {
                Change::Insert(addr, _) => Some(*addr),
                Change::Remove(_) => None,
            })
            .collect()
    }

    fn removed_addrs(changes: &[Change<SocketAddr, Endpoint>]) -> HashSet<SocketAddr> {
        changes
            .iter()
            .filter_map(|c| match c {
                Change::Remove(addr) => Some(*addr),
                Change::Insert(_, _) => None,
            })
            .collect()
    }

    // ── extract_ready_addrs ───────────────────────────────────────────────────

    #[test]
    fn extract_ready_addrs_returns_empty_for_empty_slice() {
        let slice = make_slice("s1", vec![]);
        let result = extract_ready_addrs(&slice, 50051);
        assert!(
            result.is_empty(),
            "expected empty set for empty EndpointSlice"
        );
    }

    #[test]
    fn extract_ready_addrs_includes_endpoint_with_ready_true() {
        let slice = make_slice(
            "s1",
            vec![make_endpoint_with_conditions(vec!["10.0.0.1"], Some(true))],
        );
        let result = extract_ready_addrs(&slice, 50051);
        assert_eq!(result, HashSet::from([addr("10.0.0.1", 50051)]));
    }

    #[test]
    fn extract_ready_addrs_excludes_endpoint_with_ready_false() {
        let slice = make_slice(
            "s1",
            vec![make_endpoint_with_conditions(vec!["10.0.0.1"], Some(false))],
        );
        let result = extract_ready_addrs(&slice, 50051);
        assert!(
            result.is_empty(),
            "ready=false endpoint must not be included"
        );
    }

    #[test]
    fn extract_ready_addrs_includes_endpoint_with_no_conditions() {
        // Absent conditions field defaults to ready=true per K8s spec.
        let slice = make_slice("s1", vec![make_endpoint_no_conditions(vec!["10.0.0.2"])]);
        let result = extract_ready_addrs(&slice, 50051);
        assert_eq!(result, HashSet::from([addr("10.0.0.2", 50051)]));
    }

    #[test]
    fn extract_ready_addrs_includes_endpoint_with_conditions_but_nil_ready() {
        // Conditions present but ready field is None — also defaults to true.
        let slice = make_slice(
            "s1",
            vec![K8sEndpoint {
                addresses: vec!["10.0.0.3".to_string()],
                conditions: Some(EndpointConditions {
                    ready: None,
                    ..Default::default()
                }),
                ..Default::default()
            }],
        );
        let result = extract_ready_addrs(&slice, 50051);
        assert_eq!(result, HashSet::from([addr("10.0.0.3", 50051)]));
    }

    #[test]
    fn extract_ready_addrs_uses_provided_port() {
        let slice = make_slice(
            "s1",
            vec![make_endpoint_with_conditions(vec!["10.0.0.1"], Some(true))],
        );
        assert_eq!(
            extract_ready_addrs(&slice, 9090),
            HashSet::from([addr("10.0.0.1", 9090)]),
        );
        assert_eq!(
            extract_ready_addrs(&slice, 1234),
            HashSet::from([addr("10.0.0.1", 1234)]),
        );
    }

    #[test]
    fn extract_ready_addrs_skips_unparseable_address() {
        let slice = make_slice(
            "s1",
            vec![K8sEndpoint {
                addresses: vec!["not-an-ip".to_string(), "10.0.0.5".to_string()],
                conditions: None,
                ..Default::default()
            }],
        );
        let result = extract_ready_addrs(&slice, 50051);
        // The valid address is included; the bad one is silently skipped.
        assert_eq!(result, HashSet::from([addr("10.0.0.5", 50051)]));
    }

    #[test]
    fn extract_ready_addrs_handles_mixed_ready_and_not_ready_endpoints() {
        let slice = make_slice(
            "s1",
            vec![
                make_endpoint_with_conditions(vec!["10.0.0.1"], Some(true)),
                make_endpoint_with_conditions(vec!["10.0.0.2"], Some(false)),
                make_endpoint_no_conditions(vec!["10.0.0.3"]),
            ],
        );
        let result = extract_ready_addrs(&slice, 50051);
        assert_eq!(
            result,
            HashSet::from([addr("10.0.0.1", 50051), addr("10.0.0.3", 50051)]),
        );
    }

    #[test]
    fn extract_ready_addrs_handles_multiple_addresses_per_endpoint() {
        let slice = make_slice(
            "s1",
            vec![make_endpoint_with_conditions(
                vec!["10.0.0.1", "10.0.0.2"],
                Some(true),
            )],
        );
        let result = extract_ready_addrs(&slice, 50051);
        assert_eq!(
            result,
            HashSet::from([addr("10.0.0.1", 50051), addr("10.0.0.2", 50051)]),
        );
    }

    #[test]
    fn extract_ready_addrs_handles_ipv6_address() {
        let slice = make_slice(
            "s1",
            vec![make_endpoint_with_conditions(vec!["::1"], Some(true))],
        );
        let result = extract_ready_addrs(&slice, 50051);
        assert_eq!(
            result,
            HashSet::from(["[::1]:50051".parse::<SocketAddr>().unwrap()])
        );
    }

    // ── sync_active ───────────────────────────────────────────────────────────

    #[tokio::test]
    async fn sync_active_sends_insert_for_new_addr() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        slices.insert("s1".to_string(), HashSet::from([addr("10.0.0.1", 50051)]));
        let mut active: HashSet<SocketAddr> = HashSet::new();

        discovery.sync_active(&slices, &mut active).await;

        let changes = drain_changes(&mut rx);
        assert_eq!(
            inserted_addrs(&changes),
            HashSet::from([addr("10.0.0.1", 50051)]),
            "should insert the new addr",
        );
        assert!(removed_addrs(&changes).is_empty(), "no removes expected");
        assert_eq!(active, HashSet::from([addr("10.0.0.1", 50051)]));
    }

    #[tokio::test]
    async fn sync_active_sends_remove_for_gone_addr() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        let mut active: HashSet<SocketAddr> = HashSet::from([addr("10.0.0.1", 50051)]);

        discovery.sync_active(&slices, &mut active).await;

        let changes = drain_changes(&mut rx);
        assert!(inserted_addrs(&changes).is_empty(), "no inserts expected");
        assert_eq!(
            removed_addrs(&changes),
            HashSet::from([addr("10.0.0.1", 50051)]),
            "should remove the addr that disappeared from desired",
        );
        assert!(active.is_empty());
    }

    #[tokio::test]
    async fn sync_active_noop_when_sets_are_equal() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        slices.insert("s1".to_string(), HashSet::from([addr("10.0.0.1", 50051)]));
        let mut active: HashSet<SocketAddr> = HashSet::from([addr("10.0.0.1", 50051)]);

        discovery.sync_active(&slices, &mut active).await;

        let changes = drain_changes(&mut rx);
        assert!(
            changes.is_empty(),
            "no changes expected when desired == active"
        );
    }

    #[tokio::test]
    async fn sync_active_updates_active_to_desired() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        // Desired: {.1, .2}; Active: {.1, .3}
        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        slices.insert(
            "s1".to_string(),
            HashSet::from([addr("10.0.0.1", 50051), addr("10.0.0.2", 50051)]),
        );
        let mut active: HashSet<SocketAddr> =
            HashSet::from([addr("10.0.0.1", 50051), addr("10.0.0.3", 50051)]);

        discovery.sync_active(&slices, &mut active).await;

        let changes = drain_changes(&mut rx);
        assert_eq!(
            inserted_addrs(&changes),
            HashSet::from([addr("10.0.0.2", 50051)]),
            "only the new addr is inserted",
        );
        assert_eq!(
            removed_addrs(&changes),
            HashSet::from([addr("10.0.0.3", 50051)]),
            "only the gone addr is removed",
        );
        assert_eq!(
            active,
            HashSet::from([addr("10.0.0.1", 50051), addr("10.0.0.2", 50051)]),
        );
    }

    #[tokio::test]
    async fn sync_active_aggregates_addrs_across_slices() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        slices.insert("s1".to_string(), HashSet::from([addr("10.0.0.1", 50051)]));
        slices.insert("s2".to_string(), HashSet::from([addr("10.0.0.2", 50051)]));
        let mut active: HashSet<SocketAddr> = HashSet::new();

        discovery.sync_active(&slices, &mut active).await;

        let changes = drain_changes(&mut rx);
        assert_eq!(
            inserted_addrs(&changes),
            HashSet::from([addr("10.0.0.1", 50051), addr("10.0.0.2", 50051)]),
        );
    }

    // ── handle_event ─────────────────────────────────────────────────────────

    #[tokio::test]
    async fn handle_event_apply_inserts_ready_addrs() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices = HashMap::new();
        let mut active = HashSet::new();

        let slice = make_slice(
            "s1",
            vec![make_endpoint_with_conditions(vec!["10.0.0.1"], Some(true))],
        );
        discovery
            .handle_event(Event::Apply(slice), &mut slices, &mut active)
            .await;

        let changes = drain_changes(&mut rx);
        assert_eq!(
            inserted_addrs(&changes),
            HashSet::from([addr("10.0.0.1", 50051)]),
        );
        assert_eq!(active, HashSet::from([addr("10.0.0.1", 50051)]));
    }

    #[tokio::test]
    async fn handle_event_init_apply_inserts_ready_addrs() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices = HashMap::new();
        let mut active = HashSet::new();

        let slice = make_slice(
            "s1",
            vec![make_endpoint_with_conditions(vec!["10.0.0.2"], Some(true))],
        );
        discovery
            .handle_event(Event::InitApply(slice), &mut slices, &mut active)
            .await;

        let changes = drain_changes(&mut rx);
        assert_eq!(
            inserted_addrs(&changes),
            HashSet::from([addr("10.0.0.2", 50051)]),
        );
    }

    #[tokio::test]
    async fn handle_event_delete_removes_slice_addrs_and_syncs() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        slices.insert("s1".to_string(), HashSet::from([addr("10.0.0.1", 50051)]));
        let mut active: HashSet<SocketAddr> = HashSet::from([addr("10.0.0.1", 50051)]);

        let slice = make_slice("s1", vec![]);
        discovery
            .handle_event(Event::Delete(slice), &mut slices, &mut active)
            .await;

        let changes = drain_changes(&mut rx);
        assert_eq!(
            removed_addrs(&changes),
            HashSet::from([addr("10.0.0.1", 50051)]),
            "delete should trigger removal of the slice's addrs",
        );
        assert!(active.is_empty());
        assert!(!slices.contains_key("s1"), "slice entry should be gone");
    }

    #[tokio::test]
    async fn handle_event_delete_one_slice_does_not_remove_other_slice_addrs() {
        // Critical multi-slice test: deleting s1 must not touch s2's addrs.
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        slices.insert("s1".to_string(), HashSet::from([addr("10.0.0.1", 50051)]));
        slices.insert("s2".to_string(), HashSet::from([addr("10.0.0.2", 50051)]));
        let mut active: HashSet<SocketAddr> =
            HashSet::from([addr("10.0.0.1", 50051), addr("10.0.0.2", 50051)]);

        let slice = make_slice("s1", vec![]);
        discovery
            .handle_event(Event::Delete(slice), &mut slices, &mut active)
            .await;

        let changes = drain_changes(&mut rx);
        assert_eq!(
            removed_addrs(&changes),
            HashSet::from([addr("10.0.0.1", 50051)]),
            "only s1's addr is removed",
        );
        assert!(
            inserted_addrs(&changes).is_empty(),
            "s2's addr is still active and must not be re-inserted",
        );
        assert_eq!(
            active,
            HashSet::from([addr("10.0.0.2", 50051)]),
            "s2's addr must remain in the active set",
        );
    }

    #[tokio::test]
    async fn handle_event_init_clears_slices_but_preserves_active_addrs() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        slices.insert("s1".to_string(), HashSet::from([addr("10.0.0.1", 50051)]));
        let mut active: HashSet<SocketAddr> = HashSet::from([addr("10.0.0.1", 50051)]);

        discovery
            .handle_event(Event::Init, &mut slices, &mut active)
            .await;

        let changes = drain_changes(&mut rx);
        assert!(
            changes.is_empty(),
            "Init must not send any changes — stale endpoints stay in the balancer during re-list",
        );
        assert_eq!(
            active,
            HashSet::from([addr("10.0.0.1", 50051)]),
            "active_addrs must be preserved so the balancer keeps serving during re-list",
        );
        assert!(slices.is_empty(), "slices map must be cleared for re-list");
    }

    #[tokio::test]
    async fn handle_event_init_noop_when_no_active_addrs() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices = HashMap::new();
        let mut active: HashSet<SocketAddr> = HashSet::new();

        discovery
            .handle_event(Event::Init, &mut slices, &mut active)
            .await;

        let changes = drain_changes(&mut rx);
        assert!(
            changes.is_empty(),
            "Init with no active addrs sends nothing"
        );
    }

    #[tokio::test]
    async fn handle_event_init_done_reconciles_active_with_slices() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        // Simulate post-re-list state: slices has the fresh set, active_addrs
        // still has stale endpoints from before Init.
        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        slices.insert("s1".to_string(), HashSet::from([addr("10.0.0.2", 50051)]));
        let mut active: HashSet<SocketAddr> = HashSet::from([addr("10.0.0.1", 50051)]);

        discovery
            .handle_event(Event::InitDone, &mut slices, &mut active)
            .await;

        let changes = drain_changes(&mut rx);
        assert_eq!(
            inserted_addrs(&changes),
            HashSet::from([addr("10.0.0.2", 50051)]),
            "new addr from re-listed slice is inserted",
        );
        assert_eq!(
            removed_addrs(&changes),
            HashSet::from([addr("10.0.0.1", 50051)]),
            "stale addr not in re-listed slices is removed",
        );
        assert_eq!(
            active,
            HashSet::from([addr("10.0.0.2", 50051)]),
            "active matches the re-listed state",
        );
    }

    #[tokio::test]
    async fn handle_event_init_done_noop_when_active_matches_slices() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        slices.insert("s1".to_string(), HashSet::from([addr("10.0.0.1", 50051)]));
        let mut active: HashSet<SocketAddr> = HashSet::from([addr("10.0.0.1", 50051)]);

        discovery
            .handle_event(Event::InitDone, &mut slices, &mut active)
            .await;

        let changes = drain_changes(&mut rx);
        assert!(
            changes.is_empty(),
            "no changes when active already matches re-listed slices",
        );
    }

    #[tokio::test]
    async fn handle_event_apply_updates_existing_slice_addrs() {
        // Simulates a pod being replaced: the same slice name gets new addrs.
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices: HashMap<String, HashSet<SocketAddr>> = HashMap::new();
        slices.insert("s1".to_string(), HashSet::from([addr("10.0.0.1", 50051)]));
        let mut active: HashSet<SocketAddr> = HashSet::from([addr("10.0.0.1", 50051)]);

        let updated_slice = make_slice(
            "s1",
            vec![make_endpoint_with_conditions(vec!["10.0.0.9"], Some(true))],
        );
        discovery
            .handle_event(Event::Apply(updated_slice), &mut slices, &mut active)
            .await;

        let changes = drain_changes(&mut rx);
        assert_eq!(
            inserted_addrs(&changes),
            HashSet::from([addr("10.0.0.9", 50051)]),
            "new addr is inserted",
        );
        assert_eq!(
            removed_addrs(&changes),
            HashSet::from([addr("10.0.0.1", 50051)]),
            "old addr is removed",
        );
        assert_eq!(active, HashSet::from([addr("10.0.0.9", 50051)]));
    }

    #[tokio::test]
    async fn handle_event_apply_slice_without_name_falls_back_to_uid() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices = HashMap::new();
        let mut active = HashSet::new();

        let mut slice = make_slice(
            "s1",
            vec![make_endpoint_with_conditions(vec!["10.0.0.1"], Some(true))],
        );
        slice.metadata.name = None;
        slice.metadata.uid = Some("abc-123".to_string());

        discovery
            .handle_event(Event::Apply(slice), &mut slices, &mut active)
            .await;

        assert!(
            slices.contains_key("abc-123"),
            "unnamed slice stored under UID key"
        );
        let changes = drain_changes(&mut rx);
        assert!(
            !inserted_addrs(&changes).is_empty(),
            "addr is still inserted"
        );
    }

    #[tokio::test]
    async fn handle_event_apply_slice_without_name_or_uid_uses_unknown() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices = HashMap::new();
        let mut active = HashSet::new();

        let mut slice = make_slice(
            "s1",
            vec![make_endpoint_with_conditions(vec!["10.0.0.1"], Some(true))],
        );
        slice.metadata.name = None;
        slice.metadata.uid = None;

        discovery
            .handle_event(Event::Apply(slice), &mut slices, &mut active)
            .await;

        assert!(
            slices.contains_key("unknown"),
            "slice with no name or UID stored under 'unknown' key"
        );
        let changes = drain_changes(&mut rx);
        assert!(
            !inserted_addrs(&changes).is_empty(),
            "addr is still inserted"
        );
    }

    // ── Init → re-list → InitDone full flow ─────────────────────────────────

    #[tokio::test]
    async fn relist_flow_preserves_endpoints_and_reconciles_on_init_done() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let mut slices = HashMap::new();
        let mut active = HashSet::new();

        // Initial state: two pods discovered.
        let slice = make_slice(
            "s1",
            vec![
                make_endpoint_with_conditions(vec!["10.0.0.1"], Some(true)),
                make_endpoint_with_conditions(vec!["10.0.0.2"], Some(true)),
            ],
        );
        discovery
            .handle_event(Event::Apply(slice), &mut slices, &mut active)
            .await;
        drain_changes(&mut rx);

        // API server drops the watch — Init fires.
        discovery
            .handle_event(Event::Init, &mut slices, &mut active)
            .await;
        let changes = drain_changes(&mut rx);
        assert!(
            changes.is_empty(),
            "Init must not send any removes — stale endpoints stay in the balancer",
        );
        assert_eq!(
            active,
            HashSet::from([addr("10.0.0.1", 50051), addr("10.0.0.2", 50051)]),
            "active_addrs preserved during re-list",
        );

        // Re-list: pod .2 is gone, pod .3 is new.
        let relisted_slice = make_slice(
            "s1",
            vec![
                make_endpoint_with_conditions(vec!["10.0.0.1"], Some(true)),
                make_endpoint_with_conditions(vec!["10.0.0.3"], Some(true)),
            ],
        );
        discovery
            .handle_event(Event::InitApply(relisted_slice), &mut slices, &mut active)
            .await;
        // InitApply calls sync_active, but we want to verify the full flow
        // through InitDone, so drain these intermediate changes.
        drain_changes(&mut rx);

        // InitDone signals re-list is complete.
        discovery
            .handle_event(Event::InitDone, &mut slices, &mut active)
            .await;
        let final_changes = drain_changes(&mut rx);

        // At this point active should exactly match the re-listed state.
        assert_eq!(
            active,
            HashSet::from([addr("10.0.0.1", 50051), addr("10.0.0.3", 50051)]),
            "active reflects re-listed endpoints",
        );
        // InitDone sync_active is a no-op here because InitApply already reconciled.
        assert!(
            final_changes.is_empty(),
            "InitDone is a no-op when InitApply already reconciled",
        );
    }
}
