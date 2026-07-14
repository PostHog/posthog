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
pub mod parse_headers;
pub mod restrictions;

use std::str::FromStr;
use std::sync::Arc;

use metrics::counter;
use tracing::warn;

use common_pipelines::{
    ChunkOutcome, ItemOutcome, MetricsObserver, Observer, Pipeline, VerdictKind,
};

use crate::config::Config;
use crate::types::SerializedKafkaMessage;

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
        }
    }

    /// Build the preprocessor from config, or `None` when `PREPROCESS_MODE=off`
    /// (the pipeline is not constructed).
    pub fn from_config(config: &Config) -> Option<Arc<Preprocessor>> {
        if config.preprocess_mode == PreprocessMode::Off {
            return None;
        }
        let restrictions = ApplyEventRestrictions::from_static_lists(
            &config.drop_events_by_token_distinct_id,
            &config.skip_persons_processing_by_token_distinct_id,
            &config.ingestion_force_overflow_by_token_distinct_id,
            true,
            config.overflow_preserve_partition_locality,
        );
        Some(Arc::new(Preprocessor::build(
            config.preprocess_mode,
            restrictions,
        )))
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
            PreprocessMode::Enforce => Ok(self.enforce(messages, outcome)),
        }
    }

    /// Enforce verdicts without a verdict producer (B2.4 adds production):
    /// drops are removed and counted as accepted; DLQ/redirect verdicts fail
    /// open — the event is passed through to dispatch so nothing is lost.
    fn enforce(
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
