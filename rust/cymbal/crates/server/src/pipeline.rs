//! Node-facing Cymbal ingestion service.
//!
//! This service owns orchestration only: run Cymbal's configured stage chain
//! locally or remotely according to the registry, and convert final
//! Rust-internal `EventResult`s back to the public ingestion API.

use std::collections::HashMap;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Instant;

use async_trait::async_trait;
use cymbal_alerting::{AlertingEvent, ALERTING_STAGE_ID};
use cymbal_api::cymbal::v1::cymbal_ingestion_server::CymbalIngestion;
use cymbal_api::cymbal::v1::{
    ProcessExceptionBatchRequest, ProcessExceptionBatchResult as ApiBatchResult,
};
use cymbal_core::routing::RoutingKey;
use cymbal_core::{BatchContext, Sink, StageError, StagePayload};
use cymbal_domain::{EventOutcome, EventResult as DomainEventResult, InputEvent};
use cymbal_grouping::{GroupedEvent, GROUPING_STAGE_ID};
use cymbal_linking::LINKING_STAGE_ID;
use cymbal_pipeline::{
    process_exception_pipeline_streaming, ContinueExecutor, IntermediateStageOutput, LocalExecutor,
    PipelineExecutors, PipelineStages, StageExecutor, StreamingPipelineOptions,
};
use cymbal_resolution::{ResolvedEvent, RESOLUTION_STAGE_ID};
use cymbal_runtime::RuntimeStages;
use futures::{stream, Stream};
use tokio::sync::mpsc;
use tonic::{Request, Response, Status};

use crate::api::{domain_event_result_to_api, request_to_stage_input, stage_error_to_status};
use crate::observability::{
    metered_stage, record_pipeline_batch, should_log_item_failure, InFlightBatchTracker,
    MeteredStageResult, StageExecutionKind, StageItemCounts, StageOutcomeLabel,
};
use crate::pipeline_routing::resolution_routing_key;
use crate::registry::{StageContract, StageExecution, StageRegistry};
use crate::remote::RemoteStageConnectionManager;
use crate::remote_runner::{
    process_remote_stage, RemoteStageBatch, RemoteStageCall, RemoteStageInput,
    RemoteStageItemFailure, RemoteStageOutput, RemoteStageRunOutcome,
};

pub type ProcessExceptionBatchStream =
    Pin<Box<dyn Stream<Item = Result<ApiBatchResult, Status>> + Send>>;

#[derive(Debug, Clone)]
pub struct PipelineLimits {
    pub max_batch_events: usize,
}

impl Default for PipelineLimits {
    fn default() -> Self {
        Self {
            max_batch_events: 500,
        }
    }
}

#[derive(Debug)]
pub struct CymbalPipelineService {
    registry: StageRegistry,
    remote_connections: Option<RemoteStageConnectionManager>,
    limits: PipelineLimits,
    in_flight: InFlightBatchTracker,
    stages: cymbal_pipeline::DefaultPipelineStages,
}

impl CymbalPipelineService {
    pub fn new() -> Self {
        Self::with_registry(StageRegistry::local_default())
    }

    pub fn with_registry(registry: StageRegistry) -> Self {
        Self {
            registry,
            remote_connections: None,
            limits: PipelineLimits::default(),
            in_flight: InFlightBatchTracker::default(),
            stages: cymbal_pipeline::DefaultPipelineStages::default(),
        }
    }

    pub fn with_remote_connections(
        mut self,
        remote_connections: RemoteStageConnectionManager,
    ) -> Self {
        self.remote_connections = Some(remote_connections);
        self
    }

    pub fn with_limits(mut self, limits: PipelineLimits) -> Self {
        self.limits = limits;
        self
    }

    pub fn with_in_flight_tracker(mut self, in_flight: InFlightBatchTracker) -> Self {
        self.in_flight = in_flight;
        self
    }

    pub fn with_runtime_stages(mut self, stages: RuntimeStages) -> Self {
        self.stages = PipelineStages {
            resolution: stages.resolution,
            grouping: stages.grouping,
            linking: stages.linking,
            alerting: stages.alerting,
        };
        self
    }

    fn build_pipeline_executors(&self) -> Result<PipelineExecutors, Status> {
        Ok(PipelineExecutors {
            resolution: self.resolution_executor()?,
            grouping: self.grouping_executor()?,
            linking: self.linking_executor()?,
            alerting: self.alerting_executor()?,
        })
    }

    fn resolution_executor(
        &self,
    ) -> Result<Arc<dyn StageExecutor<InputEvent, IntermediateStageOutput<ResolvedEvent>>>, Status>
    {
        let contract = self.stage_contract(RESOLUTION_STAGE_ID)?;
        Ok(match contract.execution.clone() {
            StageExecution::Local => Arc::new(MeteredLocalExecutor::new(
                RESOLUTION_STAGE_ID,
                StageExecutionKind::Local,
                ContinueExecutor::new(LocalExecutor::new(self.stages.resolution.clone())),
                intermediate_counts,
            )),
            StageExecution::Remote { target_name } => Arc::new(RemoteIntermediateExecutor::new(
                self.remote_connections.clone(),
                target_name,
                contract,
                RESOLUTION_STAGE_ID,
                InputEvent::TYPE,
                ResolvedEvent::TYPE,
            )),
        })
    }

    fn grouping_executor(
        &self,
    ) -> Result<Arc<dyn StageExecutor<ResolvedEvent, IntermediateStageOutput<GroupedEvent>>>, Status>
    {
        let contract = self.stage_contract(GROUPING_STAGE_ID)?;
        Ok(match contract.execution.clone() {
            StageExecution::Local => Arc::new(MeteredLocalExecutor::new(
                GROUPING_STAGE_ID,
                StageExecutionKind::Local,
                ContinueExecutor::new(LocalExecutor::new(self.stages.grouping.clone())),
                intermediate_counts,
            )),
            StageExecution::Remote { target_name } => Arc::new(RemoteIntermediateExecutor::new(
                self.remote_connections.clone(),
                target_name,
                contract,
                GROUPING_STAGE_ID,
                ResolvedEvent::TYPE,
                GroupedEvent::TYPE,
            )),
        })
    }

    fn linking_executor(
        &self,
    ) -> Result<Arc<dyn StageExecutor<GroupedEvent, DomainEventResult>>, Status> {
        let contract = self.stage_contract(LINKING_STAGE_ID)?;
        Ok(match contract.execution.clone() {
            StageExecution::Local => Arc::new(MeteredLocalExecutor::new(
                LINKING_STAGE_ID,
                StageExecutionKind::Local,
                LocalExecutor::new(self.stages.linking.clone()),
                StageItemCounts::from_event_results,
            )),
            StageExecution::Remote { target_name } => Arc::new(RemoteTerminalExecutor::new(
                self.remote_connections.clone(),
                target_name,
                contract,
                LINKING_STAGE_ID,
                GroupedEvent::TYPE,
                DomainEventResult::TYPE,
            )),
        })
    }

    fn alerting_executor(
        &self,
    ) -> Result<Arc<dyn StageExecutor<AlertingEvent, DomainEventResult>>, Status> {
        let contract = self.stage_contract(ALERTING_STAGE_ID)?;
        Ok(match contract.execution.clone() {
            StageExecution::Local => Arc::new(MeteredLocalExecutor::new(
                ALERTING_STAGE_ID,
                StageExecutionKind::Local,
                LocalExecutor::new(self.stages.alerting.clone()),
                StageItemCounts::from_event_results,
            )),
            StageExecution::Remote { target_name } => Arc::new(RemoteTerminalExecutor::new(
                self.remote_connections.clone(),
                target_name,
                contract,
                ALERTING_STAGE_ID,
                AlertingEvent::TYPE,
                DomainEventResult::TYPE,
            )),
        })
    }

    fn stage_contract(&self, stage_id: &str) -> Result<StageContract, Status> {
        self.registry
            .contract(stage_id)
            .cloned()
            .map_err(|error| Status::invalid_argument(error.to_string()))
    }
}

impl Default for CymbalPipelineService {
    fn default() -> Self {
        Self::new()
    }
}

#[tonic::async_trait]
impl CymbalIngestion for CymbalPipelineService {
    type ProcessExceptionBatchStream = ProcessExceptionBatchStream;

    async fn process_exception_batch(
        &self,
        request: Request<ProcessExceptionBatchRequest>,
    ) -> Result<Response<Self::ProcessExceptionBatchStream>, Status> {
        let started_at = Instant::now();
        let request = request.into_inner();
        let event_count = request.events.len();
        let batch_id = request
            .context
            .as_ref()
            .map_or("", |context| context.batch_id.as_str())
            .to_string();
        tracing::info!(
            batch_id = %batch_id,
            events = event_count,
            "cymbal batch received"
        );
        let in_flight_guard = self.in_flight.try_acquire("pipeline").map_err(|error| {
            tracing::warn!(
                batch_id = %batch_id,
                events = event_count,
                current = error.current,
                max = error.max,
                "rejecting Cymbal batch because too many batches are already in flight"
            );
            Status::resource_exhausted(error.to_string())
        })?;
        if event_count > self.limits.max_batch_events {
            tracing::info!(
                batch_id = %batch_id,
                events = event_count,
                max_events = self.limits.max_batch_events,
                duration_ms = started_at.elapsed().as_millis(),
                status = "rejected",
                "cymbal batch finished"
            );
            record_pipeline_batch(event_count, started_at.elapsed(), "rejected");
            return Err(Status::resource_exhausted(format!(
                "batch has {} events, maximum is {}",
                event_count, self.limits.max_batch_events
            )));
        }
        if let Err(error) = self
            .registry
            .validate_pipeline(&StageRegistry::default_pipeline_stage_ids())
        {
            tracing::info!(
                batch_id = %batch_id,
                events = event_count,
                duration_ms = started_at.elapsed().as_millis(),
                status = "error",
                error = %error,
                "cymbal batch finished"
            );
            record_pipeline_batch(event_count, started_at.elapsed(), "error");
            return Err(Status::invalid_argument(error.to_string()));
        }

        let input_event_ids = request
            .events
            .iter()
            .map(|event| event.event_id.clone())
            .collect::<Vec<_>>();
        let converted = request_to_stage_input(request);
        let input = converted.input;
        let context = input.context.clone();
        let context_batch_id = context.batch_id.clone();
        let input_events = input.items;
        let team_id_by_event_id: HashMap<String, i64> = input_events
            .iter()
            .map(|event| (event.event_id.clone(), event.team_id))
            .collect();

        let executors = self.build_pipeline_executors()?;
        let (sender, receiver) = mpsc::channel(16);
        let stream = stream::unfold(receiver, |mut receiver| async {
            receiver.recv().await.map(|item| (item, receiver))
        });

        tokio::spawn(async move {
            let _in_flight_guard = in_flight_guard;
            let mut sink = OrderedApiResultSink::new(input_event_ids, sender);
            let initial_emit_result = sink.emit_many(converted.terminal_results).await;
            let pipeline_result = match initial_emit_result {
                Ok(()) => {
                    process_exception_pipeline_streaming(
                        context,
                        input_events,
                        &executors,
                        StreamingPipelineOptions::default(),
                        &mut sink,
                    )
                    .await
                }
                Err(error) => Err(error),
            };

            match pipeline_result.and_then(|()| sink.finish()) {
                Ok(()) => {
                    let event_results = sink.event_results();
                    log_sampled_item_failures(
                        &context_batch_id,
                        &team_id_by_event_id,
                        event_results,
                    );
                    tracing::info!(
                        batch_id = %context_batch_id,
                        events = event_count,
                        results = event_results.len(),
                        duration_ms = started_at.elapsed().as_millis(),
                        status = "ok",
                        "cymbal batch finished"
                    );
                    record_pipeline_batch(event_count, started_at.elapsed(), "ok");
                }
                Err(error) => {
                    let status = stage_error_to_status(error);
                    tracing::info!(
                        batch_id = %context_batch_id,
                        events = event_count,
                        duration_ms = started_at.elapsed().as_millis(),
                        status = "error",
                        error = %status,
                        "cymbal batch finished"
                    );
                    drop(sink.send_status(status).await);
                    record_pipeline_batch(event_count, started_at.elapsed(), "error");
                }
            }
        });

        Ok(Response::new(Box::pin(stream)))
    }
}

struct OrderedApiResultSink {
    input_event_ids: Vec<String>,
    input_index_by_event_id: HashMap<String, usize>,
    next_ordered_index: usize,
    buffered_results: HashMap<usize, DomainEventResult>,
    sent_results: Vec<DomainEventResult>,
    sender: mpsc::Sender<Result<ApiBatchResult, Status>>,
}

impl OrderedApiResultSink {
    fn new(
        input_event_ids: Vec<String>,
        sender: mpsc::Sender<Result<ApiBatchResult, Status>>,
    ) -> Self {
        let input_index_by_event_id = input_event_ids
            .iter()
            .enumerate()
            .map(|(index, event_id)| (event_id.clone(), index))
            .collect();
        Self {
            input_event_ids,
            input_index_by_event_id,
            next_ordered_index: 0,
            buffered_results: HashMap::new(),
            sent_results: Vec::new(),
            sender,
        }
    }

    async fn emit_many(&mut self, results: Vec<DomainEventResult>) -> Result<(), StageError> {
        for result in results {
            self.emit(result).await?;
        }
        Ok(())
    }

    async fn send_status(&mut self, status: Status) -> Result<(), StageError> {
        self.sender
            .send(Err(status))
            .await
            .map_err(|_| StageError::Internal("response stream receiver dropped".to_string()))
    }

    fn event_results(&self) -> &[DomainEventResult] {
        &self.sent_results
    }

    fn finish(&self) -> Result<(), StageError> {
        if self.sent_results.len() != self.input_event_ids.len() {
            return Err(StageError::Internal(format!(
                "pipeline emitted {} results for {} input events",
                self.sent_results.len(),
                self.input_event_ids.len()
            )));
        }
        if !self.buffered_results.is_empty() {
            return Err(StageError::Internal(
                "pipeline buffered out-of-order public results that could not be emitted"
                    .to_string(),
            ));
        }
        Ok(())
    }
}

#[async_trait]
impl Sink<DomainEventResult> for OrderedApiResultSink {
    async fn emit(&mut self, result: DomainEventResult) -> Result<(), StageError> {
        let event_id = result.event_id.clone();
        let Some(index) = self.input_index_by_event_id.get(&event_id).copied() else {
            return Err(StageError::Internal(format!(
                "pipeline produced result for unknown event {event_id}"
            )));
        };
        if self.buffered_results.insert(index, result).is_some()
            || self
                .sent_results
                .iter()
                .any(|sent_result| sent_result.event_id == event_id)
        {
            return Err(StageError::Internal(format!(
                "pipeline produced duplicate result for event {event_id}"
            )));
        }

        while let Some(result) = self.buffered_results.remove(&self.next_ordered_index) {
            self.next_ordered_index += 1;
            self.sender
                .send(Ok(domain_event_result_to_api(result.clone())))
                .await
                .map_err(|_| {
                    StageError::Internal("response stream receiver dropped".to_string())
                })?;
            self.sent_results.push(result);
        }

        Ok(())
    }
}

struct MeteredLocalExecutor<I, O, Executor> {
    stage_id: &'static str,
    execution_kind: StageExecutionKind<'static>,
    inner: Executor,
    count_outputs: fn(&[O]) -> StageItemCounts,
    _input: std::marker::PhantomData<I>,
}

impl<I, O, Executor> MeteredLocalExecutor<I, O, Executor> {
    fn new(
        stage_id: &'static str,
        execution_kind: StageExecutionKind<'static>,
        inner: Executor,
        count_outputs: fn(&[O]) -> StageItemCounts,
    ) -> Self {
        Self {
            stage_id,
            execution_kind,
            inner,
            count_outputs,
            _input: std::marker::PhantomData,
        }
    }
}

#[async_trait]
impl<I, O, Executor> StageExecutor<I, O> for MeteredLocalExecutor<I, O, Executor>
where
    I: Send + Sync + 'static,
    O: Send + Sync + 'static,
    Executor: StageExecutor<I, O> + Send + Sync,
{
    async fn run(&self, ctx: Arc<BatchContext>, inputs: Vec<I>) -> Result<Vec<O>, StageError> {
        let batch_id = ctx.batch_id.clone();
        let input_count = inputs.len();
        let count_outputs = self.count_outputs;
        metered_stage(
            self.stage_id,
            self.execution_kind,
            &batch_id,
            input_count,
            async move {
                let outputs = self.inner.run(ctx, inputs).await?;
                let counts = count_outputs(&outputs);
                Ok(MeteredStageResult {
                    value: outputs,
                    outcome: StageOutcomeLabel::Ok,
                    counts,
                })
            },
        )
        .await
    }
}

struct RemoteIntermediateExecutor<I, O> {
    remote_connections: Option<RemoteStageConnectionManager>,
    target_name: String,
    contract: StageContract,
    stage_id: &'static str,
    input_type: cymbal_core::StageType,
    output_type: cymbal_core::StageType,
    _types: std::marker::PhantomData<(I, O)>,
}

impl<I, O> RemoteIntermediateExecutor<I, O> {
    fn new(
        remote_connections: Option<RemoteStageConnectionManager>,
        target_name: String,
        contract: StageContract,
        stage_id: &'static str,
        input_type: cymbal_core::StageType,
        output_type: cymbal_core::StageType,
    ) -> Self {
        Self {
            remote_connections,
            target_name,
            contract,
            stage_id,
            input_type,
            output_type,
            _types: std::marker::PhantomData,
        }
    }
}

#[async_trait]
impl<I, O> StageExecutor<I, IntermediateStageOutput<O>> for RemoteIntermediateExecutor<I, O>
where
    I: RemoteStageInput + Send + Sync + 'static,
    O: serde::de::DeserializeOwned + StagePayload + RemoteStageOutput + Send + Sync + 'static,
{
    async fn run(
        &self,
        ctx: Arc<BatchContext>,
        inputs: Vec<I>,
    ) -> Result<Vec<IntermediateStageOutput<O>>, StageError> {
        let batch_id = ctx.batch_id.clone();
        let input_count = inputs.len();
        let target_name = self.target_name.clone();
        metered_stage(
            self.stage_id,
            StageExecutionKind::Remote {
                target: &self.target_name,
            },
            &batch_id,
            input_count,
            async move {
                let RemoteStageBatch {
                    items,
                    failures,
                    outcome,
                } = process_remote_stage::<I, O>(
                    RemoteStageCall {
                        remote_connections: self.remote_connections.as_ref(),
                        target_name: &target_name,
                        stage_id: self.stage_id,
                        input_type: self.input_type,
                        output_type: self.output_type,
                        retryable_on_transient_failure: self
                            .contract
                            .retryable_on_transient_failure,
                    },
                    (*ctx).clone(),
                    inputs,
                )
                .await
                .map_err(status_to_stage_error)?;
                let mut outputs = items
                    .into_iter()
                    .map(IntermediateStageOutput::Continue)
                    .collect::<Vec<_>>();
                outputs.extend(
                    failures_to_event_results(failures)
                        .into_iter()
                        .map(IntermediateStageOutput::Terminal),
                );
                let counts = intermediate_counts(&outputs);
                Ok(MeteredStageResult {
                    value: outputs,
                    outcome: remote_outcome_label(outcome),
                    counts,
                })
            },
        )
        .await
    }
}

struct RemoteTerminalExecutor<I> {
    remote_connections: Option<RemoteStageConnectionManager>,
    target_name: String,
    contract: StageContract,
    stage_id: &'static str,
    input_type: cymbal_core::StageType,
    output_type: cymbal_core::StageType,
    _input: std::marker::PhantomData<I>,
}

impl<I> RemoteTerminalExecutor<I> {
    fn new(
        remote_connections: Option<RemoteStageConnectionManager>,
        target_name: String,
        contract: StageContract,
        stage_id: &'static str,
        input_type: cymbal_core::StageType,
        output_type: cymbal_core::StageType,
    ) -> Self {
        Self {
            remote_connections,
            target_name,
            contract,
            stage_id,
            input_type,
            output_type,
            _input: std::marker::PhantomData,
        }
    }
}

#[async_trait]
impl<I> StageExecutor<I, DomainEventResult> for RemoteTerminalExecutor<I>
where
    I: RemoteStageInput + Send + Sync + 'static,
{
    async fn run(
        &self,
        ctx: Arc<BatchContext>,
        inputs: Vec<I>,
    ) -> Result<Vec<DomainEventResult>, StageError> {
        let batch_id = ctx.batch_id.clone();
        let input_count = inputs.len();
        let target_name = self.target_name.clone();
        metered_stage(
            self.stage_id,
            StageExecutionKind::Remote {
                target: &self.target_name,
            },
            &batch_id,
            input_count,
            async move {
                let RemoteStageBatch {
                    items,
                    failures,
                    outcome,
                } = process_remote_stage::<I, DomainEventResult>(
                    RemoteStageCall {
                        remote_connections: self.remote_connections.as_ref(),
                        target_name: &target_name,
                        stage_id: self.stage_id,
                        input_type: self.input_type,
                        output_type: self.output_type,
                        retryable_on_transient_failure: self
                            .contract
                            .retryable_on_transient_failure,
                    },
                    (*ctx).clone(),
                    inputs,
                )
                .await
                .map_err(status_to_stage_error)?;
                let mut results = items;
                results.extend(failures_to_event_results(failures));
                let counts = StageItemCounts::from_event_results(&results);
                Ok(MeteredStageResult {
                    value: results,
                    outcome: remote_outcome_label(outcome),
                    counts,
                })
            },
        )
        .await
    }
}

impl RemoteStageInput for InputEvent {
    fn stage_item_id(&self) -> &str {
        &self.event_id
    }

    fn routing_key(&self, stage_id: &str) -> RoutingKey {
        match stage_id {
            RESOLUTION_STAGE_ID => resolution_routing_key(self),
            _ => RoutingKey::team_id(self.team_id),
        }
    }
}

impl RemoteStageInput for ResolvedEvent {
    fn stage_item_id(&self) -> &str {
        &self.event_id
    }

    fn routing_key(&self, _stage_id: &str) -> RoutingKey {
        RoutingKey::team_id(self.team_id)
    }
}

impl RemoteStageInput for GroupedEvent {
    fn stage_item_id(&self) -> &str {
        &self.event_id
    }

    fn routing_key(&self, _stage_id: &str) -> RoutingKey {
        RoutingKey::team_id(self.team_id)
    }
}

impl RemoteStageInput for AlertingEvent {
    fn stage_item_id(&self) -> &str {
        &self.result.event_id
    }

    fn routing_key(&self, _stage_id: &str) -> RoutingKey {
        self.spike_alert_input
            .as_ref()
            .map(|input| RoutingKey::team_id(input.issue.team_id as i64))
            .unwrap_or_else(RoutingKey::no_affinity)
    }
}

impl RemoteStageOutput for ResolvedEvent {
    fn stage_item_id(&self) -> &str {
        &self.event_id
    }
}

impl RemoteStageOutput for GroupedEvent {
    fn stage_item_id(&self) -> &str {
        &self.event_id
    }
}

impl RemoteStageOutput for DomainEventResult {
    fn stage_item_id(&self) -> &str {
        &self.event_id
    }
}

fn status_to_stage_error(status: Status) -> StageError {
    match status.code() {
        tonic::Code::InvalidArgument => StageError::InvalidInput(status.message().to_string()),
        tonic::Code::Unavailable | tonic::Code::DeadlineExceeded => {
            StageError::Transient(status.message().to_string())
        }
        _ => StageError::Internal(status.message().to_string()),
    }
}

fn remote_outcome_label(outcome: RemoteStageRunOutcome) -> StageOutcomeLabel {
    match outcome {
        RemoteStageRunOutcome::Ok => StageOutcomeLabel::Ok,
        RemoteStageRunOutcome::Timeout => StageOutcomeLabel::Timeout,
        RemoteStageRunOutcome::TransportError => StageOutcomeLabel::Error,
    }
}

fn intermediate_counts<T>(outputs: &[IntermediateStageOutput<T>]) -> StageItemCounts {
    let mut counts = StageItemCounts::default();
    for output in outputs {
        match output {
            IntermediateStageOutput::Continue(_) => counts.success += 1,
            IntermediateStageOutput::Terminal(result) => match &result.outcome {
                EventOutcome::Next { .. } => counts.success += 1,
                EventOutcome::Drop { .. } => counts.drop += 1,
                EventOutcome::Retry { .. } => counts.retry += 1,
                EventOutcome::Error { .. } => counts.error += 1,
            },
        }
    }
    counts
}

fn failures_to_event_results(failures: Vec<RemoteStageItemFailure>) -> Vec<DomainEventResult> {
    failures
        .into_iter()
        .map(|failure| DomainEventResult {
            event_id: failure.item_id,
            outcome: if failure.retryable {
                EventOutcome::Retry {
                    reason: failure.message,
                    retry_after_ms: failure.retry_after_ms,
                }
            } else {
                EventOutcome::Error {
                    message: failure.message,
                    code: Some("remote_stage_item_failed".to_string()),
                    retryable: Some(false),
                }
            },
        })
        .collect()
}

fn log_sampled_item_failures(
    batch_id: &str,
    team_id_by_event_id: &HashMap<String, i64>,
    results: &[DomainEventResult],
) {
    for result in results {
        match &result.outcome {
            EventOutcome::Retry { reason, .. } => {
                if should_log_item_failure() {
                    tracing::warn!(
                        event_id = %result.event_id,
                        team_id = ?team_id_by_event_id.get(&result.event_id).copied(),
                        batch_id,
                        outcome = "retry",
                        error = %reason,
                        sample_rate = crate::observability::ITEM_LOG_SAMPLE_RATE,
                        "cymbal per-item failure (sampled)"
                    );
                }
            }
            EventOutcome::Error { message, code, .. } => {
                if should_log_item_failure() {
                    tracing::warn!(
                        event_id = %result.event_id,
                        team_id = ?team_id_by_event_id.get(&result.event_id).copied(),
                        batch_id,
                        outcome = "error",
                        error = %message,
                        code = code.as_deref(),
                        sample_rate = crate::observability::ITEM_LOG_SAMPLE_RATE,
                        "cymbal per-item failure (sampled)"
                    );
                }
            }
            EventOutcome::Next { .. } | EventOutcome::Drop { .. } => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use cymbal_api::cymbal::v1::{
        process_exception_batch_result, ExceptionEvent, ProcessExceptionBatchRequest,
        ProcessExceptionBatchResult,
    };
    use cymbal_core::Metadata;
    use cymbal_domain::{ExceptionProperties, MISSING_TEAM_ID_DROP_REASON};
    use futures::TryStreamExt;
    use metrics_util::debugging::{DebugValue, DebuggingRecorder};
    use serde_json::{json, Value};

    use super::*;
    use cymbal_core::routing::RoutingCacheKeyKind;

    fn request_for_event_ids(event_ids: &[&str]) -> ProcessExceptionBatchRequest {
        ProcessExceptionBatchRequest {
            context: None,
            events: event_ids
                .iter()
                .map(|event_id| ExceptionEvent {
                    event_id: (*event_id).to_string(),
                    team_id: 2,
                    distinct_id: format!("distinct-{event_id}"),
                    timestamp: None,
                    properties_json: br#"{"event":"$exception"}"#.to_vec(),
                })
                .collect(),
            options: None,
        }
    }

    fn routing_input_event(properties: Value) -> InputEvent {
        InputEvent {
            event_id: "event-1".to_string(),
            team_id: 2,
            properties: ExceptionProperties::from_map(properties.as_object().unwrap().clone())
                .unwrap(),
        }
    }

    #[test]
    fn resolution_routing_key_prefers_debug_image_ids() {
        let event = routing_input_event(json!({
            "$debug_images": [{ "debug_id": "debug-image-1" }],
            "$exception_list": [{
                "stacktrace": { "frames": [{ "chunkId": "chunk-1" }] }
            }]
        }));

        assert_eq!(
            event.routing_key(RESOLUTION_STAGE_ID),
            RoutingKey::StageCache {
                kind: RoutingCacheKeyKind::DebugImageId,
                value: "team_id:2:debug-image-1".to_string(),
            }
        );
    }

    #[test]
    fn resolution_routing_key_uses_sourcemap_symbol_refs_before_team_id() {
        let event = routing_input_event(json!({
            "$exception_list": [{
                "stacktrace": { "frames": [{ "filename": "app.min.js", "chunkId": "chunk-1" }] }
            }]
        }));

        assert_eq!(
            event.routing_key(RESOLUTION_STAGE_ID),
            RoutingKey::StageCache {
                kind: RoutingCacheKeyKind::SymbolSetRef,
                value: "team_id:2:chunk-1".to_string(),
            }
        );
    }

    #[test]
    fn resolution_routing_key_falls_back_to_team_id_without_cache_refs() {
        let event = routing_input_event(json!({
            "$exception_list": [{
                "stacktrace": { "frames": [{ "filename": "app.py" }] }
            }]
        }));

        assert_eq!(
            event.routing_key(RESOLUTION_STAGE_ID),
            RoutingKey::StageCache {
                kind: RoutingCacheKeyKind::ReleaseSource,
                value: "team_id:2:source:app.py".to_string(),
            }
        );

        let event = routing_input_event(json!({ "event": "$exception" }));
        assert_eq!(
            event.routing_key(RESOLUTION_STAGE_ID),
            RoutingKey::TeamId(2)
        );
    }

    #[test]
    fn remote_stage_inputs_default_to_team_id_when_available() {
        let input = routing_input_event(json!({ "event": "$exception" }));
        let resolved = ResolvedEvent {
            event_id: "event-1".to_string(),
            team_id: 2,
            properties: ExceptionProperties::default(),
            metadata: Metadata::new(),
        };
        let grouped = GroupedEvent {
            event_id: "event-1".to_string(),
            team_id: 2,
            properties: ExceptionProperties::default(),
            metadata: Metadata::new(),
        };

        assert_eq!(
            input.routing_key(RESOLUTION_STAGE_ID),
            RoutingKey::TeamId(2)
        );
        assert_eq!(
            resolved.routing_key(GROUPING_STAGE_ID),
            RoutingKey::TeamId(2)
        );
        assert_eq!(grouped.routing_key(LINKING_STAGE_ID), RoutingKey::TeamId(2));
    }

    async fn process_with_service(
        service: &CymbalPipelineService,
        request: ProcessExceptionBatchRequest,
    ) -> Vec<ProcessExceptionBatchResult> {
        service
            .process_exception_batch(Request::new(request))
            .await
            .unwrap()
            .into_inner()
            .try_collect()
            .await
            .unwrap()
    }

    #[tokio::test]
    async fn process_exception_batch_returns_next_for_each_input_event() {
        let service = CymbalPipelineService::new();
        let request = ProcessExceptionBatchRequest {
            context: None,
            events: vec![ExceptionEvent {
                event_id: "event-1".to_string(),
                team_id: 2,
                distinct_id: "distinct-1".to_string(),
                timestamp: None,
                properties_json: br#"{"event":"$exception"}"#.to_vec(),
            }],
            options: None,
        };

        let response = service
            .process_exception_batch(Request::new(request))
            .await
            .unwrap();
        let results: Vec<ProcessExceptionBatchResult> =
            response.into_inner().try_collect().await.unwrap();

        assert_eq!(results.len(), 1);
        assert_eq!(results[0].event_id, "event-1");
        assert!(matches!(
            results[0].outcome,
            Some(process_exception_batch_result::Outcome::Next(_))
        ));
    }

    #[tokio::test]
    async fn process_exception_batch_rejects_when_in_flight_limit_is_reached() {
        let tracker = InFlightBatchTracker::standalone(1);
        let _guard = tracker.try_acquire("test").unwrap();
        let service = CymbalPipelineService::new().with_in_flight_tracker(tracker);

        let status = match service
            .process_exception_batch(Request::new(request_for_event_ids(&["event-1"])))
            .await
        {
            Ok(_) => panic!("expected resource exhausted"),
            Err(status) => status,
        };

        assert_eq!(status.code(), tonic::Code::ResourceExhausted);
        assert_eq!(service.in_flight.current(), 1);
    }

    #[tokio::test]
    async fn process_exception_batch_rejects_oversized_batches_without_leaking_in_flight_guard() {
        let tracker = InFlightBatchTracker::standalone(1);
        let service = CymbalPipelineService::new()
            .with_in_flight_tracker(tracker.clone())
            .with_limits(PipelineLimits {
                max_batch_events: 1,
            });
        let status = match service
            .process_exception_batch(Request::new(request_for_event_ids(&["event-1", "event-2"])))
            .await
        {
            Ok(_) => panic!("expected resource exhausted"),
            Err(status) => status,
        };

        assert_eq!(status.code(), tonic::Code::ResourceExhausted);
        assert_eq!(tracker.current(), 0);

        let results = process_with_service(&service, request_for_event_ids(&["event-3"])).await;

        assert_eq!(results.len(), 1);
        assert_eq!(results[0].event_id, "event-3");
        assert_eq!(tracker.current(), 0);
    }

    #[tokio::test]
    async fn process_exception_batch_drops_events_missing_team_id_at_boundary() {
        let service = CymbalPipelineService::new();
        let mut request = request_for_event_ids(&["missing-team", "valid-team"]);
        request.events[0].team_id = 0;

        let results = process_with_service(&service, request).await;

        assert_eq!(results.len(), 2);
        assert_eq!(results[0].event_id, "missing-team");
        assert!(matches!(
            results[0].outcome,
            Some(process_exception_batch_result::Outcome::Drop(ref drop))
                if drop.reason == MISSING_TEAM_ID_DROP_REASON
        ));
        assert_eq!(results[1].event_id, "valid-team");
        assert!(matches!(
            results[1].outcome,
            Some(process_exception_batch_result::Outcome::Next(_))
        ));
    }

    /// Snapshot test that verifies the orchestrator emits each of the
    /// per-stage and per-batch metric names defined in
    /// `crate::observability`. Acts as a regression target so future
    /// pipeline edits cannot silently drop a stage metric.
    ///
    /// `metrics::with_local_recorder` is sync, so we drive the async
    /// pipeline through an explicit current-thread tokio runtime instead of
    /// `#[tokio::test]` (which would prevent constructing a nested runtime).
    #[test]
    fn process_exception_batch_emits_uniform_stage_metrics() {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        metrics::with_local_recorder(&recorder, || {
            runtime.block_on(async {
                let service = CymbalPipelineService::new();
                let _results =
                    process_with_service(&service, request_for_event_ids(&["event-1", "event-2"]))
                        .await;
            });
        });

        let snapshot = snapshotter.snapshot().into_vec();
        let metric_names = snapshot
            .iter()
            .map(|(ckey, _, _, _)| ckey.key().name().to_string())
            .collect::<std::collections::BTreeSet<_>>();

        for expected in [
            crate::observability::STAGE_BATCH_SIZE,
            crate::observability::STAGE_DURATION,
            crate::observability::STAGE_ITEMS,
            crate::observability::PIPELINE_BATCH_DURATION,
            crate::observability::PIPELINE_BATCH_EVENTS,
        ] {
            assert!(
                metric_names.contains(expected),
                "expected metric {expected} to be emitted, got {:?}",
                metric_names
            );
        }

        // Each pipeline stage should have at least one stage-duration sample
        // labelled `execution="local"`. This catches a regression where a
        // newly added stage forgets to go through `metered_stage`.
        let local_duration_stages = snapshot
            .iter()
            .filter(|(ckey, _, _, _)| ckey.key().name() == crate::observability::STAGE_DURATION)
            .filter(|(ckey, _, _, _)| {
                ckey.key()
                    .labels()
                    .any(|label| label.key() == "execution" && label.value() == "local")
            })
            .filter_map(|(ckey, _, _, _)| {
                ckey.key()
                    .labels()
                    .find(|label| label.key() == "stage")
                    .map(|label| label.value().to_string())
            })
            .collect::<std::collections::BTreeSet<_>>();

        for expected_stage in [
            RESOLUTION_STAGE_ID,
            GROUPING_STAGE_ID,
            LINKING_STAGE_ID,
            ALERTING_STAGE_ID,
        ] {
            assert!(
                local_duration_stages.contains(expected_stage),
                "expected `local` duration sample for stage {expected_stage}, got {:?}",
                local_duration_stages
            );
        }

        // Sanity: there should be at least one success counter for the
        // resolution stage with execution=local.
        let has_resolution_success = snapshot.iter().any(|(ckey, _, _, value)| {
            ckey.key().name() == crate::observability::STAGE_ITEMS
                && ckey
                    .key()
                    .labels()
                    .any(|label| label.key() == "stage" && label.value() == RESOLUTION_STAGE_ID)
                && ckey
                    .key()
                    .labels()
                    .any(|label| label.key() == "execution" && label.value() == "local")
                && ckey
                    .key()
                    .labels()
                    .any(|label| label.key() == "outcome" && label.value() == "success")
                && matches!(value, DebugValue::Counter(n) if *n >= 1)
        });
        assert!(
            has_resolution_success,
            "expected resolution success counter, snapshot: {:?}",
            snapshot
        );
    }
}
