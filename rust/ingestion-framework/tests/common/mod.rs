//! Port of `docs/helpers.ts`.
#![allow(dead_code)]

use std::sync::{Arc, Mutex};
use std::time::Duration;

use ingestion_framework::{create_ok_context, ChunkPipeline, OkResultWithContext};

pub type Ctx = ();

pub fn items<T>(values: impl IntoIterator<Item = T>) -> Vec<OkResultWithContext<T, Ctx>> {
    values
        .into_iter()
        .map(|v| create_ok_context(v, ()))
        .collect()
}

/// Port of `consumeAll`: every OK value, flattened. With a paused clock, tokio advances time
/// by itself when all tasks wait, which replaces `jest.advanceTimersByTimeAsync`.
pub async fn consume_all<I, O, CI, CO>(pipeline: &dyn ChunkPipeline<I, O, CI, CO>) -> Vec<O> {
    let mut values = Vec::new();
    while let Some(chunk) = pipeline.next().await.expect("next") {
        for r in chunk {
            if let Some(v) = r.result.into_value() {
                values.push(v);
            }
        }
    }
    values
}

/// Port of `consumeAll(pipeline, advanceTimeMs)` for a paused clock. Node advances the
/// fake clock by `advance_ms` only, so a pipeline that needs longer never drains. The
/// bound is 1 ms past `advance_ms`, because tokio fires a timer and this timeout in the
/// same millisecond tick and could then reject work that Node completes at `advance_ms`.
pub async fn consume_all_within<I, O, CI, CO>(
    pipeline: &dyn ChunkPipeline<I, O, CI, CO>,
    advance_ms: u64,
) -> Vec<O> {
    within_ms(advance_ms, consume_all(pipeline)).await
}

/// Awaits `fut` with the time bound of a `jest.advanceTimersByTimeAsync(advance_ms)`.
/// See `consume_all_within` for the extra millisecond.
pub async fn within_ms<T>(advance_ms: u64, fut: impl std::future::Future<Output = T>) -> T {
    tokio::time::timeout(Duration::from_millis(advance_ms + 1), fut)
        .await
        .unwrap_or_else(|_| panic!("did not finish within {advance_ms} ms of virtual time"))
}

pub async fn collect_chunks<I, O, CI, CO>(
    pipeline: &dyn ChunkPipeline<I, O, CI, CO>,
) -> Vec<Vec<O>> {
    let mut chunks = Vec::new();
    while let Some(chunk) = pipeline.next().await.expect("next") {
        chunks.push(
            chunk
                .into_iter()
                .filter_map(|r| r.result.into_value())
                .collect(),
        );
    }
    chunks
}

pub async fn sleep_ms(ms: u64) {
    tokio::time::sleep(Duration::from_millis(ms)).await
}

pub fn shared<T>(value: T) -> Arc<Mutex<T>> {
    Arc::new(Mutex::new(value))
}

use async_trait::async_trait;
use ingestion_framework::{IngestionOutputs, KafkaMessage, OutputMessage};

#[derive(Clone)]
pub struct MockOutputs {
    pub calls: Arc<Mutex<Vec<(String, OutputMessage)>>>,
    gate: Arc<tokio::sync::watch::Sender<bool>>,
}

impl Default for MockOutputs {
    fn default() -> Self {
        let (tx, _) = tokio::sync::watch::channel(true);
        Self {
            calls: Arc::default(),
            gate: Arc::new(tx),
        }
    }
}

impl MockOutputs {
    pub fn close_gate(&self) {
        self.gate.send_replace(false);
    }
    pub fn open_gate(&self) {
        self.gate.send_replace(true);
    }
    pub fn calls(&self) -> Vec<(String, OutputMessage)> {
        self.calls.lock().unwrap().clone()
    }
}

#[async_trait]
impl IngestionOutputs for MockOutputs {
    async fn produce(&self, output: &str, message: OutputMessage) -> anyhow::Result<()> {
        self.calls
            .lock()
            .unwrap()
            .push((output.to_string(), message));
        let mut rx = self.gate.subscribe();
        let _ = rx.wait_for(|open| *open).await;
        Ok(())
    }
    async fn queue_messages(
        &self,
        output: &str,
        messages: Vec<OutputMessage>,
    ) -> anyhow::Result<()> {
        for m in messages {
            self.produce(output, m).await?;
        }
        Ok(())
    }
}

pub fn test_message(key: Option<&[u8]>) -> KafkaMessage {
    KafkaMessage {
        topic: "test-topic".into(),
        partition: 0,
        offset: 0,
        key: key.map(|k| k.to_vec()),
        value: Some(b"test-value".to_vec().into()),
        headers: vec![],
        timestamp: Some(0),
    }
}

#[derive(Debug, Clone)]
pub struct MsgCtx {
    pub message: KafkaMessage,
}

impl ingestion_framework::HasMessage for MsgCtx {
    fn message(&self) -> &KafkaMessage {
        &self.message
    }
}

#[derive(Debug, Clone)]
pub struct TeamCtx {
    pub team_id: i64,
}

impl ingestion_framework::HasTeamId for TeamCtx {
    fn team_id(&self) -> i64 {
        self.team_id
    }
}
