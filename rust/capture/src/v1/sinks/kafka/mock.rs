use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use rdkafka::error::KafkaError;

use crate::v1::sinks::kafka::producer::{ProduceError, ProduceRecord};
use crate::v1::sinks::SinkName;

// ---------------------------------------------------------------------------
// OwnedProduceRecord — owned copy for test assertions
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub struct OwnedProduceRecord {
    pub topic: String,
    pub key: Option<String>,
    pub payload: String,
}

impl<'a> From<ProduceRecord<'a>> for OwnedProduceRecord {
    fn from(r: ProduceRecord<'a>) -> Self {
        Self {
            topic: r.topic.to_owned(),
            key: r.key.map(str::to_owned),
            payload: r.payload.to_owned(),
        }
    }
}

impl<'a> From<&ProduceRecord<'a>> for OwnedProduceRecord {
    fn from(r: &ProduceRecord<'a>) -> Self {
        Self {
            topic: r.topic.to_owned(),
            key: r.key.map(str::to_owned),
            payload: r.payload.to_owned(),
        }
    }
}

// ---------------------------------------------------------------------------
// MockProducer
// ---------------------------------------------------------------------------

/// Mock Kafka producer for testing. Captures sent records and supports
/// configurable error injection and ack delays.
pub struct MockProducer {
    sink: SinkName,
    records: Arc<Mutex<Vec<OwnedProduceRecord>>>,
    send_error: Option<fn() -> ProduceError>,
    send_error_remaining: Arc<AtomicU32>,
    ack_error: Option<fn() -> ProduceError>,
    ack_delay: Option<Duration>,
    ready_override: Option<bool>,
    handle: lifecycle::Handle,
}

impl MockProducer {
    pub fn new(sink: SinkName, handle: lifecycle::Handle) -> Self {
        Self {
            sink,
            records: Arc::new(Mutex::new(Vec::new())),
            send_error: None,
            send_error_remaining: Arc::new(AtomicU32::new(u32::MAX)),
            ack_error: None,
            ack_delay: None,
            ready_override: None,
            handle,
        }
    }

    pub fn with_send_error(mut self, f: fn() -> ProduceError) -> Self {
        self.send_error = Some(f);
        self
    }

    /// Limit send errors to the first `n` calls. After `n` errors the
    /// send_error function is bypassed and sends succeed normally.
    pub fn with_send_error_count(mut self, n: u32) -> Self {
        self.send_error_remaining = Arc::new(AtomicU32::new(n));
        self
    }

    pub fn with_ack_error(mut self, f: fn() -> ProduceError) -> Self {
        self.ack_error = Some(f);
        self
    }

    pub fn with_ack_delay(mut self, d: Duration) -> Self {
        self.ack_delay = Some(d);
        self
    }

    pub fn with_not_ready(mut self) -> Self {
        self.ready_override = Some(false);
        self
    }

    pub fn record_count(&self) -> usize {
        self.records.lock().unwrap().len()
    }

    pub fn with_records<F, R>(&self, f: F) -> R
    where
        F: FnOnce(&[OwnedProduceRecord]) -> R,
    {
        let guard = self.records.lock().unwrap();
        f(&guard)
    }

    pub fn clear(&self) {
        self.records.lock().unwrap().clear();
    }
}

impl super::KafkaProducerTrait for MockProducer {
    type Ack = Pin<Box<dyn Future<Output = Result<(), ProduceError>> + Send>>;

    fn send<'a>(
        &self,
        record: ProduceRecord<'a>,
    ) -> Result<Self::Ack, (ProduceError, ProduceRecord<'a>)> {
        if let Some(err_fn) = &self.send_error {
            let remaining = self.send_error_remaining.load(Ordering::Relaxed);
            if remaining > 0 {
                if remaining != u32::MAX {
                    self.send_error_remaining.fetch_sub(1, Ordering::Relaxed);
                }
                return Err((err_fn(), record));
            }
        }
        self.records.lock().unwrap().push((&record).into());
        let ack_error = self.ack_error;
        let delay = self.ack_delay;
        Ok(Box::pin(async move {
            if let Some(d) = delay {
                tokio::time::sleep(d).await;
            }
            match ack_error {
                Some(err_fn) => Err(err_fn()),
                None => Ok(()),
            }
        }))
    }

    fn flush(&self, _: Duration) -> Result<(), KafkaError> {
        Ok(())
    }

    fn is_ready(&self) -> bool {
        self.ready_override
            .unwrap_or_else(|| self.handle.is_healthy())
    }

    fn sink_name(&self) -> SinkName {
        self.sink
    }
}
