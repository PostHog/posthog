//! Core Cymbal pipeline contracts shared by Cymbal crates.
//!
//! This crate is the reusable stage framework: stage traits, codecs,
//! executors, generic intermediate outputs, ordered emission, routing /
//! capacity / fallback primitives, batch context, and shared errors. It is
//! intentionally domain-agnostic.
//!
//! Product-specific payloads, terminal outcomes, admission gate payloads, and
//! stage identity constants live outside this crate. Some existing wire type
//! labels still report the `cymbal.core` namespace for compatibility; the label
//! is not an ownership boundary.
//!
//! The gRPC/protobuf API is intentionally kept out of this crate. These
//! types model the Rust-internal pipeline boundary; `cymbal-server` owns
//! conversion to and from the wire API exposed to Node.

use std::collections::HashMap;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::sync::Arc;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

pub mod circuit;
pub mod concurrency;
pub mod emission;
pub mod executor;
pub mod pipeline;
pub mod progress;
pub mod rate_limit;
pub mod routing;
pub mod runner;

pub use circuit::{
    deterministic_retry_after_ms, CircuitBreaker, CircuitBreakerConfig, CircuitCheckResult,
    CircuitDecision, CircuitRecordResult, CircuitState, CircuitTransition,
    DEFAULT_CIRCUIT_FAILURE_RATIO_TO_OPEN, DEFAULT_CIRCUIT_MIN_REQUESTS,
    DEFAULT_CIRCUIT_OPEN_DURATION, DEFAULT_CIRCUIT_WINDOW_SIZE,
};
pub use concurrency::{run_buffered, StageConcurrencyLimiter};
pub use emission::{EmissionOrder, IdentifiedItem, OrderedEmitter, Sink};
pub use executor::{ContinueExecutor, IntermediateStageOutput, LocalExecutor, StageExecutor};
pub use pipeline::{
    LinearPipelineSpec, PipelineSpecError, StageEffectMode, StageId, StageLinkRule, StageSpec,
    TransientFailurePolicy,
};
pub use progress::{PipelineEventState, StageProgressMode};
pub use rate_limit::{
    apply_rate_limit_mode, evaluate_rate_limit, RateLimitApplication, RateLimitDecision,
    RateLimitKeyExtractor, RateLimitMode, RateLimiter,
};
pub use runner::{
    LinearPipelineRunner, LinearPipelineRunnerError, LinearPipelineRunnerOptions, PipelineItem,
    StageBatchOutcome, StageDriver, TerminalItem,
};

pub type Metadata = HashMap<String, String>;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct StageType {
    pub namespace: &'static str,
    pub name: &'static str,
    pub version: u16,
}

impl Display for StageType {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "{}.{}@{}",
            self.namespace, self.name, self.version
        )
    }
}

/// Marker trait for values that can cross a remote stage boundary.
///
/// Local stages stay fully typed. Remote stage adapters use this type identity
/// plus a stage-specific codec to serialize items into the internal stage gRPC
/// envelope.
pub trait StagePayload: Send + 'static {
    const TYPE: StageType;
}

pub trait StageCodec<T: StagePayload>: Send + Sync {
    fn encode(&self, value: &T) -> Result<Vec<u8>, StageError>;
    fn decode(&self, payload: &[u8]) -> Result<T, StageError>;
}

pub struct StageInput<T> {
    pub context: Arc<BatchContext>,
    pub items: Vec<T>,
}

impl<T> StageInput<T>
where
    T: Send + 'static,
{
    pub fn new(context: Arc<BatchContext>, items: Vec<T>) -> Self {
        Self { context, items }
    }

    pub fn from_items(context: BatchContext, items: Vec<T>) -> Self {
        Self {
            context: Arc::new(context),
            items,
        }
    }

    pub fn from_arc_items(context: Arc<BatchContext>, items: Vec<T>) -> Self {
        Self { context, items }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BatchContext {
    pub batch_id: String,
    pub metadata: Metadata,
}

/// A Rust-internal Cymbal pipeline stage.
///
/// Stages are typed and composed linearly by the orchestrator. The stage
/// contract remains batch-based: each stage receives a vector of inputs and
/// returns a vector of outputs. Incremental pipeline runners may call stages
/// with bounded sub-batches when the stage declares item-progress semantics.
#[async_trait]
pub trait PipelineStage: Send + Sync {
    type Input: Send + 'static;
    type Output: Send + 'static;

    fn id(&self) -> StageType;

    async fn process(
        &self,
        input: StageInput<Self::Input>,
    ) -> Result<Vec<Self::Output>, StageError>;
}

/// Helper trait for stages whose behavior is independent per item.
///
/// The blanket [`PipelineStage`] implementation keeps simple stages from
/// repeating the same whole-batch loop while preserving the buffered pipeline
/// contract at the public stage boundary.
#[async_trait]
pub trait PerItemStage: Send + Sync {
    type Input: Send + 'static;
    type Output: Send + 'static;

    fn id(&self) -> StageType;

    async fn process_one(&self, input: Self::Input) -> Result<Self::Output, StageError>;
}

#[async_trait]
impl<Stage> PipelineStage for Stage
where
    Stage: PerItemStage,
{
    type Input = Stage::Input;
    type Output = Stage::Output;

    fn id(&self) -> StageType {
        PerItemStage::id(self)
    }

    async fn process(
        &self,
        input: StageInput<Self::Input>,
    ) -> Result<Vec<Self::Output>, StageError> {
        let mut outputs = Vec::with_capacity(input.items.len());
        for item in input.items {
            outputs.push(self.process_one(item).await?);
        }
        Ok(outputs)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StageError {
    InvalidInput(String),
    Transient(String),
    Internal(String),
}

impl Display for StageError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            StageError::InvalidInput(message) => write!(formatter, "invalid input: {message}"),
            StageError::Transient(message) => write!(formatter, "transient error: {message}"),
            StageError::Internal(message) => write!(formatter, "internal error: {message}"),
        }
    }
}

impl Error for StageError {}

#[cfg(test)]
mod tests {
    use async_trait::async_trait;

    use super::*;

    /// Generic per-item passthrough stage used to exercise the buffered
    /// stage contract without pulling in any domain-specific types.
    #[derive(Debug, Clone, Copy)]
    struct StringPassthroughStage;

    #[async_trait]
    impl PipelineStage for StringPassthroughStage {
        type Input = String;
        type Output = String;

        fn id(&self) -> StageType {
            StageType {
                namespace: "cymbal.stage",
                name: "passthrough",
                version: 1,
            }
        }

        async fn process(
            &self,
            input: StageInput<Self::Input>,
        ) -> Result<Vec<Self::Output>, StageError> {
            Ok(input.items)
        }
    }

    #[tokio::test]
    async fn stage_input_buffers_items() {
        let input = StageInput::from_items(
            BatchContext {
                batch_id: "batch-1".to_string(),
                metadata: Metadata::new(),
            },
            vec![1, 2, 3],
        );

        assert_eq!(input.context.batch_id, "batch-1");
        assert_eq!(input.items, vec![1, 2, 3]);
    }

    #[tokio::test]
    async fn pipeline_stage_processes_batch_items_in_order() {
        let stage = StringPassthroughStage;
        let output = stage
            .process(StageInput::from_items(
                BatchContext {
                    batch_id: "batch-1".to_string(),
                    metadata: Metadata::new(),
                },
                vec!["a".to_string(), "b".to_string()],
            ))
            .await
            .unwrap();

        assert_eq!(output, vec!["a".to_string(), "b".to_string()]);
    }
}
