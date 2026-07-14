//! Output registry and verdict result handling.
//!
//! [`OutputRegistry`] maps a pipeline's [`Outputs`] enum to concrete topics and
//! producers, plus a DLQ target. [`handle_results`] is the single place that
//! touches Kafka for non-`Continue` verdicts, producing the original payload
//! bytes with **Node-compatible provenance headers**:
//!
//! - DLQ: original headers + `dlq_reason`, `dlq_step`, `dlq_timestamp`
//!   (RFC3339), `dlq_topic`, `dlq_partition`, `dlq_offset`. Produce failures are
//!   best-effort (logged + counted, never fatal), matching Node.
//! - Redirect: original headers + `redirect-step`, `redirect-timestamp`; the
//!   Kafka key is preserved iff `preserve_key`, else a null key (round-robin).
//!
//! The [`EffectProducer`] trait abstracts the transport: [`RdKafkaEffectProducer`]
//! for production, [`MockProducer`] for tests.

use std::collections::HashMap;
use std::marker::PhantomData;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use bytes::Bytes;
use chrono::Utc;
use metrics::counter;
use rdkafka::message::{Header, OwnedHeaders};
use rdkafka::producer::{FutureProducer, FutureRecord};
use rdkafka::util::Timeout;
use rdkafka::ClientContext;
use tracing::{debug, error};

use crate::metrics_consts::{DLQ_PRODUCE_ERRORS, REDIRECT_PRODUCE_ERRORS};
use crate::plugin::Observer;
use crate::result::Outputs;
use crate::step::{ChunkOutcome, ItemOutcome, VerdictKind};

/// The minimal produce interface the registry drives: send bytes + key + headers
/// to a topic, awaiting the broker ack.
#[async_trait]
pub trait EffectProducer: Send + Sync {
    async fn send(
        &self,
        topic: &str,
        key: Option<&[u8]>,
        payload: &[u8],
        headers: &[(String, Vec<u8>)],
    ) -> anyhow::Result<()>;
}

/// Production [`EffectProducer`] over an rdkafka `FutureProducer`. Generic over
/// the client context so a caller can pass a `common/kafka` producer without this
/// crate depending on `common-kafka`.
pub struct RdKafkaEffectProducer<C: ClientContext + 'static> {
    producer: Arc<FutureProducer<C>>,
    timeout: Duration,
}

impl<C: ClientContext + 'static> RdKafkaEffectProducer<C> {
    pub fn new(producer: Arc<FutureProducer<C>>, timeout: Duration) -> Self {
        RdKafkaEffectProducer { producer, timeout }
    }
}

#[async_trait]
impl<C: ClientContext + 'static> EffectProducer for RdKafkaEffectProducer<C> {
    async fn send(
        &self,
        topic: &str,
        key: Option<&[u8]>,
        payload: &[u8],
        headers: &[(String, Vec<u8>)],
    ) -> anyhow::Result<()> {
        let mut owned = OwnedHeaders::new();
        for (k, v) in headers {
            owned = owned.insert(Header {
                key: k.as_str(),
                value: Some(v.as_slice()),
            });
        }

        let result = match key {
            Some(k) => {
                let record = FutureRecord::to(topic)
                    .payload(payload)
                    .key(k)
                    .headers(owned);
                self.producer
                    .send(record, Timeout::After(self.timeout))
                    .await
            }
            None => {
                let record: FutureRecord<'_, [u8], [u8]> =
                    FutureRecord::to(topic).payload(payload).headers(owned);
                self.producer
                    .send(record, Timeout::After(self.timeout))
                    .await
            }
        };

        result
            .map(|_| ())
            .map_err(|(e, _msg)| anyhow::anyhow!("kafka produce to '{topic}' failed: {e}"))
    }
}

/// A message captured by [`MockProducer`] for test assertions.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SentMessage {
    pub topic: String,
    pub key: Option<Vec<u8>>,
    pub payload: Vec<u8>,
    pub headers: Vec<(String, Vec<u8>)>,
}

impl SentMessage {
    /// Look up a header value by key.
    pub fn header(&self, key: &str) -> Option<&[u8]> {
        self.headers
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.as_slice())
    }
}

/// In-memory [`EffectProducer`] for tests. Records every send; can be configured
/// to fail every send.
#[derive(Default)]
pub struct MockProducer {
    sent: Mutex<Vec<SentMessage>>,
    fail: bool,
}

impl MockProducer {
    pub fn new() -> Self {
        MockProducer::default()
    }

    /// A producer whose `send` always errors (to exercise best-effort paths).
    pub fn failing() -> Self {
        MockProducer {
            sent: Mutex::new(Vec::new()),
            fail: true,
        }
    }

    /// Snapshot of everything sent so far.
    pub fn sent(&self) -> Vec<SentMessage> {
        self.sent.lock().expect("mock lock").clone()
    }
}

#[async_trait]
impl EffectProducer for MockProducer {
    async fn send(
        &self,
        topic: &str,
        key: Option<&[u8]>,
        payload: &[u8],
        headers: &[(String, Vec<u8>)],
    ) -> anyhow::Result<()> {
        if self.fail {
            anyhow::bail!("mock producer configured to fail");
        }
        self.sent.lock().expect("mock lock").push(SentMessage {
            topic: topic.to_string(),
            key: key.map(<[u8]>::to_vec),
            payload: payload.to_vec(),
            headers: headers.to_vec(),
        });
        Ok(())
    }
}

/// A resolved output: a topic and the producer that writes to it.
#[derive(Clone)]
pub struct OutputTarget {
    pub topic: String,
    pub producer: Arc<dyn EffectProducer>,
}

/// Maps a pipeline's [`Outputs`] enum (by `name()`) to topics + producers, plus
/// a DLQ target.
pub struct OutputRegistry<O: Outputs> {
    targets: HashMap<&'static str, OutputTarget>,
    dlq: Option<OutputTarget>,
    _marker: PhantomData<O>,
}

impl<O: Outputs> Default for OutputRegistry<O> {
    fn default() -> Self {
        OutputRegistry {
            targets: HashMap::new(),
            dlq: None,
            _marker: PhantomData,
        }
    }
}

impl<O: Outputs> OutputRegistry<O> {
    pub fn new() -> Self {
        Self::default()
    }

    /// Register the topic + producer for one output.
    pub fn register(
        &mut self,
        output: O,
        topic: impl Into<String>,
        producer: Arc<dyn EffectProducer>,
    ) -> &mut Self {
        self.targets.insert(
            output.name(),
            OutputTarget {
                topic: topic.into(),
                producer,
            },
        );
        self
    }

    /// Set the DLQ topic + producer.
    pub fn with_dlq(
        &mut self,
        topic: impl Into<String>,
        producer: Arc<dyn EffectProducer>,
    ) -> &mut Self {
        self.dlq = Some(OutputTarget {
            topic: topic.into(),
            producer,
        });
        self
    }

    pub fn resolve(&self, output: O) -> Option<&OutputTarget> {
        self.targets.get(output.name())
    }

    pub fn dlq_target(&self) -> Option<&OutputTarget> {
        self.dlq.as_ref()
    }

    /// Startup check (the design's `outputs.checkTopics()` analog): every listed
    /// output must have a registered topic/producer, else fail before serving.
    pub fn check(&self, outputs: &[O]) -> anyhow::Result<()> {
        for output in outputs {
            if !self.targets.contains_key(output.name()) {
                anyhow::bail!(
                    "pipeline output '{}' has no registered topic/producer",
                    output.name()
                );
            }
        }
        Ok(())
    }
}

/// The original Kafka message for one input, aligned by index with the chunk the
/// pipeline ran over. Result handling produces these bytes verbatim to DLQ /
/// redirect topics.
#[derive(Debug, Clone)]
pub struct RawRecord {
    pub payload: Bytes,
    pub key: Option<Bytes>,
    pub headers: Vec<(String, Vec<u8>)>,
    pub source_topic: String,
    pub partition: i32,
    pub offset: i64,
}

/// Counts of what result handling did, for commit accounting by the caller.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct HandleSummary {
    pub survived: usize,
    pub dropped: usize,
    pub dlq_produced: usize,
    pub dlq_failed: usize,
    pub redirected: usize,
    pub redirect_failed: usize,
}

fn with_extra_headers(
    base: &[(String, Vec<u8>)],
    extra: &[(&str, Vec<u8>)],
) -> Vec<(String, Vec<u8>)> {
    let mut headers = base.to_vec();
    for (key, value) in extra {
        headers.push(((*key).to_string(), value.clone()));
    }
    headers
}

/// Produce all non-`Continue` verdicts to their DLQ / redirect topics with
/// Node-parity provenance headers. Survivors are the caller's responsibility
/// (dispatch to workers). All produces are awaited before returning.
///
/// `outcome` and `raws` must be the same length and aligned by index.
pub async fn handle_results<Out, O: Outputs>(
    outcome: &ChunkOutcome<Out, O>,
    raws: &[RawRecord],
    registry: &OutputRegistry<O>,
    observers: &[Arc<dyn Observer>],
) -> HandleSummary {
    assert_eq!(
        outcome.items.len(),
        raws.len(),
        "handle_results: outcome and raws length mismatch"
    );

    let mut summary = HandleSummary::default();

    for (item, raw) in outcome.items.iter().zip(raws.iter()) {
        let verdict = match item {
            ItemOutcome::Survived(_) => {
                summary.survived += 1;
                continue;
            }
            ItemOutcome::Terminated(verdict) => verdict,
        };

        for observer in observers {
            observer.on_verdict(verdict.step, verdict.kind, verdict.reason);
        }

        match verdict.kind {
            VerdictKind::Drop => {
                summary.dropped += 1;
                debug!(
                    step = verdict.step,
                    reason = verdict.reason,
                    "event dropped"
                );
            }
            VerdictKind::Dlq => {
                let Some(target) = registry.dlq_target() else {
                    error!(
                        step = verdict.step,
                        "DLQ verdict but no DLQ target registered; event not produced"
                    );
                    summary.dlq_failed += 1;
                    continue;
                };
                let headers = with_extra_headers(
                    &raw.headers,
                    &[
                        ("dlq_reason", verdict.reason.as_bytes().to_vec()),
                        ("dlq_step", verdict.step.as_bytes().to_vec()),
                        ("dlq_timestamp", Utc::now().to_rfc3339().into_bytes()),
                        ("dlq_topic", raw.source_topic.clone().into_bytes()),
                        ("dlq_partition", raw.partition.to_string().into_bytes()),
                        ("dlq_offset", raw.offset.to_string().into_bytes()),
                    ],
                );
                match target
                    .producer
                    .send(&target.topic, raw.key.as_deref(), &raw.payload, &headers)
                    .await
                {
                    Ok(()) => summary.dlq_produced += 1,
                    Err(e) => {
                        // Best-effort, matching Node: log + count, never fatal.
                        error!(step = verdict.step, error = %e, "DLQ produce failed");
                        counter!(DLQ_PRODUCE_ERRORS).increment(1);
                        summary.dlq_failed += 1;
                    }
                }
            }
            VerdictKind::Redirect => {
                let output = verdict
                    .output
                    .expect("redirect verdict must carry an output");
                let Some(target) = registry.resolve(output) else {
                    error!(
                        step = verdict.step,
                        output = output.name(),
                        "redirect verdict but output not registered; event not produced"
                    );
                    counter!(REDIRECT_PRODUCE_ERRORS).increment(1);
                    summary.redirect_failed += 1;
                    continue;
                };
                let headers = with_extra_headers(
                    &raw.headers,
                    &[
                        ("redirect-step", verdict.step.as_bytes().to_vec()),
                        ("redirect-timestamp", Utc::now().to_rfc3339().into_bytes()),
                    ],
                );
                let key = if verdict.preserve_key {
                    raw.key.as_deref()
                } else {
                    None
                };
                match target
                    .producer
                    .send(&target.topic, key, &raw.payload, &headers)
                    .await
                {
                    Ok(()) => summary.redirected += 1,
                    Err(e) => {
                        error!(step = verdict.step, error = %e, "redirect produce failed");
                        counter!(REDIRECT_PRODUCE_ERRORS).increment(1);
                        summary.redirect_failed += 1;
                    }
                }
            }
        }
    }

    summary
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::step::{ItemOutcome, Verdict, VerdictKind};

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum Out {
        Overflow,
    }
    impl Outputs for Out {
        fn name(&self) -> &'static str {
            match self {
                Out::Overflow => "overflow",
            }
        }
    }

    fn raw(offset: i64) -> RawRecord {
        RawRecord {
            payload: Bytes::from_static(b"event-body"),
            key: Some(Bytes::from_static(b"token:did")),
            headers: vec![("token".to_string(), b"phc_abc".to_vec())],
            source_topic: "events_plugin_ingestion".to_string(),
            partition: 3,
            offset,
        }
    }

    fn drop_verdict() -> Verdict<Out> {
        Verdict {
            kind: VerdictKind::Drop,
            reason: "blocked_token",
            step: "restrictions",
            output: None,
            preserve_key: false,
            error: None,
        }
    }

    fn dlq_verdict() -> Verdict<Out> {
        Verdict {
            kind: VerdictKind::Dlq,
            reason: "event_in_denylist",
            step: "deny_events",
            output: None,
            preserve_key: false,
            error: None,
        }
    }

    fn redirect_verdict(preserve_key: bool) -> Verdict<Out> {
        Verdict {
            kind: VerdictKind::Redirect,
            reason: "overflow",
            step: "restrictions",
            output: Some(Out::Overflow),
            preserve_key,
            error: None,
        }
    }

    #[tokio::test]
    async fn produces_dlq_and_redirects_with_node_headers() {
        let overflow = Arc::new(MockProducer::new());
        let dlq = Arc::new(MockProducer::new());
        let mut registry = OutputRegistry::<Out>::new();
        registry
            .register(Out::Overflow, "overflow_topic", overflow.clone())
            .with_dlq("dlq_topic", dlq.clone());

        // survivor, dlq, redirect(preserve), redirect(null key), drop
        let outcome = ChunkOutcome {
            items: vec![
                ItemOutcome::Survived("kept".to_string()),
                ItemOutcome::Terminated(dlq_verdict()),
                ItemOutcome::Terminated(redirect_verdict(true)),
                ItemOutcome::Terminated(redirect_verdict(false)),
                ItemOutcome::Terminated(drop_verdict()),
            ],
        };
        let raws = vec![raw(10), raw(11), raw(12), raw(13), raw(14)];

        let summary = handle_results(&outcome, &raws, &registry, &[]).await;
        assert_eq!(
            summary,
            HandleSummary {
                survived: 1,
                dropped: 1,
                dlq_produced: 1,
                dlq_failed: 0,
                redirected: 2,
                redirect_failed: 0,
            }
        );

        // DLQ: original body + original header + provenance headers.
        let dlq_sent = dlq.sent();
        assert_eq!(dlq_sent.len(), 1);
        let m = &dlq_sent[0];
        assert_eq!(m.topic, "dlq_topic");
        assert_eq!(m.payload, b"event-body");
        assert_eq!(m.header("token"), Some(&b"phc_abc"[..]));
        assert_eq!(m.header("dlq_reason"), Some(&b"event_in_denylist"[..]));
        assert_eq!(m.header("dlq_step"), Some(&b"deny_events"[..]));
        assert_eq!(m.header("dlq_topic"), Some(&b"events_plugin_ingestion"[..]));
        assert_eq!(m.header("dlq_partition"), Some(&b"3"[..]));
        assert_eq!(m.header("dlq_offset"), Some(&b"11"[..]));
        assert!(m.header("dlq_timestamp").is_some());

        // Redirect: two messages, key preserved on first, null on second.
        let redir = overflow.sent();
        assert_eq!(redir.len(), 2);
        assert_eq!(redir[0].topic, "overflow_topic");
        assert_eq!(redir[0].key.as_deref(), Some(&b"token:did"[..]));
        assert_eq!(redir[0].header("redirect-step"), Some(&b"restrictions"[..]));
        assert!(redir[0].header("redirect-timestamp").is_some());
        assert_eq!(redir[1].key, None); // preserve_key = false -> null key
    }

    #[tokio::test]
    async fn dlq_produce_failure_is_best_effort() {
        let dlq = Arc::new(MockProducer::failing());
        let mut registry = OutputRegistry::<Out>::new();
        registry.with_dlq("dlq_topic", dlq.clone());

        let outcome = ChunkOutcome {
            items: vec![ItemOutcome::<String, Out>::Terminated(dlq_verdict())],
        };
        let raws = vec![raw(1)];

        let summary = handle_results(&outcome, &raws, &registry, &[]).await;
        assert_eq!(summary.dlq_failed, 1);
        assert_eq!(summary.dlq_produced, 0);
        assert_eq!(dlq.sent().len(), 0);
    }

    #[test]
    fn check_fails_when_output_unregistered() {
        let registry = OutputRegistry::<Out>::new();
        let err = registry.check(&[Out::Overflow]).unwrap_err();
        assert!(err.to_string().contains("overflow"));

        let mut registry = OutputRegistry::<Out>::new();
        registry.register(Out::Overflow, "t", Arc::new(MockProducer::new()));
        assert!(registry.check(&[Out::Overflow]).is_ok());
    }
}
