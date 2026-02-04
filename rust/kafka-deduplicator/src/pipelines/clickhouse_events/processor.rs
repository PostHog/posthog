//! Batch processor for ClickHouse events pipeline.
//!
//! This processor implements timestamp-based deduplication for events
//! from the `clickhouse_events_json` topic (output of ingestion pipeline).
//!
//! - Detects duplicates based on (timestamp, event, distinct_id, team_id)
//! - Tracks duplicate counts and seen UUIDs

use std::{collections::HashMap, sync::Arc, time::Instant};

use anyhow::Result;
use axum::async_trait;
use common_types::ClickHouseEvent;
use futures::future::join_all;
use itertools::Itertools;
use tracing::error;

use crate::kafka::batch_consumer::BatchConsumerProcessor;
use crate::kafka::batch_message::KafkaMessage;
use crate::kafka::types::Partition;
use crate::metrics_const::PARTITION_BATCH_PROCESSING_DURATION_MS;
use crate::pipelines::processor::{
    batch_read_timestamp_records, batch_write_timestamp_records, emit_deduplication_result_metrics,
    get_result_labels, get_store_or_drop, StoreResult,
};
use crate::pipelines::traits::DeduplicationKeyExtractor;
use crate::pipelines::{DeduplicationResult, DuplicateReason, EnrichedEvent};
use crate::store::DeduplicationStoreConfig;
use crate::store_manager::StoreManager;

use super::metadata::ClickHouseEventMetadata;
use super::parser::ClickHouseEventParser;
use crate::pipelines::traits::EventParser;

/// Configuration for the ClickHouse events deduplication processor
#[derive(Debug, Clone)]
pub struct ClickHouseEventsConfig {
    pub store_config: DeduplicationStoreConfig,
}

/// Batch processor for ClickHouse events with timestamp-based deduplication.
pub struct ClickHouseEventsBatchProcessor {
    config: ClickHouseEventsConfig,
    store_manager: Arc<StoreManager>,
}

#[async_trait]
impl BatchConsumerProcessor<ClickHouseEvent> for ClickHouseEventsBatchProcessor {
    async fn process_batch(&self, messages: Vec<KafkaMessage<ClickHouseEvent>>) -> Result<()> {
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

impl ClickHouseEventsBatchProcessor {
    /// Create a new ClickHouse events deduplication processor
    pub fn new(config: ClickHouseEventsConfig, store_manager: Arc<StoreManager>) -> Self {
        Self {
            config,
            store_manager,
        }
    }

    /// Get the store configuration
    pub fn store_config(&self) -> &DeduplicationStoreConfig {
        &self.config.store_config
    }

    async fn process_partition_batch(
        &self,
        partition: Partition,
        messages: Vec<&KafkaMessage<ClickHouseEvent>>,
    ) -> Result<()> {
        let batch_start = Instant::now();

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
                    error!("Failed to parse ClickHouseEvent: {}", e);
                    None
                } else {
                    None
                }
            })
            .collect();

        if events.is_empty() {
            return Ok(());
        }

        // Deduplicate the batch
        let dedup_results = self
            .deduplicate_batch(partition.topic(), partition.partition_number(), events)
            .await?;

        // Emit metrics
        for result in &dedup_results {
            emit_deduplication_result_metrics(
                partition.topic(),
                partition.partition_number(),
                "clickhouse_events",
                get_result_labels(result),
            );
        }

        // Record batch processing time
        let batch_duration = batch_start.elapsed();
        metrics::histogram!(PARTITION_BATCH_PROCESSING_DURATION_MS)
            .record(batch_duration.as_millis() as f64);

        Ok(())
    }

    async fn deduplicate_batch(
        &self,
        topic: &str,
        partition: i32,
        events: Vec<&ClickHouseEvent>,
    ) -> Result<Vec<DeduplicationResult>> {
        // Get the store for this partition (gracefully drops if not found)
        let store = match get_store_or_drop(&self.store_manager, topic, partition, events.len())? {
            StoreResult::Found(store) => store,
            StoreResult::NotFound => return Ok(vec![]),
        };

        // Step 1: Extract dedup keys
        let enriched_events: Vec<EnrichedEvent<ClickHouseEvent>> = events
            .into_iter()
            .map(|event| EnrichedEvent {
                dedup_key_bytes: event.extract_dedup_key(),
                event,
            })
            .collect();

        // Step 2: Batch read from RocksDB
        let keys_refs: Vec<&[u8]> = enriched_events
            .iter()
            .map(|e| e.dedup_key_bytes.as_slice())
            .collect();
        let existing_records = batch_read_timestamp_records(&store, keys_refs)?;

        // Step 3: Process results and prepare writes
        let event_count = enriched_events.len();
        let mut batch_cache: HashMap<Vec<u8>, Vec<u8>> = HashMap::with_capacity(event_count);
        let mut writes: Vec<(Vec<u8>, Vec<u8>)> = Vec::with_capacity(event_count);
        let mut dedup_results: Vec<DeduplicationResult> = Vec::with_capacity(event_count);

        for (idx, enriched) in enriched_events.iter().enumerate() {
            // Check RocksDB first, then batch cache
            let existing_bytes: Option<&[u8]> = existing_records[idx].as_deref().or_else(|| {
                batch_cache
                    .get(&enriched.dedup_key_bytes)
                    .map(|v| v.as_slice())
            });

            let (result, metadata) = Self::check_duplicate(existing_bytes, enriched.event)?;

            // Serialize and prepare write
            let value = metadata.to_bytes()?;
            writes.push((enriched.dedup_key_bytes.clone(), value.clone()));
            batch_cache.insert(enriched.dedup_key_bytes.clone(), value);

            dedup_results.push(result);
        }

        // Step 4: Batch write to RocksDB
        batch_write_timestamp_records(&store, &writes)?;

        Ok(dedup_results)
    }

    /// Check if an event is a duplicate based on existing metadata
    fn check_duplicate(
        existing_bytes: Option<&[u8]>,
        event: &ClickHouseEvent,
    ) -> Result<(DeduplicationResult, ClickHouseEventMetadata)> {
        match existing_bytes {
            Some(bytes) => {
                let mut metadata = ClickHouseEventMetadata::from_bytes(bytes)?;
                let is_same_uuid = metadata.is_same_uuid(event);
                metadata.update_duplicate(event);

                let result = if is_same_uuid {
                    DeduplicationResult::ConfirmedDuplicate(DuplicateReason::SameUuid)
                } else {
                    DeduplicationResult::PotentialDuplicate
                };

                Ok((result, metadata))
            }
            None => {
                let metadata = ClickHouseEventMetadata::new(event);
                Ok((DeduplicationResult::New, metadata))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
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

        let config = ClickHouseEventsConfig { store_config };
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

        // Second occurrence (same UUID = retry)
        let results2 = processor
            .deduplicate_batch("test-topic", 0, vec![&event])
            .await
            .unwrap();
        assert!(matches!(
            results2[0],
            DeduplicationResult::ConfirmedDuplicate(DuplicateReason::SameUuid)
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
        assert!(matches!(
            results2[0],
            DeduplicationResult::PotentialDuplicate
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
        assert!(matches!(
            results[1],
            DeduplicationResult::ConfirmedDuplicate(DuplicateReason::SameUuid)
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
