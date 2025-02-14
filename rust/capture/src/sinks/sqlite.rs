use crate::api::CaptureError;
use crate::sinks::Event;
use crate::v0_request::{ProcessedEvent, ProcessedEventMetadata, DataType};
use common_types::CapturedEvent;
use async_trait::async_trait;
use health::HealthHandle;
use metrics::{counter, histogram};
use sqlx::{Pool, Sqlite, SqlitePool};
use sqlx;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use tokio::task;
use tokio::time::{sleep, Instant};
use tracing::instrument;
use tracing::log::{debug, error, info};

const FLUSH_INTERVAL: Duration = Duration::from_secs(5);
const HEALTH_INTERVAL: Duration = Duration::from_secs(10);
const MAX_BATCH_SIZE: usize = 1000;

#[derive(sqlx::FromRow)]
struct EventRow {
    id: i64,
    event: String,
}

struct Inner {
    pool: Pool<Sqlite>,
    downstream: Box<dyn Event + Send + Sync>,
    liveness: HealthHandle,
}

pub struct SqliteSink {
    inner: Arc<Inner>,
}

impl SqliteSink {
    pub async fn new(
        path: String,
        downstream: Box<dyn Event + Send + Sync>,
        liveness: HealthHandle,
    ) -> anyhow::Result<SqliteSink> {
        info!("Initializing SQLite sink with path: {}", path);

        // Create SQLite connection pool
        let pool = SqlitePool::connect(&format!("sqlite:{}", path)).await?;

        // Initialize the database schema
        sqlx::query(
            r#"
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            "#,
        )
        .execute(&pool)
        .await?;

        let inner = Arc::new(Inner {
            pool,
            downstream,
            liveness,
        });

        // Create weak reference for background task
        let inner_weak = Arc::downgrade(&inner);

        // Spawn background task to process events
        task::spawn(async move {
            loop {
                // Try to upgrade weak reference - if it fails, the sink has been dropped
                let inner = match inner_weak.upgrade() {
                    Some(inner) => inner,
                    None => break, // Exit loop if sink was dropped
                };

                // Process batch of events
                if let Err(e) = inner.process_batch().await {
                    error!("Error processing batch: {}", e);
                } else {
                    inner.liveness.report_healthy().await;
                }
            }
        });

        Ok(SqliteSink { inner })
    }
}

impl Inner {
    async fn process_batch(&self) -> Result<(), CaptureError> {
        // Get oldest events from SQLite
        let events: Vec<EventRow> = sqlx::query_as::<_, EventRow>(
            r#"
                SELECT id, event
                FROM events
                ORDER BY id ASC
                LIMIT ?
            "#,
        )
        .bind(MAX_BATCH_SIZE as i64)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| {
            error!("Failed to fetch events from SQLite: {}", e);
            CaptureError::RetryableSinkError
        })?;

        if events.is_empty() {
            return Ok(());
        }

        let num_events = events.len();

        // Deserialize events
        let mut processed_events = Vec::with_capacity(num_events);
        let mut event_ids = Vec::with_capacity(num_events);
        for EventRow { id, event } in events {
            match serde_json::from_str::<CapturedEvent>(&event) {
                Ok(event) => {
                    let processed_event = ProcessedEvent {
                        event,
                        metadata: ProcessedEventMetadata {
                            data_type: DataType::AnalyticsMain,
                            session_id: None,
                        },
                    };
                    processed_events.push(processed_event);
                    event_ids.push(id);
                }
                Err(e) => {
                    error!("Failed to deserialize event: {}", e);
                    return Err(e.into());
                }
            }
        }

        // Send events to downstream sink
        if let Err(e) = self.downstream.send_batch(processed_events).await {
            error!("Failed to send events to downstream sink: {}", e);
            return Err(e);
        }

        // Delete events from SQLite
        sqlx::query(
                &format!(
                    "DELETE FROM events WHERE id IN ({})",
                    event_ids.iter().map(|id| id.to_string()).collect::<Vec<String>>().join(",")
                ),
            )
            .execute(&self.pool)
            .await
            .map_err(|e| {
                error!("Failed to delete events from SQLite: {}", e);
                CaptureError::RetryableSinkError
            })?;

        counter!("capture_sqlite_events_processed_total").increment(num_events as u64);
        Ok(())
    }

    async fn store_event(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let event_json = serde_json::to_string(&event.event).map_err(|e| {
            error!("Failed to serialize event: {}", e);
            CaptureError::NonRetryableSinkError
        })?;

        sqlx::query("INSERT INTO events (event) VALUES (?)")
            .bind(event_json)
            .execute(&self.pool)
            .await
            .map_err(|e| {
                error!("Failed to insert event into SQLite: {}", e);
                CaptureError::RetryableSinkError
            })?;

        counter!("capture_sqlite_events_stored_total").increment(1);
        Ok(())
    }
}

#[async_trait]
impl Event for SqliteSink {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        self.inner.store_event(event).await
    }

    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        for event in events {
            self.inner.store_event(event).await?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sinks::print::PrintSink;
    use crate::utils::uuid_v7;
    use crate::v0_request::{DataType, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use health::HealthRegistry;
    use std::time::Duration;
    use tempfile::NamedTempFile;
    use time::Duration as TimeDuration;

    fn create_test_event() -> ProcessedEvent {
        ProcessedEvent {
            event: CapturedEvent {
                uuid: uuid_v7(),
                distinct_id: "test_id".to_string(),
                ip: "127.0.0.1".to_string(),
                data: "test data".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "test_token".to_string(),
                is_cookieless_mode: false,
            },
            metadata: ProcessedEventMetadata {
                data_type: DataType::AnalyticsMain,
                session_id: None,
            },
        }
    }

    async fn setup_test_sink() -> (SqliteSink, NamedTempFile) {
        let temp_file = NamedTempFile::new().unwrap();
        let registry = HealthRegistry::new("test");
        let handle = registry
            .register("sqlite".to_string(), TimeDuration::seconds(30))
            .await;

        let sink = SqliteSink::new(
            temp_file.path().to_str().unwrap().to_string(),
            Box::new(PrintSink {}),
            handle,
        )
        .await
        .expect("Failed to create SQLite sink");

        (sink, temp_file)
    }

    #[tokio::test]
    async fn test_basic_functionality() {
        let (sink, _temp_file) = setup_test_sink().await;

        // Test single event
        let event = create_test_event();
        sink.send(event.clone())
            .await
            .expect("Failed to send event");

        // Test batch
        let batch = vec![event.clone(), event.clone()];
        sink.send_batch(batch)
            .await
            .expect("Failed to send batch");

        // Wait for processing
        tokio::time::sleep(Duration::from_secs(1)).await;
    }
}