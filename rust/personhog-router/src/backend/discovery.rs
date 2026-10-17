use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use kube::Client;
use tokio::sync::watch;
use tokio_util::sync::CancellationToken;
use tonic::transport::Endpoint;
use tracing::{info, warn};

use crate::backend::zone::{ZoneBalancer, ZoneFeeds, UNKNOWN_ZONE};
use crate::config::Http2Windows;

pub struct EndpointConfig {
    pub timeout: Duration,
    pub connect_timeout: Duration,
    pub keepalive_interval: Option<Duration>,
    pub keepalive_timeout: Option<Duration>,
    pub http2_windows: Http2Windows,
}

type ActiveEndpoints = HashMap<SocketAddr, Arc<str>>;

/// Feeds backend endpoints into per-zone balance channels, driven by the
/// shared EndpointSlice watch ([`k8s_awareness::watch_service_endpoints`]).
/// This crate only owns the transport side: diffing the member set into
/// inserts and removes, building tonic `Endpoint`s, and exposing readiness.
pub struct EndpointDiscovery {
    role: &'static str,
    client: Client,
    namespace: String,
    service_name: String,
    port: u16,
    endpoint_config: EndpointConfig,
    feeds: ZoneFeeds,
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
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        role: &'static str,
        client: Client,
        namespace: String,
        service_name: String,
        port: u16,
        endpoint_config: EndpointConfig,
        local_zone: Option<String>,
        cancel: CancellationToken,
    ) -> (Arc<ZoneBalancer>, DiscoveryReadiness, Self) {
        let balancer = Arc::new(ZoneBalancer::new(local_zone));
        let (ready_tx, ready_rx) = watch::channel(false);

        let discovery = Self {
            role,
            client,
            namespace,
            service_name,
            port,
            endpoint_config,
            feeds: ZoneFeeds::new(Arc::clone(&balancer)),
            ready_tx,
            cancel,
        };

        (balancer, DiscoveryReadiness { rx: ready_rx }, discovery)
    }

    #[cfg(test)]
    pub(crate) fn new_for_test(
        port: u16,
        local_zone: Option<String>,
    ) -> (Self, DiscoveryReadiness, Arc<ZoneBalancer>) {
        let client = kube::Client::try_from(kube::Config::new(
            "http://localhost:8080".parse().expect("valid test URL"),
        ))
        .expect("kube client");
        let (balancer, readiness, discovery) = Self::new(
            "test",
            client,
            "test".to_string(),
            "test-service".to_string(),
            port,
            EndpointConfig {
                timeout: Duration::from_secs(5),
                connect_timeout: Duration::from_secs(2),
                keepalive_interval: None,
                keepalive_timeout: None,
                http2_windows: Http2Windows::default(),
            },
            local_zone,
            CancellationToken::new(),
        );
        (discovery, readiness, balancer)
    }

    pub async fn run(mut self) {
        info!(
            backend = self.role,
            service = %self.service_name,
            namespace = %self.namespace,
            port = self.port,
            local_zone = self.feeds_local_zone(),
            "starting EndpointSlice discovery"
        );

        let (mut members, _watch_task) = k8s_awareness::watch_service_endpoints(
            self.client.clone(),
            self.namespace.clone(),
            self.service_name.clone(),
            self.cancel.clone(),
        );

        let mut active = ActiveEndpoints::new();

        loop {
            tokio::select! {
                _ = self.cancel.cancelled() => {
                    info!(backend = self.role, "endpoint discovery cancelled");
                    break;
                }
                changed = members.changed() => {
                    if changed.is_err() {
                        // The watch task only exits on cancellation, so a
                        // closed channel means shutdown is underway.
                        warn!(backend = self.role, "EndpointSlice membership watch closed");
                        break;
                    }
                    let desired: ActiveEndpoints = members
                        .borrow_and_update()
                        .iter()
                        .map(|(ip, zone)| {
                            let zone = zone.as_deref().unwrap_or(UNKNOWN_ZONE);
                            (SocketAddr::new(*ip, self.port), Arc::from(zone))
                        })
                        .collect();
                    self.sync_active(&desired, &mut active).await;
                }
            }
        }
    }

    fn feeds_local_zone(&self) -> &str {
        self.feeds.balancer().local_zone().unwrap_or(UNKNOWN_ZONE)
    }

    async fn sync_active(&mut self, desired: &ActiveEndpoints, active: &mut ActiveEndpoints) {
        for (addr, zone) in active.iter() {
            if desired.get(addr) == Some(zone) {
                continue;
            }
            if self.feeds.remove(zone, *addr).await {
                metrics::counter!("personhog_router_discovery_updates_total", "action" => "remove")
                    .increment(1);
            }
        }

        for (addr, zone) in desired {
            if active.get(addr) == Some(zone) {
                continue;
            }
            let endpoint = build_discovered_endpoint(*addr, &self.endpoint_config);
            if self.feeds.insert(zone, *addr, endpoint).await {
                metrics::counter!("personhog_router_discovery_updates_total", "action" => "insert")
                    .increment(1);
            }
        }

        *active = desired.clone();
        let count = self.feeds.publish();
        metrics::gauge!("personhog_router_discovery_endpoints_active").set(count as f64);
        for (zone, zone_count) in self.feeds.endpoint_counts() {
            metrics::gauge!(
                "personhog_router_discovery_zone_endpoints",
                "backend" => self.role,
                "zone" => zone.to_string(),
            )
            .set(zone_count as f64);
        }
        let _ = self.ready_tx.send(count > 0);
    }
}

pub fn build_discovered_endpoint(addr: SocketAddr, config: &EndpointConfig) -> Endpoint {
    let mut ep = Endpoint::from_shared(format!("http://{addr}"))
        .expect("valid endpoint URL")
        .timeout(config.timeout)
        .connect_timeout(config.connect_timeout)
        .tcp_nodelay(true);

    if let Some(interval) = config.keepalive_interval {
        ep = ep
            .http2_keep_alive_interval(interval)
            .keep_alive_while_idle(true);
    }
    if let Some(timeout) = config.keepalive_timeout {
        ep = ep.keep_alive_timeout(timeout);
    }

    config.http2_windows.apply_to_endpoint(ep)
}

#[cfg(test)]
mod tests {
    use std::net::SocketAddr;
    use std::sync::Arc;

    use super::{ActiveEndpoints, EndpointDiscovery};
    use crate::backend::zone::ZoneBalancer;

    fn addr(ip: &str) -> SocketAddr {
        format!("{ip}:50051").parse().unwrap()
    }

    fn endpoints(members: &[(&str, &str)]) -> ActiveEndpoints {
        members
            .iter()
            .map(|(ip, zone)| (addr(ip), Arc::from(*zone)))
            .collect()
    }

    fn counts(balancer: &ZoneBalancer) -> Vec<(String, usize)> {
        balancer
            .endpoint_counts()
            .into_iter()
            .map(|(zone, count)| (zone.to_string(), count))
            .collect()
    }

    #[tokio::test]
    async fn sync_active_files_new_addr_under_its_zone() {
        let (mut discovery, readiness, balancer) = EndpointDiscovery::new_for_test(50051, None);

        let desired = endpoints(&[("10.0.0.1", "us-east-1a")]);
        let mut active = ActiveEndpoints::new();

        discovery.sync_active(&desired, &mut active).await;

        assert_eq!(counts(&balancer), vec![("us-east-1a".to_string(), 1)]);
        assert_eq!(active, desired);
        assert!(readiness.is_ready(), "ready once an endpoint is active");
    }

    #[tokio::test]
    async fn sync_active_removes_gone_addr() {
        let (mut discovery, readiness, balancer) = EndpointDiscovery::new_for_test(50051, None);

        let mut active = ActiveEndpoints::new();
        discovery
            .sync_active(&endpoints(&[("10.0.0.1", "us-east-1a")]), &mut active)
            .await;
        discovery
            .sync_active(&ActiveEndpoints::new(), &mut active)
            .await;

        assert_eq!(counts(&balancer), vec![("us-east-1a".to_string(), 0)]);
        assert!(active.is_empty());
        assert!(!readiness.is_ready(), "not ready with zero endpoints");
    }

    #[tokio::test]
    async fn sync_active_moves_addr_that_changed_zone() {
        let (mut discovery, _readiness, balancer) = EndpointDiscovery::new_for_test(50051, None);

        let mut active = ActiveEndpoints::new();
        discovery
            .sync_active(&endpoints(&[("10.0.0.1", "us-east-1a")]), &mut active)
            .await;
        let desired = endpoints(&[("10.0.0.1", "us-east-1b")]);
        discovery.sync_active(&desired, &mut active).await;

        assert_eq!(
            counts(&balancer),
            vec![("us-east-1a".to_string(), 0), ("us-east-1b".to_string(), 1)]
        );
        assert_eq!(active, desired);
    }

    #[tokio::test]
    async fn sync_active_diffs_mixed_insert_and_remove() {
        let (mut discovery, _readiness, balancer) = EndpointDiscovery::new_for_test(50051, None);

        let mut active = ActiveEndpoints::new();
        discovery
            .sync_active(
                &endpoints(&[("10.0.0.1", "us-east-1a"), ("10.0.0.3", "us-east-1c")]),
                &mut active,
            )
            .await;
        let desired = endpoints(&[("10.0.0.1", "us-east-1a"), ("10.0.0.2", "us-east-1b")]);
        discovery.sync_active(&desired, &mut active).await;

        assert_eq!(
            counts(&balancer),
            vec![
                ("us-east-1a".to_string(), 1),
                ("us-east-1b".to_string(), 1),
                ("us-east-1c".to_string(), 0),
            ]
        );
        assert_eq!(active, desired);
    }
}
