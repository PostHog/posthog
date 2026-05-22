use std::{collections::HashMap, sync::Arc};

pub mod spike_alert;
pub mod spike_detection;

use uuid::Uuid;

use crate::{
    app_context::AppContext,
    issue_resolution::Issue,
    metric_consts::ALERTING_STAGE,
    stages::{
        alerting::{spike_alert::SpikeAlertStage, spike_detection::do_spike_detection},
        pipeline::ExceptionEventPipelineItem,
    },
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
        OutputErrProps,
    },
};

/// One successfully-linked event candidate for spike detection.
#[derive(Clone)]
pub struct SpikeAlertInput {
    pub issue: Issue,
    pub props: Option<OutputErrProps>,
}

pub async fn run_spike_detection_for_inputs(
    ctx: Arc<AppContext>,
    inputs: Vec<SpikeAlertInput>,
) -> Result<(), crate::error::UnhandledError> {
    if inputs.is_empty() {
        return Ok(());
    }

    let mut issues_count_by_id: HashMap<Uuid, u32> = HashMap::new();
    let mut issue_props_by_id: HashMap<Uuid, OutputErrProps> = HashMap::new();
    let mut issues_by_id: HashMap<Uuid, Issue> = HashMap::new();

    for input in inputs {
        let issue_id = input.issue.id;
        *issues_count_by_id.entry(issue_id).or_insert(0) += 1;
        if let Some(props) = input.props {
            issue_props_by_id.entry(issue_id).or_insert(props);
        }
        issues_by_id.insert(issue_id, input.issue);
    }

    do_spike_detection(ctx, issues_by_id, issue_props_by_id, issues_count_by_id).await
}

pub struct AlertingStage {
    context: Arc<AppContext>,
}

impl AlertingStage {
    pub fn new(context: Arc<AppContext>) -> Self {
        Self { context }
    }
}

impl Stage for AlertingStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;

    fn name(&self) -> &'static str {
        ALERTING_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        batch.apply_stage(SpikeAlertStage::new(self.context)).await
    }
}
