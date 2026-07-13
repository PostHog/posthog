use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;

use tonic::transport::{Channel, Endpoint};
use tracing::info;

use crate::config::RetryConfig;

pub struct ReplicaBackend {
    channels: Vec<Channel>,
    next_idx: AtomicUsize,
    retry_config: RetryConfig,
}

#[derive(Clone)]
pub struct ReplicaDnsConfig {
    pub url: String,
    pub timeout: Duration,
    pub retry_config: RetryConfig,
    pub keepalive_interval: Option<Duration>,
    pub keepalive_timeout: Option<Duration>,
    pub num_channels: usize,
}

fn build_dns_endpoint(config: &ReplicaDnsConfig) -> Endpoint {
    let mut endpoint = Channel::from_shared(config.url.clone())
        .unwrap_or_else(|e| panic!("invalid replica URL '{}': {e}", config.url))
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
    endpoint
}

impl ReplicaBackend {
    /// DNS discovery: opens multiple lazy channels to the ClusterIP service URL
    /// with round-robin selection across them.
    pub fn new_dns(config: ReplicaDnsConfig) -> Self {
        let num = config.num_channels.max(1);
        let channels: Vec<Channel> = (0..num)
            .map(|_| build_dns_endpoint(&config).connect_lazy())
            .collect();

        info!(
            url = config.url,
            num_channels = num,
            mode = "dns",
            "created replica backend"
        );

        Self {
            channels,
            next_idx: AtomicUsize::new(0),
            retry_config: config.retry_config,
        }
    }

    /// K8s discovery: single balanced channel fed by an EndpointDiscovery task
    /// that watches EndpointSlices. Tower's p2c balancer handles per-request
    /// load distribution, so a single channel is sufficient.
    pub fn new_k8s(channel: Channel, retry_config: RetryConfig) -> Self {
        info!(mode = "k8s", "created replica backend");

        Self {
            channels: vec![channel],
            next_idx: AtomicUsize::new(0),
            retry_config,
        }
    }

    pub fn channel(&self) -> Channel {
        let idx = self.next_idx.fetch_add(1, Ordering::Relaxed) % self.channels.len();
        self.channels[idx].clone()
    }

    pub fn retry_config(&self) -> &RetryConfig {
        &self.retry_config
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_backend() -> ReplicaBackend {
        ReplicaBackend::new_dns(ReplicaDnsConfig {
            url: "http://localhost:50051".to_string(),
            timeout: Duration::from_secs(1),
            retry_config: RetryConfig {
                max_retries: 0,
                initial_backoff_ms: 1,
                max_backoff_ms: 1,
            },
            keepalive_interval: None,
            keepalive_timeout: None,
            num_channels: 4,
        })
    }

    #[tokio::test]
    async fn channel_is_cloneable() {
        let backend = make_backend();
        let _ch1 = backend.channel();
        let _ch2 = backend.channel();
    }
}
