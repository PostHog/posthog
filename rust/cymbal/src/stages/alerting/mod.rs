use std::{collections::HashMap, sync::Arc};

pub mod spike_alert;
pub mod spike_detection;

use tokio::sync::Mutex;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    issue_resolution::Issue,
    metric_consts::ALERTING_STAGE,
    stages::{alerting::spike_alert::SpikeAlertStage, pipeline::ExceptionEventPipelineItem},
    types::{
        batch::Batch,
        stage::{Stage, StageResult},
        OutputErrProps,
    },
};

/// Per-request accumulator for spike-detection inputs.
///
/// The legacy `/process` flow runs `SpikeAlertStage` at the end of the
/// per-batch pipeline and does one batched Redis call covering every
/// issue in the batch. The `/v2/process` flow runs the pipeline once per
/// event for isolation — without this accumulator, each per-event run
/// would make its own Redis call, amplifying call volume by a factor of
/// events-per-request.
///
/// With the accumulator threaded through the per-event pipelines, every
/// `AlertingStage` invocation appends its `(issue, props)` to the shared
/// state instead of making a Redis call. The `/v2` handler runs spike
/// detection **once** after all per-event work has finished, with the
/// merged set of issues — recovering the single-Redis-call shape of the
/// legacy flow.
#[derive(Default)]
pub struct SpikeAlertAccumulator {
    state: Mutex<SpikeAlertAccumulatorState>,
}

#[derive(Default)]
pub struct SpikeAlertAccumulatorState {
    /// Every successfully-linked event appends its issue here. The vector
    /// holds duplicates intentionally: spike detection counts events per
    /// issue, so 3 events with the same issue produce 3 entries.
    pub issues: Vec<Issue>,
    /// One canonical `OutputErrProps` per issue — they share the same
    /// stack shape, so we only need the first one we see.
    pub issue_props_by_id: HashMap<Uuid, OutputErrProps>,
}

impl SpikeAlertAccumulator {
    pub fn new() -> Arc<Self> {
        Arc::new(Self::default())
    }

    /// Record every successfully-linked event in `batch` into the
    /// accumulator. Mirrors the iteration that `SpikeAlertStage::process`
    /// does today, but writes into shared state instead of calling spike
    /// detection immediately.
    pub async fn record_batch(&self, batch: &Batch<ExceptionEventPipelineItem>) {
        let mut state = self.state.lock().await;
        for res in batch.inner_ref() {
            let Ok(evt) = res else { continue };
            let Some(issue) = &evt.issue else { continue };
            // One canonical OutputErrProps per issue — first writer wins.
            if let std::collections::hash_map::Entry::Vacant(e) =
                state.issue_props_by_id.entry(issue.id)
            {
                if let Ok(props) = evt.to_output(issue.id) {
                    e.insert(props);
                }
            }
            state.issues.push(issue.clone());
        }
    }

    /// Consume the accumulator, returning the aggregated state ready to
    /// be passed to `do_spike_detection`.
    pub async fn take(self: Arc<Self>) -> SpikeAlertAccumulatorState {
        let mut state = self.state.lock().await;
        std::mem::take(&mut *state)
    }
}

impl SpikeAlertAccumulatorState {
    /// Aggregate `issues` into a `(issue_id -> count)` map, mirroring the
    /// fold `SpikeAlertStage::process` does in the legacy path.
    pub fn issues_count_by_id(&self) -> HashMap<Uuid, u32> {
        self.issues.iter().fold(HashMap::new(), |mut acc, issue| {
            *acc.entry(issue.id).or_insert(0) += 1;
            acc
        })
    }

    /// Aggregate `issues` into a `(issue_id -> Issue)` map, dropping
    /// duplicates — later writes win — they're identical structs because
    /// they all came from the same issue in this request.
    pub fn issues_by_id(self) -> HashMap<Uuid, Issue> {
        self.issues
            .into_iter()
            .map(|issue| (issue.id, issue))
            .collect()
    }
}

pub struct AlertingStage {
    context: Arc<AppContext>,
    /// Optional accumulator for the deferred-mode `/v2/process` flow.
    /// When `Some`, the stage appends events to the accumulator instead
    /// of making Redis calls; the request handler invokes spike detection
    /// once at end-of-request. When `None`, spike detection runs inline
    /// for this batch (legacy `/process` behaviour).
    accumulator: Option<Arc<SpikeAlertAccumulator>>,
}

impl AlertingStage {
    pub fn new(context: Arc<AppContext>, accumulator: Option<Arc<SpikeAlertAccumulator>>) -> Self {
        Self {
            context,
            accumulator,
        }
    }
}

impl Stage for AlertingStage {
    type Input = ExceptionEventPipelineItem;
    type Output = ExceptionEventPipelineItem;

    fn name(&self) -> &'static str {
        ALERTING_STAGE
    }

    async fn process(self, batch: Batch<Self::Input>) -> StageResult<Self> {
        match self.accumulator {
            // Deferred mode: append to the shared accumulator. The /v2
            // handler will run spike detection once at end-of-request
            // with the merged batch.
            Some(acc) => {
                acc.record_batch(&batch).await;
                Ok(batch)
            }
            // Legacy mode: run spike detection inline for this batch.
            None => batch.apply_stage(SpikeAlertStage::new(self.context)).await,
        }
    }
}
