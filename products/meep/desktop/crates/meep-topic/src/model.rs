mod inbox;
pub use inbox::*;

use crate::*;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// The context a topic uses to understand incoming work.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(from = "StoredTopicContext")]
pub struct Topic {
    /// Stable identity across edits and renames.
    pub id: TopicId,
    /// Display name.
    pub name: String,
    /// Description of the topic's responsibility.
    pub mission: String,
    /// Objectives in presentation order.
    pub goals: Vec<Goal>,
    /// Policy in order of increasing precedence.
    pub rules: Vec<Rule>,
    /// Knowledge and its provenance, including superseded facts.
    pub facts: Vec<Fact>,
    /// Passive context references; these do not enable monitoring.
    #[serde(default)]
    pub context_sources: Vec<Watch>,
    /// Hosted workflow receiving newly selected sources after setup.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub default_sort: Option<String>,
    /// Built-in source sorter and its subscriptions.
    pub fallback: RoutineInfo,
    /// Topic processing switches.
    pub settings: TopicSettings,
    /// Routine bindings and their latest observations.
    #[serde(default)]
    pub routines: Vec<RoutineInfo>,
    /// Time the topic was created.
    pub created_at: DateTime<Utc>,
}

/// Preferred topic-local ID for the built-in inbox sorter.
pub const SORT_INBOX_ID: &str = "system:sort-inbox";

/// Built-in that compares edited facts with topic memory.
pub const CHECK_FACTS: &str = "system:check-facts";

/// Topic processing switches.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct TopicSettings {
    /// Investigate conflicting facts.
    pub check_facts: bool,
    /// Import PostHog Scout reports into the inbox: `None` off, `Some("")` every
    /// ready report, `Some(term)` only reports matching that search.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scout_feed: Option<String>,
}
impl Default for TopicSettings {
    fn default() -> Self {
        Self {
            check_facts: true,
            scout_feed: None,
        }
    }
}
impl TopicSettings {
    pub(crate) fn setting_mut(&mut self, key: &str) -> Option<&mut bool> {
        match key {
            CHECK_FACTS | "check_facts" => Some(&mut self.check_facts),
            _ => None,
        }
    }
}
#[derive(Deserialize)]
struct StoredTopicContext {
    id: TopicId,
    name: String,
    mission: String,
    goals: Vec<Goal>,
    rules: Vec<Rule>,
    facts: Vec<Fact>,
    #[serde(default)]
    context_sources: Option<Vec<Watch>>,
    #[serde(default)]
    routines: Vec<RoutineInfo>,
    #[serde(default)]
    default_sort: Option<String>,
    #[serde(default)]
    fallback: Option<RoutineInfo>,
    #[serde(default)]
    settings: TopicSettings,
    #[serde(default, alias = "watches")]
    watch: Vec<Watch>,
    #[serde(default)]
    follow_ups: LegacyFollowUps,
    created_at: DateTime<Utc>,
}

impl From<StoredTopicContext> for Topic {
    fn from(stored: StoredTopicContext) -> Self {
        let migrate_context = stored.context_sources.is_none();
        let mut routines = stored.routines;
        let mut fallback = stored.fallback.unwrap_or_else(|| {
            let mut fallback = RoutineInfo::sort_inbox(SORT_INBOX_ID.into());
            // Older topic-level watches explicitly used the built-in sorter.
            fallback.enabled = !stored.watch.is_empty();
            fallback
        });
        let mut settings = stored.settings;
        let mut released = stored.watch;
        routines.retain_mut(|r| {
            if r.binding.is_builtin_sorter() {
                fallback = r.clone();
                false
            } else if r.binding.backend == "system" {
                if let Some(flag) = settings.setting_mut(&r.binding.external_id) {
                    *flag = r.enabled;
                }
                false
            } else if r.binding.backend == "local" {
                released.append(&mut r.binding.watches);
                false
            } else {
                true
            }
        });
        if routines.iter().any(|r| r.binding.id == fallback.binding.id) {
            fallback.binding.id = (1..)
                .map(|n| format!("{SORT_INBOX_ID}-{n}"))
                .find(|id| routines.iter().all(|r| r.binding.id != *id))
                .expect("available sorter ID");
        }
        let mut topic = Self {
            fallback,
            settings,
            default_sort: stored
                .default_sort
                .filter(|id| routines.iter().any(|r| r.binding.id == *id)),
            id: stored.id,
            name: stored.name,
            mission: stored.mission,
            goals: stored.goals,
            rules: stored.rules,
            facts: stored.facts,
            context_sources: stored.context_sources.unwrap_or_default(),

            created_at: stored.created_at,
            routines,
        };
        if stored.follow_ups.mode.as_deref() == Some("Automatic") {
            // Stable across independent replica loads, even if a rule already uses the topic UUID.
            let mut value = topic.id.0.as_u128();
            while topic.rules.iter().any(|r| r.id.0.as_u128() == value) {
                value = value.wrapping_add(1);
            }
            topic.rules.insert(
                0,
                Rule {
                    id: RuleId(uuid::Uuid::from_u128(value)),
                    text: "Always allow starting follow-ups.".into(),
                    effect: RuleEffect::Allow(ActionKind::start_follow_up()),
                    from_task: None,
                    created_at: topic.created_at,
                },
            );
        }
        let mut owned: std::collections::HashSet<_> = topic.watches().map(|w| w.id).collect();
        topic
            .default_watches_mut()
            .extend(released.into_iter().filter(|w| owned.insert(w.id)));
        if migrate_context {
            // Before passive context existed, the Context UI stored its selections on
            // the default sorter. Preserve the references without retaining implicit watches.
            let mut sources = std::mem::take(&mut topic.fallback.binding.watches);
            if let Some(default) = topic.default_sort.clone()
                && let Some(routine) = topic.routines.iter_mut().find(|r| r.binding.id == default)
            {
                sources.append(&mut routine.binding.watches);
            }
            let mut ids = std::collections::HashSet::new();
            topic
                .context_sources
                .extend(sources.into_iter().filter(|w| ids.insert(w.id)));
        }
        topic
    }
}

impl RoutineInfo {
    fn sort_inbox(id: String) -> Self {
        let mut info = Self::system(id, "", "Sort inbox", "Source event");
        info.enabled = false;
        info
    }

    fn system(id: String, key: &str, name: &str, trigger: &str) -> Self {
        Self {
            event: None,
            enabled: true,
            observations: vec![],
            binding: RoutineBinding {
                id,
                name: name.into(),
                trigger: trigger.into(),
                backend: "system".into(),
                external_id: key.into(),
                watches: vec![],
            },
            last_run: None,
            uncertain_manual_run: None,
            health: RoutineHealth::Ok,
        }
    }
}

impl Topic {
    /// Whether the configured fixed stage is running.
    pub fn stage_enabled(&self, key: &str) -> bool {
        match key {
            CHECK_FACTS => self.settings.check_facts,
            _ => true,
        }
    }
    /// All active source destinations, including the fallback.
    pub fn destinations(&self) -> impl Iterator<Item = &RoutineInfo> {
        self.routines.iter().chain(std::iter::once(&self.fallback))
    }
    /// Mutable routing destinations.
    pub fn destinations_mut(&mut self) -> impl Iterator<Item = &mut RoutineInfo> {
        self.routines
            .iter_mut()
            .chain(std::iter::once(&mut self.fallback))
    }
    /// Topic-wide source list.
    pub fn watches(&self) -> impl Iterator<Item = &Watch> {
        self.destinations().flat_map(|r| &r.binding.watches)
    }
    /// Sources of the default sorter.
    pub fn default_watches_mut(&mut self) -> &mut Vec<Watch> {
        let dest = self
            .routines
            .iter_mut()
            .find(|r| Some(&r.binding.id) == self.default_sort.as_ref())
            .unwrap_or(&mut self.fallback);
        &mut dest.binding.watches
    }

    /// Creates a named topic with empty context.
    pub fn new(id: TopicId, name: impl Into<String>, now: DateTime<Utc>) -> Self {
        let routines = vec![];
        Self {
            id,
            fallback: RoutineInfo::sort_inbox(SORT_INBOX_ID.into()),
            settings: TopicSettings::default(),
            name: name.into(),
            default_sort: None,
            mission: String::new(),
            goals: vec![],
            rules: vec![],
            facts: vec![],
            context_sources: vec![],
            routines,

            created_at: now,
        }
    }
}

#[derive(Default, Deserialize)]
struct LegacyFollowUps {
    mode: Option<String>,
}

/// Work on a topic board.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Task {
    /// PostHog model ID.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
    /// Reasoning effort for the selected model.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reasoning_effort: Option<String>,
    /// Additional task instructions.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub instructions: Option<String>,
    /// Codex model access, either own-subscription or posthog-gateway.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub billing: Option<String>,
    /// The person gave no title: the title is a placeholder until PostHog names the
    /// task from its brief when it starts.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub untitled: bool,

    /// Identity on the board.
    pub id: TaskId,
    /// Display title.
    pub title: String,
    /// Current board column.
    pub column: Column,
    /// Who created the task.
    pub added_by: Actor,
    /// Originating conversation, if any.
    pub from_thread: Option<ThreadId>,
    /// Message that caused the task to be created.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_message: Option<MessageId>,
    /// Source metadata for work that can exist independently of a thread.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub origin: Option<Origin>,
    /// Assignment made by inbox triage. Older and manually created tasks use host routing.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub assignment: Option<InboxAssignment>,
    /// Waiting for an explicit start from the person.
    #[serde(default, alias = "assignee", deserialize_with = "read_queue_flag")]
    pub queued: bool,
    /// Parent task when an automation creates follow-up work.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent: Option<TaskId>,
    /// Approval will release the assigned step.
    #[serde(default)]
    pub review_before_start: bool,
    /// Changes when a review is closed or its terms change. Stable across unrelated edits.
    #[serde(default)]
    pub review_version: u64,
    /// Standing-rule identity reserved by the exact approval of this action.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub approval_rule: Option<RuleId>,
    /// Current worker's status.
    pub worker: Option<String>,
    /// Proposed side effect, retained after approval.
    pub action: Option<Action>,
    /// Clarification awaiting a reply in this task's conversation.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub input_question: Option<String>,
    /// Independent work the person can explicitly create from this result.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub suggestions: Vec<String>,
    /// Topic files this task's runs wrote, in first-write order.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub files: Vec<String>,
    /// Summary of the work produced.
    pub result: Option<String>,
    /// Editable text awaiting approval, or final approved text.
    pub draft: Option<String>,
    /// Work history in transition order.
    pub log: Vec<LogEntry>,
    /// Time of creation.
    pub created_at: DateTime<Utc>,
    /// Time of latest update.
    pub updated_at: DateTime<Utc>,
}

// Old boards recorded the holding state as a person assignment.
fn read_queue_flag<'de, D: serde::Deserializer<'de>>(input: D) -> Result<bool, D::Error> {
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum Stored {
        Queued(bool),
        Assignee(Option<String>),
    }
    match Stored::deserialize(input)? {
        Stored::Queued(value) => Ok(value),
        Stored::Assignee(value) => match value.as_deref() {
            None | Some("agent") => Ok(false),
            Some("person") => Ok(true),
            Some(other) => Err(serde::de::Error::unknown_variant(
                other,
                &["agent", "person"],
            )),
        },
    }
}

/// One entry in a task's history.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct LogEntry {
    /// Original event for evidence supplied by a source routine.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub origin: Option<Origin>,
    /// Time of the event.
    pub at: DateTime<Utc>,
    /// Description of what happened.
    pub text: String,
}

/// Position on the task board.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Column {
    /// Ready to start.
    Todo,
    /// A worker is active.
    InProgress,
    /// Waiting for the person's approval.
    NeedsYou,
    /// Finished.
    Done,
}

impl Column {
    pub(crate) fn label(self) -> &'static str {
        match self {
            Self::Todo => "To do",
            Self::InProgress => "In progress",
            Self::NeedsYou => "Needs you",
            Self::Done => "Done",
        }
    }
}

/// Who initiated a change.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Actor {
    /// The person.
    User,
    /// A topic agent.
    Agent,
    /// A named routine.
    Routine(String),
    /// Another topic.
    Topic(TopicId),
    /// An inbox thread.
    Inbox(ThreadId),
}

/// A proposed operation that may need permission.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Action {
    /// Policy class of this operation.
    pub kind: ActionKind,
    /// Imperative label for approval.
    pub label: String,
    /// Past-tense label for the log.
    pub done_label: String,
    /// Facts required for this operation. An empty list means independent of topic facts.
    /// Older producers can omit the list, in which case any open fact dispute holds the action.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub depends_on_facts: Option<Vec<FactId>>,
    /// Service-specific parameters.
    pub payload: serde_json::Value,
}

/// Stable, extensible policy key for a class of side effects.
#[derive(Clone, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ActionKind(pub String);

impl ActionKind {
    /// Policy shared by agent-created tasks and automated leads from investigations.
    pub fn start_follow_up() -> Self {
        Self("start-follow-up".into())
    }

    /// Noun phrase used in the approval question and the resulting rule.
    pub fn description(&self) -> String {
        match self.0.as_str() {
            "start-follow-up" => "starting follow-ups".into(),
            "copy-change" => "copy-only changes".into(),
            "slack-reply" => "replies in Slack".into(),
            "slack-post-general" => "posts in #general".into(),
            "merge-pr" => "pull request merges".into(),
            other => other.replace(['-', '_'], " "),
        }
    }

    /// Sentence-case label for a settings row, e.g. "Replies in Slack".
    pub fn title(&self) -> String {
        let description = self.description();
        let mut chars = description.chars();
        match chars.next() {
            Some(first) => first.to_uppercase().chain(chars).collect(),
            None => description,
        }
    }

    /// Question shown after approving an action of this kind.
    pub fn approval_question(&self) -> String {
        format!("Always allow {}?", self.description())
    }
}

/// A piece of knowledge with its origin.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Fact {
    /// Stable identity for links to this assertion.
    pub id: FactId,
    /// Assertion text.
    pub text: String,
    /// Evidence for the assertion.
    pub provenance: Provenance,
    /// Later assertion that replaces this one.
    pub superseded_by: Option<FactId>,
    /// Withdrawn evidence that invalidated this assertion.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub invalidated_by: Option<FactId>,
    /// When a person withdrew an assertion retained as a historical reference.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub withdrawn_at: Option<DateTime<Utc>>,
}

impl Fact {
    /// Whether this assertion belongs in current context and search.
    pub fn is_current(&self) -> bool {
        self.superseded_by.is_none() && self.invalidated_by.is_none() && self.withdrawn_at.is_none()
    }
}

/// Where and when a fact was learned.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Provenance {
    /// Connector metadata for an assertion made from an observation.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub origin: Option<Origin>,
    /// Person or service credited with the fact.
    pub author: String,
    /// Channel through which it was learned.
    pub via: String,
    /// Time the evidence was recorded.
    pub at: DateTime<Utc>,
    /// Source conversation, when available.
    pub thread: Option<ThreadId>,
}

/// An ordered topic policy entry.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Rule {
    /// Identity retained in decisions.
    pub id: RuleId,
    /// Sentence explaining the policy.
    pub text: String,
    /// Executable policy.
    pub effect: RuleEffect,
    /// Task whose approval produced this rule.
    pub from_task: Option<TaskId>,
    /// Time of creation.
    pub created_at: DateTime<Utc>,
}

/// What a rule does when matched.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum RuleEffect {
    /// Run actions of this kind automatically.
    Allow(ActionKind),
    /// Require approval for actions of this kind.
    Ask(ActionKind),
    /// Refuse actions of this kind.
    Deny(ActionKind),
    /// Ignore matching messages.
    Skip(Matcher),
}

/// All supplied filters must match a message.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct Matcher {
    /// Exact connection name.
    pub connection: Option<String>,
    /// Exact channel key.
    pub channel: Option<String>,
}

/// A topic's objective.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Goal {
    /// Objective identity.
    pub id: GoalId,
    /// Description for the person.
    pub text: String,
    /// Latest measurement, if tracked.
    pub progress: Option<Progress>,
}

/// Measurement of a target or guardrail.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum Progress {
    /// A value working toward a target.
    Target {
        /// Latest measurement.
        current: f64,
        /// Desired measurement.
        target: f64,
        /// Unit shared by the two values.
        unit: String,
    },
    /// A value expected to stay inside a band.
    Guardrail {
        /// Latest measurement.
        current: f64,
        /// Bottom of the band.
        low: f64,
        /// Top of the band.
        high: f64,
        /// Unit shared by all three values.
        unit: String,
    },
}

/// Human-readable record of a mutation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Activity {
    /// Stable delivery attempt for a receipt shown on its originating work.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub delivery: Option<uuid::Uuid>,
    /// Time of the mutation.
    pub at: DateTime<Utc>,
    /// Initiator.
    pub actor: Actor,
    /// Readable description.
    pub text: String,
    /// Object this entry links to.
    pub subject: Ref,
}

/// A link into the current topic.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Ref {
    /// An inbox thread.
    Thread(ThreadId),
    /// A board task.
    Task(TaskId),
    /// A fact in context.
    Fact(FactId),
    /// A policy entry.
    Rule(RuleId),
    /// A named routine.
    Routine(String),
    /// The containing topic.
    Topic,
}

/// Sorting decision applied to a new inbox thread.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Decision {
    /// Resolve the thread with the given results.
    Handle {
        /// Inbox summary.
        summary: String,
        /// Results to link to the thread.
        outcomes: Vec<Outcome>,
    },
    /// Request a choice from the person.
    Ask {
        /// Inbox summary.
        summary: String,
        /// Explanation for asking.
        reason: String,
        /// Available choices.
        suggestions: Vec<Suggestion>,
    },
    /// Skip work on the thread.
    Skip {
        /// Explanation for skipping.
        reason: String,
        /// Matching rule for automatic skips.
        rule: Option<RuleId>,
    },
}

/// Host-independent description of a routine.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RoutineBinding {
    /// Sources processed by this routine.
    #[serde(default)]
    pub watches: Vec<Watch>,
    /// Stable topic-local key for callbacks.
    pub id: String,
    /// Display name.
    pub name: String,
    /// Human-readable trigger description.
    pub trigger: String,
    /// Backend name, such as local or posthog.
    pub backend: String,
    /// Workflow identity in the backend.
    pub external_id: String,
}

impl RoutineBinding {
    /// The built-in source sorter, including legacy bindings with a suffixed ID.
    pub fn is_builtin_sorter(&self) -> bool {
        self.is_system_stage("")
    }

    fn is_system_stage(&self, key: &str) -> bool {
        self.backend == "system" && self.external_id == key
    }

    pub(crate) fn is_default_sorter(&self, default: Option<&str>) -> bool {
        default.map_or_else(|| self.is_builtin_sorter(), |id| self.id == id)
    }

    /// Whether an invocation still refers to the same configured workflow.
    /// Editing its subscriptions does not rebind a workflow.
    pub fn same_workflow(&self, other: &Self) -> bool {
        self.id == other.id
            && self.backend == other.backend
            && self.external_id == other.external_id
            && self.name == other.name
            && self.trigger == other.trigger
    }
}

/// Replicated history for a single delivery to a routine.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ObservationReport {
    /// Stable callback and dispatch key.
    pub key: uuid::Uuid,
    /// Engine-supplied origin of the event.
    pub origin: Origin,
    /// Latest transition.
    pub outcome: ObservationOutcome,
    /// Provider invocation when accepted.
    pub invocation: Option<uuid::Uuid>,
    /// Failed dispatch attempts in order.
    pub failures: Vec<String>,
    /// Time of the latest transition.
    pub at: DateTime<Utc>,
}

/// Disposition of a source observation.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum ObservationOutcome {
    /// Waiting for dispatch or retry.
    Pending,
    /// An invocation accepted the observation.
    Dispatched,
    /// Delivered and handled in the named thread.
    Inboxed(ThreadId),
    /// Discarded by the workflow.
    Dropped {
        /// Recorded explanation.
        reason: String,
    },
    /// Created a task.
    Task(TaskId),
    /// Recorded a sourced fact.
    Fact(FactId),
    /// Asked for a decision in the named thread.
    Asked(ThreadId),
    /// Submitted work to task approval.
    Approval(TaskId),
    /// Attached the event to an existing task.
    Evidence(TaskId),
    /// Delivered by the built-in sorter.
    FellBack {
        /// Inbox conversation.
        thread: ThreadId,
        /// Dispatch failure.
        reason: String,
    },
    /// The invocation completed without consuming the event.
    Finished {
        /// Recorded explanation.
        reason: String,
    },
    /// The invocation failed.
    Failed {
        /// Recorded explanation.
        reason: String,
    },
}
impl ObservationOutcome {
    /// Whether a workflow may still report a result.
    pub fn pending(&self) -> bool {
        matches!(self, Self::Pending | Self::Dispatched)
    }
}

/// Topic change that can trigger a PostHog workflow.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TopicEvent {
    /// An inbox message arrived.
    MessageArrived,
    /// Work was added.
    TaskAdded,
    /// Work moved on the board.
    TaskMoved,
    /// A fact was added, superseded, invalidated or removed.
    FactChanged,
    /// A routine invocation failed.
    RoutineFailed,
}
impl TopicEvent {
    /// Stable event name sent to workflows.
    pub fn name(self) -> &'static str {
        match self {
            Self::MessageArrived => "message_arrived",
            Self::TaskAdded => "task_added",
            Self::TaskMoved => "task_moved",
            Self::FactChanged => "fact_changed",
            Self::RoutineFailed => "routine_failed",
        }
    }
    /// Event-specific variable names, also valid keys for equality filters.
    pub fn fields(self) -> &'static [&'static str] {
        match self {
            Self::MessageArrived => &[
                "thread",
                "message",
                "text",
                "author",
                "connection",
                "channel",
            ],
            Self::TaskAdded => &["task", "title"],
            Self::TaskMoved => &["task", "title", "from", "to", "column"],
            Self::FactChanged => &["fact", "change", "text", "replacement"],
            Self::RoutineFailed => &["routine", "error"],
        }
    }
}
/// Subscription to an engine event, scoped to the owning topic.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EventSubscription {
    /// Event to observe.
    pub on: TopicEvent,
    /// Exact matches against event fields.
    #[serde(default)]
    pub filter: std::collections::BTreeMap<String, String>,
}

/// Public routine state replicated to clients.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RoutineInfo {
    /// Manual dispatch whose provider receipt was lost and has not been acknowledged.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub uncertain_manual_run: Option<CommandId>,
    /// Engine event that starts this workflow.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub event: Option<EventSubscription>,
    /// Whether the fixed stage is enabled. Older snapshots default to enabled.
    #[serde(default = "enabled_by_default")]
    pub enabled: bool,
    /// Recent source observations, oldest first.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub observations: Vec<ObservationReport>,
    /// Binding metadata.
    #[serde(flatten)]
    pub binding: RoutineBinding,
    /// Most recent observed invocation.
    pub last_run: Option<DateTime<Utc>>,
    /// Latest backend observation.
    pub health: RoutineHealth,
}

pub(crate) fn enabled_by_default() -> bool {
    true
}

/// Last known availability of a routine.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum RoutineHealth {
    /// A new binding has yet to be checked.
    Unknown,
    /// The backend responded successfully.
    Ok,
    /// Failure detail for display.
    Failing(String),
}
