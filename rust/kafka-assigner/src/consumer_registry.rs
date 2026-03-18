use dashmap::DashMap;
use tokio::sync::mpsc;

use crate::types::AssignmentEvent;

/// A connected consumer's state on this assigner instance.
pub struct ConsumerConnection {
    pub consumer_name: String,
    /// Channel for pushing assignment events to the consumer's gRPC stream.
    pub command_tx: mpsc::Sender<AssignmentEvent>,
    /// The etcd lease ID backing this consumer's registration.
    pub lease_id: i64,
}

/// Registry of consumers connected to this assigner instance via gRPC.
///
/// Each assigner instance in the cluster has its own registry.
/// The registry does NOT contain all consumers — only those connected
/// to this specific instance.
pub struct ConsumerRegistry {
    connections: DashMap<String, ConsumerConnection>,
}

impl Default for ConsumerRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl ConsumerRegistry {
    pub fn new() -> Self {
        Self {
            connections: DashMap::new(),
        }
    }

    /// Register a consumer connection. Replaces any existing connection
    /// for the same consumer name.
    pub fn register(&self, conn: ConsumerConnection) {
        self.connections.insert(conn.consumer_name.clone(), conn);
    }

    /// Remove a consumer connection. Returns the removed connection if present.
    pub fn unregister(&self, consumer_name: &str) -> Option<ConsumerConnection> {
        self.connections.remove(consumer_name).map(|(_, v)| v)
    }

    /// Get a clone of the command sender for a consumer, if connected.
    pub fn get_sender(&self, consumer_name: &str) -> Option<mpsc::Sender<AssignmentEvent>> {
        self.connections
            .get(consumer_name)
            .map(|c| c.command_tx.clone())
    }

    /// Check if a consumer is connected to this instance.
    pub fn is_connected(&self, consumer_name: &str) -> bool {
        self.connections.contains_key(consumer_name)
    }

    /// Get all connected consumer names.
    pub fn connected_consumers(&self) -> Vec<String> {
        self.connections
            .iter()
            .map(|entry| entry.key().clone())
            .collect()
    }

    /// Get the number of connected consumers.
    pub fn len(&self) -> usize {
        self.connections.len()
    }

    /// Check if the registry is empty.
    pub fn is_empty(&self) -> bool {
        self.connections.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_connection(name: &str) -> (ConsumerConnection, mpsc::Receiver<AssignmentEvent>) {
        let (tx, rx) = mpsc::channel(16);
        let conn = ConsumerConnection {
            consumer_name: name.to_string(),
            command_tx: tx,
            lease_id: 100,
        };
        (conn, rx)
    }

    #[test]
    fn register_and_lookup() {
        let registry = ConsumerRegistry::new();
        let (conn, _rx) = make_connection("c-0");
        registry.register(conn);

        assert!(registry.is_connected("c-0"));
        assert!(!registry.is_connected("c-1"));
        assert!(registry.get_sender("c-0").is_some());
        assert!(registry.get_sender("c-1").is_none());
    }

    #[test]
    fn unregister_removes_connection() {
        let registry = ConsumerRegistry::new();
        let (conn, _rx) = make_connection("c-0");
        registry.register(conn);

        let removed = registry.unregister("c-0");
        assert!(removed.is_some());
        assert!(!registry.is_connected("c-0"));
        assert!(registry.is_empty());
    }

    #[test]
    fn unregister_nonexistent_returns_none() {
        let registry = ConsumerRegistry::new();
        assert!(registry.unregister("c-0").is_none());
    }

    #[test]
    fn connected_consumers_lists_all() {
        let registry = ConsumerRegistry::new();
        let (c0, _rx0) = make_connection("c-0");
        let (c1, _rx1) = make_connection("c-1");
        registry.register(c0);
        registry.register(c1);

        let mut names = registry.connected_consumers();
        names.sort();
        assert_eq!(names, vec!["c-0", "c-1"]);
        assert_eq!(registry.len(), 2);
    }

    #[test]
    fn register_replaces_existing() {
        let registry = ConsumerRegistry::new();
        let (conn1, _rx1) = make_connection("c-0");
        let (conn2, _rx2) = make_connection("c-0");

        registry.register(conn1);
        assert_eq!(registry.len(), 1);

        registry.register(conn2);
        assert_eq!(registry.len(), 1);
    }

    #[tokio::test]
    async fn sender_delivers_commands() {
        let registry = ConsumerRegistry::new();
        let (conn, mut rx) = make_connection("c-0");
        registry.register(conn);

        let sender = registry.get_sender("c-0").unwrap();
        let event = AssignmentEvent::Assignment {
            assigned: vec![],
            unassigned: vec![],
        };
        sender.send(event).await.unwrap();

        let received = rx.recv().await.unwrap();
        assert!(
            matches!(received, AssignmentEvent::Assignment { assigned, unassigned } if assigned.is_empty() && unassigned.is_empty())
        );
    }
}
