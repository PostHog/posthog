use std::collections::HashMap;
use std::hash::Hasher;

use siphasher::sip::SipHasher13;

use crate::types::SerializedMessage;

pub struct MessageRouter {
    target_count: usize,
}

impl MessageRouter {
    pub fn new(target_count: usize) -> Self {
        assert!(target_count > 0, "target_count must be > 0");
        Self { target_count }
    }

    pub fn route_batch(
        &self,
        messages: Vec<SerializedMessage>,
    ) -> HashMap<usize, Vec<SerializedMessage>> {
        let mut groups: HashMap<usize, Vec<SerializedMessage>> = HashMap::new();

        for msg in messages {
            let target = self.route_message(&msg);
            groups.entry(target).or_default().push(msg);
        }

        groups
    }

    fn route_message(&self, msg: &SerializedMessage) -> usize {
        let token = msg.get_header("token").unwrap_or_default();
        let distinct_id = msg.get_header("distinct_id").unwrap_or_default();
        let routing_key = format!("{token}:{distinct_id}");

        let mut hasher = SipHasher13::new();
        hasher.write(routing_key.as_bytes());
        let hash = hasher.finish();

        (hash % self.target_count as u64) as usize
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::SerializedMessage;

    fn make_message(token: &str, distinct_id: &str) -> SerializedMessage {
        SerializedMessage::from_kafka_message(
            "events_plugin_ingestion",
            0,
            0,
            None,
            None,
            Some(b"{}"),
            vec![
                ("token".to_string(), token.as_bytes().to_vec()),
                ("distinct_id".to_string(), distinct_id.as_bytes().to_vec()),
            ],
        )
    }

    #[test]
    fn test_same_key_routes_to_same_target() {
        let router = MessageRouter::new(4);

        let msg1 = make_message("phc_abc", "user-1");
        let msg2 = make_message("phc_abc", "user-1");

        let mut groups = router.route_batch(vec![msg1]);
        let target1 = *groups.keys().next().unwrap();

        groups = router.route_batch(vec![msg2]);
        let target2 = *groups.keys().next().unwrap();

        assert_eq!(target1, target2);
    }

    #[test]
    fn test_different_token_same_distinct_id_routes_differently() {
        let router = MessageRouter::new(100);

        let msg1 = make_message("phc_abc", "user-1");
        let msg2 = make_message("phc_xyz", "user-1");

        let groups1 = router.route_batch(vec![msg1]);
        let groups2 = router.route_batch(vec![msg2]);

        let target1 = *groups1.keys().next().unwrap();
        let target2 = *groups2.keys().next().unwrap();

        // With 100 targets, different tokens should (almost certainly) route to different targets
        assert_ne!(target1, target2);
    }

    #[test]
    fn test_distribution_across_targets() {
        let router = MessageRouter::new(4);
        let mut messages = Vec::new();

        for i in 0..1000 {
            messages.push(make_message("phc_abc", &format!("user-{i}")));
        }

        let groups = router.route_batch(messages);

        // All 4 targets should receive some messages
        for target in 0..4 {
            assert!(
                groups.get(&target).map_or(0, |v| v.len()) > 50,
                "target {target} received too few messages"
            );
        }
    }

    #[test]
    fn test_empty_headers_route_deterministically() {
        let router = MessageRouter::new(4);

        let msg1 = SerializedMessage::from_kafka_message(
            "test",
            0,
            0,
            None,
            None,
            Some(b"{}"),
            vec![],
        );
        let msg2 = SerializedMessage::from_kafka_message(
            "test",
            0,
            1,
            None,
            None,
            Some(b"{}"),
            vec![],
        );

        let groups1 = router.route_batch(vec![msg1]);
        let groups2 = router.route_batch(vec![msg2]);

        let target1 = *groups1.keys().next().unwrap();
        let target2 = *groups2.keys().next().unwrap();

        // Both messages without headers route to the same target (hash of ":")
        assert_eq!(target1, target2);
    }

    #[test]
    fn test_route_batch_groups_correctly() {
        let router = MessageRouter::new(4);

        let messages = vec![
            make_message("phc_abc", "user-1"),
            make_message("phc_abc", "user-1"), // same key, same target
            make_message("phc_abc", "user-2"),
        ];

        let groups = router.route_batch(messages);

        let total: usize = groups.values().map(|v| v.len()).sum();
        assert_eq!(total, 3);
    }
}
