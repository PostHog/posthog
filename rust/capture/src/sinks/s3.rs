use crate::v0_request::ProcessedEvent;
use async_trait::async_trait;
use aws_sdk_s3::config::Builder;
use aws_sdk_s3::Client as S3Client;
use chrono::{DateTime, Datelike, Timelike, Utc};
use health::HealthHandle;
use metrics::{counter, histogram};
use std::env;
use std::sync::Arc;
use std::time::{Duration, SystemTime};
use tokio::sync::broadcast;
use tokio::sync::broadcast::Sender;
use tokio::sync::oneshot;
use tokio::sync::Mutex;
use tokio::task;
use tokio::time::sleep;
use tokio::time::Instant;
use tracing::instrument;
use tracing::log::{debug, error, info};

use crate::api::CaptureError;
use crate::sinks::Event;

const FLUSH_INTERVAL: Duration = Duration::from_secs(1);
const HEALTH_INTERVAL: Duration = Duration::from_secs(10);
const MAX_BUFFER_SIZE: usize = 4 * 1024 * 1024; // 4MB

pub struct S3Sink {
    client: S3Client,
    bucket: String,
    prefix: String,
    buffer: Arc<Mutex<EventBuffer>>,
    liveness: HealthHandle,
    shutdown: Option<oneshot::Sender<()>>,
}

struct EventBuffer {
    event_bytes: Vec<u8>,
    event_count: usize,
    time_elapsed: Instant,
    tx: Sender<Result<(), CaptureError>>,
}

impl EventBuffer {
    fn new() -> Self {
        let (tx, _) = broadcast::channel(32);

        Self {
            event_bytes: Vec::new(),
            event_count: 0,
            time_elapsed: Instant::now(),
            tx,
        }
    }

    fn add_event(&mut self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let json = serde_json::to_string(&event.event)?;
        self.event_bytes.extend_from_slice(json.as_bytes());
        self.event_bytes.push(b'\n');
        self.event_count += 1;
        Ok(())
    }
}

impl S3Sink {
    pub async fn new(
        bucket: String,
        prefix: String,
        s3_endpoint: Option<String>,
        liveness: HealthHandle,
    ) -> anyhow::Result<S3Sink> {
        info!("Initializing S3 sink with bucket: {}", bucket);

        // Load base config
        let mut config_loader = aws_config::defaults(aws_config::BehaviorVersion::latest());

        if let Some(s3_endpoint) = s3_endpoint.clone() {
            config_loader = config_loader.endpoint_url(s3_endpoint);
        }

        let mut config = Builder::from(&config_loader.load().await);
        if s3_endpoint.is_some() {
            // custom s3 endpoints need force_path_style set
            config = config.force_path_style(true);
        }

        let client = S3Client::from_conf(config.build());
        let buffer = Arc::new(Mutex::new(EventBuffer::new()));

        let (shutdown_tx, mut shutdown_rx) = oneshot::channel();
        let s3sink = S3Sink {
            client: client.clone(),
            bucket: bucket.clone(),
            prefix: prefix.clone(),
            buffer: buffer.clone(),
            liveness: liveness.clone(),
            shutdown: None,
        };
        s3sink.healthcheck().await;

        // Spawn background task with shutdown handling
        task::spawn(async move {
            let mut last_healthcheck = Instant::now();
            loop {
                tokio::select! {
                    _ = sleep(Duration::from_millis(10)) => {
                        let mut buffer = s3sink.buffer.lock().await;
                        let should_flush = !buffer.event_bytes.is_empty()
                         && (buffer.event_bytes.len() >= MAX_BUFFER_SIZE ||
                            buffer.time_elapsed.elapsed() >= FLUSH_INTERVAL);

                        if should_flush {
                            let mut old_buffer = {
                                // Replace the current buffer with a brand-new one.
                                std::mem::replace(&mut *buffer, EventBuffer::new())
                            };

                            let result = s3sink.flush_buffer(&mut old_buffer).await;
                            if result.is_ok() {
                                last_healthcheck = Instant::now();
                            }
                            // drop the old buffer so the lock is freed and we can keep writing
                            drop(old_buffer.tx.send(result));
                        }

                        // if we haven't written any events the healthcheck will stall
                        // force healthcheck at least every HEALTH_INTERVAL
                        if last_healthcheck.elapsed() >= HEALTH_INTERVAL {
                            s3sink.healthcheck().await;
                        }
                    }
                    _ = &mut shutdown_rx => {
                        // Final flush on shutdown
                        let mut buffer = s3sink.buffer.lock().await;
                        if !buffer.event_bytes.is_empty() {
                            let result = s3sink.flush_buffer(&mut buffer).await;
                            drop(buffer.tx.send(result));
                        }
                        break;
                    }
                }
            }
        });

        Ok(S3Sink {
            client,
            bucket,
            prefix,
            buffer,
            liveness,
            shutdown: Some(shutdown_tx),
        })
    }

    async fn healthcheck(&self) {
        // Verify bucket exists and is accessible
        if self
            .client
            .head_bucket()
            .bucket(&self.bucket)
            .send()
            .await
            .is_ok()
        {
            self.liveness.report_healthy().await;
        };
    }

    async fn flush_buffer(&self, buffer: &mut EventBuffer) -> Result<(), CaptureError> {
        let start = Instant::now();
        let events_count = buffer.event_count;
        let batch_size = buffer.event_bytes.len();

        match self.do_flush(buffer).await {
            Ok(_) => {
                let duration = start.elapsed();
                histogram!("capture_s3_flush_duration_ms").record(duration.as_millis() as f64);
                histogram!("capture_s3_batch_size_events").record(events_count as f64);
                histogram!("capture_s3_batch_size_bytes").record(batch_size as f64);
                Ok(())
            }
            Err(e) => {
                counter!("capture_s3_flush_errors_total", "error" => e.to_string()).increment(1);
                Err(e)
            }
        }
    }

    async fn do_flush(&self, buffer: &mut EventBuffer) -> Result<(), CaptureError> {
        let mut retries = 3;

        loop {
            match self.try_flush(buffer).await {
                Ok(_) => return Ok(()),
                Err(e) => {
                    retries -= 1;
                    if retries == 0 {
                        return Err(e);
                    }
                    sleep(Duration::from_millis(100 * (4 - retries))).await;
                }
            }
        }
    }

    async fn try_flush(&self, buffer: &mut EventBuffer) -> Result<(), CaptureError> {
        if buffer.event_bytes.is_empty() {
            return Ok(());
        }

        let hostname = env::var("HOSTNAME").unwrap_or("unknown".to_string());

        let now: DateTime<Utc> = SystemTime::now().into();
        let path = format!(
            "{}year={}/month={:02}/day={:02}/hour={:02}/events_{}_{}.json.gz",
            self.prefix,
            now.year(),
            now.month(),
            now.day(),
            now.hour(),
            now.timestamp_millis(),
            hostname
        );

        debug!(
            "Flushing {} events to S3 path: {}",
            buffer.event_count,
            path
        );

        let event_count = buffer.event_count;
        let written_bytes = buffer.event_bytes.len();

        // take the event_bytes - this will implicitly reset to a new Vec
        let event_bytes = std::mem::take(&mut buffer.event_bytes);
        buffer.event_count = 0;
        buffer.time_elapsed = Instant::now();

        match self
            .client
            .put_object()
            .bucket(&self.bucket)
            .key(&path)
            .body(event_bytes.into())
            .send()
            .await
        {
            Ok(_) => {
                counter!("capture_s3_events_written_total").increment(event_count as u64);
                counter!("capture_s3_bytes_written_total").increment(written_bytes as u64);
                histogram!("capture_s3_batch_size").record(event_count as f64);
                self.liveness.report_healthy().await;
                Ok(())
            }
            Err(err) => {
                error!("Failed to write to S3: {}", err);
                counter!("capture_s3_write_errors_total").increment(1);
                Err(CaptureError::RetryableSinkError)
            }
        }
    }
}

impl Drop for S3Sink {
    fn drop(&mut self) {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
    }
}

#[async_trait]
impl Event for S3Sink {
    #[instrument(skip_all)]
    async fn send(&self, event: ProcessedEvent) -> Result<(), CaptureError> {
        let mut buffer = self.buffer.lock().await;
        buffer.add_event(event)?;
        let mut rx = buffer.tx.subscribe();
        drop(buffer);
        rx.recv()
            .await
            .map_err(|_| CaptureError::NonRetryableSinkError)?
    }

    #[instrument(skip_all)]
    async fn send_batch(&self, events: Vec<ProcessedEvent>) -> Result<(), CaptureError> {
        let mut buffer = self.buffer.lock().await;
        for event in events {
            buffer.add_event(event)?;
        }
        let mut rx = buffer.tx.subscribe();
        drop(buffer);
        rx.recv()
            .await
            .map_err(|_| CaptureError::NonRetryableSinkError)?
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::utils::uuid_v7;
    use crate::v0_request::{DataType, ProcessedEventMetadata};
    use common_types::CapturedEvent;
    use health::HealthRegistry;
    use time::Duration as TimeDuration;

    async fn setup_test_sink() -> S3Sink {
        let registry = HealthRegistry::new("test");
        let handle = registry
            .register("s3".to_string(), TimeDuration::seconds(30))
            .await;

        // Use environment variables for test configuration
        env::set_var("AWS_ACCESS_KEY_ID", "object_storage_root_user");
        env::set_var("AWS_SECRET_ACCESS_KEY", "object_storage_root_password");

        S3Sink::new(
            "capture".to_string(),
            "".to_string(),
            Some("http://localhost:19000".to_string()),
            handle,
        )
        .await
        .expect("Failed to create S3 sink")
    }

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

    #[tokio::test]
    async fn test_basic_functionality() {
        let sink = setup_test_sink().await;

        // Test single event
        let event = create_test_event();
        sink.send(event.clone())
            .await
            .expect("Failed to send event");

        // Test batch
        let batch = vec![event.clone(), event.clone()];
        sink.send_batch(batch).await.expect("Failed to send batch");
    }

    #[tokio::test]
    async fn test_large_event() {
        let sink = setup_test_sink().await;

        // Create event that will exceed MAX_BUFFER_SIZE
        let large_data = "x".repeat(MAX_BUFFER_SIZE + 1000);
        let event = ProcessedEvent {
            event: CapturedEvent {
                data: large_data,
                ..create_test_event().event
            },
            metadata: create_test_event().metadata,
        };

        sink.send(event).await.expect("Failed to send large event");
    }
}
