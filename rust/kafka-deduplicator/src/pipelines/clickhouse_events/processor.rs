//! Batch processor for ClickHouse events pipeline.
//!
//! This processor implements timestamp-based deduplication for events
//! from the `clickhouse_events_json` topic (output of ingestion pipeline).
//!
//! It uses the generic `TimestampDeduplicator` for the core deduplication logic.

use std::sync::Arc;

use anyhow::Result;
use axum::async_trait;
use common_types::ClickHouseEvent;
use futures::future::join_all;
use itertools::Itertools;
use tracing::error;

use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::batch_message::KafkaMessage;
use crate::kafka::types::Partition;
use crate::pipelines::timestamp_deduplicator::{
    TimestampDeduplicator, TimestampDeduplicatorConfig,
};
use crate::pipelines::traits::{EventParser, FailOpenProcessor};
use crate::store::DeduplicationStoreConfig;
use crate::store_manager::StoreManager;

use super::parser::ClickHouseEventParser;

/// Configuration for the ClickHouse events deduplication processor
#[derive(Debug, Clone)]
pub struct ClickHouseEventsConfig {
    pub store_config: DeduplicationStoreConfig,
    /// When true, bypass all deduplication and skip processing entirely.
    pub fail_open: bool,
}

/// Batch processor for ClickHouse events with timestamp-based deduplication.
///
/// This processor wraps `TimestampDeduplicator<ClickHouseEvent>` and implements
/// the `BatchConsumerProcessor` trait for Kafka batch consumption.
pub struct ClickHouseEventsBatchProcessor {
    config: ClickHouseEventsConfig,
    deduplicator: TimestampDeduplicator<ClickHouseEvent>,
}

#[async_trait]
impl BatchConsumerProcessor<ClickHouseEvent> for ClickHouseEventsBatchProcessor {
    async fn process_batch(&self, messages: Vec<KafkaMessage<ClickHouseEvent>>) -> Result<()> {
        if self.config.fail_open {
            return self.process_batch_fail_open(messages).await;
        }

        // Organize messages by partition
        let messages_by_partition = messages
            .iter()
            .map(|message| (message.get_topic_partition(), message))
            .into_group_map();

        // Process partitions concurrently
        let mut promises = vec![];
        for (partition, messages) in messages_by_partition {
            promises.push(self.process_partition_batch(partition, messages));
        }

        let results = join_all(promises).await;

        for result in results {
            result?;
        }

        Ok(())
    }
}

#[async_trait]
impl FailOpenProcessor<ClickHouseEvent> for ClickHouseEventsBatchProcessor {
    async fn process_batch_fail_open(
        &self,
        _messages: Vec<KafkaMessage<ClickHouseEvent>>,
    ) -> Result<()> {
        // Read-only pipeline — nothing to forward in fail-open mode
        Ok(())
    }
}

impl ClickHouseEventsBatchProcessor {
    /// Create a new ClickHouse events deduplication processor
    pub fn new(config: ClickHouseEventsConfig, store_manager: Arc<StoreManager>) -> Self {
        let dedup_config = TimestampDeduplicatorConfig {
            pipeline_name: "clickhouse_events".to_string(),
            publisher: None, // ClickHouse events pipeline doesn't publish
            offset_tracker: None,
        };

        let deduplicator = TimestampDeduplicator::new(dedup_config, store_manager);

        Self {
            config,
            deduplicator,
        }
    }

    async fn process_partition_batch(
        &self,
        partition: Partition,
        messages: Vec<&KafkaMessage<ClickHouseEvent>>,
    ) -> Result<()> {
        // Parse events (identity transform for ClickHouseEvent)
        let parsed_events: Vec<Result<ClickHouseEvent>> = messages
            .iter()
            .map(|msg| ClickHouseEventParser::parse(msg))
            .collect();

        // Collect successful parses
        let events: Vec<&ClickHouseEvent> = parsed_events
            .iter()
            .enumerate()
            .filter_map(|(idx, result)| {
                if let Ok(event) = result {
                    Some(event)
                } else if let Err(e) = &parsed_events[idx] {
                    error!("Failed to parse ClickHouseEvent: {e:#}");
                    None
                } else {
                    None
                }
            })
            .collect();

        if events.is_empty() {
            return Ok(());
        }

        // Deduplicate using the generic deduplicator
        // Metrics are emitted inside deduplicate_batch
        let _results = self
            .deduplicator
            .deduplicate_batch(partition.topic(), partition.partition_number(), events)
            .await?;

        Ok(())
    }

    /// Deduplicate a batch of events (for testing)
    #[cfg(test)]
    pub async fn deduplicate_batch(
        &self,
        topic: &str,
        partition: i32,
        events: Vec<&ClickHouseEvent>,
    ) -> Result<Vec<crate::pipelines::DeduplicationResult<ClickHouseEvent>>> {
        self.deduplicator
            .deduplicate_batch(topic, partition, events)
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::pipelines::{DeduplicationResult, DuplicateReason};
    use crate::test_utils::create_test_tracker;
    use common_types::PersonMode;
    use tempfile::TempDir;
    use uuid::Uuid;

    fn create_test_config() -> (ClickHouseEventsConfig, TempDir) {
        let temp_dir = TempDir::new().unwrap();
        let store_config = DeduplicationStoreConfig {
            path: temp_dir.path().to_path_buf(),
            max_capacity: 1000,
        };

        let config = ClickHouseEventsConfig {
            store_config,
            fail_open: false,
        };
        (config, temp_dir)
    }

    fn create_test_event(
        uuid: Uuid,
        event: &str,
        distinct_id: &str,
        timestamp: &str,
    ) -> ClickHouseEvent {
        ClickHouseEvent {
            uuid,
            team_id: 123,
            project_id: Some(456),
            event: event.to_string(),
            distinct_id: distinct_id.to_string(),
            properties: Some(r#"{"foo": "bar"}"#.to_string()),
            person_id: Some("person-uuid".to_string()),
            timestamp: timestamp.to_string(),
            created_at: "2024-01-01 12:00:00.000000".to_string(),
            captured_at: None,
            elements_chain: None,
            person_created_at: None,
            person_properties: None,
            group0_properties: None,
            group1_properties: None,
            group2_properties: None,
            group3_properties: None,
            group4_properties: None,
            group0_created_at: None,
            group1_created_at: None,
            group2_created_at: None,
            group3_created_at: None,
            group4_created_at: None,
            person_mode: PersonMode::Full,
            historical_migration: None,
        }
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_all_new_events() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        store_manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let processor = ClickHouseEventsBatchProcessor::new(config, store_manager);

        let events = [
            create_test_event(
                Uuid::new_v4(),
                "event1",
                "user1",
                "2024-01-01 12:00:00.000000",
            ),
            create_test_event(
                Uuid::new_v4(),
                "event2",
                "user2",
                "2024-01-01 12:00:01.000000",
            ),
            create_test_event(
                Uuid::new_v4(),
                "event3",
                "user3",
                "2024-01-01 12:00:02.000000",
            ),
        ];

        let event_refs: Vec<&ClickHouseEvent> = events.iter().collect();
        let results = processor
            .deduplicate_batch("test-topic", 0, event_refs)
            .await
            .unwrap();

        assert_eq!(results.len(), 3);
        for result in results {
            assert!(matches!(result, DeduplicationResult::New));
        }
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_duplicate_same_uuid() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        store_manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let processor = ClickHouseEventsBatchProcessor::new(config, store_manager);

        let uuid = Uuid::new_v4();
        let event = create_test_event(uuid, "event1", "user1", "2024-01-01 12:00:00.000000");

        // First occurrence
        let results1 = processor
            .deduplicate_batch("test-topic", 0, vec![&event])
            .await
            .unwrap();
        assert!(matches!(results1[0], DeduplicationResult::New));

        // Second occurrence (exact same event = SameEvent)
        let results2 = processor
            .deduplicate_batch("test-topic", 0, vec![&event])
            .await
            .unwrap();
        assert!(matches!(
            &results2[0],
            DeduplicationResult::ConfirmedDuplicate(info) if info.reason == DuplicateReason::SameEvent
        ));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_duplicate_different_uuid() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        store_manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let processor = ClickHouseEventsBatchProcessor::new(config, store_manager);

        // Same event with different UUIDs (SDK bug scenario)
        let event1 = create_test_event(
            Uuid::new_v4(),
            "event1",
            "user1",
            "2024-01-01 12:00:00.000000",
        );
        let event2 = create_test_event(
            Uuid::new_v4(),
            "event1",
            "user1",
            "2024-01-01 12:00:00.000000",
        );

        let results1 = processor
            .deduplicate_batch("test-topic", 0, vec![&event1])
            .await
            .unwrap();
        assert!(matches!(results1[0], DeduplicationResult::New));

        let results2 = processor
            .deduplicate_batch("test-topic", 0, vec![&event2])
            .await
            .unwrap();
        // Different UUID with same dedup key is detected as OnlyUuidDifferent
        assert!(matches!(
            &results2[0],
            DeduplicationResult::ConfirmedDuplicate(info) if info.reason == DuplicateReason::OnlyUuidDifferent
        ));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_within_batch_duplicates() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        store_manager
            .get_or_create_for_rebalance("test-topic", 0)
            .await
            .unwrap();

        let processor = ClickHouseEventsBatchProcessor::new(config, store_manager);

        let uuid = Uuid::new_v4();
        let event = create_test_event(uuid, "event1", "user1", "2024-01-01 12:00:00.000000");

        // Same event twice in one batch
        let results = processor
            .deduplicate_batch("test-topic", 0, vec![&event, &event])
            .await
            .unwrap();

        assert_eq!(results.len(), 2);
        assert!(matches!(results[0], DeduplicationResult::New));
        // Same exact event in batch = SameEvent (not SameUuid, which is for different content)
        assert!(matches!(
            &results[1],
            DeduplicationResult::ConfirmedDuplicate(info) if info.reason == DuplicateReason::SameEvent
        ));
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_graceful_drop_when_store_missing() {
        let (config, _temp_dir) = create_test_config();
        let store_manager = Arc::new(StoreManager::new(
            config.store_config.clone(),
            create_test_tracker(),
        ));

        // Don't create store - simulates revoked partition
        let processor = ClickHouseEventsBatchProcessor::new(config, store_manager);

        let event = create_test_event(
            Uuid::new_v4(),
            "event1",
            "user1",
            "2024-01-01 12:00:00.000000",
        );

        let result = processor
            .deduplicate_batch("test-topic", 0, vec![&event])
            .await;

        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }
}
