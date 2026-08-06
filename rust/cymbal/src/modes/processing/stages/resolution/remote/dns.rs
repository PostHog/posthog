use std::io;
use std::net::SocketAddr;

use async_trait::async_trait;
use tokio::net::lookup_host;

/// DNS resolver abstraction. Production uses `TokioDnsResolver`; tests
/// substitute a deterministic fake so endpoint-pool behavior can be exercised
/// without touching the network.
#[async_trait]
pub trait DnsResolver: Send + Sync + 'static {
    async fn resolve(&self, host: &str, port: u16) -> io::Result<Vec<SocketAddr>>;
}

/// Default DNS resolver backed by tokio's async `lookup_host`. Unlike
/// `common_dns::PublicIPv4Resolver`, this does not filter out private/cluster
/// IPv4 addresses — the cymbal-resolution service typically lives on a
/// cluster-internal hostname (e.g. `cymbal-resolution.posthog.svc.cluster.local`),
/// so filtering by globally-routable IP would remove every legitimate target.
#[derive(Default, Debug)]
pub struct TokioDnsResolver;

#[async_trait]
impl DnsResolver for TokioDnsResolver {
    async fn resolve(&self, host: &str, port: u16) -> io::Result<Vec<SocketAddr>> {
        let target = format!("{host}:{port}");
        let addrs = lookup_host(target).await?.collect::<Vec<_>>();
        Ok(addrs)
    }
}
