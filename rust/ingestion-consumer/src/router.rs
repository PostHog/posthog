use std::collections::HashMap;
use std::hash::{Hash, Hasher};

use metrics::{counter, histogram};

use crate::types::SerializedKafkaMessage;

/// Routes messages to workers using hash-based assignment on `token:distinct_id`.
///
/// All messages for the same distinct_id go to the same worker within a batch,
/// preserving person batching semantics. Stage 4 replaces this with least-loaded
/// assignment for better load distribution on skewed workloads.
pub struct MessageRouter {
    worker_count: usize,
}

impl MessageRouter {
    pub fn new(worker_count: usize) -> Self {
        assert!(worker_count > 0, "worker_count must be > 0");
        Self { worker_count }
    }

    /// Extract the routing key from a message's headers (`token:distinct_id`).
    fn routing_key(message: &SerializedKafkaMessage) -> String {
        let token = message
            .headers
            .get("token")
            .map(|s| s.as_str())
            .unwrap_or("");
        let distinct_id = message
            .headers
            .get("distinct_id")
            .map(|s| s.as_str())
            .unwrap_or("");
        format!("{token}:{distinct_id}")
    }

    /// Assign a routing key to a worker index.
    fn assign(&self, key: &str) -> usize {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        key.hash(&mut hasher);
        (hasher.finish() as usize) % self.worker_count
    }

    /// Route a batch of messages, grouping them by assigned worker index.
    pub fn route_batch(
        &self,
        messages: Vec<SerializedKafkaMessage>,
    ) -> HashMap<usize, Vec<SerializedKafkaMessage>> {
        let mut groups: HashMap<usize, Vec<SerializedKafkaMessage>> = HashMap::new();
        let mut unique_keys: std::collections::HashSet<String> = std::collections::HashSet::new();
        let mut missing_headers: u64 = 0;

        for message in messages {
            let key = Self::routing_key(&message);
            if key == ":" {
                missing_headers += 1;
            }
            unique_keys.insert(key.clone());
            let worker_idx = self.assign(&key);
            groups.entry(worker_idx).or_default().push(message);
        }

        // Record per-worker message distribution
        for (worker_idx, msgs) in &groups {
            counter!("ingestion_consumer_messages_routed_total", "worker" => worker_idx.to_string())
                .increment(msgs.len() as u64);
        }

        histogram!("ingestion_consumer_distinct_ids_per_batch").record(unique_keys.len() as f64);

        if missing_headers > 0 {
            counter!("ingestion_consumer_missing_routing_headers_total").increment(missing_headers);
        }

        groups
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_message(token: &str, distinct_id: &str) -> SerializedKafkaMessage {
        let mut headers = HashMap::new();
        headers.insert("token".to_string(), token.to_string());
        headers.insert("distinct_id".to_string(), distinct_id.to_string());
        SerializedKafkaMessage {
            topic: "test".to_string(),
            partition: 0,
            offset: 0,
            timestamp: 0,
            key: None,
            value: None,
            headers,
        }
    }

    #[test]
    fn same_distinct_id_routes_to_same_worker() {
        let router = MessageRouter::new(4);
        let m1 = make_message("tok", "user-1");
        let m2 = make_message("tok", "user-1");

        let key1 = MessageRouter::routing_key(&m1);
        let key2 = MessageRouter::routing_key(&m2);
        assert_eq!(router.assign(&key1), router.assign(&key2));
    }

    #[test]
    fn route_batch_groups_by_worker() {
        let router = MessageRouter::new(4);
        let messages = vec![
            make_message("tok", "user-1"),
            make_message("tok", "user-2"),
            make_message("tok", "user-1"),
        ];

        let groups = router.route_batch(messages);

        let total: usize = groups.values().map(|v| v.len()).sum();
        assert_eq!(total, 3);

        // user-1 messages should be in the same group
        let user1_worker = router.assign("tok:user-1");
        let user1_msgs = &groups[&user1_worker];
        assert!(user1_msgs.len() >= 2);
    }

    #[test]
    fn empty_headers_produce_consistent_routing() {
        let router = MessageRouter::new(4);
        let m1 = SerializedKafkaMessage {
            topic: "test".to_string(),
            partition: 0,
            offset: 0,
            timestamp: 0,
            key: None,
            value: None,
            headers: HashMap::new(),
        };
        let m2 = SerializedKafkaMessage {
            topic: "test".to_string(),
            partition: 0,
            offset: 1,
            timestamp: 0,
            key: None,
            value: None,
            headers: HashMap::new(),
        };

        let key1 = MessageRouter::routing_key(&m1);
        let key2 = MessageRouter::routing_key(&m2);
        assert_eq!(key1, ":");
        assert_eq!(router.assign(&key1), router.assign(&key2));
    }
}
