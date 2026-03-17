use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use dashmap::DashMap;
use personhog_proto::personhog::leader::v1::person_hog_leader_client::PersonHogLeaderClient;
use personhog_proto::personhog::leader::v1::{
    LeaderGetPersonRequest, UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};
use personhog_proto::personhog::types::v1::{GetPersonRequest, GetPersonResponse};
use tokio::sync::RwLock;
use tonic::transport::Channel;
use tonic::{Request, Status};

use super::retry::with_retry;
use super::LeaderOps;
use crate::config::RetryConfig;

type AddressResolver = Arc<dyn Fn(&str) -> Option<String> + Send + Sync>;

/// Backend that routes person writes and strong reads to leader pods
/// based on Kafka-compatible partitioning of person_id.
pub struct LeaderBackend {
    /// Read-only handle to the routing table (partition → pod_name).
    routing_table: Arc<RwLock<HashMap<u32, String>>>,
    /// Cached gRPC clients keyed by pod gRPC address.
    clients: DashMap<String, PersonHogLeaderClient<Channel>>,
    /// Resolves pod_name → gRPC address.
    address_resolver: AddressResolver,
    /// Number of partitions (must match the Kafka topic partition count).
    num_partitions: u32,
    retry_config: RetryConfig,
    timeout: Duration,
}

impl LeaderBackend {
    pub fn new(
        routing_table: Arc<RwLock<HashMap<u32, String>>>,
        address_resolver: AddressResolver,
        num_partitions: u32,
        timeout: Duration,
        retry_config: RetryConfig,
    ) -> Self {
        assert!(
            num_partitions > 0,
            "num_partitions must be > 0 to avoid division by zero in partition_for_person"
        );
        Self {
            routing_table,
            clients: DashMap::new(),
            address_resolver,
            num_partitions,
            retry_config,
            timeout,
        }
    }

    /// Compute the Kafka partition for a person using murmur2.
    /// The key is `team_id:person_id`, matching the Kafka topic key.
    fn partition_for_person(&self, team_id: i64, person_id: i64) -> u32 {
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
        positive % self.num_partitions
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
            .timeout(self.timeout)
            .connect_lazy();
        let client = PersonHogLeaderClient::new(channel);
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
        with_retry(&self.retry_config, "get_person", || {
            let client_fut = self.resolve_leader(partition);
            let req = leader_req;
            async move {
                let mut client = client_fut.await?;
                client
                    .get_person(Request::new(req))
                    .await
                    .map(|r| r.into_inner())
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
        with_retry(&self.retry_config, "update_person_properties", || {
            let client_fut = self.resolve_leader(partition);
            let req = req_with_partition.clone();
            async move {
                let mut client = client_fut.await?;
                client
                    .update_person_properties(Request::new(req))
                    .await
                    .map(|r| r.into_inner())
            }
        })
        .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
            16,
            Duration::from_secs(5),
            RetryConfig {
                max_retries: 0,
                initial_backoff_ms: 1,
                max_backoff_ms: 1,
            },
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
            8,
            Duration::from_secs(5),
            RetryConfig {
                max_retries: 0,
                initial_backoff_ms: 1,
                max_backoff_ms: 1,
            },
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
            8,
            Duration::from_secs(5),
            RetryConfig {
                max_retries: 0,
                initial_backoff_ms: 1,
                max_backoff_ms: 1,
            },
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
            8,
            Duration::from_secs(5),
            RetryConfig {
                max_retries: 0,
                initial_backoff_ms: 1,
                max_backoff_ms: 1,
            },
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
            8,
            Duration::from_secs(5),
            RetryConfig {
                max_retries: 0,
                initial_backoff_ms: 1,
                max_backoff_ms: 1,
            },
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
            8,
            Duration::from_secs(5),
            RetryConfig {
                max_retries: 0,
                initial_backoff_ms: 1,
                max_backoff_ms: 1,
            },
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
}
