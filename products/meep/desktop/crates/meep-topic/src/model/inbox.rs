use super::*;

/// A subscription to a service-defined resource or another topic.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Watch {
    /// Identity of this subscription.
    pub id: WatchId,
    /// Connection name, or `topic` for inter-topic delivery.
    pub connection: String,
    /// Service-defined resource kind.
    pub kind: String,
    /// Resource key within the service.
    pub key: String,
    /// Human-readable resource name.
    pub label: String,
}

/// Origin of an inbox message or destination of a reply.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Source {
    /// The person using the topic.
    User,
    /// Another topic.
    Topic(TopicId),
    /// A resource on a connected service.
    Connection {
        /// Name of the service connection.
        connection: String,
        /// Channel or resource within the service.
        channel: String,
    },
}

/// Entity that created an inbox message.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Producer {
    /// Stable topic-local routine ID.
    Routine(String),
    /// Parent investigation that proposed this follow-up.
    PostHogTask(TaskId),
    /// The person using the topic.
    User,
    /// Built-in engine behavior.
    System,
}

/// Original connector metadata retained across derived work.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Origin {
    /// Connection ID or reserved user/topic origin.
    pub connection: String,
    /// Resource within the connection.
    pub channel: String,
    /// Message identity assigned by the service.
    pub external_id: Option<String>,
    /// Conversation identity assigned by the service.
    pub thread_hint: Option<String>,
    /// Sender at the source.
    pub author: String,
    /// Timestamp at the source.
    pub at: DateTime<Utc>,
}

impl Origin {
    /// Whether two observations identify the same connector thread or source record.
    pub fn relates_to(&self, other: &Self) -> bool {
        self.connection == other.connection
            && self.channel == other.channel
            && [
                (&self.thread_hint, &other.thread_hint),
                (&self.external_id, &other.external_id),
            ]
            .iter()
            .any(|(a, b)| a.as_deref().is_some_and(|v| !v.is_empty()) && a == b)
    }
}

impl Source {
    /// Reconstruct the available origin metadata for a source-addressed message.
    pub fn into_origin(
        self,
        author: String,
        at: DateTime<Utc>,
        external_id: Option<String>,
    ) -> Origin {
        let (connection, channel) = match self {
            Self::User => ("user".into(), String::new()),
            Self::Topic(id) => ("topic".into(), id.to_string()),
            Self::Connection {
                connection,
                channel,
            } => (connection, channel),
        };
        Origin {
            connection,
            channel,
            external_id,
            thread_hint: None,
            author,
            at,
        }
    }
}

/// An individual message in the inbox.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(from = "StoredMessage")]
pub struct Message {
    /// Local message identity.
    pub id: MessageId,
    /// Entity that created this message.
    pub producer: Producer,
    /// Original event metadata, when available.
    pub origin: Option<Origin>,
    /// Name shown for the sender.
    pub author: String,
    /// Time at the source.
    pub at: DateTime<Utc>,
    /// Message body.
    pub text: String,
    /// ID assigned by the source, when available.
    pub external_id: Option<String>,
}

#[derive(Deserialize)]
struct StoredMessage {
    id: MessageId,
    producer: Option<Producer>,
    origin: Option<Origin>,
    source: Option<Source>,
    author: String,
    at: DateTime<Utc>,
    text: String,
    external_id: Option<String>,
}

impl From<StoredMessage> for Message {
    fn from(m: StoredMessage) -> Self {
        let (producer, origin) = match m.producer {
            Some(producer) => (producer, m.origin),
            None => {
                let producer = if m.source == Some(Source::User) {
                    Producer::User
                } else {
                    Producer::System
                };
                let origin = m
                    .source
                    .map(|s| s.into_origin(m.author.clone(), m.at, m.external_id.clone()));
                (producer, origin)
            }
        };
        Self {
            id: m.id,
            producer,
            origin,
            author: m.author,
            at: m.at,
            text: m.text,
            external_id: m.external_id,
        }
    }
}

impl Message {
    /// Destination for a reply to this message.
    pub fn reply_target(&self) -> Option<Source> {
        match &self.origin {
            Some(o) => match o.connection.as_str() {
                "topic" => o.channel.parse().ok().map(Source::Topic),
                "user" => Some(Source::User),
                _ => Some(Source::Connection {
                    connection: o.connection.clone(),
                    channel: o.channel.clone(),
                }),
            },
            None => (self.producer == Producer::User).then_some(Source::User),
        }
    }
}

/// The scheduled retry for the next unsorted message in a thread.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SortRetry {
    /// Consecutive failed attempts for this message.
    pub failures: u32,
    /// Server time when the sorter can try again.
    pub next_at: DateTime<Utc>,
    /// Explanation of the most recent failure.
    pub reason: String,
}

/// Evidence cited by the producer of an inbox report, and how the report reads:
/// its priority, the impact in one line, the proposed next step, and the
/// person's verdict once they resolve or dismiss it.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ReportSources {
    /// Source links or named records supplied by the producer.
    pub references: Vec<String>,
    /// Described evidence with a citable source identifier.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub evidence: Vec<ReportEvidence>,
    /// Original connector record attached by the engine for source triggers.
    pub observation: Option<Origin>,
    /// Urgency, P0 (drop everything) to P4 (whenever).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub priority: Option<ReportPriority>,
    /// One sentence with the number that says how much this matters.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub impact: Option<String>,
    /// What the producer would do about it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub proposal: Option<String>,
    /// The person resolved or dismissed the report.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub verdict: Option<ReportVerdict>,
    /// A report imported from another system, such as a PostHog Scout report.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub external: Option<ExternalReport>,
}

/// Where an imported report came from, and whether the person's verdict reached it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ExternalReport {
    /// The producing system, such as `posthog-scout`.
    pub provider: String,
    /// The report's identity there.
    pub id: String,
    /// Where to open it there.
    pub url: String,
    /// The verdict that was last written back, so it is sent once.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub synced: Option<ReportOutcome>,
}

/// How urgent a report is.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
pub enum ReportPriority {
    /// Drop everything.
    P0,
    /// Today.
    P1,
    /// This week.
    P2,
    /// When there is time.
    P3,
    /// Worth knowing.
    P4,
}
impl ReportPriority {
    /// Parse "P0".."P4", case-insensitively.
    pub fn parse(text: &str) -> Option<Self> {
        Some(match text.trim().to_ascii_uppercase().as_str() {
            "P0" => Self::P0,
            "P1" => Self::P1,
            "P2" => Self::P2,
            "P3" => Self::P3,
            "P4" => Self::P4,
            _ => return None,
        })
    }
    /// The label shown beside the report.
    pub fn label(self) -> &'static str {
        match self {
            Self::P0 => "P0",
            Self::P1 => "P1",
            Self::P2 => "P2",
            Self::P3 => "P3",
            Self::P4 => "P4",
        }
    }
}

/// The person's closing word on a report.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ReportVerdict {
    /// Resolved (dealt with) or dismissed (not worth doing).
    pub outcome: ReportOutcome,
    /// Why, from a short list.
    pub reason: String,
    /// When they decided.
    pub at: DateTime<Utc>,
}

/// Whether a report was dealt with or set aside.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ReportOutcome {
    /// Dealt with.
    Resolved,
    /// Not worth doing.
    Dismissed,
}

/// One piece of evidence supporting an agent-authored report.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ReportEvidence {
    /// What the source establishes.
    pub description: String,
    /// Source link or provider identifier.
    pub source_id: String,
    /// What kind of source: replay, error, event, insight, ticket, slack,
    /// github, survey, log or other. Picks the evidence row's icon.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<String>,
    /// When the source happened.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub at: Option<DateTime<Utc>>,
}

/// A conversation about one subject.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Thread {
    /// Identity independent of the grouping key.
    pub id: ThreadId,
    /// Source-sort working record used for evidence and decisions.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub source_material: bool,
    /// Evidence for a published report. Older conversations have no report metadata.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub report_sources: Option<ReportSources>,
    /// Subject shown in the inbox.
    pub subject: String,
    /// Sorter's summary of the conversation.
    pub summary: String,
    /// Current inbox disposition.
    pub state: ThreadState,
    /// Why sorting is waiting and when the worker will retry.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sort_retry: Option<SortRetry>,
    /// Identifies the question that a device saw when answering this thread.
    #[serde(default)]
    pub review_version: u64,
    /// Message that prompted the visible question.
    #[serde(default)]
    pub question_source: Option<MessageId>,
    /// Investigation that produced this follow-up.
    #[serde(default)]
    pub parent_task: Option<TaskId>,
    /// Later questions on the same conversation, in arrival order.
    #[serde(default)]
    pub pending_questions: std::collections::VecDeque<InboxQuestion>,
    /// Messages in arrival order.
    pub messages: Vec<Message>,
    /// Consequences of handling this thread.
    pub outcomes: Vec<Outcome>,
    /// Ingest-supplied grouping key.
    pub key: String,
    /// Whether an update awaits reading.
    pub unseen: bool,
    /// Time the thread opened.
    pub created_at: DateTime<Utc>,
    /// Time of its latest update.
    pub updated_at: DateTime<Utc>,
}

impl Thread {
    /// An inbox report from a topic task, a workflow or an imported Scout report.
    pub fn is_agent_report(&self) -> bool {
        let imported = self
            .report_sources
            .as_ref()
            .is_some_and(|r| r.external.is_some());
        self.report_sources.is_some()
            && !self.source_material
            && self.messages.first().is_some_and(|m| {
                matches!(m.producer, Producer::PostHogTask(_) | Producer::Routine(_))
                    || (imported && m.producer == Producer::System)
            })
    }
}

/// A second decision can arrive while a person is reviewing the first.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct InboxQuestion {
    /// Origin of the question and any reply drafted from it.
    pub source: MessageId,
    /// Summary shown in the inbox.
    pub summary: String,
    /// Explanation shown to the person.
    pub reason: String,
    /// Choices for this specific question.
    pub suggestions: Vec<Suggestion>,
}

/// Disposition of an inbox thread.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum ThreadState {
    /// Waiting for a sorting decision.
    Sorting,
    /// Waiting for a person's answer.
    NeedsYou {
        /// Why the person is needed.
        reason: String,
        /// Choices offered in the inbox.
        suggestions: Vec<Suggestion>,
    },
    /// Work on the thread has been accounted for.
    Handled,
    /// No work will be started for this thread.
    Skipped {
        /// Explanation visible in the inbox.
        reason: String,
        /// Matching skip rule, if any.
        rule: Option<RuleId>,
    },
}

/// A choice offered to resolve a thread.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Suggestion {
    /// Requeue the original message after sorting recovered.
    SortAgain {
        /// Message to sort.
        message: MessageId,
    },
    /// Treat the person's original chat message as a question and return a task-backed answer.
    AnswerInChat,
    /// Prepare a reply for review.
    DraftReply {
        /// Proposed reply body.
        draft: String,
        /// Title for the approval task.
        task_title: String,
    },
    /// Put work on the board.
    MakeTask {
        /// Title for the new task.
        title: String,
    },
    /// Start an investigation into the message that prompted this question.
    Investigate,
    /// Apply the proposed use of one inbox message after a person confirms it.
    AcceptEvidence {
        /// Source message in the thread being answered.
        message: MessageId,
        /// Open task that would receive this evidence.
        task: Option<TaskId>,
        /// Assertion to save with the original message's provenance.
        fact: Option<String>,
    },
    /// Choose which immutable version of a topic file becomes current.
    ChooseFileRevision {
        /// Logical file name.
        path: String,
        /// Head displayed to the reviewer.
        current: u64,
        /// Competing offline revision.
        candidate: u64,
        /// Select the competing revision instead of retaining the displayed head.
        use_candidate: bool,
    },
    /// Resolve a specific pair of facts compared during reconciliation.
    ResolveFacts {
        /// Added or withdrawn assertion.
        changed: FactId,
        /// Other assertion under review.
        other: FactId,
        /// Person's resolution.
        resolution: FactResolution,
    },
    /// Skip this thread without creating work.
    Leave,
}

/// Choices offered when two facts need a person's judgment.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum FactResolution {
    /// The changed assertion supersedes the other.
    KeepChanged,
    /// The other assertion supersedes the changed one.
    KeepExisting,
    /// Both assertions are still valid.
    KeepBoth,
    /// The remaining assertion has independent evidence.
    KeepDependent,
    /// The remaining assertion lost its support.
    RetireDependent,
}

impl FactResolution {
    /// True when the changed assertion has already been withdrawn.
    pub fn withdrawal(self) -> bool {
        matches!(self, Self::KeepDependent | Self::RetireDependent)
    }
}

/// Result linked from a handled thread.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum Outcome {
    /// Related work on the board.
    Task(TaskId),
    /// Knowledge saved in the topic.
    Fact(FactId),
    /// File written in the topic.
    File(String),
    /// A reply to a message.
    Reply {
        /// Reply destination.
        to: Source,
        /// Reply body.
        text: String,
    },
    /// A free-form observation.
    Note(String),
}

/// Who owns the next step of work identified by the inbox.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum InboxAssignment {
    /// Answer a direct chat question via PostHog Tasks and return its result to the conversation.
    ChatAnswer,
    /// Delegate an investigation to the topic agent.
    Investigate,
    /// Run the named task-added automation.
    Routine(String),
    /// A decision for the person.
    Human,
    /// Work the topic agent picks up later in its own conversation, without a run of its own.
    Session,
}
