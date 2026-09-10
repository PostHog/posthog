use std::collections::HashSet;
use std::net::SocketAddr;
use std::time::Duration;

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

/// Feeds replica endpoints into a tonic balance channel, driven by the shared
/// EndpointSlice membership watch ([`k8s_awareness::watch_service_members`]).
/// This crate only owns the transport side: diffing the member set into
/// `Change::Insert`/`Change::Remove`, building tonic `Endpoint`s, and exposing
/// readiness.
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
        info!(
            service = %self.service_name,
            namespace = %self.namespace,
            port = self.port,
            "starting EndpointSlice discovery"
        );

        let (mut members, _watch_task) = k8s_awareness::watch_service_members(
            self.client.clone(),
            self.namespace.clone(),
            self.service_name.clone(),
            self.cancel.clone(),
        );

        let mut active_addrs: HashSet<SocketAddr> = HashSet::new();

        loop {
            tokio::select! {
                _ = self.cancel.cancelled() => {
                    info!("endpoint discovery cancelled");
                    break;
                }
                changed = members.changed() => {
                    if changed.is_err() {
                        // The watch task only exits on cancellation, so a
                        // closed channel means shutdown is underway.
                        warn!("EndpointSlice membership watch closed");
                        break;
                    }
                    let desired: HashSet<SocketAddr> = members
                        .borrow_and_update()
                        .iter()
                        .map(|ip| SocketAddr::new(*ip, self.port))
                        .collect();
                    self.sync_active(&desired, &mut active_addrs).await;
                }
            }
        }
    }

    async fn sync_active(
        &self,
        desired: &HashSet<SocketAddr>,
        active_addrs: &mut HashSet<SocketAddr>,
    ) {
        for addr in desired.difference(active_addrs) {
            let endpoint = self.build_endpoint(*addr);
            if self.tx.send(Change::Insert(*addr, endpoint)).await.is_ok() {
                metrics::counter!("personhog_router_discovery_updates_total", "action" => "insert")
                    .increment(1);
            }
        }

        for addr in active_addrs.difference(desired) {
            if self.tx.send(Change::Remove(*addr)).await.is_ok() {
                metrics::counter!("personhog_router_discovery_updates_total", "action" => "remove")
                    .increment(1);
            }
        }

        *active_addrs = desired.clone();
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
    use std::collections::HashSet;
    use std::net::SocketAddr;

    use tokio::sync::mpsc;
    use tonic::transport::Endpoint;
    use tower::discover::Change;

    use super::EndpointDiscovery;

    // ── helpers ──────────────────────────────────────────────────────────────

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

    // ── sync_active ───────────────────────────────────────────────────────────

    #[tokio::test]
    async fn sync_active_sends_insert_for_new_addr() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let desired = HashSet::from([addr("10.0.0.1", 50051)]);
        let mut active: HashSet<SocketAddr> = HashSet::new();

        discovery.sync_active(&desired, &mut active).await;

        let changes = drain_changes(&mut rx);
        assert_eq!(
            inserted_addrs(&changes),
            HashSet::from([addr("10.0.0.1", 50051)]),
            "should insert the new addr",
        );
        assert!(removed_addrs(&changes).is_empty(), "no removes expected");
        assert_eq!(active, desired);
        assert!(readiness.is_ready(), "ready once an endpoint is active");
    }

    #[tokio::test]
    async fn sync_active_sends_remove_for_gone_addr() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let desired: HashSet<SocketAddr> = HashSet::new();
        let mut active: HashSet<SocketAddr> = HashSet::from([addr("10.0.0.1", 50051)]);

        discovery.sync_active(&desired, &mut active).await;

        let changes = drain_changes(&mut rx);
        assert!(inserted_addrs(&changes).is_empty(), "no inserts expected");
        assert_eq!(
            removed_addrs(&changes),
            HashSet::from([addr("10.0.0.1", 50051)]),
            "should remove the addr that disappeared from desired",
        );
        assert!(active.is_empty());
        assert!(!readiness.is_ready(), "not ready with zero endpoints");
    }

    #[tokio::test]
    async fn sync_active_noop_when_sets_are_equal() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        let desired = HashSet::from([addr("10.0.0.1", 50051)]);
        let mut active = desired.clone();

        discovery.sync_active(&desired, &mut active).await;

        let changes = drain_changes(&mut rx);
        assert!(
            changes.is_empty(),
            "no changes expected when desired == active"
        );
    }

    #[tokio::test]
    async fn sync_active_diffs_mixed_insert_and_remove() {
        let (tx, mut rx) = mpsc::channel(64);
        let (discovery, _readiness) = EndpointDiscovery::new_for_test(50051, tx);

        // Desired: {.1, .2}; Active: {.1, .3}
        let desired = HashSet::from([addr("10.0.0.1", 50051), addr("10.0.0.2", 50051)]);
        let mut active: HashSet<SocketAddr> =
            HashSet::from([addr("10.0.0.1", 50051), addr("10.0.0.3", 50051)]);

        discovery.sync_active(&desired, &mut active).await;

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
        assert_eq!(active, desired);
    }
}
