use std::net::SocketAddr;
use std::str::FromStr;
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use cymbal_proto::cymbal::path_resolution::v1::path_resolution_client::PathResolutionClient;
use cymbal_proto::cymbal::path_resolution::v1::{ResolvePathsRequest, ResolvePathsResponse};
use tokio::task::JoinHandle;
use tonic::metadata::{Ascii, MetadataValue};
use tonic::transport::{Channel, Endpoint};
use tonic::{Code, Request};
use tracing::warn;

use crate::modes::path_resolution::auth::PATH_RESOLUTION_SECRET_HEADER;
use crate::stages::resolution::remote::dns::DnsResolver;
use crate::stages::resolution::rendezvous::rendezvous_score;

#[derive(Debug, thiserror::Error)]
pub enum LookupError {
    #[error("no cymbal-path-resolution pods are known")]
    NoPods,
    #[error("cymbal-path-resolution did not answer before the deadline")]
    Timeout,
    #[error("cymbal-path-resolution failed with {0:?}")]
    Failed(Code),
}

#[async_trait]
pub trait PathLookup: Send + Sync {
    async fn resolve_paths(
        &self,
        request: ResolvePathsRequest,
        deadline: Instant,
    ) -> Result<ResolvePathsResponse, LookupError>;
}

#[derive(Clone)]
struct Pod {
    addr: SocketAddr,
    label: String,
    client: PathResolutionClient<Channel>,
}

/// The `cymbal-path-resolution` pods behind a headless service, found through DNS.
pub struct PathResolutionPods {
    host: String,
    port: u16,
    secret: Option<MetadataValue<Ascii>>,
    connect_timeout: Duration,
    dns: Arc<dyn DnsResolver>,
    pods: RwLock<Arc<Vec<Pod>>>,
}

impl PathResolutionPods {
    pub fn new(
        host: String,
        port: u16,
        secret: &str,
        connect_timeout: Duration,
        dns: Arc<dyn DnsResolver>,
    ) -> Arc<Self> {
        let secret = Some(secret.trim())
            .filter(|secret| !secret.is_empty())
            .and_then(|secret| MetadataValue::from_str(secret).ok());
        Arc::new(Self {
            host,
            port,
            secret,
            connect_timeout,
            dns,
            pods: RwLock::new(Arc::new(Vec::new())),
        })
    }

    /// Resolve the service host again. Known pods keep their channel.
    pub async fn refresh(&self) -> std::io::Result<usize> {
        let addrs = self.dns.resolve(&self.host, self.port).await?;
        let current = self.snapshot();
        let mut next = Vec::with_capacity(addrs.len());
        for addr in addrs {
            if let Some(pod) = current.iter().find(|pod| pod.addr == addr) {
                next.push(pod.clone());
                continue;
            }
            match Endpoint::from_shared(format!("http://{addr}")) {
                Ok(endpoint) => next.push(Pod {
                    addr,
                    label: addr.to_string(),
                    client: PathResolutionClient::new(
                        endpoint
                            .connect_timeout(self.connect_timeout)
                            .connect_lazy(),
                    ),
                }),
                Err(error) => warn!(%addr, %error, "invalid cymbal-path-resolution address"),
            }
        }
        let count = next.len();
        *self
            .pods
            .write()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = Arc::new(next);
        Ok(count)
    }

    pub fn spawn_refresh_task(self: &Arc<Self>, every: Duration) -> JoinHandle<()> {
        let pods = self.clone();
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(every);
            loop {
                ticker.tick().await;
                if let Err(error) = pods.refresh().await {
                    warn!(host = %pods.host, %error, "cymbal-path-resolution DNS refresh failed");
                }
            }
        })
    }

    fn snapshot(&self) -> Arc<Vec<Pod>> {
        self.pods
            .read()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .clone()
    }

    fn ranked(&self, routing_key: &str) -> Vec<Pod> {
        let mut pods: Vec<(u64, Pod)> = self
            .snapshot()
            .iter()
            .map(|pod| (rendezvous_score(routing_key, &pod.label), pod.clone()))
            .collect();
        pods.sort_by(|a, b| b.0.cmp(&a.0));
        pods.into_iter().map(|(_, pod)| pod).collect()
    }
}

#[async_trait]
impl PathLookup for PathResolutionPods {
    async fn resolve_paths(
        &self,
        request: ResolvePathsRequest,
        deadline: Instant,
    ) -> Result<ResolvePathsResponse, LookupError> {
        // One commit's list stays warm on one pod, because every processing pod picks the same one.
        let routing_key = format!(
            "team:{}:repo:{}:commit:{}",
            request.team_id, request.repo, request.commit
        );
        let ranked = self.ranked(&routing_key);
        if ranked.is_empty() {
            return Err(LookupError::NoPods);
        }

        // A pod that refuses the connection gets one replacement, inside the same deadline.
        for (attempt, pod) in ranked.into_iter().take(2).enumerate() {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(LookupError::Timeout);
            }
            let mut call = Request::new(request.clone());
            call.set_timeout(remaining);
            if let Some(secret) = &self.secret {
                call.metadata_mut()
                    .insert(PATH_RESOLUTION_SECRET_HEADER, secret.clone());
            }
            let mut client = pod.client;
            match tokio::time::timeout(remaining, client.resolve_paths(call)).await {
                Err(_) => return Err(LookupError::Timeout),
                Ok(Ok(response)) => return Ok(response.into_inner()),
                Ok(Err(status)) if status.code() == Code::Unavailable && attempt == 0 => continue,
                Ok(Err(status))
                    if matches!(status.code(), Code::DeadlineExceeded | Code::Cancelled) =>
                {
                    return Err(LookupError::Timeout)
                }
                Ok(Err(status)) => return Err(LookupError::Failed(status.code())),
            }
        }
        Err(LookupError::Failed(Code::Unavailable))
    }
}

#[cfg(test)]
mod tests {
    use std::io;

    use cymbal_proto::cymbal::path_resolution::v1::path_resolution_server::{
        PathResolution, PathResolutionServer,
    };
    use cymbal_proto::cymbal::path_resolution::v1::ListState;
    use tokio::net::TcpListener;
    use tokio_stream::wrappers::TcpListenerStream;
    use tonic::{Response, Status};

    use super::*;

    struct FixedDns(Vec<SocketAddr>);

    #[async_trait]
    impl DnsResolver for FixedDns {
        async fn resolve(&self, _host: &str, _port: u16) -> io::Result<Vec<SocketAddr>> {
            Ok(self.0.clone())
        }
    }

    struct Answering;

    #[tonic::async_trait]
    impl PathResolution for Answering {
        async fn resolve_paths(
            &self,
            request: tonic::Request<ResolvePathsRequest>,
        ) -> Result<Response<ResolvePathsResponse>, Status> {
            if request
                .metadata()
                .get(PATH_RESOLUTION_SECRET_HEADER)
                .is_none()
            {
                return Err(Status::unauthenticated("no secret"));
            }
            Ok(Response::new(ResolvePathsResponse {
                list_state: ListState::Missing as i32,
                results: Vec::new(),
            }))
        }
    }

    async fn serving_addr() -> SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(
            tonic::transport::Server::builder()
                .add_service(PathResolutionServer::new(Answering))
                .serve_with_incoming(TcpListenerStream::new(listener)),
        );
        addr
    }

    async fn refused_addr() -> SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        listener.local_addr().unwrap()
    }

    fn request() -> ResolvePathsRequest {
        ResolvePathsRequest {
            team_id: 1,
            repo: "github.com/acme/shop".to_string(),
            commit: "0123456789abcdef0123456789abcdef01234567".to_string(),
            paths: vec!["src/index.ts".to_string()],
        }
    }

    #[tokio::test]
    async fn a_refused_connection_moves_to_the_next_pod_once() {
        let serving = serving_addr().await;
        let refused = refused_addr().await;

        // Rendezvous order depends on the ports the OS picked, so try both orders.
        for addrs in [vec![refused, serving], vec![serving, refused]] {
            let pods = PathResolutionPods::new(
                "cymbal-path-resolution".to_string(),
                0,
                "posthog123",
                Duration::from_millis(200),
                Arc::new(FixedDns(addrs)),
            );
            assert_eq!(pods.refresh().await.unwrap(), 2);

            let response = pods
                .resolve_paths(request(), Instant::now() + Duration::from_secs(5))
                .await
                .unwrap();
            assert_eq!(response.list_state, ListState::Missing as i32);
        }
    }

    #[tokio::test]
    async fn no_pods_and_two_refusals_give_no_answer() {
        let empty = PathResolutionPods::new(
            "cymbal-path-resolution".to_string(),
            0,
            "posthog123",
            Duration::from_millis(200),
            Arc::new(FixedDns(Vec::new())),
        );
        empty.refresh().await.unwrap();
        assert!(matches!(
            empty
                .resolve_paths(request(), Instant::now() + Duration::from_secs(1))
                .await,
            Err(LookupError::NoPods)
        ));

        let refusing = PathResolutionPods::new(
            "cymbal-path-resolution".to_string(),
            0,
            "posthog123",
            Duration::from_millis(200),
            Arc::new(FixedDns(vec![refused_addr().await, refused_addr().await])),
        );
        refusing.refresh().await.unwrap();
        assert!(refusing
            .resolve_paths(request(), Instant::now() + Duration::from_secs(1))
            .await
            .is_err());
    }
}
