use std::{collections::HashMap, sync::Arc};

use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::UnhandledError,
    issue_resolution::Issue,
    pipeline::exception::spike_detection::do_spike_detection,
    types::{
        batch::Batch,
        pipeline::ExceptionEventPipelineItem,
        stage::{Stage, StageResult},
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
    type Error = UnhandledError;

    async fn process(self, batch: Batch<ExceptionEventPipelineItem>) -> StageResult<Self> {
        // Implement spike alert logic here
        let issues: Vec<Issue> = batch
            .inner_ref()
            .iter()
            .filter_map(|res| match res {
                Ok(evt) => match &evt.issue {
                    Some(issue) => Some(issue.clone()),
                    None => {
                        error!("no issue associated with event");
                        None
                    }
                },
                Err(_) => None,
            })
            .collect::<Vec<Issue>>();

        let issues_by_id = issues
            .into_iter()
            .map(|issue| (issue.id, issue))
            .collect::<HashMap<_, _>>();

        let issues_count_by_id: HashMap<Uuid, u32> =
            issues_by_id
                .iter()
                .fold(HashMap::new(), |mut acc, (id, _)| {
                    *acc.entry(*id).or_insert(0) += 1;
                    acc
                });

        do_spike_detection(self.context, issues_by_id, issues_count_by_id).await;

        Ok(batch)
    }
}
