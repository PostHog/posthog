//! Shared test utilities for the kafka-deduplicator crate.
//!
//! This module provides common test helpers to avoid duplication across test files.

use std::sync::Arc;

use crate::rebalance_tracker::RebalanceTracker;

/// Creates a test `RebalanceTracker`.
///
/// This is a convenience function that wraps `RebalanceTracker::new()` in an `Arc`.
pub fn create_test_tracker() -> Arc<RebalanceTracker> {
    Arc::new(RebalanceTracker::new())
}

/// Test helpers for creating test data.
/// These don't depend on dev-dependencies and are available in all builds.
pub mod test_helpers {
    use std::collections::HashMap;
    use std::path::Path;

    use common_types::RawEvent;
    use serde_json::{json, Value};
    use uuid::Uuid;

    use crate::store::{DeduplicationStore, DeduplicationStoreConfig};

    /// Creates a simple test RawEvent with reasonable defaults.
    ///
    /// Use `TestRawEventBuilder` for more control over the event fields.
    pub fn create_test_raw_event() -> RawEvent {
        TestRawEventBuilder::new().build()
    }

    /// Creates a test RawEvent with the specified distinct_id and event name.
    pub fn create_test_raw_event_simple(distinct_id: &str, event: &str) -> RawEvent {
        TestRawEventBuilder::new()
            .distinct_id(distinct_id)
            .event(event)
            .build()
    }

    /// Builder for creating test RawEvents with flexible configuration.
    #[derive(Default)]
    pub struct TestRawEventBuilder {
        uuid: Option<Uuid>,
        event: Option<String>,
        distinct_id: Option<String>,
        token: Option<String>,
        timestamp: Option<String>,
        properties: HashMap<String, Value>,
    }

    impl TestRawEventBuilder {
        pub fn new() -> Self {
            Self::default()
        }

        pub fn uuid(mut self, uuid: Uuid) -> Self {
            self.uuid = Some(uuid);
            self
        }

        pub fn random_uuid(mut self) -> Self {
            self.uuid = Some(Uuid::now_v7());
            self
        }

        pub fn event(mut self, event: &str) -> Self {
            self.event = Some(event.to_string());
            self
        }

        pub fn distinct_id(mut self, distinct_id: &str) -> Self {
            self.distinct_id = Some(distinct_id.to_string());
            self
        }

        pub fn token(mut self, token: &str) -> Self {
            self.token = Some(token.to_string());
            self
        }

        pub fn timestamp(mut self, timestamp: &str) -> Self {
            self.timestamp = Some(timestamp.to_string());
            self
        }

        pub fn current_timestamp(mut self) -> Self {
            self.timestamp = Some(
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs()
                    .to_string(),
            );
            self
        }

        pub fn property(mut self, key: &str, value: Value) -> Self {
            self.properties.insert(key.to_string(), value);
            self
        }

        pub fn build(self) -> RawEvent {
            RawEvent {
                uuid: self.uuid,
                event: self.event.unwrap_or_else(|| "test_event".to_string()),
                distinct_id: Some(json!(self
                    .distinct_id
                    .unwrap_or_else(|| "test_user".to_string()))),
                token: Some(self.token.unwrap_or_else(|| "test_token".to_string())),
                timestamp: self.timestamp,
                properties: self.properties,
                ..Default::default()
            }
        }
    }

    /// Creates a DeduplicationStore at the specified path.
    ///
    /// The caller is responsible for managing the directory lifetime.
    pub fn create_test_dedup_store(path: &Path, topic: &str, partition: i32) -> DeduplicationStore {
        let config = DeduplicationStoreConfig {
            path: path.to_path_buf(),
            max_capacity: 1_000_000,
        };
        DeduplicationStore::new(config, topic.to_string(), partition).unwrap()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_create_test_tracker() {
        let tracker = create_test_tracker();
        assert!(!tracker.is_rebalancing());
    }

    mod test_helpers_tests {
        use super::super::test_helpers::*;
        use super::*;
        use serde_json::json;

        #[test]
        fn test_raw_event_builder_defaults() {
            let event = create_test_raw_event();
            assert_eq!(event.event, "test_event");
            assert!(event.distinct_id.is_some());
            assert!(event.token.is_some());
        }

        #[test]
        fn test_raw_event_builder_custom() {
            let event = TestRawEventBuilder::new()
                .random_uuid()
                .event("custom_event")
                .distinct_id("user123")
                .token("token456")
                .property("key", json!("value"))
                .build();

            assert!(event.uuid.is_some());
            assert_eq!(event.event, "custom_event");
            assert_eq!(event.distinct_id, Some(json!("user123")));
            assert_eq!(event.token, Some("token456".to_string()));
            assert_eq!(event.properties.get("key"), Some(&json!("value")));
        }

        #[test]
        fn test_create_dedup_store() {
            let temp_dir = TempDir::new().unwrap();
            let store = create_test_dedup_store(temp_dir.path(), "test_topic", 0);
            // Store should be usable
            assert!(store.get_total_size().is_ok());
        }
    }
}
