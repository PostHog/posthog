use crate::{Agent, AgentRun, RunHandle, RunState};
use anyhow::{Context, Result, ensure};
use async_trait::async_trait;

use meep_posthog::{chat::History, tasks::Tasks};
use serde_json::json;
use uuid::Uuid;

mod brief;

/// Environment variable naming the PostHog `origin_product` for Meep tasks. Unset or empty
/// sends none, so PostHog applies its default. Set it once PostHog accepts a Meep origin.
pub const TASK_ORIGIN_ENV: &str = "MEEP_TASK_ORIGIN";

/// Instructions attached to every Meep PostHog Tasks run: what Meep is, which tools change
/// it, the approval rules and the chat reply style. Maintained in `src/skill.md`.
/// PostHog Tasks has no per-run instructions field, so it leads each task description.
pub const MEEP_SKILL: &str = include_str!("skill.md");

/// Heading that separates the skill from a topic run's JSON context in a task description.
pub const RUN_CONTEXT_HEADING: &str = "## Run context";

/// What a Meep-created PostHog task works for.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TaskSubject {
    /// A topic run: agent task, chat answer or setup.
    Topic(meep_topic::TopicId),
    /// A workspace view authoring session.
    View(Uuid),
}
impl TaskSubject {
    /// The first line of every Meep task description, so tasks are attributable in PostHog.
    pub fn marker(self) -> String {
        match self {
            Self::Topic(id) => format!("[meep topic:{id}]"),
            Self::View(id) => format!("[meep view:{id}]"),
        }
    }
}

/// Agent backed by PostHog Tasks and its ACP session transcript.
/// The access token stays in this adapter. Persisted handles contain only task and run IDs.
pub struct PostHogAgent {
    tasks: Tasks,
    token: String,
    origin: Option<String>,
}

struct LaunchSelection<'a> {
    model: Option<&'a meep_posthog::tasks::Model>,
    runtime: Option<&'a str>,
    effort: Option<&'a str>,
    billing: Option<&'a str>,
    /// What PostHog names the task from: the person's brief, not the run context.
    naming: Option<&'a str>,
}

fn proposal(text: &str) -> Option<RunState> {
    text.match_indices('{').rev().find_map(|(offset, _)| {
        let parsed = serde_json::Deserializer::from_str(&text[offset..])
            .into_iter::<RunState>()
            .next()?
            .ok()?;
        matches!(
            parsed,
            RunState::Submitted { .. } | RunState::Findings { .. }
        )
        .then_some(parsed)
    })
}

impl PostHogAgent {
    /// Connects to the host's project using a token supplied by its credential store.
    pub fn new(origin: &str, project: u64, token: impl Into<String>) -> Result<Self> {
        Ok(Self {
            tasks: Tasks::new(origin, project)?,
            token: token.into(),
            origin: std::env::var(TASK_ORIGIN_ENV)
                .ok()
                .map(|v| v.trim().to_owned())
                .filter(|v| !v.is_empty()),
        })
    }

    /// Override the `origin_product` read from [`TASK_ORIGIN_ENV`]. `None` sends none.
    pub fn with_task_origin(mut self, origin: Option<&str>) -> Self {
        self.origin = origin.map(str::to_owned);
        self
    }

    /// The single place Meep creates PostHog Tasks. It prefixes the attribution marker and
    /// the Meep skill, and applies the configured origin.
    pub async fn create_task(
        &self,
        subject: TaskSubject,
        description: &str,
    ) -> Result<meep_posthog::tasks::Task> {
        self.create_task_with_runtime(subject, description, None, None)
            .await
    }

    async fn create_task_with_runtime(
        &self,
        subject: TaskSubject,
        description: &str,
        runtime: Option<&str>,
        naming: Option<&str>,
    ) -> Result<meep_posthog::tasks::Task> {
        let description = format!(
            "{}\n{}\n{description}",
            subject.marker(),
            MEEP_SKILL.trim_end()
        );
        self.tasks
            .create_with_runtime(
                &self.token,
                &description,
                self.origin.as_deref(),
                runtime,
                naming,
            )
            .await
    }

    async fn launch(
        &self,
        subject: TaskSubject,
        prompt: &str,
        mcp: Option<(&str, &str)>,
        selection: LaunchSelection<'_>,
    ) -> Result<RunHandle> {
        let task = self
            .create_task_with_runtime(subject, prompt, selection.runtime, selection.naming)
            .await?;
        let started = self
            .tasks
            .start_with_optional_model(
                &self.token,
                task.id,
                selection.model,
                mcp,
                selection.effort,
                selection.billing,
            )
            .await;
        // Keep PostHog's own refusal: it is what the person needs to see.
        let refusal = match &started {
            Ok(reply) => reply.run_error.clone(),
            Err(e) => Some(format!("{e:#}")),
        };
        let run = match started.ok().and_then(|reply| reply.run) {
            Some(run) => run,
            // A failed response can follow a successful start. Read this new
            // task's history before reporting an unconfirmed outcome.
            None => self
                .tasks
                .task(&self.token, task.id)
                .await
                .with_context(|| format!("Cannot verify the start of PostHog task {}", task.id))?
                .latest_run
                .with_context(|| match &refusal {
                    Some(why) => format!("PostHog did not start task {}: {why}", task.id),
                    None => format!(
                        "No run confirmed for PostHog task {}. Check its history before retrying.",
                        task.id
                    ),
                })?,
        };
        Ok(RunHandle(json!([task.id, run.id])))
    }

    /// Build or reshape a script view using a capability scoped to this turn.
    /// Start or continue authoring a view: the chosen model and effort, and the
    /// files the person attached, staged on the view's task before the run starts.
    #[allow(clippy::too_many_arguments)]
    pub async fn author_view(
        &self,
        view: Uuid,
        previous: Option<&RunHandle>,
        prompt: &str,
        url: &str,
        bearer: &str,
        model: Option<&str>,
        effort: Option<&str>,
        files: Vec<(String, Vec<u8>)>,
    ) -> Result<RunHandle> {
        let (task, resume) = if let Some(handle) = previous {
            let (task, run): (Uuid, Uuid) = serde_json::from_value(handle.0.clone())?;
            (task, Some(run))
        } else {
            let description = format!(
                "\n## This run\nBuild the requested view using the meep-view MCP. Read design_system and list_sources first. Inspect existing source, then publish validated JavaScript with write_view or patch_view. Choose a short title and emoji. Use live data. Report the result to the person.\n\n{prompt}"
            );
            (
                self.create_task(TaskSubject::View(view), &description)
                    .await?
                    .id,
                None,
            )
        };
        let mut artifacts = Vec::with_capacity(files.len());
        for (name, bytes) in files {
            artifacts.push(
                self.tasks
                    .upload_attachment_bytes(&self.token, task, None, &name, bytes)
                    .await
                    .with_context(|| format!("Could not attach {name}"))?,
            );
        }
        let result = self
            .tasks
            .author(
                &self.token,
                task,
                resume,
                prompt,
                url,
                bearer,
                meep_posthog::tasks::Authoring {
                    model,
                    effort,
                    artifacts: &artifacts,
                },
            )
            .await
            .map_err(|error| {
                if resume.is_some()
                    && error.downcast_ref::<meep_posthog::api::ApiError>().is_some_and(|e| {
                        e.status == 409 && e.detail == "This task already has a run in progress. Wait for it to finish or cancel it first."
                    })
                {
                    error.context("This authoring session is still open in PostHog. Start a new session, or finish the existing run in PostHog before trying again")
                } else {
                    error
                }
            })?;
        let run = result
            .run
            .context("PostHog did not confirm the view run. Inspect Tasks before retrying.")?;
        Ok(RunHandle(json!([task, run.id])))
    }

    /// Cancel a view authoring run the person stopped.
    pub async fn cancel_view(&self, handle: &RunHandle) -> Result<()> {
        let (task, run): (Uuid, Uuid) = serde_json::from_value(handle.0.clone())?;
        self.tasks.cancel(&self.token, task, run).await?;
        Ok(())
    }

    /// Read the provider observation and its decoded ACP transcript in one pass.
    pub async fn observe_run(&self, handle: &RunHandle) -> Result<(RunState, History)> {
        let (task, run): (Uuid, Uuid) = serde_json::from_value(handle.0.clone())?;
        let status = self.tasks.run(&self.token, task, run).await?;
        let progress = status.status.unwrap_or_else(|| "pending".into());
        let error = status.error_message.filter(|s| !s.trim().is_empty());
        if matches!(
            progress.as_str(),
            "failed" | "cancelled" | "canceled" | "error"
        ) || error.is_some()
        {
            return Ok((
                RunState::Failed {
                    error: error.unwrap_or(progress),
                },
                History::default(),
            ));
        }
        if matches!(progress.as_str(), "queued" | "pending" | "starting") {
            return Ok((RunState::Running { progress }, History::default()));
        }
        let history = self.history(task, run).await?;
        if history.stopped {
            return Ok((
                RunState::Failed {
                    error: "Run cancelled".into(),
                },
                history,
            ));
        }
        if matches!(
            progress.as_str(),
            "completed" | "done" | "finished" | "succeeded"
        ) || (history.completed_turns > 0 && history.busy == Some(false))
        {
            // The newest answer with words in it: a turn can end on a tool call.
            let text = history
                .turns()
                .iter()
                .rev()
                .filter(|t| t.role == "assistant")
                .map(|t| final_answer(t))
                .find(|answer| !answer.trim().is_empty());
            return Ok((
                match text {
                    Some(result) => proposal(&result).unwrap_or(RunState::Done { result }),
                    None => RunState::Failed {
                        error: "Run finished without assistant text".into(),
                    },
                },
                history,
            ));
        }
        Ok((RunState::Running { progress }, history))
    }

    async fn history(&self, task: Uuid, run: Uuid) -> Result<History> {
        let mut history = History::default();
        let mut offset = 0;
        loop {
            let page = self.tasks.logs(&self.token, task, run, offset).await?;
            offset += page.entries.len();
            for entry in &page.entries {
                history.apply(run, entry, None);
            }
            if !page.has_more {
                return Ok(history);
            }
            ensure!(
                !page.entries.is_empty(),
                "PostHog returned an empty continuing log page"
            );
        }
    }
    /// Start a topic run. With `mcp` (endpoint URL and run-scoped bearer), the run can read
    /// and change the topic through the `meep-topic` MCP server.
    pub async fn start_with_mcp(
        &self,
        topic: meep_topic::TopicId,
        context: AgentRun,
        mcp: Option<(&str, &str)>,
    ) -> Result<RunHandle> {
        self.start_on_model(topic, context, mcp, None).await
    }

    /// Start a topic run like [`Self::start_with_mcp`] on a chosen model, or on the
    /// service default with `None`.
    pub async fn start_on_model(
        &self,
        topic: meep_topic::TopicId,
        context: AgentRun,
        mcp: Option<(&str, &str)>,
        model: Option<&str>,
    ) -> Result<RunHandle> {
        let chosen = context.task.model.as_deref().or(model);
        let defaults = if chosen.is_none() {
            Some(self.tasks.run_defaults(&self.token).await?)
        } else {
            None
        };
        let resolved = if let Some(id) = chosen {
            Some(self.tasks.resolve_model(&self.token, Some(id)).await?)
        } else {
            defaults.as_ref().and_then(|d| {
                d.model.as_ref().map(|id| meep_posthog::tasks::Model {
                    model: id.clone(),
                    display_name: id.clone(),
                    runtime_adapter: d.runtime_adapter.clone(),
                    supported_efforts: vec![],
                })
            })
        };
        let runtime = defaults
            .as_ref()
            .and_then(|d| (d.runtime == "pi").then_some("pi"));
        let tools = mcp.is_some()
            && runtime.is_none()
            && resolved.as_ref().is_none_or(|m| m.supports_imported_mcp());
        let naming = context
            .task
            .instructions
            .clone()
            .filter(|b| !b.trim().is_empty())
            .unwrap_or_else(|| context.task.title.clone());
        let mut prompt = brief::run_context(&context, tools)?;
        prompt["instructions"] = if context.setup {
            json!(if tools {
                "This topic was just created. Read its mission and respect all limits the person stated, including instructions not to run workflows, watch sources, or change data. Do not treat setup as permission to override those limits. Use meep-topic tools to make only changes the mission supports: add goals only when appropriate. Context references are passive: never watch sources or create routines unless the person explicitly requests monitoring or automation. If the person's intent is unclear, ask rather than make a potentially conflicting change. Then reply in chat: what you set up and why, and what you need from the person. You are this topic's agent and this is the start of your one ongoing conversation with the person; later messages continue it here."
            } else if mcp.is_some() {
                "Set up the topic from the supplied context. This runtime has no imported Meep tools. Propose sources, goals and routines for the person to configure."
            } else {
                "This topic was just created, but this run has no meep-topic tools: the Meep server has no public address (MEEP_PUBLIC_BASE_URL is not set), so you cannot change the topic yourself. Say that in one sentence. Then propose how to set it up: the sources to watch, one to three measurable goals and any recurring work. Ask the person to make these changes in the app, or to configure MEEP_PUBLIC_BASE_URL so you can."
            })
        } else if context.task.assignment == Some(meep_topic::InboxAssignment::ChatAnswer) {
            json!(if tools {
                "You are this topic's agent and this is your one ongoing conversation with the person: later messages continue it here. Reply to the person's chat message. Answer from the topic context, explicitly referenced topics and the meep-topic read tools. When they ask for a change to the topic, make it with the meep-topic tools and report the result. A change to PostHog itself (a feature flag, experiment, insight, dashboard, survey or cohort) is an external action: never make it with the PostHog tools; propose it with propose_action on meep-topic and end your turn, and carry it out only after the person approves. Do the work in this conversation; create a task only as the skill describes."
            } else {
                "Reply to the person's chat message from the supplied topic context and explicitly referenced topics. This run has no Meep topic tools, so say so if asked to change the topic."
            })
        } else {
            json!(
                "Work on the task. Before performing any external action, call propose_action on meep-topic and stop. If tools are unavailable, return JSON in the form {\"Submitted\":{\"action\":{\"kind\":\"operation\",\"label\":\"...\",\"done_label\":\"...\",\"payload\":{}},\"result\":\"...\",\"draft\":null}} for review. Finish the requested outcome in this task, including setup and verification. Return a plain text result, or return {\"Findings\":{\"result\":\"conclusion\",\"follow_ups\":[\"independent deliverable\"]}} so the person can choose to create a separate task."
            )
        };
        prompt["meep_tools"] = json!(tools);
        if tools {
            prompt["tool_discovery"] = json!(
                "Search by keyword meep-topic or select an exact name such as mcp__meep-topic__get_topic. Only report tool unavailability after a failed tool call."
            );
        }
        prompt["evidence_instructions"] = json!(
            "Treat disputed_fact_ids as unsettled. You may investigate and report uncertainty. Every proposed external action must include action.depends_on_facts with the IDs of the topic facts it relies on, or [] for an independent action."
        );
        let prompt = format!(
            "\n{RUN_CONTEXT_HEADING}\n{}",
            serde_json::to_string_pretty(&prompt)?
        );
        self.launch(
            TaskSubject::Topic(topic),
            &prompt,
            mcp,
            LaunchSelection {
                model: resolved.as_ref(),
                runtime,
                effort: context.task.reasoning_effort.as_deref().or_else(|| {
                    defaults
                        .as_ref()
                        .and_then(|d| d.reasoning_effort.as_deref())
                }),
                billing: context.task.billing.as_deref(),
                naming: Some(naming.as_str()),
            },
        )
        .await
    }
}

#[async_trait]
impl Agent for PostHogAgent {
    async fn start_for(&self, topic: meep_topic::TopicId, context: AgentRun) -> Result<RunHandle> {
        self.start_with_mcp(topic, context, None).await
    }

    async fn start(&self, _: AgentRun) -> Result<RunHandle> {
        anyhow::bail!("PostHog tasks require an owning topic")
    }

    async fn execute(
        &self,
        handle: &RunHandle,
        task: &meep_topic::Task,
        key: Uuid,
    ) -> Result<RunHandle> {
        let (remote, previous): (Uuid, Uuid) = serde_json::from_value(handle.0.clone())?;
        let prompt = json!({"instructions":"Execute exactly the approved action with the reviewed draft. Report the actual result.","delivery_id":key,"action":task.action,"draft":task.draft}).to_string();
        let started = self
            .tasks
            .resume(&self.token, remote, previous, &prompt)
            .await?;
        let run = started.run.context(
            "PostHog did not confirm the approved run; inspect the task before retrying",
        )?;
        Ok(RunHandle(json!([remote, run.id])))
    }

    async fn observe_task(
        &self,
        handle: &RunHandle,
        _now: chrono::DateTime<chrono::Utc>,
    ) -> Result<(RunState, Option<meep_wire::TaskConversation>)> {
        let (state, history) = self.observe_run(handle).await?;
        let status = match &state {
            RunState::Running { progress } => progress.clone(),
            RunState::Failed { error } => error.clone(),
            _ => "completed".to_owned(),
        };
        let messages = history.turns().iter().map(|t| t.message.clone()).collect();
        Ok((
            state,
            Some(meep_wire::TaskConversation { status, messages }),
        ))
    }
    async fn message_task(&self, handle: &RunHandle, text: &str) -> Result<RunHandle> {
        self.message_task_on_model(handle, text, None).await
    }
    async fn message_task_on_model(
        &self,
        handle: &RunHandle,
        text: &str,
        model: Option<&str>,
    ) -> Result<RunHandle> {
        self.continue_with_tools(handle, text, model, None, false)
            .await
    }
    async fn resume_task(&self, handle: &RunHandle, text: &str) -> Result<RunHandle> {
        self.continue_with_tools(handle, text, None, None, true)
            .await
    }
    async fn task_title(&self, handle: &RunHandle) -> Result<Option<String>> {
        let (task, _run): (Uuid, Uuid) = serde_json::from_value(handle.0.clone())?;
        let title = self.tasks.task(&self.token, task).await?.title;
        Ok(title.filter(|t| !t.trim().is_empty()))
    }
    async fn cancel(&self, handle: &RunHandle) -> Result<()> {
        let (task, run) = serde_json::from_value(handle.0.clone())?;
        self.tasks.cancel(&self.token, task, run).await?;
        Ok(())
    }
    async fn poll(&self, handle: &RunHandle) -> Result<RunState> {
        Ok(self.observe_run(handle).await?.0)
    }
}

impl PostHogAgent {
    /// Queue a turn on an open run, or resume it as a new run when it finished or
    /// `fresh` asks for one.
    pub async fn continue_with_tools(
        &self,
        handle: &RunHandle,
        text: &str,
        model: Option<&str>,
        mcp: Option<(&str, &str)>,
        fresh: bool,
    ) -> Result<RunHandle> {
        let (task, run) = serde_json::from_value(handle.0.clone())?;
        let previous = self.tasks.run(&self.token, task, run).await?;
        let mut status = previous.status.unwrap_or_default();
        // Stop an idle live run so the next turn starts fresh with working tools.
        // If it cannot be stopped, the message is queued on it instead.
        if fresh && !terminal(&status) && self.tasks.cancel(&self.token, task, run).await.is_ok() {
            for _ in 0..20 {
                tokio::time::sleep(std::time::Duration::from_millis(500)).await;
                status = self
                    .tasks
                    .run(&self.token, task, run)
                    .await?
                    .status
                    .unwrap_or_default();
                if terminal(&status) {
                    break;
                }
            }
        }
        let mcp = mcp.filter(|_| {
            !model
                .or(previous.model.as_deref())
                .is_some_and(meep_posthog::tasks::excludes_imported_mcp)
        });
        if model.is_some() || terminal(&status) {
            let started = self
                .tasks
                .resume_with_tools(&self.token, task, run, text, model, mcp)
                .await?;
            return Ok(RunHandle(json!([
                task,
                started.run.context("No resumed run confirmed")?.id
            ])));
        }
        self.tasks
            .message(&self.token, task, run, text, Uuid::new_v4())
            .await?;
        Ok(handle.clone())
    }
}

/// The turn's answer. Agents often write a line before working and a full answer after;
/// when the last text says as much as everything before it, that is the answer.
fn final_answer(turn: &meep_posthog::chat::Turn) -> String {
    let blocks: Vec<(&str, &str)> = turn
        .blocks
        .iter()
        .map(|b| (b.kind.as_str(), b.text.as_str()))
        .collect();
    final_text(&blocks, &turn.text)
}

/// The reply a turn ends with: the text after its last tool call. Narration before
/// that ("Let me check…") and a restated answer are left out, so the person sees
/// one answer, not the agent thinking aloud or saying it twice.
fn final_text(blocks: &[(&str, &str)], whole: &str) -> String {
    let tail = blocks
        .iter()
        .rposition(|(kind, _)| *kind != "text" && *kind != "thinking")
        .map_or(0, |i| i + 1);
    let texts: Vec<&str> = blocks[tail..]
        .iter()
        .filter(|(kind, text)| *kind == "text" && !text.trim().is_empty())
        .map(|(_, text)| text.trim())
        .collect();
    let opening = |t: &str| t.chars().take(24).collect::<String>();
    match texts.split_last() {
        None if blocks.is_empty() => whole.to_owned(),
        None => blocks
            .iter()
            .rev()
            .find(|(kind, text)| *kind == "text" && !text.trim().is_empty())
            .map_or_else(|| whole.to_owned(), |(_, text)| text.trim().to_owned()),
        Some((last, [])) => (*last).to_owned(),
        Some((last, earlier)) => {
            let before: usize = earlier.iter().map(|t| t.len()).sum();
            if last.len() >= before || earlier.iter().any(|e| opening(e) == opening(last)) {
                (*last).to_owned()
            } else {
                texts.join("\n\n")
            }
        }
    }
}

fn terminal(status: &str) -> bool {
    matches!(
        status,
        "completed"
            | "done"
            | "finished"
            | "succeeded"
            | "failed"
            | "cancelled"
            | "canceled"
            | "error"
    )
}

#[cfg(test)]
mod tests;
