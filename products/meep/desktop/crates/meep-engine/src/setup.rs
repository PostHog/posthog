//! One setup conversation per new topic. It starts as a chat answer once an agent can
//! take work for the topic, so its turns and result appear in the topic's chat.
use super::*;

/// Progress of a topic's one-time setup.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub(crate) enum Setup {
    /// Not requested: topics created before setup existed or without host support.
    #[default]
    None,
    /// Waiting for an eligible agent.
    Pending,
    /// The setup conversation was opened with this chat-answer task.
    Started(TaskId),
}
impl Setup {
    pub(crate) fn is_none(&self) -> bool {
        *self == Self::None
    }
}

/// Title of the chat-answer task that carries the setup run.
pub const SETUP_TITLE: &str = "Set up this topic";
const SETUP_REQUEST: &str = "Set up this topic for its mission, respecting any limits the person stated. Suggest or make only changes appropriate for that mission.";

/// Open the setup conversation: a chat message and the chat-answer task that replies to it.
fn open(
    state: &mut TopicState,
    thread: ThreadId,
    task: TaskId,
    now: DateTime<Utc>,
) -> std::result::Result<Changes, TopicError> {
    let mut changes = state.receive(
        Message {
            id: MessageId(thread.0),
            producer: Producer::System,
            origin: Some(Source::User.into_origin("Meep".into(), now, None)),
            author: "Meep".into(),
            at: now,
            text: SETUP_REQUEST.into(),
            external_id: None,
        },
        thread.to_string(),
        thread,
        now,
    )?;
    changes.extend(state.add_requested_task(
        task,
        thread,
        SETUP_TITLE.into(),
        InboxAssignment::ChatAnswer,
        now,
    )?);
    changes.extend(state.sort(
        thread,
        Decision::Handle {
            summary: "Setting up this topic.".into(),
            outcomes: vec![Outcome::Task(task)],
        },
        now,
    )?);
    Ok(changes)
}

impl Engine {
    /// Open one setup conversation for every topic created after this call. The host enables
    /// it when its agent can configure topics. A topic waits until an agent can take its work.
    pub fn enable_topic_setup(&self) {
        self.set_topic_setup(true);
    }

    /// Choose whether topics created from now on get a setup conversation.
    /// Topics already waiting for setup keep their pending setup.
    pub fn set_topic_setup(&self, enabled: bool) {
        self.0
            .setup
            .store(enabled, std::sync::atomic::Ordering::SeqCst);
    }

    pub(crate) fn setup_due(&self, s: &StoredTopic) -> bool {
        if s.state.archived || s.state.deleted || s.setup != Setup::Pending {
            return false;
        }
        // Ask the agent about the exact task setup would add. A new topic's state is small.
        let mut scratch = s.state.clone();
        let (thread, task) = (ThreadId(Uuid::nil()), TaskId(Uuid::nil()));
        if open(&mut scratch, thread, task, self.0.clock.now()).is_err() {
            return false;
        }
        scratch
            .tasks
            .iter()
            .find(|t| t.id == task)
            .is_some_and(|probe| self.0.agent.can_take_for(s.state.topic.id, probe))
    }

    /// Open the setup conversation when it is due. The state change and the marker commit
    /// together, so a restart never opens a second one.
    pub(crate) async fn begin_setup(&self, topic: TopicId) -> Result<()> {
        if !self.setup_due(&self.slot(topic)?.saved.read()) {
            return Ok(());
        }
        self.update(topic, &Causality::default(), |s, now| {
            if s.state.archived || s.state.deleted || s.setup != Setup::Pending {
                return Ok(vec![]);
            }
            let task: TaskId = id();
            let changes = open(&mut s.state, id(), task, now)?;
            s.setup = Setup::Started(task);
            Ok(changes)
        })
        .await?;
        Ok(())
    }
}

impl StoredTopic {
    pub(super) fn default_activation(&self, task: TaskId, action: &Action) -> bool {
        self.default_sort_request == Some(task)
            && action.kind.0 == "routine-activate"
            && action.payload["routine"] == "default:sort-inbox"
    }
}

impl Engine {
    /// Whether this topic was created with a pending hosted inbox workflow.
    pub fn default_sort_pending(&self, topic: TopicId) -> Result<bool> {
        Ok(self
            .slot(topic)?
            .saved
            .read()
            .default_sort_request
            .is_some())
    }
}
