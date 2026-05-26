//! Pure Rust Cymbal exception pipeline composition.
//!
//! This crate wires the typed business stages together without any public gRPC,
//! internal remote-stage transport, or removed HTTP pre/post-processing concerns.
//! Server crates adapt wire requests into `StageInput<InputEvent>` and stream
//! domain-level `EventResult` outcomes through the incremental API here.
//!
//! Submodules carve up responsibilities to keep ownership clear:
//!
//! * Generic stage execution primitives — the [`StageExecutor`] trait, the
//!   local-stage adapter [`LocalExecutor`], the continue-only adapter
//!   [`ContinueExecutor`], and the [`IntermediateStageOutput`] envelope used
//!   between stages — live in `cymbal-core` and are re-exported here so the
//!   exception pipeline keeps a single import surface. The
//!   [`IntermediateStageOutput`] re-export is a type alias that pins the
//!   generic terminal parameter to [`EventResult`].
//! * [`stage_graph`] — the static description of the pipeline shape:
//!   [`PipelineStages`], [`DefaultPipelineStages`], the typed executor bundle
//!   [`PipelineExecutors`], [`ExceptionPipelineStage`], per-stage progress
//!   modes, and per-event progress state.
//! * [`sink`] — the [`EventResultSink`] trait used by the streaming
//!   orchestrator to deliver per-event outcomes with backpressure.
//! * [`streaming`] — [`PipelineOutputOrder`], [`StreamingPipelineOptions`],
//!   and the incremental orchestrator
//!   [`process_exception_pipeline_streaming`].
//! * [`ordering`] — pure helpers for splitting stage outputs into
//!   continue/terminal halves, ordering results, and converting linking
//!   outcomes into alerting inputs.
//! * [`runner`] — the exception-domain item enum and stage driver that adapt
//!   [`PipelineExecutors`] to the generic `cymbal-core` linear runner for the
//!   buffered batch path.
//!
//! The root module owns the public batch entry point
//! [`ExceptionPipeline`]/[`process_exception_pipeline`] and re-exports the
//! public types from each submodule. Tests intentionally live here because
//! they exercise the full composed pipeline across every submodule.

use std::sync::Arc;

use cymbal_alerting::AlertingEvent;
use cymbal_core::{BatchContext, PipelineStage, StageError, StageInput};
use cymbal_domain::{EventResult, InputEvent, RateLimitGateOutput};
use cymbal_grouping::GroupedEvent;
use cymbal_resolution::ResolvedEvent;

mod ordering;
mod runner;
mod sink;
mod stage_graph;
mod streaming;

pub use cymbal_core::{
    ContinueExecutor, EmissionOrder, LocalExecutor, OrderedEmitter, PipelineEventState, Sink,
    StageExecutor, StageProgressMode,
};

/// Exception-pipeline alias for the generic [`cymbal_core::IntermediateStageOutput`].
///
/// The orchestrator and stage submodules use this alias so call sites
/// keep the simple `IntermediateStageOutput<T>` shape they had before the
/// framework primitive moved into `cymbal-core`. Terminal results are
/// always [`EventResult`]s in the exception pipeline.
pub type IntermediateStageOutput<T> = cymbal_core::IntermediateStageOutput<T, EventResult>;

pub use ordering::{
    event_result_to_alerting_event, order_event_results, split_intermediate_outputs,
    split_rate_limit_outputs,
};
pub use runner::{ExceptionPipelineItem, ExceptionStageDriver};
pub use sink::EventResultSink;
pub use stage_graph::{
    CymbalStageProgress, DefaultPipelineStages, ExceptionPipelineStage, PipelineExecutors,
    PipelineStages,
};
pub use streaming::{
    process_exception_pipeline_streaming, PipelineOutputOrder, StreamingPipelineOptions,
};

/// The domain-level exception pipeline.
///
/// The pipeline accepts normalized exception input events and emits one outcome
/// per event for the gRPC server to translate to the public protobuf API. It is
/// intentionally unaware of HTTP-only event decoding, response formatting, and
/// remote-stage gRPC placement.
#[derive(Clone)]
pub struct ExceptionPipeline {
    executors: PipelineExecutors,
}

impl ExceptionPipeline {
    pub fn default_stages() -> Self {
        Self::from_executors(PipelineExecutors::default())
    }

    pub fn new<RL, R, G, L, A>(stages: PipelineStages<RL, R, G, L, A>) -> Self
    where
        RL: PipelineStage<Input = InputEvent, Output = RateLimitGateOutput> + Send + Sync + 'static,
        R: PipelineStage<Input = InputEvent, Output = ResolvedEvent> + Send + Sync + 'static,
        G: PipelineStage<Input = ResolvedEvent, Output = GroupedEvent> + Send + Sync + 'static,
        L: PipelineStage<Input = GroupedEvent, Output = EventResult> + Send + Sync + 'static,
        A: PipelineStage<Input = AlertingEvent, Output = EventResult> + Send + Sync + 'static,
    {
        Self::from_executors(PipelineExecutors::from_stages(stages))
    }

    pub fn from_executors(executors: PipelineExecutors) -> Self {
        Self { executors }
    }

    pub async fn process(
        &self,
        input: StageInput<InputEvent>,
    ) -> Result<Vec<EventResult>, StageError> {
        process_exception_pipeline(input.context, input.items, &self.executors).await
    }
}

pub async fn process_exception_pipeline(
    context: Arc<BatchContext>,
    input_events: Vec<InputEvent>,
    executors: &PipelineExecutors,
) -> Result<Vec<EventResult>, StageError> {
    runner::process_exception_pipeline_with_runner(context, input_events, executors).await
}

#[cfg(test)]
mod tests {
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

    use async_trait::async_trait;
    use cymbal_alerting::AlertingEvent;
    use cymbal_core::{BatchContext, Metadata, PipelineStage, Sink, StageError, StageType};
    use cymbal_domain::{EventOutcome, ExceptionProperties, RateLimitGateOutput};
    use cymbal_grouping::GroupedEvent;
    use cymbal_resolution::ResolvedEvent;
    use tokio::sync::mpsc;
    use tokio::time::timeout;

    use super::*;

    #[derive(Clone, Default)]
    struct MockRateLimitingStage;

    #[async_trait]
    impl PipelineStage for MockRateLimitingStage {
        type Input = InputEvent;
        type Output = RateLimitGateOutput;

        fn id(&self) -> StageType {
            StageType {
                namespace: "cymbal.stage",
                name: "mock-rate-limiting",
                version: 1,
            }
        }

        async fn process(
            &self,
            input: StageInput<Self::Input>,
        ) -> Result<Vec<Self::Output>, StageError> {
            Ok(input
                .items
                .into_iter()
                .map(|event| {
                    if event.event_id == "limited-event" {
                        RateLimitGateOutput::drop(
                            event.event_id,
                            "rate_limited:team_id".to_string(),
                        )
                    } else {
                        RateLimitGateOutput::allowed(
                            event,
                            cymbal_domain::RateLimitDecision::Disabled,
                        )
                    }
                })
                .collect())
        }
    }

    #[derive(Clone, Default)]
    struct MockResolutionStage;

    #[async_trait]
    impl PipelineStage for MockResolutionStage {
        type Input = InputEvent;
        type Output = ResolvedEvent;

        fn id(&self) -> StageType {
            StageType {
                namespace: "cymbal.stage",
                name: "mock-resolution",
                version: 1,
            }
        }

        async fn process(
            &self,
            input: StageInput<Self::Input>,
        ) -> Result<Vec<Self::Output>, StageError> {
            Ok(input
                .items
                .into_iter()
                .map(|event| ResolvedEvent {
                    event_id: event.event_id,
                    team_id: event.team_id,
                    properties: event.properties,
                    metadata: [("resolution".to_string(), "ran".to_string())].into(),
                })
                .collect())
        }
    }

    #[derive(Clone, Default)]
    struct MockGroupingStage;

    #[async_trait]
    impl PipelineStage for MockGroupingStage {
        type Input = ResolvedEvent;
        type Output = GroupedEvent;

        fn id(&self) -> StageType {
            StageType {
                namespace: "cymbal.stage",
                name: "mock-grouping",
                version: 1,
            }
        }

        async fn process(
            &self,
            input: StageInput<Self::Input>,
        ) -> Result<Vec<Self::Output>, StageError> {
            Ok(input
                .items
                .into_iter()
                .map(|event| {
                    let mut metadata = event.metadata;
                    metadata.insert("grouping".to_string(), "ran".to_string());
                    GroupedEvent {
                        event_id: event.event_id,
                        team_id: event.team_id,
                        properties: event.properties,
                        metadata,
                    }
                })
                .collect())
        }
    }

    #[derive(Clone, Default)]
    struct MockLinkingStage;

    #[async_trait]
    impl PipelineStage for MockLinkingStage {
        type Input = GroupedEvent;
        type Output = EventResult;

        fn id(&self) -> StageType {
            StageType {
                namespace: "cymbal.stage",
                name: "mock-linking",
                version: 1,
            }
        }

        async fn process(
            &self,
            input: StageInput<Self::Input>,
        ) -> Result<Vec<Self::Output>, StageError> {
            Ok(input
                .items
                .into_iter()
                .map(|event| EventResult {
                    event_id: event.event_id,
                    outcome: EventOutcome::Next {
                        properties: Some(event.properties),
                        metadata: event.metadata,
                    },
                })
                .collect())
        }
    }

    fn input_event(event_id: &str) -> InputEvent {
        InputEvent {
            event_id: event_id.to_string(),
            team_id: 1,
            properties: ExceptionProperties::default(),
        }
    }

    #[derive(Clone, Default)]
    struct MockAlertingStage {
        seen_event_ids: Arc<Mutex<Vec<String>>>,
    }

    #[async_trait]
    impl PipelineStage for MockAlertingStage {
        type Input = AlertingEvent;
        type Output = EventResult;

        fn id(&self) -> StageType {
            StageType {
                namespace: "cymbal.stage",
                name: "mock-alerting",
                version: 1,
            }
        }

        async fn process(
            &self,
            input: StageInput<Self::Input>,
        ) -> Result<Vec<Self::Output>, StageError> {
            Ok(input
                .items
                .into_iter()
                .map(|event| {
                    self.seen_event_ids
                        .lock()
                        .unwrap()
                        .push(event.result.event_id.clone());
                    event.result
                })
                .collect())
        }
    }

    fn test_context() -> BatchContext {
        BatchContext {
            batch_id: "batch-1".to_string(),
            metadata: Metadata::new(),
        }
    }

    #[tokio::test]
    async fn pipeline_composes_resolution_grouping_linking_and_alerting() {
        let alerting = MockAlertingStage::default();
        let seen_event_ids = alerting.seen_event_ids.clone();
        let pipeline = ExceptionPipeline::new(PipelineStages {
            rate_limiting: MockRateLimitingStage,
            resolution: MockResolutionStage,
            grouping: MockGroupingStage,
            linking: MockLinkingStage,
            alerting,
        });

        let results = pipeline
            .process(StageInput::from_items(
                test_context(),
                vec![input_event("event-1")],
            ))
            .await
            .unwrap();

        assert_eq!(results.len(), 1);
        assert_eq!(results[0].event_id, "event-1");
        assert_eq!(seen_event_ids.lock().unwrap().as_slice(), ["event-1"]);
        let EventOutcome::Next { metadata, .. } = &results[0].outcome else {
            panic!("expected next outcome");
        };
        assert_eq!(metadata.get("resolution"), Some(&"ran".to_string()));
        assert_eq!(metadata.get("grouping"), Some(&"ran".to_string()));
    }

    #[derive(Clone, Default)]
    struct FailingResolutionStage;

    #[async_trait]
    impl PipelineStage for FailingResolutionStage {
        type Input = InputEvent;
        type Output = ResolvedEvent;

        fn id(&self) -> StageType {
            StageType {
                namespace: "cymbal.stage",
                name: "failing-resolution",
                version: 1,
            }
        }

        async fn process(
            &self,
            _input: StageInput<Self::Input>,
        ) -> Result<Vec<Self::Output>, StageError> {
            Err(StageError::InvalidInput("resolution failed".to_string()))
        }
    }

    #[tokio::test]
    async fn pipeline_propagates_stage_errors_without_http_adaptation() {
        let pipeline = ExceptionPipeline::new(PipelineStages {
            rate_limiting: MockRateLimitingStage,
            resolution: FailingResolutionStage,
            grouping: MockGroupingStage,
            linking: MockLinkingStage,
            alerting: MockAlertingStage::default(),
        });

        let error = pipeline
            .process(StageInput::from_items(
                test_context(),
                vec![input_event("event-1")],
            ))
            .await
            .unwrap_err();

        assert_eq!(
            error,
            StageError::InvalidInput("resolution failed".to_string())
        );
    }

    #[tokio::test]
    async fn pipeline_rate_limit_merges_terminal_results_in_input_order() {
        let alerting = MockAlertingStage::default();
        let seen_event_ids = alerting.seen_event_ids.clone();
        let pipeline = ExceptionPipeline::new(PipelineStages {
            rate_limiting: MockRateLimitingStage,
            resolution: MockResolutionStage,
            grouping: MockGroupingStage,
            linking: MockLinkingStage,
            alerting,
        });

        let results = pipeline
            .process(StageInput::from_items(
                test_context(),
                vec![
                    input_event("event-1"),
                    input_event("limited-event"),
                    input_event("event-3"),
                ],
            ))
            .await
            .unwrap();

        assert_eq!(
            results
                .iter()
                .map(|result| result.event_id.as_str())
                .collect::<Vec<_>>(),
            vec!["event-1", "limited-event", "event-3"]
        );
        assert!(matches!(results[0].outcome, EventOutcome::Next { .. }));
        assert_eq!(
            results[1].outcome,
            EventOutcome::Drop {
                reason: "rate_limited:team_id".to_string()
            }
        );
        assert!(matches!(results[2].outcome, EventOutcome::Next { .. }));
        assert_eq!(
            seen_event_ids.lock().unwrap().as_slice(),
            ["event-1", "event-3"]
        );
    }

    struct ChannelSink {
        sender: mpsc::Sender<EventResult>,
    }

    #[async_trait]
    impl Sink<EventResult> for ChannelSink {
        async fn emit(&mut self, result: EventResult) -> Result<(), StageError> {
            self.sender
                .send(result)
                .await
                .map_err(|_| StageError::Internal("result receiver dropped".to_string()))
        }
    }

    #[derive(Clone)]
    struct StreamingResolutionExecutor {
        delayed_event_ids: Arc<std::collections::HashSet<String>>,
        terminal_event_ids: Arc<std::collections::HashSet<String>>,
        seen_batches: Arc<Mutex<Vec<Vec<String>>>>,
    }

    impl StreamingResolutionExecutor {
        fn new(delayed_event_ids: &[&str], terminal_event_ids: &[&str]) -> Self {
            Self {
                delayed_event_ids: Arc::new(
                    delayed_event_ids
                        .iter()
                        .map(|event_id| (*event_id).to_string())
                        .collect(),
                ),
                terminal_event_ids: Arc::new(
                    terminal_event_ids
                        .iter()
                        .map(|event_id| (*event_id).to_string())
                        .collect(),
                ),
                seen_batches: Arc::new(Mutex::new(Vec::new())),
            }
        }

        fn seen_batches(&self) -> Vec<Vec<String>> {
            self.seen_batches.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl StageExecutor<InputEvent, IntermediateStageOutput<ResolvedEvent>>
        for StreamingResolutionExecutor
    {
        async fn run(
            &self,
            _ctx: Arc<BatchContext>,
            inputs: Vec<InputEvent>,
        ) -> Result<Vec<IntermediateStageOutput<ResolvedEvent>>, StageError> {
            self.seen_batches
                .lock()
                .unwrap()
                .push(inputs.iter().map(|event| event.event_id.clone()).collect());
            if inputs
                .iter()
                .any(|event| self.delayed_event_ids.contains(&event.event_id))
            {
                tokio::time::sleep(Duration::from_millis(200)).await;
            }

            Ok(inputs
                .into_iter()
                .map(|event| {
                    if self.terminal_event_ids.contains(&event.event_id) {
                        IntermediateStageOutput::Terminal(EventResult {
                            event_id: event.event_id,
                            outcome: EventOutcome::Retry {
                                reason: "terminal in resolution".to_string(),
                                retry_after_ms: None,
                            },
                        })
                    } else {
                        IntermediateStageOutput::Continue(ResolvedEvent {
                            event_id: event.event_id,
                            team_id: event.team_id,
                            properties: event.properties,
                            metadata: Metadata::new(),
                        })
                    }
                })
                .collect())
        }
    }

    fn streaming_test_executors(resolution: StreamingResolutionExecutor) -> PipelineExecutors {
        PipelineExecutors {
            rate_limiting: Arc::new(LocalExecutor::new(MockRateLimitingStage)),
            resolution: Arc::new(resolution),
            grouping: Arc::new(ContinueExecutor::new(LocalExecutor::new(MockGroupingStage))),
            linking: Arc::new(LocalExecutor::new(MockLinkingStage)),
            alerting: Arc::new(LocalExecutor::new(MockAlertingStage::default())),
        }
    }

    async fn collect_streaming_results(mut receiver: mpsc::Receiver<EventResult>) -> Vec<String> {
        let mut event_ids = Vec::new();
        while let Some(result) = receiver.recv().await {
            event_ids.push(result.event_id);
        }
        event_ids
    }

    #[tokio::test]
    async fn streaming_pipeline_emits_ordered_prefix_before_later_slow_events() {
        let resolution = StreamingResolutionExecutor::new(&["slow-event"], &["terminal-1"]);
        let seen_batches = resolution.clone();
        let executors = streaming_test_executors(resolution);
        let (sender, receiver) = mpsc::channel(2);
        let task = tokio::spawn(async move {
            process_exception_pipeline_streaming(
                Arc::new(test_context()),
                vec![
                    input_event("terminal-1"),
                    input_event("event-2"),
                    input_event("slow-event"),
                ],
                &executors,
                StreamingPipelineOptions {
                    item_progress_chunk_size: 2,
                    max_concurrent_item_progress_chunks: 2,
                    ..Default::default()
                },
                ChannelSink { sender },
            )
            .await
        });

        let first = timeout(Duration::from_millis(100), collect_one(receiver))
            .await
            .unwrap();
        let (first, receiver) = first;
        assert_eq!(first.event_id, "terminal-1");

        task.await.unwrap().unwrap();
        let remaining = collect_streaming_results(receiver).await;
        assert_eq!(remaining, vec!["event-2", "slow-event"]);
        assert_eq!(
            seen_batches.seen_batches(),
            vec![
                vec!["terminal-1".to_string(), "event-2".to_string()],
                vec!["slow-event".to_string()]
            ]
        );
    }

    async fn collect_one(
        mut receiver: mpsc::Receiver<EventResult>,
    ) -> (EventResult, mpsc::Receiver<EventResult>) {
        let result = receiver.recv().await.unwrap();
        (result, receiver)
    }

    #[tokio::test]
    async fn streaming_pipeline_buffers_fast_later_results_to_preserve_input_order() {
        let resolution = StreamingResolutionExecutor::new(&["slow-1", "slow-2"], &["terminal-3"]);
        let executors = streaming_test_executors(resolution);
        let (sender, mut receiver) = mpsc::channel(4);
        let task = tokio::spawn(async move {
            process_exception_pipeline_streaming(
                Arc::new(test_context()),
                vec![
                    input_event("slow-1"),
                    input_event("slow-2"),
                    input_event("terminal-3"),
                    input_event("event-4"),
                ],
                &executors,
                StreamingPipelineOptions {
                    item_progress_chunk_size: 2,
                    max_concurrent_item_progress_chunks: 2,
                    ..Default::default()
                },
                ChannelSink { sender },
            )
            .await
        });

        assert!(timeout(Duration::from_millis(75), receiver.recv())
            .await
            .is_err());

        task.await.unwrap().unwrap();
        let mut event_ids = Vec::new();
        while let Some(result) = receiver.recv().await {
            event_ids.push(result.event_id);
        }
        assert_eq!(event_ids, vec!["slow-1", "slow-2", "terminal-3", "event-4"]);
    }
}
