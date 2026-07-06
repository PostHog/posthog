use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use bytes::Bytes;
use dashmap::DashMap;
use http::{HeaderMap, HeaderValue};
use http_body_util::{BodyExt, Full};
use metrics::histogram;
use tokio::sync::RwLock;
use tonic::body::BoxBody;
use tonic::transport::Channel;
use tonic::{Code, Status};
use tower::{Service, ServiceExt};

use personhog_common::grpc::current_client_name;

use super::retry::with_retry;
use super::stash::{StashDecision, StashTable};
use crate::config::RetryConfig;
use crate::grpc_http::grpc_error_response;

pub type AddressResolver = Arc<dyn Fn(&str) -> Option<String> + Send + Sync>;

/// gRPC path prefix for the leader service; raw forwards target
/// `{LEADER_PREFIX}{method}`.
const LEADER_PREFIX: &str = "/personhog.leader.v1.PersonHogLeader/";

/// Static configuration for `LeaderBackend`. Bundles the knobs that come
/// from `Config` so the constructor stays narrow as we add fields.
pub struct LeaderBackendConfig {
    pub num_partitions: u32,
    pub timeout: Duration,
    pub retry_config: RetryConfig,
}

/// Backend that routes person writes and strong reads to leader pods
/// based on Kafka-compatible partitioning of person_id.
pub struct LeaderBackend {
    /// Read-only handle to the routing table (partition → pod_name).
    routing_table: Arc<RwLock<HashMap<u32, String>>>,
    /// Cached gRPC channels keyed by pod gRPC address. All leader traffic —
    /// strong reads and writes — forwards raw request frames over these
    /// channels.
    channels: DashMap<String, Channel>,
    /// Resolves pod_name → gRPC address.
    address_resolver: AddressResolver,
    config: LeaderBackendConfig,
    /// Per-partition stash queue used to buffer writes during partition
    /// handoffs. Consulted before every write; normal operation has no stash
    /// entries and hits the dashmap miss-path once per request.
    stash: StashTable,
}

impl LeaderBackend {
    pub fn new(
        routing_table: Arc<RwLock<HashMap<u32, String>>>,
        address_resolver: AddressResolver,
        config: LeaderBackendConfig,
        stash: StashTable,
    ) -> Self {
        assert!(
            config.num_partitions > 0,
            "num_partitions must be > 0 to avoid division by zero in partition_for_person"
        );
        Self {
            routing_table,
            channels: DashMap::new(),
            address_resolver,
            config,
            stash,
        }
    }

    /// Clone of the stash table, for wiring into the `StashHandler`
    /// implementation.
    pub fn stash_table(&self) -> StashTable {
        self.stash.clone()
    }

    /// Remove the cached gRPC channel for a pod so the next request
    /// reconnects. Called during partition handoff cutover to drop the
    /// connection to the old leader pod.
    pub fn clear_client_cache(&self, pod_name: &str) {
        if let Some(address) = (self.address_resolver)(pod_name) {
            self.channels.remove(&address);
        }
    }

    /// Compute the Kafka partition for a person using murmur2.
    /// The key is `team_id:person_id`, matching the Kafka topic key.
    pub fn partition_for_person(&self, team_id: i64, person_id: i64) -> u32 {
        // i64 max string length is 20 chars. Two i64s + ':' = 41 bytes max.
        let mut buf = [0u8; 41];
        let len = {
            use std::io::Write;
            let mut cursor = std::io::Cursor::new(&mut buf[..]);
            write!(cursor, "{team_id}:{person_id}").unwrap();
            cursor.position() as usize
        };
        let hash = kafka_murmur2(&buf[..len]);
        let positive = (hash & 0x7fffffff) as u32;
        positive % self.config.num_partitions
    }

    /// Resolve the leader gRPC channel for a given partition, building and
    /// caching a lazy channel on first use. All leader traffic — strong
    /// reads and writes — forwards raw requests over this channel.
    pub async fn resolve_leader_channel(&self, partition: u32) -> Result<Channel, Status> {
        let pod_name = self
            .routing_table
            .read()
            .await
            .get(&partition)
            .cloned()
            .ok_or_else(|| {
                Status::unavailable(format!("no leader assigned for partition {partition}"))
            })?;

        let address = (self.address_resolver)(&pod_name).ok_or_else(|| {
            Status::unavailable(format!("cannot resolve address for pod {pod_name}"))
        })?;

        if let Some(channel) = self.channels.get(&address) {
            return Ok(channel.clone());
        }

        let channel = Channel::from_shared(address.clone())
            .map_err(|e| Status::internal(format!("invalid leader address: {e}")))?
            .timeout(self.config.timeout)
            .tcp_nodelay(true)
            .connect_lazy();
        self.channels.insert(address, channel.clone());
        Ok(channel)
    }

    /// Forward a raw gRPC request frame to the leader pod owning
    /// `partition`, retrying transient channel failures. The partition
    /// travels in the `x-partition` header the leader reads in place of a
    /// body field; the client's own headers (`x-client-name`,
    /// `x-caller-tag`, etc.) are forwarded verbatim. A leader response that
    /// carries a gRPC error is returned as `Ok` — only transport failures
    /// retry and surface as `Err`. On success also returns the channel
    /// round-trip time, used by the read path's network-overhead metric.
    pub async fn forward_raw(
        &self,
        method: &'static str,
        partition: u32,
        headers: &HeaderMap,
        frame: &Bytes,
    ) -> Result<(http::Response<BoxBody>, f64), Status> {
        let path = format!("{LEADER_PREFIX}{method}");
        let partition_header = HeaderValue::from(partition);
        let client = current_client_name();

        with_retry(&self.config.retry_config, method, || {
            let channel_fut = self.resolve_leader_channel(partition);
            let headers = headers.clone();
            let frame = frame.clone();
            let path = path.clone();
            let partition_header = partition_header.clone();
            let client = client.clone();
            async move {
                let mut channel = channel_fut.await?;

                let ready_start = Instant::now();
                let ready_result = channel.ready().await;
                let ready_outcome = if ready_result.is_ok() { "ok" } else { "error" };
                histogram!(
                    "personhog_router_channel_ready_wait_ms",
                    "method" => method,
                    "client" => client.clone(),
                    "outcome" => ready_outcome,
                )
                .record(ready_start.elapsed().as_secs_f64() * 1000.0);
                let ready = ready_result
                    .map_err(|e| Status::unavailable(format!("leader channel not ready: {e}")))?;

                let body = BoxBody::new(Full::new(frame).map_err(|never| match never {}));
                let mut req = http::Request::new(body);
                *req.method_mut() = http::Method::POST;
                *req.uri_mut() = http::Uri::builder()
                    .path_and_query(path)
                    .build()
                    .expect("leader path is a valid URI");
                *req.version_mut() = http::Version::HTTP_2;
                *req.headers_mut() = headers;
                req.headers_mut().insert("x-partition", partition_header);

                let call_start = Instant::now();
                let call_result = ready.call(req).await;
                let call_ms = call_start.elapsed().as_secs_f64() * 1000.0;
                let call_outcome = if call_result.is_ok() { "ok" } else { "error" };
                histogram!(
                    "personhog_router_channel_call_ms",
                    "method" => method,
                    "client" => client,
                    "outcome" => call_outcome,
                )
                .record(call_ms);
                let response = call_result
                    .map_err(|e| Status::unavailable(format!("leader backend error: {e}")))?;
                Ok((response, call_ms))
            }
        })
        .await
    }

    /// Forward a write to the leader, honoring the per-partition stash.
    /// While a handoff for this partition is in a non-terminal phase the
    /// stash is open and the request parks until drain replays it to the
    /// new owner (or its deadline expires); otherwise it forwards
    /// immediately. Returns the final gRPC response — the leader's, or a
    /// router-generated error when the stash is full or dropped — plus the
    /// channel round-trip time when the request forwarded directly
    /// (`None` for stashed requests, whose latency is dominated by the
    /// handoff wait and tracked by the stash-wait histogram instead).
    pub async fn forward_or_stash(
        &self,
        method: &'static str,
        partition: u32,
        key: (i64, i64),
        headers: HeaderMap,
        frame: Bytes,
    ) -> (http::Response<BoxBody>, Option<f64>) {
        // The stash module emits its own enqueued/rejected counters at the
        // source; we don't double-count here.
        match self
            .stash
            .enqueue_or_forward(partition, frame.clone(), headers.clone(), key)
            .await
        {
            StashDecision::Stashed(rx) => {
                let response = rx.await.unwrap_or_else(|_| {
                    grpc_error_response(
                        Code::Unavailable,
                        "router stash dropped before handoff completed",
                    )
                });
                (response, None)
            }
            StashDecision::Rejected => (
                grpc_error_response(
                    Code::Unavailable,
                    &format!("router stash full for partition {partition}"),
                ),
                None,
            ),
            StashDecision::Forward => {
                match self.forward_raw(method, partition, &headers, &frame).await {
                    Ok((response, call_ms)) => (response, Some(call_ms)),
                    Err(status) => (grpc_error_response(status.code(), status.message()), None),
                }
            }
        }
    }
}

/// Kafka-compatible murmur2 hash.
///
/// This matches the Java Kafka client's `Utils.murmur2()` implementation
/// so that partition assignment is consistent with Kafka's default partitioner.
fn kafka_murmur2(data: &[u8]) -> i32 {
    let length = data.len();
    let seed: i32 = 0x9747b28cu32 as i32;
    let m: i32 = 0x5bd1e995u32 as i32;
    let r: u32 = 24;

    let mut h: i32 = seed ^ (length as i32);

    let length4 = length / 4;
    for i in 0..length4 {
        let i4 = i * 4;
        let mut k: i32 = (data[i4] as i32 & 0xff)
            | ((data[i4 + 1] as i32 & 0xff) << 8)
            | ((data[i4 + 2] as i32 & 0xff) << 16)
            | ((data[i4 + 3] as i32 & 0xff) << 24);

        k = k.wrapping_mul(m);
        k ^= (k as u32 >> r) as i32;
        k = k.wrapping_mul(m);
        h = h.wrapping_mul(m);
        h ^= k;
    }

    let tail = length & !3;
    match length % 4 {
        3 => {
            h ^= (data[tail + 2] as i32 & 0xff) << 16;
            h ^= (data[tail + 1] as i32 & 0xff) << 8;
            h ^= data[tail] as i32 & 0xff;
            h = h.wrapping_mul(m);
        }
        2 => {
            h ^= (data[tail + 1] as i32 & 0xff) << 8;
            h ^= data[tail] as i32 & 0xff;
            h = h.wrapping_mul(m);
        }
        1 => {
            h ^= data[tail] as i32 & 0xff;
            h = h.wrapping_mul(m);
        }
        _ => {}
    }

    h ^= (h as u32 >> 13) as i32;
    h = h.wrapping_mul(m);
    h ^= (h as u32 >> 15) as i32;

    h
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config(num_partitions: u32) -> LeaderBackendConfig {
        LeaderBackendConfig {
            num_partitions,
            timeout: Duration::from_secs(5),
            retry_config: RetryConfig {
                max_retries: 0,
                initial_backoff_ms: 1,
                max_backoff_ms: 1,
            },
        }
    }

    #[test]
    fn murmur2_deterministic_and_consistent() {
        // Same input always produces same hash
        let h1 = kafka_murmur2(b"42");
        let h2 = kafka_murmur2(b"42");
        assert_eq!(h1, h2);

        // Different inputs produce different hashes
        let h3 = kafka_murmur2(b"43");
        assert_ne!(h1, h3);
    }

    /// Pin murmur2 output so accidental algorithm changes are caught.
    /// These values must match `org.apache.kafka.common.utils.Utils.murmur2()`
    /// to ensure partition assignment is consistent with Kafka's default partitioner.
    #[test]
    fn murmur2_pinned_values() {
        assert_eq!(kafka_murmur2(b""), 275646681);
        assert_eq!(kafka_murmur2(b"21"), -973932308);
        assert_eq!(kafka_murmur2(b"42"), 417700972);
        assert_eq!(kafka_murmur2(b"1:42"), -1141388408);
        assert_eq!(kafka_murmur2(b"hello"), 2132663229);
        assert_eq!(kafka_murmur2(b"test-key"), -1341026247);
    }

    #[test]
    fn murmur2_kafka_partition_assignment() {
        // Kafka's toPositive: hash & 0x7fffffff
        let hash = kafka_murmur2(b"21");
        let positive = (hash & 0x7fffffff) as u32;
        let partition = positive % 16;
        assert!(partition < 16);

        // Same input always produces same partition
        let hash2 = kafka_murmur2(b"21");
        assert_eq!(hash, hash2);
    }

    #[test]
    fn partition_for_person_deterministic() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let resolver: AddressResolver = Arc::new(|_| Some("http://localhost:50053".to_string()));
        let backend = LeaderBackend::new(
            routing_table,
            resolver,
            test_config(16),
            StashTable::with_bounds(usize::MAX, usize::MAX),
        );

        let p1 = backend.partition_for_person(1, 42);
        let p2 = backend.partition_for_person(1, 42);
        assert_eq!(p1, p2);
        assert!(p1 < 16);

        // Different person_ids should (likely) produce different partitions
        let p3 = backend.partition_for_person(1, 43);
        assert!(p3 < 16);
    }

    #[test]
    fn partition_distribution_is_reasonable() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let resolver: AddressResolver = Arc::new(|_| Some("http://localhost:50053".to_string()));
        let backend = LeaderBackend::new(
            routing_table,
            resolver,
            test_config(8),
            StashTable::with_bounds(usize::MAX, usize::MAX),
        );

        let mut counts = [0u32; 8];
        for person_id in 1..=1000 {
            let partition = backend.partition_for_person(1, person_id);
            counts[partition as usize] += 1;
        }

        // Each partition should get at least some keys (rough check)
        for (i, count) in counts.iter().enumerate() {
            assert!(
                *count > 50,
                "partition {i} only got {count} keys out of 1000"
            );
        }
    }

    #[tokio::test]
    async fn resolve_leader_returns_unavailable_when_no_assignment() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let resolver: AddressResolver = Arc::new(|_| Some("http://localhost:50053".to_string()));
        let backend = LeaderBackend::new(
            routing_table,
            resolver,
            test_config(8),
            StashTable::with_bounds(usize::MAX, usize::MAX),
        );

        let partition = backend.partition_for_person(1, 42);
        let result = backend.resolve_leader_channel(partition).await;
        assert!(result.is_err());
        assert_eq!(result.unwrap_err().code(), tonic::Code::Unavailable);
    }

    #[tokio::test]
    async fn resolve_leader_returns_unavailable_when_address_unresolvable() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let backend = LeaderBackend::new(
            Arc::clone(&routing_table),
            Arc::new(|_| None), // resolver returns None
            test_config(8),
            StashTable::with_bounds(usize::MAX, usize::MAX),
        );

        let partition = backend.partition_for_person(1, 42);
        routing_table
            .write()
            .await
            .insert(partition, "leader-0".to_string());

        let partition = backend.partition_for_person(1, 42);
        let result = backend.resolve_leader_channel(partition).await;
        assert!(result.is_err());
        assert_eq!(result.unwrap_err().code(), tonic::Code::Unavailable);
    }

    #[tokio::test]
    async fn resolve_leader_returns_client_when_assigned() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let resolver: AddressResolver = Arc::new(|_| Some("http://localhost:50053".to_string()));
        let backend = LeaderBackend::new(
            Arc::clone(&routing_table),
            resolver,
            test_config(8),
            StashTable::with_bounds(usize::MAX, usize::MAX),
        );

        let partition = backend.partition_for_person(1, 42);
        routing_table
            .write()
            .await
            .insert(partition, "leader-0".to_string());

        let partition = backend.partition_for_person(1, 42);
        let result = backend.resolve_leader_channel(partition).await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn resolve_leader_caches_channel() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let resolver: AddressResolver = Arc::new(|_| Some("http://localhost:50053".to_string()));
        let backend = LeaderBackend::new(
            Arc::clone(&routing_table),
            resolver,
            test_config(8),
            StashTable::with_bounds(usize::MAX, usize::MAX),
        );

        let partition = backend.partition_for_person(1, 42);
        routing_table
            .write()
            .await
            .insert(partition, "leader-0".to_string());

        let partition = backend.partition_for_person(1, 42);
        let _channel1 = backend.resolve_leader_channel(partition).await.unwrap();
        assert_eq!(backend.channels.len(), 1);

        let _channel2 = backend.resolve_leader_channel(partition).await.unwrap();
        assert_eq!(backend.channels.len(), 1); // still 1, cached
    }

    /// When the partition's stash is open and full, `forward_or_stash`
    /// must short-circuit with an UNAVAILABLE gRPC response instead of
    /// forwarding, so callers see a retryable status rather than getting
    /// their write silently dropped.
    #[tokio::test]
    async fn forward_or_stash_returns_unavailable_when_stash_full() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let resolver: AddressResolver = Arc::new(|_| Some("http://localhost:50053".to_string()));
        // `max_messages = 0` rejects any enqueue once the stash is open.
        let stash = StashTable::with_bounds(0, usize::MAX);
        let backend = LeaderBackend::new(
            Arc::clone(&routing_table),
            resolver,
            test_config(8),
            stash.clone(),
        );

        // Determine which partition this request lands on, then open the
        // stash for that exact partition.
        let partition = backend.partition_for_person(1, 42);
        stash.begin_stash(partition).await;

        let (response, call_ms) = backend
            .forward_or_stash(
                "UpdatePersonProperties",
                partition,
                (1, 42),
                HeaderMap::new(),
                Bytes::new(),
            )
            .await;

        assert_eq!(
            response.headers().get("grpc-status").unwrap(),
            &format!("{}", Code::Unavailable as i32),
            "rejection must surface as UNAVAILABLE so callers retry"
        );
        assert!(call_ms.is_none(), "no forward happened, so no call time");
    }
}
