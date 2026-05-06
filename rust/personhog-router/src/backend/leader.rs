use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use dashmap::DashMap;
use personhog_proto::personhog::leader::v1::person_hog_leader_client::PersonHogLeaderClient;
use personhog_proto::personhog::leader::v1::LeaderGetPersonRequest;
use personhog_proto::personhog::types::v1::{
    GetPersonRequest, GetPersonResponse, UpdatePersonPropertiesRequest,
    UpdatePersonPropertiesResponse,
};
use tokio::sync::RwLock;
use tonic::codec::CompressionEncoding;
use tonic::transport::Channel;
use tonic::{Request, Status};

use personhog_common::grpc::current_client_name;

use super::retry::with_retry;
use super::stash::{StashDecision, StashTable};
use super::LeaderOps;
use crate::config::RetryConfig;

pub type AddressResolver = Arc<dyn Fn(&str) -> Option<String> + Send + Sync>;

/// Static configuration for `LeaderBackend`. Mirrors `ReplicaBackendConfig`
/// in the same crate; bundles the knobs that come from `Config` so the
/// constructor stays narrow as we add fields.
pub struct LeaderBackendConfig {
    pub num_partitions: u32,
    pub timeout: Duration,
    pub retry_config: RetryConfig,
    pub max_send_message_size: usize,
    pub max_recv_message_size: usize,
}

/// Backend that routes person writes and strong reads to leader pods
/// based on Kafka-compatible partitioning of person_id.
pub struct LeaderBackend {
    /// Read-only handle to the routing table (partition → pod_name).
    routing_table: Arc<RwLock<HashMap<u32, String>>>,
    /// Cached gRPC clients keyed by pod gRPC address.
    clients: DashMap<String, PersonHogLeaderClient<Channel>>,
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
            clients: DashMap::new(),
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

    /// Remove cached gRPC client for a pod so the next request reconnects.
    /// Called during partition handoff cutover to drop the connection to the
    /// old leader pod.
    pub fn clear_client_cache(&self, pod_name: &str) {
        if let Some(address) = (self.address_resolver)(pod_name) {
            self.clients.remove(&address);
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

    /// Resolve the leader gRPC client for a given partition.
    async fn resolve_leader(
        &self,
        partition: u32,
    ) -> Result<PersonHogLeaderClient<Channel>, Status> {
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

        if let Some(client) = self.clients.get(&address) {
            return Ok(client.clone());
        }

        let channel = Channel::from_shared(address.clone())
            .map_err(|e| Status::internal(format!("invalid leader address: {e}")))?
            .timeout(self.config.timeout)
            .tcp_nodelay(true)
            .connect_lazy();
        let client = PersonHogLeaderClient::new(channel)
            .max_encoding_message_size(self.config.max_send_message_size)
            .max_decoding_message_size(self.config.max_recv_message_size)
            .send_compressed(CompressionEncoding::Zstd)
            .accept_compressed(CompressionEncoding::Zstd);
        self.clients.insert(address, client.clone());
        Ok(client)
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

#[async_trait]
impl LeaderOps for LeaderBackend {
    async fn get_person(&self, request: GetPersonRequest) -> Result<GetPersonResponse, Status> {
        let partition = self.partition_for_person(request.team_id, request.person_id);
        let leader_req = LeaderGetPersonRequest {
            team_id: request.team_id,
            person_id: request.person_id,
            partition,
        };
        with_retry(&self.config.retry_config, "get_person", || {
            let client_fut = self.resolve_leader(partition);
            let req = leader_req;
            let client_name = current_client_name();
            async move {
                let mut client = client_fut.await?;
                let mut request = Request::new(req);
                if let Ok(val) = client_name.parse() {
                    request.metadata_mut().insert("x-client-name", val);
                }
                client.get_person(request).await.map(|r| r.into_inner())
            }
        })
        .await
    }

    async fn update_person_properties(
        &self,
        request: UpdatePersonPropertiesRequest,
    ) -> Result<UpdatePersonPropertiesResponse, Status> {
        let partition = self.partition_for_person(request.team_id, request.person_id);
        let mut req_with_partition = request;
        req_with_partition.partition = partition;

        // Stash fast path. While a handoff for this partition is in any
        // non-terminal phase (`Freezing`, `Draining`, or `Warming`), the
        // partition is registered in the stash table and writes are
        // queued instead of forwarded. The coordinator atomically writes
        // `Complete` together with the new `PartitionAssignment`; at
        // that point `drain_stash` flushes the queue to the new owner
        // via `update_person_properties_no_stash` (bypassing this hook
        // to avoid re-enqueueing during drain), and subsequent requests
        // fall through to the normal forward path below.
        // The stash module emits its own enqueued/rejected counters with
        // appropriate labels at the source; we don't double-count here.
        match self
            .stash
            .enqueue_or_forward(
                partition,
                req_with_partition.clone(),
                Some(current_client_name().to_string()),
            )
            .await
        {
            StashDecision::Stashed(rx) => {
                return rx.await.unwrap_or_else(|_| {
                    Err(Status::unavailable(
                        "router stash dropped before handoff completed",
                    ))
                });
            }
            StashDecision::Rejected => {
                return Err(Status::unavailable(format!(
                    "router stash full for partition {partition}"
                )));
            }
            StashDecision::Forward => {}
        }

        self.forward_to_leader(req_with_partition, partition).await
    }
}

impl LeaderBackend {
    /// Forward an update directly to the leader, bypassing the stash
    /// hook. Used by the drain handler so each replayed request goes to
    /// the leader instead of re-entering the stash queue (which would
    /// deadlock the drain — the dashmap entry is still present until
    /// the drain loop observes the queue empty under the lock).
    ///
    /// Callers that want the normal stash-aware path should call
    /// `update_person_properties` instead. This method assumes its
    /// caller has already computed the correct partition and stamped
    /// it onto the request.
    pub async fn update_person_properties_no_stash(
        &self,
        request: UpdatePersonPropertiesRequest,
    ) -> Result<UpdatePersonPropertiesResponse, Status> {
        let partition = request.partition;
        self.forward_to_leader(request, partition).await
    }

    /// Internal: do the actual gRPC forward to the leader for a given
    /// partition, with retry on transient errors. Shared between the
    /// normal `update_person_properties` (post-stash) and the drain's
    /// `update_person_properties_no_stash` path.
    async fn forward_to_leader(
        &self,
        request: UpdatePersonPropertiesRequest,
        partition: u32,
    ) -> Result<UpdatePersonPropertiesResponse, Status> {
        with_retry(
            &self.config.retry_config,
            "update_person_properties",
            || {
                let client_fut = self.resolve_leader(partition);
                let req = request.clone();
                let client_name = current_client_name();
                async move {
                    let mut client = client_fut.await?;
                    let mut request = Request::new(req);
                    if let Ok(val) = client_name.parse() {
                        request.metadata_mut().insert("x-client-name", val);
                    }
                    client
                        .update_person_properties(request)
                        .await
                        .map(|r| r.into_inner())
                }
            },
        )
        .await
    }
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
            max_send_message_size: 4 * 1024 * 1024,
            max_recv_message_size: 4 * 1024 * 1024,
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
        let result = backend.resolve_leader(partition).await;
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
        let result = backend.resolve_leader(partition).await;
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
        let result = backend.resolve_leader(partition).await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn resolve_leader_caches_client() {
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
        let _client1 = backend.resolve_leader(partition).await.unwrap();
        assert_eq!(backend.clients.len(), 1);

        let _client2 = backend.resolve_leader(partition).await.unwrap();
        assert_eq!(backend.clients.len(), 1); // still 1, cached
    }

    /// When the partition's stash is open and full, `update_person_properties`
    /// must short-circuit with `Status::unavailable` instead of falling
    /// through to the forward path. This proves the stash-rejection branch
    /// in `update_person_properties` and that callers see a retryable
    /// error code rather than getting their request silently dropped.
    #[tokio::test]
    async fn update_person_properties_returns_unavailable_when_stash_full() {
        use personhog_proto::personhog::types::v1::UpdatePersonPropertiesRequest;
        use tonic::Code;

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

        let request = UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            partition: 0, // overwritten by update_person_properties
            event_name: "test".to_string(),
            set_properties: Vec::new(),
            set_once_properties: Vec::new(),
            unset_properties: Vec::new(),
        };

        let result = backend.update_person_properties(request).await;
        let err = result.expect_err("stash with max_messages=0 must reject");
        assert_eq!(
            err.code(),
            Code::Unavailable,
            "rejection must surface as UNAVAILABLE so callers retry"
        );
    }
}
