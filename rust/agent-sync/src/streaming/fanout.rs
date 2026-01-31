use parking_lot::RwLock;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::mpsc::{self, Receiver, Sender};

use crate::types::AgentEvent;

const METRIC_DROPPED_EVENTS: &str = "agent_sync_dropped_events_total";

const CHANNEL_BUFFER_SIZE: usize = 1000;

pub struct FanoutRouter {
    subscriptions: RwLock<HashMap<String, Vec<Sender<AgentEvent>>>>,
}

impl FanoutRouter {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            subscriptions: RwLock::new(HashMap::new()),
        })
    }

    pub fn subscribe(&self, run_id: &str) -> Receiver<AgentEvent> {
        let (tx, rx) = mpsc::channel(CHANNEL_BUFFER_SIZE);
        self.subscriptions
            .write()
            .entry(run_id.to_string())
            .or_default()
            .push(tx);
        rx
    }

    pub fn has_subscribers(&self, run_id: &str) -> bool {
        self.subscriptions
            .read()
            .get(run_id)
            .map(|s| !s.is_empty())
            .unwrap_or(false)
    }

    pub async fn route(&self, event: AgentEvent) {
        let run_id = event.run_id.to_string();
        let senders = self.subscriptions.read().get(&run_id).cloned();

        if let Some(senders) = senders {
            for tx in senders {
                if let Err(e) = tx.try_send(event.clone()) {
                    tracing::warn!(
                        run_id = %run_id,
                        error = %e,
                        "Failed to send event to subscriber, channel full or closed"
                    );
                    let labels = vec![
                        ("run_id".to_string(), run_id.clone()),
                        ("reason".to_string(), "channel_full".to_string()),
                    ];
                    common_metrics::inc(METRIC_DROPPED_EVENTS, &labels, 1);
                }
            }
        }
    }

    pub fn cleanup_closed(&self, run_id: &str) {
        let mut subs = self.subscriptions.write();
        if let Some(senders) = subs.get_mut(run_id) {
            senders.retain(|tx| !tx.is_closed());
            if senders.is_empty() {
                subs.remove(run_id);
            }
        }
    }

    pub fn subscriber_count(&self, run_id: &str) -> usize {
        self.subscriptions
            .read()
            .get(run_id)
            .map(|s| s.len())
            .unwrap_or(0)
    }
}

impl Default for FanoutRouter {
    fn default() -> Self {
        Self {
            subscriptions: RwLock::new(HashMap::new()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use uuid::Uuid;

    fn test_event() -> AgentEvent {
        AgentEvent {
            team_id: 1,
            task_id: Uuid::new_v4(),
            run_id: Uuid::new_v4(),
            sequence: 1,
            timestamp: Utc::now(),
            entry_type: "test".to_string(),
            entry: serde_json::json!({"test": true}),
        }
    }

    #[tokio::test]
    async fn test_subscribe_and_receive() {
        let router = FanoutRouter::new();
        let event = test_event();
        let run_id = event.run_id.to_string();

        let mut rx = router.subscribe(&run_id);
        assert!(router.has_subscribers(&run_id));
        assert_eq!(router.subscriber_count(&run_id), 1);

        router.route(event.clone()).await;

        let received = rx.recv().await.unwrap();
        assert_eq!(received.sequence, event.sequence);
    }

    #[tokio::test]
    async fn test_multiple_subscribers() {
        let router = FanoutRouter::new();
        let event = test_event();
        let run_id = event.run_id.to_string();

        let mut rx1 = router.subscribe(&run_id);
        let mut rx2 = router.subscribe(&run_id);
        assert_eq!(router.subscriber_count(&run_id), 2);

        router.route(event.clone()).await;

        let received1 = rx1.recv().await.unwrap();
        let received2 = rx2.recv().await.unwrap();
        assert_eq!(received1.sequence, event.sequence);
        assert_eq!(received2.sequence, event.sequence);
    }

    #[tokio::test]
    async fn test_cleanup_closed() {
        let router = FanoutRouter::new();
        let run_id = "test-run";

        let rx = router.subscribe(run_id);
        assert_eq!(router.subscriber_count(run_id), 1);

        drop(rx);
        router.cleanup_closed(run_id);

        assert_eq!(router.subscriber_count(run_id), 0);
        assert!(!router.has_subscribers(run_id));
    }

    #[test]
    fn test_no_subscribers() {
        let router = FanoutRouter::new();
        assert!(!router.has_subscribers("nonexistent"));
        assert_eq!(router.subscriber_count("nonexistent"), 0);
    }
}
