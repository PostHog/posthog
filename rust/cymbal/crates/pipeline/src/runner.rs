//! Exception-pipeline adapter for the generic linear runner.
//!
//! The reusable runner lives in `cymbal-core`; this module keeps Cymbal's
//! exception-domain item enum, stage dispatch, and linking-to-alerting adapter
//! in `cymbal-pipeline`.

use std::sync::Arc;

use async_trait::async_trait;
use cymbal_alerting::{AlertingEvent, ALERTING_STAGE_ID, ALERTING_STAGE_TYPE};
use cymbal_core::{
    BatchContext, EmissionOrder, IdentifiedItem, LinearPipelineRunner, LinearPipelineRunnerError,
    LinearPipelineRunnerOptions, LinearPipelineSpec, PipelineItem, Sink, StageBatchOutcome,
    StageDriver, StageEffectMode, StageError, StageLinkRule, StagePayload, StageSpec, StageType,
    TerminalItem, TransientFailurePolicy,
};
use cymbal_domain::{
    EventResult, InputEvent, RateLimitGateOutput, RATE_LIMITING_STAGE_ID, RATE_LIMITING_STAGE_TYPE,
};
use cymbal_grouping::{GroupedEvent, GROUPING_STAGE_ID, GROUPING_STAGE_TYPE};
use cymbal_linking::{LINKING_STAGE_ID, LINKING_STAGE_TYPE};
use cymbal_resolution::{ResolvedEvent, RESOLUTION_STAGE_ID, RESOLUTION_STAGE_TYPE};

use crate::ordering::{
    event_result_to_alerting_event, split_intermediate_outputs, split_rate_limit_outputs,
};
use crate::stage_graph::{CymbalStageProgress, PipelineExecutors};

/// Product-owned item enum used by the generic runner for Cymbal's exception pipeline.
///
/// Terminal [`EventResult`]s stay out of this enum and are emitted through the
/// runner's separate terminal channel.
#[allow(clippy::large_enum_variant)]
pub enum ExceptionPipelineItem {
    Input(InputEvent),
    Resolved(ResolvedEvent),
    Grouped(GroupedEvent),
    Alerting(AlertingEvent),
}

impl IdentifiedItem for ExceptionPipelineItem {
    fn item_id(&self) -> &str {
        match self {
            ExceptionPipelineItem::Input(event) => event.event_id.as_str(),
            ExceptionPipelineItem::Resolved(event) => event.event_id.as_str(),
            ExceptionPipelineItem::Grouped(event) => event.event_id.as_str(),
            ExceptionPipelineItem::Alerting(event) => event.result.event_id.as_str(),
        }
    }
}

impl PipelineItem for ExceptionPipelineItem {
    fn payload_type(&self) -> StageType {
        match self {
            ExceptionPipelineItem::Input(_) => InputEvent::TYPE,
            ExceptionPipelineItem::Resolved(_) => ResolvedEvent::TYPE,
            ExceptionPipelineItem::Grouped(_) => GroupedEvent::TYPE,
            ExceptionPipelineItem::Alerting(_) => AlertingEvent::TYPE,
        }
    }
}

struct ExceptionPipelineTerminal(EventResult);

impl ExceptionPipelineTerminal {
    fn into_result(self) -> EventResult {
        self.0
    }
}

impl IdentifiedItem for ExceptionPipelineTerminal {
    fn item_id(&self) -> &str {
        self.0.event_id.as_str()
    }
}

impl TerminalItem for ExceptionPipelineTerminal {
    fn payload_type(&self) -> StageType {
        EventResult::TYPE
    }
}

/// Stage driver that adapts Cymbal's typed executor bundle to the generic runner.
pub struct ExceptionStageDriver<'a> {
    executors: &'a PipelineExecutors,
}

impl<'a> ExceptionStageDriver<'a> {
    pub fn new(executors: &'a PipelineExecutors) -> Self {
        Self { executors }
    }
}

#[async_trait]
impl StageDriver<ExceptionPipelineItem, ExceptionPipelineTerminal> for ExceptionStageDriver<'_> {
    async fn run_stage(
        &self,
        context: Arc<BatchContext>,
        stage: &StageSpec,
        items: Vec<ExceptionPipelineItem>,
    ) -> Result<StageBatchOutcome<ExceptionPipelineItem, ExceptionPipelineTerminal>, StageError>
    {
        match stage.stage_id.as_str() {
            RATE_LIMITING_STAGE_ID => self.run_rate_limiting(context, items).await,
            RESOLUTION_STAGE_ID => self.run_resolution(context, items).await,
            GROUPING_STAGE_ID => self.run_grouping(context, items).await,
            LINKING_STAGE_ID => self.run_linking(context, items).await,
            ALERTING_STAGE_ID => self.run_alerting(context, items).await,
            stage_id => Err(StageError::Internal(format!(
                "exception pipeline has no executor for stage {stage_id}"
            ))),
        }
    }
}

impl ExceptionStageDriver<'_> {
    async fn run_rate_limiting(
        &self,
        context: Arc<BatchContext>,
        items: Vec<ExceptionPipelineItem>,
    ) -> Result<StageBatchOutcome<ExceptionPipelineItem, ExceptionPipelineTerminal>, StageError>
    {
        let outputs = self
            .executors
            .rate_limiting
            .run(context, into_input_events(RATE_LIMITING_STAGE_ID, items)?)
            .await?;
        let (allowed_events, terminal_results) = split_rate_limit_outputs(outputs);

        Ok(StageBatchOutcome::new(
            allowed_events
                .into_iter()
                .map(ExceptionPipelineItem::Input)
                .collect(),
            terminal_results
                .into_iter()
                .map(ExceptionPipelineTerminal)
                .collect(),
        ))
    }

    async fn run_resolution(
        &self,
        context: Arc<BatchContext>,
        items: Vec<ExceptionPipelineItem>,
    ) -> Result<StageBatchOutcome<ExceptionPipelineItem, ExceptionPipelineTerminal>, StageError>
    {
        let outputs = self
            .executors
            .resolution
            .run(context, into_input_events(RESOLUTION_STAGE_ID, items)?)
            .await?;
        let (resolved_events, terminal_results) = split_intermediate_outputs(outputs);

        Ok(StageBatchOutcome::new(
            resolved_events
                .into_iter()
                .map(ExceptionPipelineItem::Resolved)
                .collect(),
            terminal_results
                .into_iter()
                .map(ExceptionPipelineTerminal)
                .collect(),
        ))
    }

    async fn run_grouping(
        &self,
        context: Arc<BatchContext>,
        items: Vec<ExceptionPipelineItem>,
    ) -> Result<StageBatchOutcome<ExceptionPipelineItem, ExceptionPipelineTerminal>, StageError>
    {
        let outputs = self
            .executors
            .grouping
            .run(context, into_resolved_events(GROUPING_STAGE_ID, items)?)
            .await?;
        let (grouped_events, terminal_results) = split_intermediate_outputs(outputs);

        Ok(StageBatchOutcome::new(
            grouped_events
                .into_iter()
                .map(ExceptionPipelineItem::Grouped)
                .collect(),
            terminal_results
                .into_iter()
                .map(ExceptionPipelineTerminal)
                .collect(),
        ))
    }

    async fn run_linking(
        &self,
        context: Arc<BatchContext>,
        items: Vec<ExceptionPipelineItem>,
    ) -> Result<StageBatchOutcome<ExceptionPipelineItem, ExceptionPipelineTerminal>, StageError>
    {
        let outputs = self
            .executors
            .linking
            .run(context, into_grouped_events(LINKING_STAGE_ID, items)?)
            .await?;

        Ok(StageBatchOutcome::continue_only(
            outputs
                .into_iter()
                .map(event_result_to_alerting_event)
                .map(ExceptionPipelineItem::Alerting)
                .collect(),
        ))
    }

    async fn run_alerting(
        &self,
        context: Arc<BatchContext>,
        items: Vec<ExceptionPipelineItem>,
    ) -> Result<StageBatchOutcome<ExceptionPipelineItem, ExceptionPipelineTerminal>, StageError>
    {
        let outputs = self
            .executors
            .alerting
            .run(context, into_alerting_events(ALERTING_STAGE_ID, items)?)
            .await?;

        Ok(StageBatchOutcome::terminal_only(
            outputs.into_iter().map(ExceptionPipelineTerminal).collect(),
        ))
    }
}

pub(crate) async fn process_exception_pipeline_with_runner(
    context: Arc<BatchContext>,
    input_events: Vec<InputEvent>,
    executors: &PipelineExecutors,
) -> Result<Vec<EventResult>, StageError> {
    let input_items = input_events
        .into_iter()
        .map(ExceptionPipelineItem::Input)
        .collect::<Vec<_>>();
    let driver = ExceptionStageDriver::new(executors);
    let runner = LinearPipelineRunner::new(
        exception_pipeline_spec(CymbalStageProgress::default()),
        driver,
        LinearPipelineRunnerOptions {
            emission_order: EmissionOrder::InputOrder,
        },
    );
    let mut sink = CollectingResultSink::default();

    runner
        .run(context, input_items, &mut sink)
        .await
        .map_err(runner_error_to_stage_error)?;

    Ok(sink.results)
}

fn exception_pipeline_spec(stage_progress: CymbalStageProgress) -> LinearPipelineSpec {
    LinearPipelineSpec {
        input_type: InputEvent::TYPE,
        terminal_type: EventResult::TYPE,
        stages: vec![
            StageSpec {
                stage_id: RATE_LIMITING_STAGE_ID.to_string(),
                stage_type: RATE_LIMITING_STAGE_TYPE,
                input_type: InputEvent::TYPE,
                output_type: RateLimitGateOutput::TYPE,
                progress: stage_progress.rate_limiting,
                effects: StageEffectMode::IdempotentSideEffects,
                transient_failure_policy: TransientFailurePolicy::NotRetryableAfterDispatch,
            },
            StageSpec {
                stage_id: RESOLUTION_STAGE_ID.to_string(),
                stage_type: RESOLUTION_STAGE_TYPE,
                input_type: InputEvent::TYPE,
                output_type: ResolvedEvent::TYPE,
                progress: stage_progress.resolution,
                effects: StageEffectMode::IdempotentSideEffects,
                transient_failure_policy: TransientFailurePolicy::RetryableIfStageDeclaresSafe,
            },
            StageSpec {
                stage_id: GROUPING_STAGE_ID.to_string(),
                stage_type: GROUPING_STAGE_TYPE,
                input_type: ResolvedEvent::TYPE,
                output_type: GroupedEvent::TYPE,
                progress: stage_progress.grouping,
                effects: StageEffectMode::Pure,
                transient_failure_policy: TransientFailurePolicy::RetryableIfStageDeclaresSafe,
            },
            StageSpec {
                stage_id: LINKING_STAGE_ID.to_string(),
                stage_type: LINKING_STAGE_TYPE,
                input_type: GroupedEvent::TYPE,
                // The linking executor still returns EventResult for remote/local contract
                // compatibility; the exception driver immediately wraps those results as
                // AlertingEvent continue items so alerting remains a conservative barrier.
                output_type: AlertingEvent::TYPE,
                progress: stage_progress.linking,
                effects: StageEffectMode::OrderedSideEffects,
                transient_failure_policy: TransientFailurePolicy::RetryableIfStageDeclaresSafe,
            },
            StageSpec {
                stage_id: ALERTING_STAGE_ID.to_string(),
                stage_type: ALERTING_STAGE_TYPE,
                input_type: AlertingEvent::TYPE,
                output_type: EventResult::TYPE,
                progress: stage_progress.alerting,
                effects: StageEffectMode::OrderedSideEffects,
                transient_failure_policy: TransientFailurePolicy::RetryableIfStageDeclaresSafe,
            },
        ],
        allowed_links: vec![
            StageLinkRule::ExactType,
            StageLinkRule::FanOutContinue {
                stage_output_type: RateLimitGateOutput::TYPE,
                next_input_type: InputEvent::TYPE,
                terminal_type: EventResult::TYPE,
            },
        ],
    }
}

#[derive(Default)]
struct CollectingResultSink {
    results: Vec<EventResult>,
}

#[async_trait]
impl Sink<ExceptionPipelineTerminal> for CollectingResultSink {
    async fn emit(&mut self, item: ExceptionPipelineTerminal) -> Result<(), StageError> {
        self.results.push(item.into_result());
        Ok(())
    }
}

fn runner_error_to_stage_error(error: LinearPipelineRunnerError) -> StageError {
    match error {
        LinearPipelineRunnerError::StageFailed { source, .. }
        | LinearPipelineRunnerError::EmissionFailed(source) => source,
        other => StageError::Internal(other.to_string()),
    }
}

fn into_input_events(
    stage_id: &str,
    items: Vec<ExceptionPipelineItem>,
) -> Result<Vec<InputEvent>, StageError> {
    items
        .into_iter()
        .map(|item| match item {
            ExceptionPipelineItem::Input(event) => Ok(event),
            item => Err(unexpected_item_error(stage_id, item.payload_type())),
        })
        .collect()
}

fn into_resolved_events(
    stage_id: &str,
    items: Vec<ExceptionPipelineItem>,
) -> Result<Vec<ResolvedEvent>, StageError> {
    items
        .into_iter()
        .map(|item| match item {
            ExceptionPipelineItem::Resolved(event) => Ok(event),
            item => Err(unexpected_item_error(stage_id, item.payload_type())),
        })
        .collect()
}

fn into_grouped_events(
    stage_id: &str,
    items: Vec<ExceptionPipelineItem>,
) -> Result<Vec<GroupedEvent>, StageError> {
    items
        .into_iter()
        .map(|item| match item {
            ExceptionPipelineItem::Grouped(event) => Ok(event),
            item => Err(unexpected_item_error(stage_id, item.payload_type())),
        })
        .collect()
}

fn into_alerting_events(
    stage_id: &str,
    items: Vec<ExceptionPipelineItem>,
) -> Result<Vec<AlertingEvent>, StageError> {
    items
        .into_iter()
        .map(|item| match item {
            ExceptionPipelineItem::Alerting(event) => Ok(event),
            item => Err(unexpected_item_error(stage_id, item.payload_type())),
        })
        .collect()
}

fn unexpected_item_error(stage_id: &str, actual_type: StageType) -> StageError {
    StageError::Internal(format!(
        "stage {stage_id} received unexpected exception pipeline item type {actual_type}"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exception_pipeline_spec_validates() {
        assert_eq!(
            exception_pipeline_spec(CymbalStageProgress::default()).validate(),
            Ok(())
        );
    }

    #[test]
    fn exception_pipeline_item_reports_payload_type() {
        let event = InputEvent {
            event_id: "event-1".to_string(),
            team_id: 1,
            properties: Default::default(),
        };
        let item = ExceptionPipelineItem::Input(event);

        assert_eq!(item.item_id(), "event-1");
        assert_eq!(item.payload_type(), InputEvent::TYPE);
    }
}
