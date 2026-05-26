//! Generic linear pipeline runner primitives.
//!
//! The runner is intentionally small and opinionated: products own a
//! homogeneous item enum, implement [`PipelineItem`] / [`TerminalItem`], and
//! provide a [`StageDriver`] that knows how to execute each [`StageSpec`]. Core
//! owns the linear stage loop, terminal bypass, spec validation, and ordered
//! terminal emission. It does not own product payloads, transport, retries,
//! metrics, or deployment placement.
//!
//! `StageProgressMode::ItemProgress` is currently executed as a single
//! in-process batch. Chunking and concurrent item-progress execution are left
//! for a future migration once a product adapter needs them; the API keeps the
//! progress metadata visible to drivers so they can make conservative choices.

use std::collections::HashSet;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::marker::PhantomData;
use std::sync::Arc;

use async_trait::async_trait;

use crate::emission::IdentifiedItem;
use crate::{
    BatchContext, EmissionOrder, LinearPipelineSpec, OrderedEmitter, PipelineSpecError, Sink,
    StageError, StageId, StageSpec, StageType,
};

/// Product-owned non-terminal item flowing between stages.
///
/// Implement this for a homogeneous product enum such as
/// `ExceptionPipelineItem`. The runner uses `payload_type` to validate that a
/// driver returned items that match the next linear stage's contract.
pub trait PipelineItem: IdentifiedItem + Send + 'static {
    fn payload_type(&self) -> StageType;
}

/// Product-owned terminal item emitted by the runner.
///
/// This is separate from [`PipelineItem`] so products can keep terminal DTOs out
/// of their intermediate item enum while still sharing the same identity API.
pub trait TerminalItem: IdentifiedItem + Send + 'static {
    fn payload_type(&self) -> StageType;
}

/// Output from one stage invocation.
///
/// `continue_items` proceed to the next stage. `terminal_items` bypass all
/// remaining stages and are emitted through the runner's ordered emitter.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StageBatchOutcome<Item, Terminal> {
    pub continue_items: Vec<Item>,
    pub terminal_items: Vec<Terminal>,
}

impl<Item, Terminal> StageBatchOutcome<Item, Terminal> {
    pub fn new(continue_items: Vec<Item>, terminal_items: Vec<Terminal>) -> Self {
        Self {
            continue_items,
            terminal_items,
        }
    }

    pub fn continue_only(continue_items: Vec<Item>) -> Self {
        Self {
            continue_items,
            terminal_items: Vec::new(),
        }
    }

    pub fn terminal_only(terminal_items: Vec<Terminal>) -> Self {
        Self {
            continue_items: Vec::new(),
            terminal_items,
        }
    }
}

/// Product adapter that executes a stage for the current batch of items.
#[async_trait]
pub trait StageDriver<Item, Terminal>: Send + Sync
where
    Item: PipelineItem,
    Terminal: TerminalItem,
{
    async fn run_stage(
        &self,
        context: Arc<BatchContext>,
        stage: &StageSpec,
        items: Vec<Item>,
    ) -> Result<StageBatchOutcome<Item, Terminal>, StageError>;
}

/// Runner-level options that are independent of product payloads.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LinearPipelineRunnerOptions {
    pub emission_order: EmissionOrder,
}

impl Default for LinearPipelineRunnerOptions {
    fn default() -> Self {
        Self {
            emission_order: EmissionOrder::InputOrder,
        }
    }
}

/// Errors raised by the generic runner before product transport concerns.
#[derive(Debug, PartialEq, Eq)]
pub enum LinearPipelineRunnerError {
    InvalidSpec(PipelineSpecError),
    DuplicateInputItemId {
        item_id: String,
    },
    InvalidInputItemType {
        item_id: String,
        expected_type: String,
        actual_type: String,
    },
    InvalidContinueItemType {
        stage_id: StageId,
        item_id: String,
        expected_type: String,
        actual_type: String,
    },
    InvalidTerminalItemType {
        stage_id: StageId,
        item_id: String,
        expected_type: String,
        actual_type: String,
    },
    UnexpectedContinueAfterFinalStage {
        stage_id: StageId,
        item_id: String,
    },
    StageFailed {
        stage_id: StageId,
        source: StageError,
    },
    EmissionFailed(StageError),
}

impl Display for LinearPipelineRunnerError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            LinearPipelineRunnerError::InvalidSpec(error) => {
                write!(formatter, "invalid pipeline spec: {error}")
            }
            LinearPipelineRunnerError::DuplicateInputItemId { item_id } => {
                write!(formatter, "pipeline input contains duplicate item ID {item_id}")
            }
            LinearPipelineRunnerError::InvalidInputItemType {
                item_id,
                expected_type,
                actual_type,
            } => write!(
                formatter,
                "pipeline input item {item_id} has payload type {actual_type}, expected {expected_type}"
            ),
            LinearPipelineRunnerError::InvalidContinueItemType {
                stage_id,
                item_id,
                expected_type,
                actual_type,
            } => write!(
                formatter,
                "stage {stage_id} returned continue item {item_id} with payload type {actual_type}, expected {expected_type}"
            ),
            LinearPipelineRunnerError::InvalidTerminalItemType {
                stage_id,
                item_id,
                expected_type,
                actual_type,
            } => write!(
                formatter,
                "stage {stage_id} returned terminal item {item_id} with payload type {actual_type}, expected {expected_type}"
            ),
            LinearPipelineRunnerError::UnexpectedContinueAfterFinalStage { stage_id, item_id } => {
                write!(
                    formatter,
                    "final stage {stage_id} returned continue item {item_id} with no downstream stage"
                )
            }
            LinearPipelineRunnerError::StageFailed { stage_id, source } => {
                write!(formatter, "stage {stage_id} failed: {source}")
            }
            LinearPipelineRunnerError::EmissionFailed(error) => {
                write!(formatter, "terminal emission failed: {error}")
            }
        }
    }
}

impl Error for LinearPipelineRunnerError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            LinearPipelineRunnerError::InvalidSpec(error) => Some(error),
            LinearPipelineRunnerError::StageFailed { source, .. } => Some(source),
            LinearPipelineRunnerError::EmissionFailed(error) => Some(error),
            _ => None,
        }
    }
}

/// Opinionated linear runner for product-owned item enums.
pub struct LinearPipelineRunner<Item, Terminal, Driver>
where
    Item: PipelineItem,
    Terminal: TerminalItem,
    Driver: StageDriver<Item, Terminal>,
{
    spec: LinearPipelineSpec,
    driver: Driver,
    options: LinearPipelineRunnerOptions,
    _item_marker: PhantomData<fn() -> (Item, Terminal)>,
}

impl<Item, Terminal, Driver> LinearPipelineRunner<Item, Terminal, Driver>
where
    Item: PipelineItem,
    Terminal: TerminalItem,
    Driver: StageDriver<Item, Terminal>,
{
    pub fn new(
        spec: LinearPipelineSpec,
        driver: Driver,
        options: LinearPipelineRunnerOptions,
    ) -> Self {
        Self {
            spec,
            driver,
            options,
            _item_marker: PhantomData,
        }
    }

    pub fn spec(&self) -> &LinearPipelineSpec {
        &self.spec
    }

    pub fn options(&self) -> LinearPipelineRunnerOptions {
        self.options
    }

    pub async fn run<S>(
        &self,
        context: Arc<BatchContext>,
        input_items: Vec<Item>,
        sink: S,
    ) -> Result<(), LinearPipelineRunnerError>
    where
        S: Sink<Terminal>,
    {
        self.spec
            .validate()
            .map_err(LinearPipelineRunnerError::InvalidSpec)?;
        self.validate_input_items(&input_items)?;

        let input_ids = input_items
            .iter()
            .map(|item| item.item_id().to_string())
            .collect();
        let mut emitter =
            OrderedEmitter::for_identified(input_ids, self.options.emission_order, sink);
        let mut current_items = input_items;

        for (stage_index, stage) in self.spec.stages.iter().enumerate() {
            if current_items.is_empty() {
                break;
            }

            let next_input_type = self
                .spec
                .stages
                .get(stage_index + 1)
                .map(|next_stage| next_stage.input_type);
            let outcome = self
                .driver
                .run_stage(Arc::clone(&context), stage, current_items)
                .await
                .map_err(|source| LinearPipelineRunnerError::StageFailed {
                    stage_id: stage.stage_id.clone(),
                    source,
                })?;

            self.validate_terminal_items(stage, &outcome.terminal_items)?;
            emitter
                .emit_many(outcome.terminal_items)
                .await
                .map_err(LinearPipelineRunnerError::EmissionFailed)?;
            self.validate_continue_items(stage, next_input_type, &outcome.continue_items)?;
            current_items = outcome.continue_items;
        }

        emitter
            .finish()
            .map_err(LinearPipelineRunnerError::EmissionFailed)
    }

    fn validate_input_items(&self, items: &[Item]) -> Result<(), LinearPipelineRunnerError> {
        let mut seen_item_ids = HashSet::with_capacity(items.len());
        for item in items {
            if !seen_item_ids.insert(item.item_id().to_string()) {
                return Err(LinearPipelineRunnerError::DuplicateInputItemId {
                    item_id: item.item_id().to_string(),
                });
            }
            if item.payload_type() != self.spec.input_type {
                return Err(LinearPipelineRunnerError::InvalidInputItemType {
                    item_id: item.item_id().to_string(),
                    expected_type: self.spec.input_type.to_string(),
                    actual_type: item.payload_type().to_string(),
                });
            }
        }
        Ok(())
    }

    fn validate_continue_items(
        &self,
        stage: &StageSpec,
        next_input_type: Option<StageType>,
        items: &[Item],
    ) -> Result<(), LinearPipelineRunnerError> {
        let Some(expected_type) = next_input_type else {
            if let Some(item) = items.first() {
                return Err(
                    LinearPipelineRunnerError::UnexpectedContinueAfterFinalStage {
                        stage_id: stage.stage_id.clone(),
                        item_id: item.item_id().to_string(),
                    },
                );
            }
            return Ok(());
        };

        for item in items {
            if item.payload_type() != expected_type {
                return Err(LinearPipelineRunnerError::InvalidContinueItemType {
                    stage_id: stage.stage_id.clone(),
                    item_id: item.item_id().to_string(),
                    expected_type: expected_type.to_string(),
                    actual_type: item.payload_type().to_string(),
                });
            }
        }
        Ok(())
    }

    fn validate_terminal_items(
        &self,
        stage: &StageSpec,
        items: &[Terminal],
    ) -> Result<(), LinearPipelineRunnerError> {
        for item in items {
            if item.payload_type() != self.spec.terminal_type {
                return Err(LinearPipelineRunnerError::InvalidTerminalItemType {
                    stage_id: stage.stage_id.clone(),
                    item_id: item.item_id().to_string(),
                    expected_type: self.spec.terminal_type.to_string(),
                    actual_type: item.payload_type().to_string(),
                });
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use std::sync::{Arc, Mutex};

    use super::*;
    use crate::{
        Metadata, StageEffectMode, StageLinkRule, StageProgressMode, TransientFailurePolicy,
    };

    const RAW_TYPE: StageType = stage_type("example.runner", "raw", 1);
    const GATE_TYPE: StageType = stage_type("example.runner", "gate", 1);
    const ENRICHED_TYPE: StageType = stage_type("example.runner", "enriched", 1);
    const TERMINAL_TYPE: StageType = stage_type("example.runner", "terminal", 1);
    const OTHER_TYPE: StageType = stage_type("example.runner", "other", 1);

    const fn stage_type(namespace: &'static str, name: &'static str, version: u16) -> StageType {
        StageType {
            namespace,
            name,
            version,
        }
    }

    #[derive(Clone, Debug, PartialEq, Eq)]
    enum ToyItem {
        Raw { id: String, value: &'static str },
        Enriched { id: String, value: &'static str },
        Other { id: String },
    }

    impl IdentifiedItem for ToyItem {
        fn item_id(&self) -> &str {
            match self {
                ToyItem::Raw { id, .. } | ToyItem::Enriched { id, .. } | ToyItem::Other { id } => {
                    id.as_str()
                }
            }
        }
    }

    impl PipelineItem for ToyItem {
        fn payload_type(&self) -> StageType {
            match self {
                ToyItem::Raw { .. } => RAW_TYPE,
                ToyItem::Enriched { .. } => ENRICHED_TYPE,
                ToyItem::Other { .. } => OTHER_TYPE,
            }
        }
    }

    #[derive(Clone, Debug, PartialEq, Eq)]
    struct ToyTerminal {
        id: String,
        value: &'static str,
        payload_type: StageType,
    }

    impl IdentifiedItem for ToyTerminal {
        fn item_id(&self) -> &str {
            self.id.as_str()
        }
    }

    impl TerminalItem for ToyTerminal {
        fn payload_type(&self) -> StageType {
            self.payload_type
        }
    }

    fn raw(id: &str, value: &'static str) -> ToyItem {
        ToyItem::Raw {
            id: id.to_string(),
            value,
        }
    }

    fn enriched(id: &str, value: &'static str) -> ToyItem {
        ToyItem::Enriched {
            id: id.to_string(),
            value,
        }
    }

    fn terminal(id: &str, value: &'static str) -> ToyTerminal {
        ToyTerminal {
            id: id.to_string(),
            value,
            payload_type: TERMINAL_TYPE,
        }
    }

    fn other_terminal(id: &str) -> ToyTerminal {
        ToyTerminal {
            id: id.to_string(),
            value: "wrong-type",
            payload_type: OTHER_TYPE,
        }
    }

    fn stage(
        stage_id: &'static str,
        input_type: StageType,
        output_type: StageType,
        progress: StageProgressMode,
    ) -> StageSpec {
        StageSpec {
            stage_id: stage_id.to_string(),
            stage_type: stage_type("example.runner.stage", stage_id, 1),
            input_type,
            output_type,
            progress,
            effects: StageEffectMode::Pure,
            transient_failure_policy: TransientFailurePolicy::RetryableBeforeWork,
        }
    }

    fn spec(stages: Vec<StageSpec>) -> LinearPipelineSpec {
        LinearPipelineSpec {
            input_type: RAW_TYPE,
            terminal_type: TERMINAL_TYPE,
            stages,
            allowed_links: vec![StageLinkRule::ExactType],
        }
    }

    fn two_stage_spec() -> LinearPipelineSpec {
        spec(vec![
            stage(
                "enrich",
                RAW_TYPE,
                ENRICHED_TYPE,
                StageProgressMode::ItemProgress,
            ),
            stage(
                "finish",
                ENRICHED_TYPE,
                TERMINAL_TYPE,
                StageProgressMode::BatchBarrier,
            ),
        ])
    }

    fn context() -> Arc<BatchContext> {
        Arc::new(BatchContext {
            batch_id: "batch-1".to_string(),
            metadata: Metadata::new(),
        })
    }

    #[derive(Default, Clone)]
    struct RecordingSink {
        emitted: Arc<Mutex<Vec<ToyTerminal>>>,
    }

    impl RecordingSink {
        fn values(&self) -> Vec<&'static str> {
            self.emitted
                .lock()
                .unwrap()
                .iter()
                .map(|item| item.value)
                .collect()
        }
    }

    #[async_trait]
    impl Sink<ToyTerminal> for RecordingSink {
        async fn emit(&mut self, item: ToyTerminal) -> Result<(), StageError> {
            self.emitted.lock().unwrap().push(item);
            Ok(())
        }
    }

    #[derive(Default, Clone)]
    struct ToyDriver {
        calls: Arc<Mutex<Vec<DriverCall>>>,
        fail_stage_id: Option<&'static str>,
        invalid_terminal_stage_id: Option<&'static str>,
        invalid_continue_stage_id: Option<&'static str>,
    }

    #[derive(Debug, Clone, PartialEq, Eq)]
    struct DriverCall {
        stage_id: String,
        item_ids: Vec<String>,
        progress: StageProgressMode,
        effects: StageEffectMode,
        transient_failure_policy: TransientFailurePolicy,
    }

    impl ToyDriver {
        fn calls(&self) -> Vec<DriverCall> {
            self.calls.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl StageDriver<ToyItem, ToyTerminal> for ToyDriver {
        async fn run_stage(
            &self,
            _context: Arc<BatchContext>,
            stage: &StageSpec,
            items: Vec<ToyItem>,
        ) -> Result<StageBatchOutcome<ToyItem, ToyTerminal>, StageError> {
            self.calls.lock().unwrap().push(DriverCall {
                stage_id: stage.stage_id.clone(),
                item_ids: items
                    .iter()
                    .map(|item| item.item_id().to_string())
                    .collect(),
                progress: stage.progress,
                effects: stage.effects,
                transient_failure_policy: stage.transient_failure_policy,
            });

            if self.fail_stage_id == Some(stage.stage_id.as_str()) {
                return Err(StageError::Transient("driver failed".to_string()));
            }

            if self.invalid_terminal_stage_id == Some(stage.stage_id.as_str()) {
                return Ok(StageBatchOutcome::terminal_only(vec![other_terminal("a")]));
            }

            if self.invalid_continue_stage_id == Some(stage.stage_id.as_str()) {
                return Ok(StageBatchOutcome::continue_only(vec![ToyItem::Other {
                    id: "a".to_string(),
                }]));
            }

            match stage.stage_id.as_str() {
                "admit" => {
                    let mut continue_items = Vec::new();
                    let mut terminal_items = Vec::new();
                    for item in items {
                        match item {
                            ToyItem::Raw { id, value: "drop" } => {
                                terminal_items.push(terminal(&id, "dropped"));
                            }
                            ToyItem::Raw { id, value } => {
                                continue_items.push(ToyItem::Raw { id, value })
                            }
                            other => continue_items.push(other),
                        }
                    }
                    Ok(StageBatchOutcome::new(continue_items, terminal_items))
                }
                "enrich" => Ok(StageBatchOutcome::continue_only(
                    items
                        .into_iter()
                        .map(|item| match item {
                            ToyItem::Raw { id, value } => enriched(&id, value),
                            item => item,
                        })
                        .collect(),
                )),
                "finish" => Ok(StageBatchOutcome::terminal_only(
                    items
                        .into_iter()
                        .map(|item| terminal(item.item_id(), "finished"))
                        .rev()
                        .collect(),
                )),
                _ => Ok(StageBatchOutcome::continue_only(items)),
            }
        }
    }

    #[tokio::test]
    async fn executes_stages_in_spec_order_and_carries_metadata_to_driver() {
        let mut pipeline_spec = two_stage_spec();
        pipeline_spec.stages[0].effects = StageEffectMode::IdempotentSideEffects;
        pipeline_spec.stages[0].transient_failure_policy =
            TransientFailurePolicy::RetryableIfStageDeclaresSafe;
        let driver = ToyDriver::default();
        let sink = RecordingSink::default();
        let runner = LinearPipelineRunner::new(
            pipeline_spec,
            driver.clone(),
            LinearPipelineRunnerOptions::default(),
        );

        runner
            .run(context(), vec![raw("a", "one"), raw("b", "two")], sink)
            .await
            .unwrap();

        let calls = driver.calls();
        assert_eq!(
            calls
                .iter()
                .map(|call| call.stage_id.as_str())
                .collect::<Vec<_>>(),
            vec!["enrich", "finish"]
        );
        assert_eq!(calls[0].progress, StageProgressMode::ItemProgress);
        assert_eq!(calls[0].effects, StageEffectMode::IdempotentSideEffects);
        assert_eq!(
            calls[0].transient_failure_policy,
            TransientFailurePolicy::RetryableIfStageDeclaresSafe
        );
    }

    #[tokio::test]
    async fn terminal_items_bypass_remaining_stages() {
        let pipeline_spec = LinearPipelineSpec {
            input_type: RAW_TYPE,
            terminal_type: TERMINAL_TYPE,
            stages: vec![
                stage(
                    "admit",
                    RAW_TYPE,
                    GATE_TYPE,
                    StageProgressMode::BatchBarrier,
                ),
                stage(
                    "enrich",
                    RAW_TYPE,
                    ENRICHED_TYPE,
                    StageProgressMode::ItemProgress,
                ),
                stage(
                    "finish",
                    ENRICHED_TYPE,
                    TERMINAL_TYPE,
                    StageProgressMode::BatchBarrier,
                ),
            ],
            allowed_links: vec![
                StageLinkRule::ExactType,
                StageLinkRule::FanOutContinue {
                    stage_output_type: GATE_TYPE,
                    next_input_type: RAW_TYPE,
                    terminal_type: TERMINAL_TYPE,
                },
            ],
        };
        let driver = ToyDriver::default();
        let sink = RecordingSink::default();
        let runner = LinearPipelineRunner::new(
            pipeline_spec,
            driver.clone(),
            LinearPipelineRunnerOptions::default(),
        );

        runner
            .run(
                context(),
                vec![raw("a", "drop"), raw("b", "keep")],
                sink.clone(),
            )
            .await
            .unwrap();

        let calls = driver.calls();
        assert_eq!(calls[0].item_ids, vec!["a", "b"]);
        assert_eq!(calls[1].item_ids, vec!["b"]);
        assert_eq!(calls[2].item_ids, vec!["b"]);
        assert_eq!(sink.values(), vec!["dropped", "finished"]);
    }

    #[tokio::test]
    async fn input_order_emission_buffers_completion_order_terminals() {
        let driver = ToyDriver::default();
        let sink = RecordingSink::default();
        let runner = LinearPipelineRunner::new(
            two_stage_spec(),
            driver,
            LinearPipelineRunnerOptions {
                emission_order: EmissionOrder::InputOrder,
            },
        );

        runner
            .run(
                context(),
                vec![raw("a", "one"), raw("b", "two")],
                sink.clone(),
            )
            .await
            .unwrap();

        assert_eq!(sink.values(), vec!["finished", "finished"]);
        let ids = sink
            .emitted
            .lock()
            .unwrap()
            .iter()
            .map(|item| item.id.clone())
            .collect::<Vec<_>>();
        assert_eq!(ids, vec!["a", "b"]);
    }

    #[tokio::test]
    async fn completion_order_emission_emits_driver_order() {
        let driver = ToyDriver::default();
        let sink = RecordingSink::default();
        let runner = LinearPipelineRunner::new(
            two_stage_spec(),
            driver,
            LinearPipelineRunnerOptions {
                emission_order: EmissionOrder::CompletionOrder,
            },
        );

        runner
            .run(
                context(),
                vec![raw("a", "one"), raw("b", "two")],
                sink.clone(),
            )
            .await
            .unwrap();

        let ids = sink
            .emitted
            .lock()
            .unwrap()
            .iter()
            .map(|item| item.id.clone())
            .collect::<Vec<_>>();
        assert_eq!(ids, vec!["b", "a"]);
    }

    #[tokio::test]
    async fn batch_barrier_stage_receives_the_whole_current_batch_before_downstream_progress() {
        let pipeline_spec = LinearPipelineSpec {
            input_type: RAW_TYPE,
            terminal_type: TERMINAL_TYPE,
            stages: vec![
                stage(
                    "admit",
                    RAW_TYPE,
                    GATE_TYPE,
                    StageProgressMode::BatchBarrier,
                ),
                stage(
                    "enrich",
                    RAW_TYPE,
                    ENRICHED_TYPE,
                    StageProgressMode::ItemProgress,
                ),
                stage(
                    "finish",
                    ENRICHED_TYPE,
                    TERMINAL_TYPE,
                    StageProgressMode::BatchBarrier,
                ),
            ],
            allowed_links: vec![
                StageLinkRule::ExactType,
                StageLinkRule::FanOutContinue {
                    stage_output_type: GATE_TYPE,
                    next_input_type: RAW_TYPE,
                    terminal_type: TERMINAL_TYPE,
                },
            ],
        };
        let driver = ToyDriver::default();
        let runner = LinearPipelineRunner::new(
            pipeline_spec,
            driver.clone(),
            LinearPipelineRunnerOptions::default(),
        );

        runner
            .run(
                context(),
                vec![raw("a", "keep"), raw("b", "keep"), raw("c", "drop")],
                RecordingSink::default(),
            )
            .await
            .unwrap();

        let calls = driver.calls();
        assert_eq!(calls[0].stage_id, "admit");
        assert_eq!(calls[0].progress, StageProgressMode::BatchBarrier);
        assert_eq!(calls[0].item_ids, vec!["a", "b", "c"]);
        assert_eq!(calls[1].stage_id, "enrich");
        assert_eq!(calls[1].item_ids, vec!["a", "b"]);
    }

    #[tokio::test]
    async fn item_progress_stages_are_currently_run_as_one_batch_without_chunking() {
        let driver = ToyDriver::default();
        let runner = LinearPipelineRunner::new(
            two_stage_spec(),
            driver.clone(),
            LinearPipelineRunnerOptions::default(),
        );

        runner
            .run(
                context(),
                vec![raw("a", "one"), raw("b", "two"), raw("c", "three")],
                RecordingSink::default(),
            )
            .await
            .unwrap();

        let calls = driver.calls();
        assert_eq!(calls[0].progress, StageProgressMode::ItemProgress);
        assert_eq!(calls[0].item_ids, vec!["a", "b", "c"]);
    }

    #[tokio::test]
    async fn validation_failures_are_returned_before_driver_runs() {
        let invalid_spec = spec(vec![stage(
            "enrich",
            OTHER_TYPE,
            ENRICHED_TYPE,
            StageProgressMode::ItemProgress,
        )]);
        let driver = ToyDriver::default();
        let runner = LinearPipelineRunner::new(
            invalid_spec,
            driver.clone(),
            LinearPipelineRunnerOptions::default(),
        );

        let error = runner
            .run(context(), vec![raw("a", "one")], RecordingSink::default())
            .await
            .unwrap_err();

        assert!(matches!(
            error,
            LinearPipelineRunnerError::InvalidSpec(
                PipelineSpecError::InvalidFirstStageInput { .. }
            )
        ));
        assert!(driver.calls().is_empty());
    }

    #[tokio::test]
    async fn invalid_initial_item_payload_type_is_rejected() {
        let driver = ToyDriver::default();
        let runner = LinearPipelineRunner::new(
            two_stage_spec(),
            driver.clone(),
            LinearPipelineRunnerOptions::default(),
        );

        let error = runner
            .run(
                context(),
                vec![ToyItem::Other {
                    id: "a".to_string(),
                }],
                RecordingSink::default(),
            )
            .await
            .unwrap_err();

        assert_eq!(
            error,
            LinearPipelineRunnerError::InvalidInputItemType {
                item_id: "a".to_string(),
                expected_type: RAW_TYPE.to_string(),
                actual_type: OTHER_TYPE.to_string(),
            }
        );
        assert!(driver.calls().is_empty());
    }

    #[tokio::test]
    async fn invalid_continue_item_payload_type_is_rejected() {
        let driver = ToyDriver {
            invalid_continue_stage_id: Some("enrich"),
            ..ToyDriver::default()
        };
        let runner = LinearPipelineRunner::new(
            two_stage_spec(),
            driver,
            LinearPipelineRunnerOptions::default(),
        );

        let error = runner
            .run(context(), vec![raw("a", "one")], RecordingSink::default())
            .await
            .unwrap_err();

        assert_eq!(
            error,
            LinearPipelineRunnerError::InvalidContinueItemType {
                stage_id: "enrich".to_string(),
                item_id: "a".to_string(),
                expected_type: ENRICHED_TYPE.to_string(),
                actual_type: OTHER_TYPE.to_string(),
            }
        );
    }

    #[tokio::test]
    async fn invalid_terminal_item_payload_type_is_rejected() {
        let driver = ToyDriver {
            invalid_terminal_stage_id: Some("finish"),
            ..ToyDriver::default()
        };
        let runner = LinearPipelineRunner::new(
            two_stage_spec(),
            driver,
            LinearPipelineRunnerOptions::default(),
        );

        let error = runner
            .run(context(), vec![raw("a", "one")], RecordingSink::default())
            .await
            .unwrap_err();

        assert_eq!(
            error,
            LinearPipelineRunnerError::InvalidTerminalItemType {
                stage_id: "finish".to_string(),
                item_id: "a".to_string(),
                expected_type: TERMINAL_TYPE.to_string(),
                actual_type: OTHER_TYPE.to_string(),
            }
        );
    }

    #[tokio::test]
    async fn driver_errors_include_the_stage_id() {
        let driver = ToyDriver {
            fail_stage_id: Some("enrich"),
            ..ToyDriver::default()
        };
        let runner = LinearPipelineRunner::new(
            two_stage_spec(),
            driver,
            LinearPipelineRunnerOptions::default(),
        );

        let error = runner
            .run(context(), vec![raw("a", "one")], RecordingSink::default())
            .await
            .unwrap_err();

        assert_eq!(
            error,
            LinearPipelineRunnerError::StageFailed {
                stage_id: "enrich".to_string(),
                source: StageError::Transient("driver failed".to_string()),
            }
        );
    }
}
