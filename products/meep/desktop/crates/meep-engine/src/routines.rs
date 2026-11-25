mod bindings;
mod callback;
pub use callback::{RoutineAsk, RoutineOp, RoutineReports, RoutineSortContext};

use super::*;
use meep_workflows::Workflow;
use serde_json::{Value, json};

#[derive(PartialEq, Eq)]
pub(super) enum InvocationStatus {
    Pending,
    Succeeded,
    Failed,
}

impl InvocationStatus {
    pub(super) fn from_provider(status: &str) -> Self {
        match status.to_ascii_lowercase().as_str() {
            "completed" | "succeeded" | "success" | "done" => Self::Succeeded,
            "error" | "failed" | "canceled" | "cancelled" => Self::Failed,
            _ => Self::Pending,
        }
    }
}

#[derive(Clone, Default, Serialize, Deserialize)]
pub(super) struct Causality {
    pub(super) hops: u32,
    pub(super) stack: Vec<(TopicId, String)>,
}

#[derive(Clone, Serialize, Deserialize)]
pub(super) struct Routine {
    #[serde(default)]
    pub(super) defer_sort: bool,
    #[serde(default)]
    pub(super) observation_only: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(super) workflow: Option<Workflow>,
    #[serde(default = "Uuid::new_v4")]
    secret: Uuid,
    #[serde(default)]
    receipts: BTreeMap<Uuid, (RoutineOp, Value)>,
    #[serde(default)]
    pending_sends: BTreeMap<Uuid, RoutineOp>,
    #[serde(default)]
    pub(super) invocations: BTreeMap<Uuid, String>,
    #[serde(default)]
    pub(super) bound_by: Option<CommandId>,
}

pub(super) fn task_routines(s: &StoredTopic, cause: &Causality) -> Vec<String> {
    s.state
        .topic
        .routines
        .iter()
        .filter(|r| {
            s.routines.contains_key(&r.binding.id)
                && r.event.is_none()
                && !cause
                    .stack
                    .contains(&(s.state.topic.id, r.binding.id.clone()))
        })
        .map(|r| r.binding.id.clone())
        .collect()
}

/// Queue the selected automation in the same transaction as the board transition.
pub(super) fn start_assigned(
    s: &mut StoredTopic,
    task_id: TaskId,
    cause: &Causality,
    now: DateTime<Utc>,
) -> Result<Changes> {
    if s.state.archived || s.state.deleted {
        return Ok(vec![]);
    }
    let task = s
        .state
        .tasks
        .iter()
        .find(|t| t.id == task_id)
        .context("Missing assigned task")?;
    let Some(InboxAssignment::Routine(id)) = &task.assignment else {
        return Ok(vec![]);
    };
    if task.column != Column::Todo || task.review_before_start {
        return Ok(vec![]);
    }
    if let Some(binding) = s
        .state
        .topic
        .routines
        .iter()
        .map(|r| &r.binding)
        .find(|b| b.id == *id && b.backend != "local")
        .cloned()
        && let Some(routine) = s.routines.get(id)
        && !cause.stack.contains(&(s.state.topic.id, id.clone()))
    {
        s.runs.insert(
            task_id,
            Work::AssignedFlow {
                binding: binding.clone(),
                generation: routine.bound_by,
                key: Uuid::new_v4(),
                invocation: None,
            },
        );
        return Ok(s.state.start(task_id, &binding.name, now)?);
    }
    Ok(s.state.work_needs_attention(
        task_id,
        "The assigned automation is unavailable.".into(),
        now,
    )?)
}

pub(super) fn on_changes<'a>(
    s: &mut StoredTopic,
    changes: impl IntoIterator<Item = &'a Change>,
    cause: &Causality,
) {
    for change in changes {
        s.queue_topic_change(change, cause);
    }
}

pub(super) fn migrate(saved: &mut StoredTopic) {
    saved.routines.retain(|_, r| r.workflow.is_none());
    if !saved.jobs.is_empty() {
        saved.jobs.clear();
        saved.state.activity.push(Activity {
            delivery: None,
            at: Utc::now(),
            actor: Actor::User,
            subject: Ref::Topic,
            text:
                "Dropped pending local routine jobs because local routines are no longer supported."
                    .into(),
        });
    }
}
