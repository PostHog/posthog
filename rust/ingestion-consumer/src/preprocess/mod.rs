//! Header-only preprocess pipeline for the ingestion consumer.
//!
//! Runs a small `common-pipelines` pipeline over each Kafka batch before
//! dispatch: parse headers, deny misrouted event types, apply event
//! restrictions (drop / DLQ / force-overflow). Gated behind `PREPROCESS_MODE`
//! (`off` by default — the pipeline is not constructed and behavior is
//! identical to today). See `common/pipelines/POC_NOTES.md` §consumer for the
//! POC's scope and deviations.

pub mod context;
pub mod deny_events;
pub mod headers;
pub mod metrics_consts;
pub mod outputs;
pub mod parse_headers;
pub mod restrictions;

use std::str::FromStr;
use std::sync::Arc;

use bytes::Bytes;
use metrics::counter;
use tracing::warn;

use common_pipelines::{
    handle_results, ChunkOutcome, ItemOutcome, MetricsObserver, Observer, OutputRegistry, Pipeline,
    RawRecord, VerdictKind,
};

use crate::config::Config;
use crate::types::SerializedKafkaMessage;

use outputs::build_output_registry;

pub use context::{PreprocessOutput, RawMessage, WithHeaders};
pub use deny_events::DenyEvents;
pub use headers::EventHeaders;
pub use parse_headers::ParseHeaders;
pub use restrictions::ApplyEventRestrictions;

use metrics_consts::PREPROCESS_DRYRUN_RESULTS;

/// How the preprocess pipeline runs. `off` (default) means the pipeline is never
/// constructed and the consumer behaves exactly as before.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum PreprocessMode {
    /// Pipeline not constructed; zero behavior change.
    #[default]
    Off,
    /// Compute verdicts, emit `ingestion_preprocess_dryrun_results`, pass
    /// everything through untouched.
    DryRun,
    /// Act on verdicts: drops are removed from dispatch (and counted as accepted
    /// so the commit gate still closes). DLQ/redirect production is wired in B2.4.
    Enforce,
}

impl FromStr for PreprocessMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_lowercase().as_str() {
            "off" | "" => Ok(PreprocessMode::Off),
            "dry_run" | "dryrun" | "dry-run" => Ok(PreprocessMode::DryRun),
            "enforce" => Ok(PreprocessMode::Enforce),
            other => Err(format!(
                "unknown PREPROCESS_MODE '{other}' (expected 'off', 'dry_run', or 'enforce')"
            )),
        }
    }
}

/// Result of running the preprocess pipeline over one batch.
pub struct PreprocessOutcome {
    /// Messages that should still be dispatched to workers, in original order.
    pub survivors: Vec<SerializedKafkaMessage>,
    /// Count of messages removed from dispatch that must still be counted as
    /// accepted for commit accounting (so the offset commit gate closes).
    pub removed_accepted: u32,
}

impl PreprocessOutcome {
    /// Everything passes through; nothing removed. Used for `off`/`dry_run`.
    fn passthrough(messages: Vec<SerializedKafkaMessage>) -> Self {
        PreprocessOutcome {
            survivors: messages,
            removed_accepted: 0,
        }
    }
}

/// The assembled preprocess pipeline plus its run mode. Constructed once at
/// startup (service-scoped) and shared across batches.
pub struct Preprocessor {
    mode: PreprocessMode,
    pipeline: Pipeline<RawMessage, WithHeaders, (), PreprocessOutput>,
    observers: Vec<Arc<dyn Observer>>,
    /// DLQ / overflow output topics + producer, for enforce mode. `None` leaves
    /// DLQ/redirect verdicts to fail open (passthrough to dispatch).
    outputs: Option<OutputRegistry<PreprocessOutput>>,
}

impl Preprocessor {
    /// Assemble the pipeline (parse headers -> deny events -> restrictions).
    pub fn build(mode: PreprocessMode, restrictions: ApplyEventRestrictions) -> Self {
        let pipeline = Pipeline::<RawMessage, WithHeaders, (), PreprocessOutput>::builder()
            .step(ParseHeaders)
            .step(DenyEvents::with_defaults())
            .step(restrictions)
            .build();
        Preprocessor {
            mode,
            pipeline,
            observers: vec![Arc::new(MetricsObserver)],
            outputs: None,
        }
    }

    /// Attach the DLQ / overflow output registry (enables verdict production).
    pub fn with_outputs(mut self, registry: OutputRegistry<PreprocessOutput>) -> Self {
        self.outputs = Some(registry);
        self
    }

    /// Build the preprocessor from config, or `None` when `PREPROCESS_MODE=off`
    /// (the pipeline is not constructed). In enforce mode with a DLQ/overflow
    /// topic configured, a Kafka producer is created and wired for verdict
    /// production; `liveness` is the producer's liveness reporter.
    pub async fn from_config(
        config: &Config,
        liveness: lifecycle::Handle,
    ) -> anyhow::Result<Option<Arc<Preprocessor>>> {
        if config.preprocess_mode == PreprocessMode::Off {
            return Ok(None);
        }
        let restrictions = ApplyEventRestrictions::from_static_lists(
            &config.drop_events_by_token_distinct_id,
            &config.skip_persons_processing_by_token_distinct_id,
            &config.ingestion_force_overflow_by_token_distinct_id,
            true,
            config.overflow_preserve_partition_locality,
        );
        let mut preprocessor = Preprocessor::build(config.preprocess_mode, restrictions);

        if config.preprocess_mode == PreprocessMode::Enforce {
            if let Some(registry) = build_output_registry(config, liveness).await? {
                preprocessor = preprocessor.with_outputs(registry);
            }
        }

        Ok(Some(Arc::new(preprocessor)))
    }

    pub fn mode(&self) -> PreprocessMode {
        self.mode
    }

    /// Run the pipeline over one batch and return the survivors to dispatch plus
    /// the count of removed-but-accepted messages. An `Err` is the
    /// unexpected-error channel: it poisons the batch (process exits, Kafka
    /// redelivers).
    pub async fn process(
        &self,
        messages: Vec<SerializedKafkaMessage>,
    ) -> anyhow::Result<PreprocessOutcome> {
        let inputs: Vec<RawMessage> = messages
            .iter()
            .map(|m| RawMessage {
                headers: m.headers.clone(),
            })
            .collect();

        let outcome = self
            .pipeline
            .run_chunk(inputs, &mut ())
            .await
            .map_err(|e| anyhow::anyhow!("preprocess pipeline error: {e}"))?;

        match self.mode {
            PreprocessMode::Off => Ok(PreprocessOutcome::passthrough(messages)),
            PreprocessMode::DryRun => {
                for item in &outcome.items {
                    if let ItemOutcome::Terminated(verdict) = item {
                        counter!(
                            PREPROCESS_DRYRUN_RESULTS,
                            "step" => verdict.step,
                            "result" => verdict.kind.as_str(),
                            "details" => verdict.reason,
                        )
                        .increment(1);
                    }
                }
                Ok(PreprocessOutcome::passthrough(messages))
            }
            PreprocessMode::Enforce => self.enforce(messages, outcome).await,
        }
    }

    async fn enforce(
        &self,
        messages: Vec<SerializedKafkaMessage>,
        outcome: ChunkOutcome<WithHeaders, PreprocessOutput>,
    ) -> anyhow::Result<PreprocessOutcome> {
        match &self.outputs {
            Some(registry) => self.enforce_produce(messages, outcome, registry).await,
            None => Ok(self.enforce_passthrough(messages, outcome)),
        }
    }

    /// Enforce verdicts and produce DLQ/redirect messages to their topics. A
    /// terminated event is removed from dispatch and counted as accepted only
    /// after its produce (if any) is acked; a produce failure fails the batch so
    /// nothing that was meant to land somewhere is silently lost.
    async fn enforce_produce(
        &self,
        messages: Vec<SerializedKafkaMessage>,
        outcome: ChunkOutcome<WithHeaders, PreprocessOutput>,
        registry: &OutputRegistry<PreprocessOutput>,
    ) -> anyhow::Result<PreprocessOutcome> {
        let mut survivors = Vec::with_capacity(messages.len());
        let mut terminated_items = Vec::new();
        let mut terminated_raws = Vec::new();

        for (msg, item) in messages.into_iter().zip(outcome.items) {
            if item.is_survivor() {
                survivors.push(msg);
            } else {
                terminated_raws.push(raw_record(msg));
                terminated_items.push(item);
            }
        }

        // `handle_results` produces every DLQ/redirect verdict with Node-parity
        // provenance headers and awaits all produces before returning; the
        // built-in metrics observer emits `ingestion_pipeline_results`.
        let compact = ChunkOutcome {
            items: terminated_items,
        };
        let summary = handle_results(&compact, &terminated_raws, registry, &self.observers).await;

        if summary.dlq_failed > 0 || summary.redirect_failed > 0 {
            anyhow::bail!(
                "preprocess verdict produce failed (dlq_failed={}, redirect_failed={}); failing batch",
                summary.dlq_failed,
                summary.redirect_failed
            );
        }

        let removed_accepted = (summary.dropped + summary.dlq_produced + summary.redirected) as u32;
        Ok(PreprocessOutcome {
            survivors,
            removed_accepted,
        })
    }

    /// Enforce without a verdict producer: drops are removed and counted as
    /// accepted; DLQ/redirect verdicts fail open — the event is passed through
    /// to dispatch so nothing is lost. (B2.4 fallback when no output topic is
    /// configured.)
    fn enforce_passthrough(
        &self,
        messages: Vec<SerializedKafkaMessage>,
        outcome: ChunkOutcome<WithHeaders, PreprocessOutput>,
    ) -> PreprocessOutcome {
        let mut survivors = Vec::with_capacity(messages.len());
        let mut removed_accepted = 0u32;

        for (msg, item) in messages.into_iter().zip(outcome.items) {
            match item {
                ItemOutcome::Survived(_) => survivors.push(msg),
                ItemOutcome::Terminated(verdict) => {
                    for observer in &self.observers {
                        observer.on_verdict(verdict.step, verdict.kind, verdict.reason);
                    }
                    match verdict.kind {
                        VerdictKind::Drop => removed_accepted += 1,
                        VerdictKind::Dlq | VerdictKind::Redirect => {
                            warn!(
                                step = verdict.step,
                                kind = verdict.kind.as_str(),
                                reason = verdict.reason,
                                "preprocess verdict without an output topic; passing event through"
                            );
                            survivors.push(msg);
                        }
                    }
                }
            }
        }

        PreprocessOutcome {
            survivors,
            removed_accepted,
        }
    }
}

/// Convert a consumed Kafka message into the raw record result-handling
/// produces verbatim (original payload / key / headers) to DLQ / overflow.
fn raw_record(msg: SerializedKafkaMessage) -> RawRecord {
    RawRecord {
        payload: msg.value.map(Bytes::from).unwrap_or_default(),
        key: msg.key.map(Bytes::from),
        headers: msg
            .headers
            .into_iter()
            .map(|(k, v)| (k, v.into_bytes()))
            .collect(),
        source_topic: msg.topic,
        partition: msg.partition,
        offset: msg.offset,
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    fn msg(token: &str, event: &str) -> SerializedKafkaMessage {
        let mut headers = HashMap::new();
        headers.insert("token".to_string(), token.to_string());
        headers.insert("event".to_string(), event.to_string());
        SerializedKafkaMessage {
            topic: "events_plugin_ingestion".to_string(),
            partition: 0,
            offset: 0,
            timestamp: 0,
            key: Some(format!("{token}:did")),
            value: Some("{}".to_string()),
            headers,
        }
    }

    fn drop_only_preprocessor(mode: PreprocessMode) -> Preprocessor {
        let restrictions =
            ApplyEventRestrictions::from_static_lists("phc_drop", "", "", true, false);
        Preprocessor::build(mode, restrictions)
    }

    #[tokio::test]
    async fn enforce_counts_dropped_as_accepted() {
        let pp = drop_only_preprocessor(PreprocessMode::Enforce);
        let messages = vec![
            msg("phc_keep", "$pageview"),  // survivor
            msg("phc_drop", "$pageview"),  // dropped -> removed + counted
            msg("phc_keep", "$exception"), // denylist DLQ -> fail-open passthrough
        ];
        let out = pp.process(messages).await.unwrap();

        // Commit-gate invariant: every input is either dispatched or accepted.
        assert_eq!(out.survivors.len() as u32 + out.removed_accepted, 3);
        assert_eq!(out.removed_accepted, 1, "one dropped event counted");
        assert_eq!(out.survivors.len(), 2, "keep + DLQ passthrough dispatched");
    }

    #[tokio::test]
    async fn enforce_produces_verdicts_and_counts_accepted() {
        use common_pipelines::{MockProducer, OutputRegistry};

        let dlq = Arc::new(MockProducer::new());
        let overflow = Arc::new(MockProducer::new());
        let mut registry = OutputRegistry::<PreprocessOutput>::new();
        registry.register(
            PreprocessOutput::Overflow,
            "overflow_topic",
            overflow.clone(),
        );
        registry.with_dlq("dlq_topic", dlq.clone());

        let restrictions =
            ApplyEventRestrictions::from_static_lists("phc_drop", "", "phc_of", true, false);
        let pp = Preprocessor::build(PreprocessMode::Enforce, restrictions).with_outputs(registry);

        let messages = vec![
            msg("phc_keep", "$pageview"),  // survivor -> dispatched
            msg("phc_drop", "$pageview"),  // drop -> removed, no produce
            msg("phc_keep", "$exception"), // denylist -> DLQ produce
            msg("phc_of", "$pageview"),    // force overflow -> redirect produce
        ];
        let out = pp.process(messages).await.unwrap();

        // Commit-gate invariant: 1 dispatched + 3 removed-accepted == 4.
        assert_eq!(out.survivors.len(), 1);
        assert_eq!(out.removed_accepted, 3);

        let dlq_sent = dlq.sent();
        assert_eq!(dlq_sent.len(), 1);
        assert_eq!(dlq_sent[0].topic, "dlq_topic");
        assert_eq!(
            dlq_sent[0].header("dlq_reason"),
            Some(&b"event_in_denylist"[..])
        );

        let overflow_sent = overflow.sent();
        assert_eq!(overflow_sent.len(), 1);
        assert_eq!(overflow_sent[0].topic, "overflow_topic");
        assert!(overflow_sent[0].header("redirect-step").is_some());
    }

    #[tokio::test]
    async fn dry_run_passes_everything_through() {
        let pp = drop_only_preprocessor(PreprocessMode::DryRun);
        let messages = vec![msg("phc_drop", "$pageview"), msg("phc_keep", "$pageview")];
        let out = pp.process(messages).await.unwrap();
        assert_eq!(out.survivors.len(), 2, "nothing removed in dry-run");
        assert_eq!(out.removed_accepted, 0);
    }

    #[test]
    fn mode_parses_from_env_strings() {
        assert_eq!("off".parse(), Ok(PreprocessMode::Off));
        assert_eq!("dry_run".parse(), Ok(PreprocessMode::DryRun));
        assert_eq!("enforce".parse(), Ok(PreprocessMode::Enforce));
        assert!("nope".parse::<PreprocessMode>().is_err());
    }
}
