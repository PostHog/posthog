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
    /// Select the system sorter when a host cannot create remote workflows.
    pub async fn builtin_sorter(
        &self,
        topic: TopicId,
        watches: Option<Vec<Watch>>,
    ) -> Result<RoutineInfo> {
        if let Some(watches) = watches {
            self.update(topic, &Default::default(), |s, now| {
                Ok(s.state.set_routine_watches(
                    &s.state.topic.fallback.binding.id.clone(),
                    watches,
                    now,
                )?)
            })
            .await?;
        }
        self.read_topic(topic, |s| s.topic.fallback.clone())
    }
    /// Remote draft recovered or created during this topic's setup.
    pub fn default_flow(&self, topic: TopicId) -> Result<Option<String>> {
        Ok(self.slot(topic)?.saved.read().default_flow.clone())
    }
    /// Remember which draft setup owns before binding or updating it.
    pub async fn remember_default_flow(&self, topic: TopicId, flow: &str) -> Result<()> {
        self.update(topic, &Default::default(), |s, _| {
            if s.default_flow
                .as_ref()
                .is_some_and(|previous| previous != flow)
            {
                return Err(anyhow::anyhow!("Default workflow changed during setup").into());
            }
            s.default_flow = Some(flow.into());
            Ok(vec![])
        })
        .await?;
        Ok(())
    }

    /// Reserve the remote create before sending. A resumed attempt must locate the existing draft.
    pub async fn claim_default_create(&self, topic: TopicId) -> Result<bool> {
        if self.slot(topic)?.saved.read().default_create_claimed {
            return Ok(false);
        }
        let mut acquired = false;
        self.update(topic, &Default::default(), |s, _| {
            acquired = !s.default_create_claimed && s.default_sort_request.is_some();
            s.default_create_claimed = true;
            Ok(vec![])
        })
        .await?;
        Ok(acquired)
    }
    /// Retry a remote create after a definite rejection or connection failure before sending.
    pub async fn release_default_create(&self, topic: TopicId) -> Result<()> {
        self.update(topic, &Default::default(), |s, _| {
            s.default_create_claimed = false;
            Ok(vec![])
        })
        .await?;
        Ok(())
    }

    /// A prepared default graph can resume activation without resetting the remote flow to draft.
    pub fn prepared_default_sort(&self, topic: TopicId) -> Result<Option<RoutineBinding>> {
        let slot = self.slot(topic)?;
        let s = slot.saved.read();
        Ok(s.state
            .topic
            .routines
            .iter()
            .find(|r| {
                r.binding.id == "default:sort-inbox"
                    && s.default_flow.as_ref() == Some(&r.binding.external_id)
                    && s.routines
                        .get(&r.binding.id)
                        .is_some_and(|r| r.observation_only)
            })
            .map(|r| r.binding.clone()))
    }

    /// Enroll a restored topic that predates automatic workflow provisioning.
    pub async fn enroll_legacy_default(&self, topic: TopicId) -> Result<()> {
        fn eligible(s: &StoredTopic) -> bool {
            !s.state.archived
                && !s.state.deleted
                && !s.default_sort_removed
                && s.default_sort_request.is_none()
                && s.default_flow.is_none()
                && s.state.topic.default_sort.is_none()
                && !s.routines.contains_key("default:sort-inbox")
        }
        if self.0.setup.load(std::sync::atomic::Ordering::SeqCst)
            && eligible(&self.slot(topic)?.saved.read())
        {
            self.update(topic, &Default::default(), |s, _| {
                if eligible(s) {
                    s.default_sort_request = Some(id());
                }
                Ok(vec![])
            })
            .await?;
        }
        Ok(())
    }

    /// Whether this topic was created with a pending hosted inbox workflow.
    pub fn default_sort_pending(&self, topic: TopicId) -> Result<bool> {
        Ok(self
            .slot(topic)?
            .saved
            .read()
            .default_sort_request
            .is_some())
    }

    /// Request activation once and transfer subscriptions after confirmed delivery.
    pub async fn activate_default_sort(
        &self,
        topic: TopicId,
        binding: &RoutineBinding,
    ) -> Result<()> {
        let Some(request) = self.slot(topic)?.saved.read().default_sort_request else {
            return Ok(());
        };
        let activated = match self
            .request_routine_activation(topic, binding, request, Some(vec![]))
            .await
        {
            Ok(task) => task.result.as_deref() == Some("Activated Sort inbox."),
            Err(Error::Topic(TopicError::ActionDenied(_))) => false,
            Err(e) => return Err(e),
        };
        if activated {
            self.update(topic, &Default::default(), |s, now| {
                if s.default_sort_request.take().is_none() {
                    return Ok(vec![]);
                }
                let changes = s.state.install_default_sort(&binding.id, now)?;
                s.release_default_observations(&binding.id, now)?;
                Ok(changes)
            })
            .await?;
        }
        Ok(())
    }
}
