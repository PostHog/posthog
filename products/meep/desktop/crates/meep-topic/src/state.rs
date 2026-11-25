use crate::*;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;

mod command;
pub use command::*;
mod context;
mod inbox;
mod tasks;

/// One ordered notification for subscribers to a topic.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Change {
    /// Strictly increasing within this topic, beginning at one.
    pub seq: u64,
    /// Time the change was applied.
    pub at: DateTime<Utc>,
    /// Change and affected identities.
    pub kind: ChangeKind,
}

/// Granular change to a topic.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ChangeKind {
    /// A thread opened.
    ThreadOpened(ThreadId),
    /// A conversation's contents or disposition changed.
    ThreadUpdated(ThreadId),
    /// A provisional intake thread was joined to an existing conversation.
    ThreadJoined {
        /// Identity of the provisional thread.
        incoming: ThreadId,
        /// Conversation that now owns its messages.
        target: ThreadId,
    },
    /// A thread was skipped.
    ThreadSkipped(ThreadId),
    /// A message was received in the specified thread.
    MessageReceived(ThreadId, MessageId),
    /// A task was added.
    TaskAdded(TaskId),
    /// Work on a task was updated.
    TaskUpdated(TaskId),
    /// A task moved on the board.
    TaskMoved {
        /// Affected task.
        task: TaskId,
        /// Previous column.
        from: Column,
        /// New column.
        to: Column,
    },
    /// A person approved a task.
    TaskApproved {
        /// Approved task.
        task: TaskId,
        /// Whether to offer to allow this kind in the future.
        offer_always: bool,
    },
    /// A fact was learned.
    FactAdded(FactId),
    /// A newer fact superseded a previous one.
    FactSuperseded(FactId, FactId),
    /// An assertion lost its support when another fact was withdrawn.
    FactInvalidated(FactId, FactId),
    /// A fact was removed.
    FactRemoved(FactId),
    /// A policy entry was added.
    RuleAdded(RuleId),
    /// A policy entry was removed.
    RuleRemoved(RuleId),
    /// An objective was added.
    GoalAdded(GoalId),
    /// An objective's progress changed.
    GoalUpdated(GoalId),
    /// Topic context changed.
    TopicUpdated(TopicId),
}

/// A rejected operation. The state is unchanged.
#[derive(Clone, Debug, Eq, PartialEq, Error, Serialize, Deserialize)]
pub enum TopicError {
    /// Only published reports can create a report-linked task.
    #[error("This item is not an agent report")]
    NotAgentReport,
    /// Topic lifecycle prevents the requested edit.
    #[error("Topic is archived or deleted")]
    InactiveTopic,
    /// A planned task named an owner other than the person, the agent or a sub-agent.
    #[error("A planned task is for the person, the topic agent or a sub-agent")]
    PlannedTaskOwner,
    /// A required name is empty.
    #[error("A nonempty name is required")]
    EmptyName,
    /// The envelope cannot initialize a catalog entry.
    #[error("expected a CreateTopic command")]
    ExpectedCreate,
    /// The assertions in a fact review have changed.
    #[error("this fact review is no longer current")]
    StaleFactReview,
    /// The task has left or changed the review seen by the person.
    #[error("This task review has changed. Open the current proposal to review it.")]
    StaleTaskReview,
    /// A manual workflow acknowledgement referred to an older dispatch.
    #[error("The uncertain run changed. Refresh before acknowledging it.")]
    StaleRoutineDispatch,
    /// Current action policy prohibits the operation under review.
    #[error("A current topic rule blocks this action ({0}).")]
    ActionDenied(RuleId),
    /// A proposal relies on evidence awaiting a person's judgment.
    #[error("Resolve the disputed evidence in Needs You before approving this action.")]
    DisputedEvidence,
    /// The proposal cites an assertion which no longer holds.
    #[error("A fact used by this proposal is no longer current ({0}). Request a revised proposal.")]
    RetiredEvidence(FactId),
    /// Another answer advanced this conversation to a different question.
    #[error("This inbox question has changed. Open the current question to answer it.")]
    StaleInboxReview,
    /// Built-in routine metadata is managed by the topic.
    #[error("reserved routine {0}")]
    ReservedRoutine(String),
    /// No such routine is bound to the topic.
    #[error("unknown routine {0}")]
    UnknownRoutine(String),
    /// An envelope belongs to a different topic.
    #[error("command belongs to topic {0}")]
    WrongTopic(TopicId),
    /// Topic creation requires an empty slot in the catalog.
    #[error("topic {0} already exists")]
    ExistingTopic(TopicId),
    /// An operation referenced an unknown thread.
    #[error("unknown thread {0}")]
    UnknownThread(ThreadId),
    /// An operation referenced an unknown task.
    #[error("unknown task {0}")]
    UnknownTask(TaskId),
    /// An operation referenced an unknown fact.
    #[error("unknown fact {0}")]
    UnknownFact(FactId),
    /// An operation referenced an unknown rule.
    #[error("unknown rule {0}")]
    UnknownRule(RuleId),
    /// An operation referenced an unknown goal.
    #[error("unknown goal {0}")]
    UnknownGoal(GoalId),
    /// The ID for a new object is already used.
    #[error("duplicate ID {0}")]
    DuplicateId(String),
    /// The requested operation does not apply in this thread's state.
    #[error("thread {0} is not in the required state")]
    ThreadState(ThreadId),
    /// A person's answer was not offered on the thread.
    #[error("choice was not offered on thread {0}")]
    SuggestionNotOffered(ThreadId),
    /// A pending start requires explicit approval.
    #[error("approve task {0} before starting it")]
    StartNeedsApproval(TaskId),
    /// The task is no longer waiting for an explicit start.
    #[error("task {0} is not queued")]
    TaskNotQueued(TaskId),
    /// The requested operation does not apply in this column.
    #[error("task {0} is in {1:?}")]
    TaskColumn(TaskId, Column),
    /// Only current facts can be added or superseded.
    #[error("fact {0} is already superseded")]
    Superseded(FactId),
    /// Another fact links to this replacement in its provenance chain.
    #[error("fact {0} is a replacement for another fact")]
    ReferencedFact(FactId),
    /// JSON measurements must be finite and guardrail bounds ordered.
    #[error("invalid measurement for goal {0}")]
    InvalidProgress(GoalId),
}

/// IDs waiting for the person, in inbox and board order.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct NeedsYou {
    /// Inbox choices requiring a decision.
    pub threads: Vec<ThreadId>,
    /// Board tasks awaiting review.
    pub tasks: Vec<TaskId>,
}

/// Counts of work recorded since an inclusive cutoff.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct Digest {
    /// Messages received.
    pub messages: usize,
    /// Tasks created.
    pub tasks: usize,
    /// Facts learned, including those subsequently removed or superseded.
    pub facts: usize,
    /// Decisions to skip a thread.
    pub skips: usize,
}

/// Counts of metered calls on a UTC calendar day or week.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct CallCounts {
    /// System One decision requests.
    pub system_one: u64,
    /// Distinct routine dispatches accepted by the provider.
    pub routine_dispatches: u64,
}

/// Rolling usage replicated with the topic, including the active agent-start cap.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct TopicUsage {
    /// Admission timestamps retained for the latest hour.
    pub agent_starts: Vec<DateTime<Utc>>,
    /// Maximum starts allowed in one hour.
    pub hourly_cap: usize,
    /// Calendar totals for this UTC week, beginning Monday.
    pub days: std::collections::BTreeMap<chrono::NaiveDate, CallCounts>,
}

impl TopicUsage {
    /// Agent starts still in the rolling hour, even while the device is offline.
    pub fn last_hour(&self, now: DateTime<Utc>) -> usize {
        self.agent_starts
            .iter()
            .filter(|t| **t > now - chrono::TimeDelta::hours(1) && **t <= now)
            .count()
    }
    /// Today's calls.
    pub fn today(&self, now: DateTime<Utc>) -> CallCounts {
        self.days
            .get(&now.date_naive())
            .copied()
            .unwrap_or_default()
    }
    /// Calls since Monday at 00:00 UTC.
    pub fn this_week(&self, now: DateTime<Utc>) -> CallCounts {
        let day = now.date_naive();
        let monday = day.week(chrono::Weekday::Mon).first_day();
        self.days
            .range(monday..=day)
            .fold(CallCounts::default(), |mut total, (_, v)| {
                total.system_one += v.system_one;
                total.routine_dispatches += v.routine_dispatches;
                total
            })
    }
}

/// Findings received for one triggering event in a bound workflow.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RoutineReportRun {
    /// Topic-local routine binding.
    pub routine: String,
    /// PostHog trigger event shared by the steps of this invocation.
    pub event: uuid::Uuid,
    /// Most recent report delivery in this invocation.
    pub at: DateTime<Utc>,
    /// Workflow agent run IDs, in delivery order.
    pub runs: Vec<uuid::Uuid>,
    /// Published reports, in delivery order. Empty for a run without findings.
    pub threads: Vec<ThreadId>,
}

/// A PostHog Signals scout linked to this topic.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LinkedScout {
    /// Native scout configuration ID.
    pub id: uuid::Uuid,
    /// Display name from PostHog.
    pub name: String,
    /// Stable name used by the PostHog scout detail route.
    pub skill_name: String,
    /// Whether the scout is active.
    pub enabled: bool,
    /// Recent findings from the scout, newest first.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub reports: Vec<ScoutReport>,
}

/// A scout finding delivered to a topic.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ScoutReport {
    /// Upstream finding ID.
    pub id: uuid::Uuid,
    /// Finding headline.
    pub title: String,
    /// Short description of what the scout found.
    pub summary: String,
    /// Time PostHog received the finding.
    pub filed_at: DateTime<Utc>,
}

/// A topic, its work and its serializable history.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TopicState {
    /// Replicated provider usage.
    #[serde(default)]
    pub usage: TopicUsage,
    /// Archived topics are retained outside the active workspace.
    #[serde(default)]
    pub archived: bool,
    /// A minimal replicated deletion marker for offline devices.
    #[serde(default)]
    pub deleted: bool,
    /// Conversations hidden from the inbox.
    #[serde(default)]
    pub archived_threads: std::collections::BTreeSet<ThreadId>,
    /// Removed facts available for undo.
    #[serde(default)]
    pub removed_facts: std::collections::BTreeMap<FactId, Fact>,
    /// Removed rules with their original precedence and removal time.
    #[serde(default)]
    pub removed_rules: std::collections::BTreeMap<RuleId, (DateTime<Utc>, usize, Rule)>,
    /// Deleted logical files and the tombstone revision of each.
    #[serde(default)]
    pub deleted_files: std::collections::BTreeMap<String, u64>,
    /// Topic metadata and context.
    pub topic: Topic,
    /// Inbox conversations.
    pub threads: Vec<Thread>,
    /// Task board.
    pub tasks: Vec<Task>,
    /// Human-readable history in mutation order.
    pub activity: Vec<Activity>,
    /// Completed workflow analyses used for the folded routine history in chat.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub routine_report_runs: Vec<RoutineReportRun>,
    /// PostHog scouts linked to the topic, included in the device replica.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub scouts: Vec<LinkedScout>,
    /// Latest data published by a bound routine for each workspace view.
    #[serde(default, skip_serializing_if = "std::collections::BTreeMap::is_empty")]
    pub view_data: std::collections::BTreeMap<uuid::Uuid, serde_json::Value>,
    history: Vec<Change>,
}

/// Ordered domain notifications produced by one operation.
pub type Changes = Vec<Change>;

type Transition = Result<Changes, TopicError>;

impl TopicState {
    /// Opens an empty inbox and board for the supplied context.
    pub fn new(topic: Topic) -> Self {
        let mut state = Self {
            usage: Default::default(),
            archived: false,
            deleted: false,
            archived_threads: Default::default(),
            removed_facts: Default::default(),
            removed_rules: Default::default(),
            deleted_files: Default::default(),
            topic,
            threads: vec![],
            tasks: vec![],
            activity: vec![],
            routine_report_runs: vec![],
            scouts: vec![],
            view_data: Default::default(),
            history: vec![],
        };
        for fact in &state.topic.facts {
            state.history.push(Change {
                seq: state.history.len() as u64 + 1,
                at: fact.provenance.at,
                kind: ChangeKind::FactAdded(fact.id),
            });
        }
        state
    }

    /// Lists the outstanding inbox decisions and task reviews.
    pub fn needs_you(&self) -> NeedsYou {
        if self.archived || self.deleted {
            return NeedsYou::default();
        }
        NeedsYou {
            threads: self
                .threads
                .iter()
                .filter(|t| {
                    !self.archived_threads.contains(&t.id)
                        && matches!(t.state, ThreadState::NeedsYou { .. })
                })
                .map(|t| t.id)
                .collect(),
            tasks: self
                .tasks
                .iter()
                .filter(|t| t.column == Column::NeedsYou && !t.is_session())
                .map(|t| t.id)
                .collect(),
        }
    }

    /// Counts arrivals, additions and skip decisions by the time they were applied.
    pub fn digest(&self, since: DateTime<Utc>) -> Digest {
        let mut d = Digest::default();
        for change in self.history.iter().filter(|change| change.at >= since) {
            match change.kind {
                ChangeKind::MessageReceived(..) => d.messages += 1,
                ChangeKind::TaskAdded(_) => d.tasks += 1,
                ChangeKind::FactAdded(_) => d.facts += 1,
                ChangeKind::ThreadSkipped(_) => d.skips += 1,
                _ => (),
            }
        }
        d
    }

    fn record(
        &mut self,
        at: DateTime<Utc>,
        actor: Actor,
        subject: Ref,
        text: String,
        kinds: impl IntoIterator<Item = ChangeKind>,
    ) -> Vec<Change> {
        self.activity.push(Activity {
            delivery: None,
            at,
            actor,
            text,
            subject,
        });
        let start = self.history.len();
        for kind in kinds {
            self.history.push(Change {
                seq: self.history.len() as u64 + 1,
                at,
                kind,
            });
        }
        self.history[start..].to_vec()
    }

    fn thread_index(&self, id: ThreadId) -> Result<usize, TopicError> {
        self.threads
            .iter()
            .position(|t| t.id == id)
            .ok_or(TopicError::UnknownThread(id))
    }

    fn task_index(&self, id: TaskId) -> Result<usize, TopicError> {
        self.tasks
            .iter()
            .position(|t| t.id == id)
            .ok_or(TopicError::UnknownTask(id))
    }

    fn fact_index(&self, id: FactId) -> Result<usize, TopicError> {
        self.topic
            .facts
            .iter()
            .position(|f| f.id == id)
            .ok_or(TopicError::UnknownFact(id))
    }
}
