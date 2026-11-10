use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tonic::transport::{Channel, Endpoint};
use tracing::info;

use crate::backend::affinity::PodChannels;
use crate::backend::discovery::DiscoveryReadiness;
use crate::config::{Http2Windows, RetryConfig};

/// Channels to a backend whose pods are interchangeable (replica or
/// identity), handed out round-robin.
pub struct ChannelBackend {
    role: &'static str,
    channels: Vec<Channel>,
    next_idx: AtomicUsize,
    retry_config: RetryConfig,
    readiness: Option<DiscoveryReadiness>,
    pods: Option<Arc<PodChannels>>,
}

#[derive(Clone)]
pub struct DnsBackendConfig {
    pub url: String,
    pub timeout: Duration,
    pub retry_config: RetryConfig,
    pub keepalive_interval: Option<Duration>,
    pub keepalive_timeout: Option<Duration>,
    pub http2_windows: Http2Windows,
    pub num_channels: usize,
}

fn build_dns_endpoint(role: &str, config: &DnsBackendConfig) -> Endpoint {
    let mut endpoint = Channel::from_shared(config.url.clone())
        .unwrap_or_else(|e| panic!("invalid {role} URL '{}': {e}", config.url))
        .timeout(config.timeout)
        .tcp_nodelay(true);
    if let Some(interval) = config.keepalive_interval {
        endpoint = endpoint
            .http2_keep_alive_interval(interval)
            .keep_alive_while_idle(true);
    }
    if let Some(timeout) = config.keepalive_timeout {
        endpoint = endpoint.keep_alive_timeout(timeout);
    }
    config.http2_windows.apply_to_endpoint(endpoint)
}

impl ChannelBackend {
    /// DNS discovery: opens multiple lazy channels to the ClusterIP service URL
    /// with round-robin selection across them.
    pub fn new_dns(role: &'static str, config: DnsBackendConfig) -> Self {
        let num = config.num_channels.max(1);
        let channels: Vec<Channel> = (0..num)
            .map(|_| build_dns_endpoint(role, &config).connect_lazy())
            .collect();

        info!(
            role,
            url = config.url,
            num_channels = num,
            mode = "dns",
            "created channel backend"
        );

        Self {
            role,
            channels,
            next_idx: AtomicUsize::new(0),
            retry_config: config.retry_config,
            readiness: None,
            pods: None,
        }
    }

    /// K8s discovery: single balanced channel fed by an EndpointDiscovery task
    /// that watches EndpointSlices. Tower's p2c balancer handles per-request
    /// load distribution, so a single channel is sufficient.
    pub fn new_k8s(
        role: &'static str,
        channel: Channel,
        retry_config: RetryConfig,
        readiness: DiscoveryReadiness,
    ) -> Self {
        info!(role, mode = "k8s", "created channel backend");

        Self {
            role,
            channels: vec![channel],
            next_idx: AtomicUsize::new(0),
            retry_config,
            readiness: Some(readiness),
            pods: None,
        }
    }

    pub fn with_pods(mut self, pods: Arc<PodChannels>) -> Self {
        self.pods = Some(pods);
        self
    }

    pub fn role(&self) -> &'static str {
        self.role
    }

    pub fn channel(&self) -> Channel {
        let idx = self.next_idx.fetch_add(1, Ordering::Relaxed) % self.channels.len();
        self.channels[idx].clone()
    }

    /// Best effort: without a key or a known pod, the balanced channel serves the request.
    /// The channel pinned to the key's pod, or none when the backend has no pod for it.
    pub fn pinned_channel(&self, affinity_key: &[u8]) -> Option<Channel> {
        let channel = self.pods.as_ref().and_then(|pods| pods.pick(affinity_key));
        metrics::counter!(
            "personhog_router_affinity_picks_total",
            "role" => self.role,
            "outcome" => if channel.is_some() { "pinned" } else { "unpinned" },
        )
        .increment(1);
        channel
    }

    pub fn channel_for(&self, affinity_key: Option<&[u8]>) -> Channel {
        affinity_key
            .and_then(|key| self.pinned_channel(key))
            .unwrap_or_else(|| self.channel())
    }

    pub fn retry_config(&self) -> &RetryConfig {
        &self.retry_config
    }

    /// False only while EndpointSlice discovery has no member to dial; a DNS
    /// pool resolves on connect and always reports true.
    pub fn has_endpoints(&self) -> bool {
        self.readiness
            .as_ref()
            .is_none_or(DiscoveryReadiness::is_ready)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_backend() -> ChannelBackend {
        ChannelBackend::new_dns(
            "replica",
            DnsBackendConfig {
                url: "http://localhost:50051".to_string(),
                timeout: Duration::from_secs(1),
                retry_config: RetryConfig {
                    max_retries: 0,
                    initial_backoff_ms: 1,
                    max_backoff_ms: 1,
                },
                keepalive_interval: None,
                keepalive_timeout: None,
                http2_windows: Http2Windows::default(),
                num_channels: 4,
            },
        )
    }

    #[tokio::test]
    async fn channel_is_cloneable() {
        let backend = make_backend();
        let _ch1 = backend.channel();
        let _ch2 = backend.channel();
    }

    #[tokio::test]
    async fn dns_backend_always_has_endpoints() {
        assert!(make_backend().has_endpoints());
    }
}
