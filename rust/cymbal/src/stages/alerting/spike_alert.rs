use std::{
    collections::{hash_map::Entry, HashMap},
    sync::Arc,
};

use uuid::Uuid;

use crate::{
    app_context::AppContext,
    issue_resolution::Issue,
    metric_consts::SPIKE_ALERT_STAGE,
    stages::{alerting::spike_detection::do_spike_detection, pipeline::ExceptionEventPipelineItem},
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
        OutputErrProps,
    },
};

use tracing::error;

#[derive(Clone)]
pub struct SpikeAlertStage {
    context: Arc<AppContext>,
}

impl SpikeAlertStage {
    pub fn new(context: Arc<AppContext>) -> Self {
        Self { context }
    }
}

impl Stage for SpikeAlertStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;

    fn name(&self) -> &'static str {
        SPIKE_ALERT_STAGE
    }

    async fn process(self, batch: Batch<ExceptionEventPipelineItem>) -> StageResult<Self> {
        let mut issues: Vec<Issue> = Vec::new();
        let mut issue_props_by_id: HashMap<Uuid, OutputErrProps> = HashMap::new();

        for res in batch.inner_ref() {
            let Ok(evt) = res else { continue };
            let Some(issue) = &evt.issue else {
                error!("no issue associated with event");
                continue;
            };
            // Keep one OutputErrProps per issue (they share the same stack shape)
            if let Entry::Vacant(e) = issue_props_by_id.entry(issue.id) {
                if let Ok(props) = evt.to_output(issue.id) {
                    e.insert(props);
                }
            }
            issues.push(issue.clone());
        }

        let issues_count_by_id: HashMap<Uuid, u32> =
            issues.iter().fold(HashMap::new(), |mut acc, issue| {
                *acc.entry(issue.id).or_insert(0) += 1;
                acc
            });

        let issues_by_id = issues
            .into_iter()
            .map(|issue| (issue.id, issue))
            .collect::<HashMap<_, _>>();

        do_spike_detection(
            self.context,
            issues_by_id,
            issue_props_by_id,
            issues_count_by_id,
        )
        .await?;

        Ok(batch)
    }
}
