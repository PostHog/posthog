use anyhow::Result;
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use meep_topic::{Action, Fact, Rule, Task};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Context captured when a worker takes or revises a task.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentRun {
    /// Name of the topic that owns the task.
    #[serde(default)]
    pub topic_name: String,
    /// Topic goals at the time the task starts.
    #[serde(default)]
    pub goals: Vec<meep_topic::Goal>,
    /// Passive references available as context; these do not enable monitoring.
    #[serde(default)]
    pub context_sources: Vec<meep_topic::Watch>,
    /// Sources watched by this topic.
    #[serde(default)]
    pub watches: Vec<meep_topic::Watch>,
    /// Automations available to this topic.
    #[serde(default)]
    pub routines: Vec<meep_topic::RoutineInfo>,
    /// Topic's responsibility.
    pub mission: String,
    /// Current, unsuperseded facts.
    pub facts: Vec<Fact>,
    /// Historical assertions available for resolving citations in tool-enabled briefs.
    #[serde(skip)]
    pub historical_facts: Vec<Fact>,
    /// Facts whose interpretation is awaiting human review.
    #[serde(default)]
    pub disputed_fact_ids: std::collections::BTreeSet<meep_topic::FactId>,
    /// Policy in precedence order.
    pub rules: Vec<Rule>,
    /// Task including previous results and revision notes.
    pub task: Task,
    /// Source conversation at launch, including the evidence behind the task.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thread: Option<meep_topic::Thread>,
    /// This run sets up a newly created topic for its mission.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub setup: bool,
    /// Time the worker started.
    pub started_at: DateTime<Utc>,
}

/// Agent-owned serializable token, saved until the run finishes.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct RunHandle(pub Value);

/// Latest observation of an agent run.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum RunState {
    /// Work continues.
    Running {
        /// Status shown on the board.
        progress: String,
    },
    /// Work has produced a proposed action for policy review.
    Submitted {
        /// Operation proposed by the agent.
        action: Action,
        /// Readable summary of the work.
        result: String,
        /// Optional editable text.
        draft: Option<String>,
    },
    /// Work finished without proposing an action.
    Done {
        /// Final result to keep on the task.
        result: String,
    },
    /// Finished investigation with recommendations for the task result.
    Findings {
        /// Evidence and conclusion of this task.
        result: String,
        /// Suggested next steps retained with the investigation.
        follow_ups: Vec<String>,
    },
    /// The run stopped with a diagnostic.
    Failed {
        /// Readable explanation retained in the log.
        error: String,
    },
}

/// A provider starts, resumes polling and answers questions on behalf of a topic.
/// A poll error is transient. Return `Failed` for a terminal provider failure.
#[async_trait]
pub trait Agent: Send + Sync {
    /// Whether this provider can take the task.
    fn can_take(&self, _task: &Task) -> bool {
        true
    }
    /// Whether this topic has an eligible provider for the task.
    fn can_take_for(&self, _topic: meep_topic::TopicId, task: &Task) -> bool {
        self.can_take(task)
    }
    /// Start using credentials granted to the owning topic.
    async fn start_for(&self, _topic: meep_topic::TopicId, run: AgentRun) -> Result<RunHandle> {
        self.start(run).await
    }
    /// Starts work with the full topic context.
    async fn start(&self, run: AgentRun) -> Result<RunHandle>;
    /// Reads the latest provider status for a saved handle.
    async fn poll(&self, handle: &RunHandle) -> Result<RunState>;
    /// Observe status and the transcript, when supported.
    async fn observe_task(
        &self,
        handle: &RunHandle,
        now: DateTime<Utc>,
    ) -> Result<(RunState, Option<meep_wire::TaskConversation>)> {
        Ok((self.poll_at(handle, now).await?, None))
    }
    /// The title the provider gave a started task, when it names tasks itself.
    async fn task_title(&self, _handle: &RunHandle) -> Result<Option<String>> {
        Ok(None)
    }
    /// Send a user turn to a running or finished investigation.
    async fn message_task(&self, _handle: &RunHandle, _text: &str) -> Result<RunHandle> {
        anyhow::bail!("Task messaging is unavailable")
    }
    /// Continue a task, optionally requesting another model.
    async fn message_task_on_model(
        &self,
        handle: &RunHandle,
        text: &str,
        model: Option<&str>,
    ) -> Result<RunHandle> {
        anyhow::ensure!(
            model.is_none(),
            "Provider does not support switching models"
        );
        self.message_task(handle, text).await
    }
    /// Continue an idle conversation in a new run that resumes this one.
    async fn resume_task(&self, handle: &RunHandle, text: &str) -> Result<RunHandle> {
        self.message_task_on_model(handle, text, None).await
    }
    /// Cancel an in-flight investigation at its provider.
    async fn cancel(&self, _handle: &RunHandle) -> Result<()> {
        anyhow::bail!("Provider does not support cancellation")
    }
    /// Polls with an explicit observation time. Time-driven fixture providers can override this.
    async fn poll_at(&self, handle: &RunHandle, _now: DateTime<Utc>) -> Result<RunState> {
        self.poll(handle).await
    }
    /// Execute the reviewed action with its edited draft on the proposing run.
    /// Return a handle whose final poll supplies the actual execution result.
    async fn execute(
        &self,
        _handle: &RunHandle,
        _task: &Task,
        _key: uuid::Uuid,
    ) -> Result<RunHandle> {
        anyhow::bail!("This agent cannot execute approved actions")
    }
    /// Deliver a reply through the source account using the stable delivery key.
    async fn reply(
        &self,
        _topic: meep_topic::TopicId,
        _message: &meep_topic::Message,
        _text: &str,
        _key: uuid::Uuid,
    ) -> Result<String> {
        anyhow::bail!("The source has no configured reply transport")
    }
}

pub(crate) struct NoAgent;
#[async_trait]
impl Agent for NoAgent {
    fn can_take(&self, _: &Task) -> bool {
        false
    }
    async fn start(&self, _: AgentRun) -> Result<RunHandle> {
        anyhow::bail!("No agent connected")
    }
    async fn poll(&self, _: &RunHandle) -> Result<RunState> {
        anyhow::bail!("No agent connected")
    }
}

#[cfg(any(test, feature = "fixtures"))]
pub use scripted::{FixtureAgent, Script};
#[cfg(any(test, feature = "fixtures"))]
mod scripted {
    use super::*;
    use chrono::TimeDelta;
    use serde_json::json;
    use std::collections::BTreeMap;
    /// Scripted work for a single task title.
    #[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
    pub struct Script {
        /// Time between starting and returning the outcome.
        pub delay: TimeDelta,
        /// Status while the delay elapses.
        pub progress: String,
        /// Result after the delay.
        pub outcome: RunState,
    }

    /// Deterministic agent. Unscripted work stays available for the person.
    #[derive(Clone, Debug, Default, Serialize, Deserialize)]
    pub struct FixtureAgent {
        scripts: BTreeMap<String, Script>,
    }

    impl FixtureAgent {
        /// Adds or replaces the script for an exact task title.
        pub fn script(&mut self, title: impl Into<String>, script: Script) {
            self.scripts.insert(title.into(), script);
        }
    }

    #[async_trait]
    impl Agent for FixtureAgent {
        async fn execute(&self, _: &RunHandle, task: &Task, _: uuid::Uuid) -> Result<RunHandle> {
            let label = &task
                .action
                .as_ref()
                .ok_or_else(|| anyhow::anyhow!("missing approved action"))?
                .label;
            Ok(RunHandle(json!({"script":Script {
                delay:TimeDelta::zero(), progress:"Executing".into(), outcome:RunState::Done {result:format!("Executed {label}: {}",task.draft.as_deref().unwrap_or_default())}
            }, "started": DateTime::<Utc>::UNIX_EPOCH})))
        }
        fn can_take(&self, task: &Task) -> bool {
            self.scripts.contains_key(&task.title)
        }
        async fn start(&self, run: AgentRun) -> Result<RunHandle> {
            let script = self
                .scripts
                .get(&run.task.title)
                .ok_or_else(|| anyhow::anyhow!("no script for {}", run.task.title))?;
            // Like PostHog, it names a task the person left untitled from its brief.
            let brief = run.task.instructions.as_deref().unwrap_or(&run.task.title);
            let name = run.task.untitled.then(|| format!("Named: {brief}"));
            Ok(RunHandle(
                json!({"script":script, "started":run.started_at, "name":name}),
            ))
        }
        async fn task_title(&self, handle: &RunHandle) -> Result<Option<String>> {
            Ok(handle.0["name"].as_str().map(str::to_owned))
        }
        async fn message_task(&self, handle: &RunHandle, text: &str) -> Result<RunHandle> {
            // A follow-up turn finishes at once, echoing what it was asked.
            let mut next = handle.0.clone();
            next["script"]["outcome"] = serde_json::to_value(RunState::Done {
                result: format!("Re: {text}"),
            })?;
            next["script"]["delay"] = serde_json::to_value(TimeDelta::zero())?;
            next["turn"] = json!(text);
            Ok(RunHandle(next))
        }
        async fn poll(&self, handle: &RunHandle) -> Result<RunState> {
            self.poll_at(handle, Utc::now()).await
        }
        async fn poll_at(&self, handle: &RunHandle, now: DateTime<Utc>) -> Result<RunState> {
            #[derive(Deserialize)]
            struct Saved {
                script: Script,
                started: DateTime<Utc>,
            }
            let Saved { script, started } = serde_json::from_value(handle.0.clone())?;
            Ok(if now.signed_duration_since(started) < script.delay {
                RunState::Running {
                    progress: script.progress,
                }
            } else {
                script.outcome
            })
        }
    }
}
