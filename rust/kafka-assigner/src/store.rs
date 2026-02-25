use assignment_coordination::store::EtcdStore;
use etcd_client::{Compare, CompareOp, Txn, TxnOp, WatchStream};

use crate::error::{Error, Result};
use crate::types::{
    AssignmentStatus, ConsumerStatus, HandoffState, PartitionAssignment, RegisteredConsumer,
    TopicConfig, TopicPartition,
};

/// All etcd key patterns used by the kafka-assigner store.
///
/// The consumer group is encoded in the prefix (set at `StoreConfig` level),
/// so keys within a store instance are implicitly group-scoped.
///
/// Full key scheme:
/// ```text
/// {prefix}consumers/{consumer_name}
/// {prefix}assignments/{topic}/{partition}
/// {prefix}handoffs/{topic}/{partition}
/// {prefix}config/topics/{topic}
/// ```
///
/// The leader key (`{prefix}coordinator/leader`) is managed by the
/// `assignment-coordination` crate's leader election module.
enum StoreKey<'a> {
    Consumer(&'a str),
    ConsumersPrefix,
    Assignment {
        topic: &'a str,
        partition: u32,
    },
    AssignmentsPrefix,
    /// All assignments for a specific topic.
    AssignmentsForTopic(&'a str),
    Handoff {
        topic: &'a str,
        partition: u32,
    },
    HandoffsPrefix,
    TopicConfig(&'a str),
    TopicConfigsPrefix,
}

impl StoreKey<'_> {
    fn resolve(&self, prefix: &str) -> String {
        match self {
            StoreKey::Consumer(name) => format!("{prefix}consumers/{name}"),
            StoreKey::ConsumersPrefix => format!("{prefix}consumers/"),
            StoreKey::Assignment { topic, partition } => {
                format!("{prefix}assignments/{topic}/{partition}")
            }
            StoreKey::AssignmentsPrefix => format!("{prefix}assignments/"),
            StoreKey::AssignmentsForTopic(topic) => {
                format!("{prefix}assignments/{topic}/")
            }
            StoreKey::Handoff { topic, partition } => {
                format!("{prefix}handoffs/{topic}/{partition}")
            }
            StoreKey::HandoffsPrefix => format!("{prefix}handoffs/"),
            StoreKey::TopicConfig(topic) => format!("{prefix}config/topics/{topic}"),
            StoreKey::TopicConfigsPrefix => format!("{prefix}config/topics/"),
        }
    }
}

/// Domain-specific store for kafka-assigner coordination state.
///
/// Wraps the shared `EtcdStore` (generic JSON helpers, lease ops) and adds
/// kafka-assigner-specific key resolution and transactional operations.
#[derive(Clone)]
pub struct KafkaAssignerStore {
    inner: EtcdStore,
}

impl KafkaAssignerStore {
    pub fn new(inner: EtcdStore) -> Self {
        Self { inner }
    }

    pub fn inner(&self) -> &EtcdStore {
        &self.inner
    }

    fn key(&self, k: StoreKey<'_>) -> String {
        k.resolve(self.inner.prefix())
    }

    // ── Consumer operations ──────────────────────────────────────

    pub async fn register_consumer(
        &self,
        consumer: &RegisteredConsumer,
        lease_id: i64,
    ) -> Result<()> {
        let key = self.key(StoreKey::Consumer(&consumer.consumer_name));
        Ok(self.inner.put(&key, consumer, Some(lease_id)).await?)
    }

    pub async fn get_consumer(&self, name: &str) -> Result<Option<RegisteredConsumer>> {
        let key = self.key(StoreKey::Consumer(name));
        Ok(self.inner.get(&key).await?)
    }

    pub async fn list_consumers(&self) -> Result<Vec<RegisteredConsumer>> {
        let key = self.key(StoreKey::ConsumersPrefix);
        Ok(self.inner.list(&key).await?)
    }

    pub async fn update_consumer_status(
        &self,
        name: &str,
        status: ConsumerStatus,
        lease_id: i64,
    ) -> Result<()> {
        let key = self.key(StoreKey::Consumer(name));
        let mut consumer: RegisteredConsumer = self
            .inner
            .get(&key)
            .await?
            .ok_or_else(|| Error::NotFound(format!("consumer {name}")))?;
        consumer.status = status;
        Ok(self.inner.put(&key, &consumer, Some(lease_id)).await?)
    }

    pub async fn watch_consumers(&self) -> Result<WatchStream> {
        let key = self.key(StoreKey::ConsumersPrefix);
        Ok(self.inner.watch(&key).await?)
    }

    // ── Assignment operations ───────────────────────────────────

    pub async fn get_assignment(&self, tp: &TopicPartition) -> Result<Option<PartitionAssignment>> {
        let key = self.key(StoreKey::Assignment {
            topic: &tp.topic,
            partition: tp.partition,
        });
        Ok(self.inner.get(&key).await?)
    }

    pub async fn list_assignments(&self) -> Result<Vec<PartitionAssignment>> {
        let key = self.key(StoreKey::AssignmentsPrefix);
        Ok(self.inner.list(&key).await?)
    }

    pub async fn list_assignments_for_topic(
        &self,
        topic: &str,
    ) -> Result<Vec<PartitionAssignment>> {
        let key = self.key(StoreKey::AssignmentsForTopic(topic));
        Ok(self.inner.list(&key).await?)
    }

    pub async fn put_assignments(&self, assignments: &[PartitionAssignment]) -> Result<()> {
        if assignments.is_empty() {
            return Ok(());
        }
        let ops: Vec<TxnOp> = assignments
            .iter()
            .map(|a| {
                let key = self.key(StoreKey::Assignment {
                    topic: &a.topic,
                    partition: a.partition,
                });
                let value = serde_json::to_vec(a).expect("serialize assignment");
                TxnOp::put(key, value, None)
            })
            .collect();
        let txn = Txn::new().and_then(ops);
        self.inner.txn(txn).await?;
        Ok(())
    }

    pub async fn watch_assignments(&self) -> Result<WatchStream> {
        let key = self.key(StoreKey::AssignmentsPrefix);
        Ok(self.inner.watch(&key).await?)
    }

    // ── Handoff operations ──────────────────────────────────────

    pub async fn get_handoff(&self, tp: &TopicPartition) -> Result<Option<HandoffState>> {
        let key = self.key(StoreKey::Handoff {
            topic: &tp.topic,
            partition: tp.partition,
        });
        Ok(self.inner.get(&key).await?)
    }

    pub async fn list_handoffs(&self) -> Result<Vec<HandoffState>> {
        let key = self.key(StoreKey::HandoffsPrefix);
        Ok(self.inner.list(&key).await?)
    }

    pub async fn put_handoff(&self, handoff: &HandoffState) -> Result<()> {
        let key = self.key(StoreKey::Handoff {
            topic: &handoff.topic,
            partition: handoff.partition,
        });
        Ok(self.inner.put(&key, handoff, None).await?)
    }

    pub async fn delete_handoff(&self, tp: &TopicPartition) -> Result<()> {
        let key = self.key(StoreKey::Handoff {
            topic: &tp.topic,
            partition: tp.partition,
        });
        Ok(self.inner.delete(&key).await?)
    }

    pub async fn watch_handoffs(&self) -> Result<WatchStream> {
        let key = self.key(StoreKey::HandoffsPrefix);
        Ok(self.inner.watch(&key).await?)
    }

    // ── Transactional operations ────────────────────────────────

    /// Atomically write assignments and create handoff states.
    pub async fn create_assignments_and_handoffs(
        &self,
        assignments: &[PartitionAssignment],
        handoffs: &[HandoffState],
    ) -> Result<()> {
        let mut ops: Vec<TxnOp> = Vec::with_capacity(assignments.len() + handoffs.len());

        for a in assignments {
            let key = self.key(StoreKey::Assignment {
                topic: &a.topic,
                partition: a.partition,
            });
            let value = serde_json::to_vec(a)?;
            ops.push(TxnOp::put(key, value, None));
        }
        for h in handoffs {
            let key = self.key(StoreKey::Handoff {
                topic: &h.topic,
                partition: h.partition,
            });
            let value = serde_json::to_vec(h)?;
            ops.push(TxnOp::put(key, value, None));
        }

        let txn = Txn::new().and_then(ops);
        self.inner.txn(txn).await?;
        Ok(())
    }

    /// Atomically: set handoff phase to Complete and update the assignment owner.
    ///
    /// Uses compare-and-swap on the handoff key's version to prevent stale
    /// writes (e.g. if another actor already completed or deleted the handoff
    /// between our read and write).
    ///
    /// Returns `Ok(false)` if the handoff was modified concurrently (CAS failed).
    pub async fn complete_handoff(&self, tp: &TopicPartition) -> Result<bool> {
        let handoff_key = self.key(StoreKey::Handoff {
            topic: &tp.topic,
            partition: tp.partition,
        });

        let (mut handoff, version) = self
            .inner
            .get_versioned::<HandoffState>(&handoff_key)
            .await?
            .ok_or_else(|| Error::NotFound(format!("handoff for {}/{}", tp.topic, tp.partition)))?;

        handoff.phase = crate::types::HandoffPhase::Complete;

        let assignment = PartitionAssignment {
            topic: tp.topic.clone(),
            partition: tp.partition,
            owner: handoff.new_owner.clone(),
            status: AssignmentStatus::Active,
        };

        let assignment_key = self.key(StoreKey::Assignment {
            topic: &tp.topic,
            partition: tp.partition,
        });

        let txn = Txn::new()
            .when(vec![Compare::version(
                handoff_key.clone(),
                CompareOp::Equal,
                version,
            )])
            .and_then(vec![
                TxnOp::put(handoff_key, serde_json::to_vec(&handoff)?, None),
                TxnOp::put(assignment_key, serde_json::to_vec(&assignment)?, None),
            ]);
        let resp = self.inner.txn(txn).await?;
        Ok(resp.succeeded())
    }

    // ── Topic config operations ─────────────────────────────────

    pub async fn get_topic_config(&self, topic: &str) -> Result<Option<TopicConfig>> {
        let key = self.key(StoreKey::TopicConfig(topic));
        Ok(self.inner.get(&key).await?)
    }

    pub async fn list_topic_configs(&self) -> Result<Vec<TopicConfig>> {
        let key = self.key(StoreKey::TopicConfigsPrefix);
        Ok(self.inner.list(&key).await?)
    }

    pub async fn set_topic_config(&self, config: &TopicConfig) -> Result<()> {
        let key = self.key(StoreKey::TopicConfig(&config.topic));
        Ok(self.inner.put(&key, config, None).await?)
    }

    // ── Lease operations ────────────────────────────────────────

    pub async fn grant_lease(&self, ttl: i64) -> Result<i64> {
        Ok(self.inner.grant_lease(ttl).await?)
    }

    pub async fn keep_alive(
        &self,
        lease_id: i64,
    ) -> Result<(etcd_client::LeaseKeeper, etcd_client::LeaseKeepAliveStream)> {
        Ok(self.inner.keep_alive(lease_id).await?)
    }

    pub async fn revoke_lease(&self, lease_id: i64) -> Result<()> {
        Ok(self.inner.revoke_lease(lease_id).await?)
    }

    // ── Cleanup ─────────────────────────────────────────────────

    /// Delete all keys under the store's prefix. Useful for tests.
    pub async fn delete_all(&self) -> Result<()> {
        Ok(self.inner.delete_all().await?)
    }
}

/// Parse a watch event's value as JSON into type `T`.
pub fn parse_watch_value<T: serde::de::DeserializeOwned>(
    event: &etcd_client::Event,
) -> std::result::Result<T, Error> {
    Ok(assignment_coordination::store::parse_watch_value(event)?)
}

/// Extract a `TopicPartition` from an etcd key like
/// `{prefix}assignments/{topic}/{partition}` or `{prefix}handoffs/{topic}/{partition}`.
pub fn extract_topic_partition_from_key(key: &str) -> Option<TopicPartition> {
    // Key format: .../{kind}/{topic}/{partition}
    // We need the last two segments.
    let mut parts = key.rsplitn(3, '/');
    let partition_str = parts.next()?;
    let topic = parts.next()?;
    let partition = partition_str.parse().ok()?;
    Some(TopicPartition {
        topic: topic.to_string(),
        partition,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn store_key_consumer() {
        let prefix = "/kafka-assigner/dedup/";
        assert_eq!(
            StoreKey::Consumer("c-0").resolve(prefix),
            "/kafka-assigner/dedup/consumers/c-0"
        );
    }

    #[test]
    fn store_key_assignment() {
        let prefix = "/kafka-assigner/dedup/";
        assert_eq!(
            StoreKey::Assignment {
                topic: "events",
                partition: 42
            }
            .resolve(prefix),
            "/kafka-assigner/dedup/assignments/events/42"
        );
    }

    #[test]
    fn store_key_handoff() {
        let prefix = "/kafka-assigner/dedup/";
        assert_eq!(
            StoreKey::Handoff {
                topic: "events",
                partition: 7
            }
            .resolve(prefix),
            "/kafka-assigner/dedup/handoffs/events/7"
        );
    }

    #[test]
    fn store_key_topic_config() {
        let prefix = "/test/";
        assert_eq!(
            StoreKey::TopicConfig("events_json").resolve(prefix),
            "/test/config/topics/events_json"
        );
    }

    #[test]
    fn extract_topic_partition_from_assignment_key() {
        let key = "/kafka-assigner/dedup/assignments/events_json/42";
        let tp = extract_topic_partition_from_key(key).unwrap();
        assert_eq!(tp.topic, "events_json");
        assert_eq!(tp.partition, 42);
    }

    #[test]
    fn extract_topic_partition_from_handoff_key() {
        let key = "/kafka-assigner/dedup/handoffs/clicks/0";
        let tp = extract_topic_partition_from_key(key).unwrap();
        assert_eq!(tp.topic, "clicks");
        assert_eq!(tp.partition, 0);
    }

    #[test]
    fn store_key_assignments_for_topic() {
        let prefix = "/kafka-assigner/dedup/";
        assert_eq!(
            StoreKey::AssignmentsForTopic("events").resolve(prefix),
            "/kafka-assigner/dedup/assignments/events/"
        );
    }

    #[test]
    fn store_key_topic_configs_prefix() {
        let prefix = "/test/";
        assert_eq!(
            StoreKey::TopicConfigsPrefix.resolve(prefix),
            "/test/config/topics/"
        );
    }

    #[test]
    fn extract_topic_partition_invalid_key() {
        assert!(extract_topic_partition_from_key("no-slashes").is_none());
        assert!(extract_topic_partition_from_key("/prefix/assignments/topic/notanumber").is_none());
    }
}
