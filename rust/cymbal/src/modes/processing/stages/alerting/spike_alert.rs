use std::{
    collections::{hash_map::Entry, HashMap},
    sync::Arc,
};

use uuid::Uuid;

use crate::{
    app_context::AppContext,
    issue_resolution::{Issue, IssueStatus},
    metric_consts::SPIKE_ALERT_STAGE,
    stages::{
        alerting::spike_detection::{do_spike_detection, SpikeSample},
        pipeline::{FinalizedPipelineItem, RateCheckedPipelineItem},
    },
    types::{
        batch::Batch,
        exception_event::{ExceptionEvent, RateChecked},
        stage::{Stage, StageResult},
    },
};

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
    type Input = RateCheckedPipelineItem;
    type Output = FinalizedPipelineItem;

    fn name(&self) -> &'static str {
        SPIKE_ALERT_STAGE
    }

    async fn process(self, batch: Batch<RateCheckedPipelineItem>) -> StageResult<Self> {
        let counted =
            count_events_per_issue(batch.inner_ref().iter().filter_map(|res| res.as_ref().ok()));

        do_spike_detection(
            self.context,
            counted.issues_by_id,
            counted.samples_by_id,
            counted.counts_by_id,
        )
        .await?;

        Ok(batch.map(|item, ()| item.map(ExceptionEvent::into_finalized), &mut ()))
    }
}

struct IssueEventCounts {
    issues_by_id: HashMap<Uuid, Issue>,
    samples_by_id: HashMap<Uuid, SpikeSample>,
    counts_by_id: HashMap<Uuid, u32>,
}

fn count_events_per_issue<'a>(
    events: impl Iterator<Item = &'a ExceptionEvent<RateChecked>>,
) -> IssueEventCounts {
    let mut counted = IssueEventCounts {
        issues_by_id: HashMap::new(),
        samples_by_id: HashMap::new(),
        counts_by_id: HashMap::new(),
    };

    for evt in events {
        let issue = evt.issue();
        // Keep one ProcessedExceptionProperties per issue (they share the same stack shape)
        if let Entry::Vacant(e) = counted.samples_by_id.entry(issue.id) {
            e.insert(SpikeSample {
                props: evt.processed_properties(),
                event_uuid: evt.uuid(),
                event_timestamp: evt.timestamp().to_string(),
            });
        }
        *counted.counts_by_id.entry(issue.id).or_insert(0) += 1;
        // A batch can hold events from before and after the issue reopened. The active copy is the
        // current state, and only an active issue can alert.
        match counted.issues_by_id.entry(issue.id) {
            Entry::Vacant(e) => {
                e.insert(issue.clone());
            }
            Entry::Occupied(mut e) if issue.status == IssueStatus::Active => {
                e.insert(issue.clone());
            }
            Entry::Occupied(_) => {}
        }
    }

    counted
}

#[cfg(test)]
mod tests {
    use chrono::Utc;

    use super::*;
    use crate::types::{
        exception_event::{Linked, ResolvedMetadata, SelectedFingerprint},
        ExceptionList,
    };

    fn issue(status: IssueStatus) -> Issue {
        Issue {
            id: Uuid::now_v7(),
            team_id: 1,
            status,
            severity: None,
            name: None,
            description: None,
            created_at: Utc::now(),
            latest_release_id: None,
            latest_release_created_at: None,
            resolved_until: None,
        }
    }

    fn event_on(issue: &Issue) -> ExceptionEvent<RateChecked> {
        ExceptionEvent {
            uuid: Uuid::now_v7(),
            team_id: issue.team_id,
            timestamp: String::new(),
            exception_list: ExceptionList(vec![]),
            debug_images: vec![],
            props: HashMap::new(),
            proposed_issue_name: None,
            proposed_issue_description: None,
            proposed_issue_severity: None,
            state: Linked {
                metadata: ResolvedMetadata {
                    sources: vec![],
                    types: vec![],
                    messages: vec![],
                    functions: vec![],
                    handled: false,
                    release: None,
                },
                fingerprint: SelectedFingerprint::manual("fingerprint".to_string()),
                issue: issue.clone(),
            },
        }
        .into_rate_checked()
    }

    #[test]
    fn events_on_a_resolved_issue_count_and_a_reopen_in_the_batch_wins() {
        let stays_resolved = issue(IssueStatus::Resolved);
        let reopened = Issue {
            status: IssueStatus::Active,
            ..issue(IssueStatus::Resolved)
        };
        let reopened_before = Issue {
            status: IssueStatus::Resolved,
            ..reopened.clone()
        };
        let events = [
            event_on(&reopened_before),
            event_on(&stays_resolved),
            event_on(&reopened),
            event_on(&reopened_before),
        ];

        let counted = count_events_per_issue(events.iter());

        assert_eq!(
            counted.counts_by_id,
            HashMap::from([(stays_resolved.id, 1), (reopened.id, 3)])
        );
        assert_eq!(
            counted.issues_by_id[&stays_resolved.id].status,
            IssueStatus::Resolved
        );
        assert_eq!(
            counted.issues_by_id[&reopened.id].status,
            IssueStatus::Active
        );
    }
}
