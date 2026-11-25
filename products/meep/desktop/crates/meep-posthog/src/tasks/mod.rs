//! Cloud Tasks API. An embedding host supplies the API origin, project and access token.
pub mod artifacts;
mod conversation;
use anyhow::{Context as _, Result, bail, ensure};
pub use conversation::{ConversationPage, LogWindow};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use uuid::Uuid;

/// A PostHog cloud task and its most recent run.
#[derive(Debug, Serialize, Deserialize)]
pub struct Task {
    /// PostHog task identifier.
    pub id: Uuid,
    /// Display title assigned to the task.
    pub title: Option<String>,
    /// Task prompt or description.
    pub description: Option<String>,
    /// Current task status supplied by PostHog.
    pub status: Option<String>,
    /// Latest run when the task has been started.
    pub latest_run: Option<Run>,
}

/// A single attempt to execute a cloud task.
#[derive(Debug, Serialize, Deserialize)]
pub struct Run {
    /// Model selected for this run.
    pub model: Option<String>,
    /// Creation timestamp returned by the service.
    pub created_at: Option<String>,
    /// PostHog run identifier.
    pub id: Uuid,
    /// Execution status supplied by the service.
    pub status: Option<String>,
    /// Error detail when the execution failed.
    pub error_message: Option<String>,
}

/// Even an unsuccessful dispatch can persist a run. Retain its ID for inspection.
#[derive(Debug, Serialize, Deserialize)]
pub struct Started {
    /// Persisted run, if the dispatch created one.
    pub run: Option<Run>,
    /// Dispatch failure reported alongside the run.
    pub run_error: Option<String>,
}

/// One page of tasks in service order.
#[derive(Debug, Serialize, Deserialize)]
pub struct TaskPage {
    /// Tasks returned for the requested offset.
    pub results: Vec<Task>,
}

/// A saved discussion message attached to a task.
#[derive(Debug, Serialize, Deserialize)]
pub struct ThreadMessage {
    /// Creation timestamp returned by the service.
    pub created_at: Option<String>,
    /// Saved message identifier.
    pub id: Uuid,
    /// Kind of author reported by PostHog.
    pub author_kind: String,
    /// Message body.
    pub content: String,
}

/// A model available for a task run.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Model {
    /// Model ID used in start requests.
    pub model: String,
    /// Human-readable model label.
    pub display_name: String,
    /// Adapter responsible for running the model.
    pub runtime_adapter: Option<String>,
    /// Reasoning effort choices advertised by the adapter.
    #[serde(default)]
    pub supported_efforts: Vec<String>,
}

impl Model {
    /// Whether PostHog's agent runtime imports external MCP tools for this model.
    pub fn supports_imported_mcp(&self) -> bool {
        self.runtime_adapter.as_deref() == Some("claude") && !excludes_imported_mcp(&self.model)
    }
}

/// Effective PostHog Tasks preference for the signed-in user and project.
#[derive(Clone, Debug, Default, Deserialize)]
pub struct RunDefaults {
    /// Task harness, normally `acp` or `pi`.
    #[serde(default)]
    pub runtime: String,
    /// ACP adapter, if a preference has one.
    pub runtime_adapter: Option<String>,
    /// Preferred model, or none if no preference is configured.
    pub model: Option<String>,
    /// Preferred reasoning effort.
    pub reasoning_effort: Option<String>,
}

/// How a view authoring turn runs.
#[derive(Clone, Copy, Debug, Default)]
pub struct Authoring<'a> {
    /// Model ID; `None` picks the default Claude model.
    pub model: Option<&'a str>,
    /// Reasoning effort the model advertises.
    pub effort: Option<&'a str>,
    /// Staged attachment IDs for this turn.
    pub artifacts: &'a [String],
}

/// Models for which PostHog's Claude adapter does not import external MCP servers.
pub fn excludes_imported_mcp(model: &str) -> bool {
    model == "claude-haiku-4-5"
}

/// A page of execution attempts for a single task.
#[derive(Debug, Serialize, Deserialize)]
pub struct RunPage {
    /// Runs returned for this page.
    pub results: Vec<Run>,
    /// Next page URL, when further results are available.
    pub next: Option<String>,
}

/// One page of events from a run's session log.
#[derive(Debug, Serialize, Deserialize)]
pub struct LogPage {
    /// Events in server order.
    pub entries: Vec<Value>,
    /// Whether a subsequent page may contain more entries.
    pub has_more: bool,
}

pub use crate::api::ApiError;
use crate::api::ProjectEndpoint;

/// Parameters for starting an interactive turn.
#[derive(Default)]
pub struct NewTurn<'a> {
    /// Run to resume when continuing an earlier attempt.
    pub previous: Option<Uuid>,
    /// Requested model ID or the service default.
    pub model: Option<&'a str>,
    /// User message queued for the new turn.
    pub text: Option<&'a str>,
    /// IDs of artifacts already staged for this turn.
    pub artifacts: &'a [String],
    /// Topic tools (endpoint URL and run-scoped bearer) for a resumed run. A resume
    /// starts a new run, which does not inherit the previous run's MCP servers.
    pub mcp: Option<(&'a str, &'a str)>,
}

/// Project-scoped client for PostHog cloud tasks.
#[derive(Clone)]
pub struct Tasks {
    api: ProjectEndpoint,
}

impl Tasks {
    /// Open the task collection for a numeric project.
    pub fn new(origin: &str, project: u64) -> Result<Self> {
        Ok(Self {
            api: ProjectEndpoint::new(origin, project, "tasks")?,
        })
    }
    /// Use the current project of the authenticated account.
    pub fn current(origin: &str) -> Result<Self> {
        Ok(Self {
            api: ProjectEndpoint::current(origin, "tasks")?,
        })
    }
    /// Fetch up to 25 tasks starting at the given offset.
    pub async fn list(&self, token: &str, offset: usize) -> Result<TaskPage> {
        self.api
            .get(token, &format!("?limit=25&offset={offset}"))
            .await
    }

    /// Retrieve one task by ID.
    pub async fn task(&self, token: &str, task: Uuid) -> Result<Task> {
        self.api.get(token, &format!("{task}/")).await
    }

    /// Create a task from a prompt and leave it ready to start.
    pub async fn create(&self, token: &str, prompt: &str) -> Result<Task> {
        self.create_with_origin(token, prompt, None).await
    }

    /// Create a task with an optional `origin_product`, leaving it ready to start.
    pub async fn create_with_origin(
        &self,
        token: &str,
        prompt: &str,
        origin_product: Option<&str>,
    ) -> Result<Task> {
        self.create_with_runtime(token, prompt, origin_product, None, None)
            .await
    }

    /// Create a task using the specified PostHog harness when one is configured.
    /// PostHog names the task with AI, from `naming` when given (the person's brief)
    /// or else from the full description.
    pub async fn create_with_runtime(
        &self,
        token: &str,
        prompt: &str,
        origin_product: Option<&str>,
        runtime: Option<&str>,
        naming: Option<&str>,
    ) -> Result<Task> {
        ensure!(!prompt.trim().is_empty(), "Task description is empty");
        let mut body = json!({"description":prompt,"start_run":false});
        if let Some(naming) = naming.map(str::trim).filter(|n| !n.is_empty()) {
            body["naming_source"] = json!(naming);
        }
        if let Some(runtime) = runtime {
            body["runtime"] = json!(runtime);
        }
        if let Some(origin) = origin_product {
            body["origin_product"] = json!(origin);
        }
        self.api.post(token, "", body).await
    }

    /// Fetch the signed-in user's effective PostHog Tasks defaults.
    pub async fn run_defaults(&self, token: &str) -> Result<RunDefaults> {
        #[derive(Deserialize)]
        struct Config {
            resolved_ai_run_defaults: RunDefaults,
        }
        Ok(self
            .api
            .get::<Config>(token, "@me/config/")
            .await?
            .resolved_ai_run_defaults)
    }

    /// Resolve an explicit choice or the highest Claude family available in catalogue order.
    pub async fn resolve_model(&self, token: &str, chosen: Option<&str>) -> Result<Model> {
        let models = self.models(token).await?;
        if let Some(id) = chosen {
            return models
                .into_iter()
                .find(|m| m.model == id)
                .with_context(|| format!("PostHog does not offer {id}"));
        }
        models
            .into_iter()
            .filter(|m| m.runtime_adapter.as_deref() == Some("claude"))
            .min_by_key(|m| {
                if m.model.contains("opus") {
                    0
                } else if m.model.contains("sonnet") {
                    1
                } else {
                    2
                }
            })
            .context("PostHog offers no Claude model")
    }

    /// Start a topic run with its selected runtime and billing preferences.
    pub async fn start_configured(
        &self,
        token: &str,
        task: Uuid,
        model: &Model,
        mcp: Option<(&str, &str)>,
        effort: Option<&str>,
        billing: Option<&str>,
    ) -> Result<Started> {
        self.start_with_optional_model(token, task, Some(model), mcp, effort, billing)
            .await
    }

    /// Start a topic run, allowing PostHog to choose its model when none is configured.
    pub async fn start_with_optional_model(
        &self,
        token: &str,
        task: Uuid,
        model: Option<&Model>,
        mcp: Option<(&str, &str)>,
        effort: Option<&str>,
        billing: Option<&str>,
    ) -> Result<Started> {
        let mut body = json!({"mode":"interactive"});
        if let Some(model) = model {
            body["model"] = json!(model.model);
            if let Some(adapter) = &model.runtime_adapter {
                body["runtime_adapter"] = json!(adapter);
            }
        }
        if let Some(effort) = effort {
            body["reasoning_effort"] = json!(effort);
        }
        if let Some(billing) = billing {
            ensure!(
                model.is_some_and(|m| m.runtime_adapter.as_deref() == Some("codex"))
                    && matches!(billing, "posthog-gateway" | "own-subscription"),
                "Choose a Codex model for ChatGPT billing"
            );
            body["codex_model_access"] = json!(billing);
        }
        if let Some((url, bearer)) = mcp
            && model.is_none_or(Model::supports_imported_mcp)
        {
            body["imported_mcp_servers"] = json!([imported_mcp("meep-topic", url, bearer)]);
            unattended(&mut body, model.and_then(|m| m.runtime_adapter.as_deref()));
        }
        self.api.post(token, &format!("{task}/run/"), body).await
    }

    /// List the models available to the account.
    pub async fn models(&self, token: &str) -> Result<Vec<Model>> {
        #[derive(Deserialize)]
        struct Catalogue {
            models: Vec<Model>,
        }
        Ok(self.api.get::<Catalogue>(token, "models/").await?.models)
    }

    /// Start a new interactive run with the service defaults.
    pub async fn start(&self, token: &str, task: Uuid) -> Result<Started> {
        self.start_turn(token, task, NewTurn::default()).await
    }
    /// Start a new interactive run with a specific model.
    pub async fn start_with_model(&self, token: &str, task: Uuid, model: &str) -> Result<Started> {
        ensure!(!model.trim().is_empty(), "Model ID is empty");
        self.start_turn(
            token,
            task,
            NewTurn {
                model: Some(model),
                ..Default::default()
            },
        )
        .await
    }
    /// Start or resume an interactive run, optionally attaching staged artifacts.
    pub async fn start_turn(&self, token: &str, task: Uuid, turn: NewTurn<'_>) -> Result<Started> {
        self.start_turn_with_effort(token, task, turn, None).await
    }

    /// Start or resume a turn with an optional reasoning effort.
    pub async fn start_turn_with_effort(
        &self,
        token: &str,
        task: Uuid,
        turn: NewTurn<'_>,
        effort: Option<&str>,
    ) -> Result<Started> {
        let mut body = json!({"mode":"interactive"});
        if let Some(value) = effort {
            body["reasoning_effort"] = json!(value);
        }
        if let Some(id) = turn.previous {
            body["resume_from_run_id"] = json!(id);
        }
        if let Some((url, bearer)) = turn.mcp
            && !turn.model.is_some_and(excludes_imported_mcp)
        {
            body["imported_mcp_servers"] = json!([imported_mcp("meep-topic", url, bearer)]);
        }
        if let Some(model) = turn.model {
            body["model"] = json!(model);
            if turn.previous.is_some()
                && let Some(runtime) = self
                    .resolve_model(token, Some(model))
                    .await?
                    .runtime_adapter
            {
                body["runtime_adapter"] = json!(runtime);
            }
        }
        if body.get("imported_mcp_servers").is_some() {
            let adapter = body
                .get("runtime_adapter")
                .and_then(Value::as_str)
                .map(str::to_owned);
            unattended(&mut body, adapter.as_deref());
        }
        if let Some(text) = turn.text {
            body["pending_user_message"] = json!(text);
        }
        if !turn.artifacts.is_empty() {
            body["pending_user_artifact_ids"] = json!(turn.artifacts);
        }
        self.api.post(token, &format!("{task}/run/"), body).await
    }

    /// Start a cloud authoring turn with a run-scoped Streamable HTTP MCP server,
    /// on the chosen Claude model and effort, with any staged attachments.
    #[allow(clippy::too_many_arguments)]
    pub async fn author(
        &self,
        token: &str,
        task: Uuid,
        previous: Option<Uuid>,
        prompt: &str,
        url: &str,
        bearer: &str,
        turn: Authoring<'_>,
    ) -> Result<Started> {
        let mut body = json!({"mode":"interactive","imported_mcp_servers":[imported_mcp("meep-view",url,bearer)]});
        self.claude_runtime(token, &mut body, turn.model).await?;
        if let Some(effort) = turn.effort {
            body["reasoning_effort"] = json!(effort);
        }
        if !turn.artifacts.is_empty() {
            body["pending_user_artifact_ids"] = json!(turn.artifacts);
        }
        if let Some(previous) = previous {
            body["resume_from_run_id"] = json!(previous);
            body["pending_user_message"] = json!(prompt);
        }
        self.api.post(token, &format!("{task}/run/"), body).await
    }

    /// Start a new interactive run that can call one run-scoped Streamable HTTP MCP server.
    pub async fn start_with_mcp(
        &self,
        token: &str,
        task: Uuid,
        name: &str,
        url: &str,
        bearer: &str,
    ) -> Result<Started> {
        self.start_with_mcp_model(token, task, name, url, bearer, None)
            .await
    }

    /// Start a run that can call one run-scoped MCP server, on a chosen Claude-runtime
    /// model or, with `None`, the signed-in user's PostHog default.
    pub async fn start_with_mcp_model(
        &self,
        token: &str,
        task: Uuid,
        name: &str,
        url: &str,
        bearer: &str,
        model: Option<&str>,
    ) -> Result<Started> {
        ensure!(!name.trim().is_empty(), "MCP server name is empty");
        let mut body =
            json!({"mode":"interactive","imported_mcp_servers":[imported_mcp(name,url,bearer)]});
        self.claude_runtime(token, &mut body, model).await?;
        self.api.post(token, &format!("{task}/run/"), body).await
    }

    /// PostHog loads imported MCP servers only into Claude-runtime runs, and a
    /// selected model must support imported tools; with no choice, PostHog resolves its default.
    async fn claude_runtime(
        &self,
        token: &str,
        body: &mut Value,
        chosen: Option<&str>,
    ) -> Result<()> {
        if let Some(chosen) = chosen {
            let model = self.resolve_model(token, Some(chosen)).await?;
            ensure!(
                model.supports_imported_mcp(),
                "Building a view needs a Claude model that can use Meep's tools"
            );
            body["runtime_adapter"] = json!("claude");
            body["model"] = json!(model.model);
        } else {
            let defaults = self.run_defaults(token).await?;
            if let Some(model) = &defaults.model {
                ensure!(
                    defaults.runtime != "pi"
                        && defaults.runtime_adapter.as_deref() == Some("claude")
                        && !excludes_imported_mcp(model),
                    "Your PostHog default cannot use Meep view tools. Choose a supported Claude model for this view."
                );
            }
            // With no preference, let PostHog choose its own fallback.
        }
        Ok(())
    }

    /// Resume a run with a follow-up message.
    pub async fn resume(
        &self,
        token: &str,
        task: Uuid,
        previous: Uuid,
        message: &str,
    ) -> Result<Started> {
        self.resume_with_model(token, task, previous, message, None)
            .await
    }

    /// Resume a run with a follow-up message and optional model override.
    pub async fn resume_with_model(
        &self,
        token: &str,
        task: Uuid,
        previous: Uuid,
        message: &str,
        model: Option<&str>,
    ) -> Result<Started> {
        self.resume_with_tools(token, task, previous, message, model, None)
            .await
    }

    /// Resume a run with a follow-up message, an optional model and the topic tools.
    pub async fn resume_with_tools(
        &self,
        token: &str,
        task: Uuid,
        previous: Uuid,
        message: &str,
        model: Option<&str>,
        mcp: Option<(&str, &str)>,
    ) -> Result<Started> {
        ensure!(!message.trim().is_empty(), "Follow-up is empty");
        self.start_turn(
            token,
            task,
            NewTurn {
                previous: Some(previous),
                text: Some(message),
                model,
                mcp,
                ..Default::default()
            },
        )
        .await
    }

    /// Read run history one bounded page at a time, newest first.
    pub async fn runs(&self, token: &str, task: Uuid, offset: usize) -> Result<RunPage> {
        self.api
            .get(token, &format!("{task}/runs/?limit=50&offset={offset}"))
            .await
    }

    /// Fetch the current state of a specific run.
    pub async fn run(&self, token: &str, task: Uuid, run: Uuid) -> Result<Run> {
        self.api.get(token, &format!("{task}/runs/{run}/")).await
    }

    /// Persist a discussion message on the task independently of any running agent.
    pub async fn comment(&self, token: &str, task: Uuid, content: &str) -> Result<ThreadMessage> {
        ensure!(!content.trim().is_empty(), "Comment is empty");
        self.api
            .post(
                token,
                &format!("{task}/thread_messages/"),
                json!({"content":content}),
            )
            .await
    }

    /// List the task's saved discussion messages.
    pub async fn thread(&self, token: &str, task: Uuid) -> Result<Vec<ThreadMessage>> {
        self.api
            .get(token, &format!("{task}/thread_messages/"))
            .await
    }

    /// Queue a user message on an active run with a caller-owned request ID.
    pub async fn message(
        &self,
        token: &str,
        task: Uuid,
        run: Uuid,
        message: &str,
        request_id: Uuid,
    ) -> Result<()> {
        ensure!(!message.trim().is_empty(), "Follow-up is empty");
        self.command(
            token,
            task,
            run,
            request_id,
            "user_message",
            json!({"content":message}),
        )
        .await?;
        Ok(())
    }

    /// Send one command to the run. A failed or ambiguous write is never replayed.
    pub async fn command(
        &self,
        token: &str,
        task: Uuid,
        run: Uuid,
        id: Uuid,
        method: &str,
        params: Value,
    ) -> Result<Value> {
        let response: Value = self
            .api
            .post(
                token,
                &format!("{task}/runs/{run}/command/"),
                json!({"jsonrpc":"2.0","id":id,"method":method,"params":params}),
            )
            .await?;
        if let Some(error) = response.get("error").filter(|e| !e.is_null()) {
            bail!(
                "PostHog command failed: {}",
                error
                    .get("message")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown command error")
            );
        }
        let result = response
            .get("result")
            .ok_or_else(|| anyhow::anyhow!("PostHog returned no command result"))?;
        if method == "user_message" {
            ensure!(
                result["queued"] == true,
                "PostHog did not confirm queuing the message. Inspect the run before resending."
            );
        }
        Ok(result.clone())
    }

    /// Request cancellation and return the resulting run state.
    pub async fn cancel(&self, token: &str, task: Uuid, run: Uuid) -> Result<Run> {
        self.api
            .post(token, &format!("{task}/runs/{run}/cancel/"), json!({}))
            .await
    }

    /// Fetch up to 200 session log events at the supplied offset.
    pub async fn logs(&self, token: &str, task: Uuid, run: Uuid, offset: usize) -> Result<LogPage> {
        let path = format!("{task}/runs/{run}/session_logs/?limit=200&offset={offset}");
        let response = self.api.get_response(token, &path).await?;
        let more = response
            .headers()
            .get("x-has-more")
            .and_then(|v| v.to_str().ok())
            .map(|v| v.eq_ignore_ascii_case("true"));
        let entries: Vec<Value> = response.json().await?;
        Ok(LogPage {
            has_more: more.unwrap_or(entries.len() == 200),
            entries,
        })
    }
}

fn imported_mcp(name: &str, url: &str, bearer: &str) -> Value {
    json!({"type":"http","name":name,"url":url,"headers":[{"name":"Authorization","value":format!("Bearer {bearer}")}]})
}

/// ACP text from a cloud run. A final message may repeat all previous chunks.
pub enum AssistantText<'a> {
    /// Incremental text to append to the current answer.
    Chunk(&'a str),
    /// Complete answer text from a final message.
    Final(&'a str),
}

/// A topic agent works without a person at the keyboard: its runs must not stop on
/// tool permission prompts that nobody answers. Meep's own approval for external actions
/// (`propose_action`) still applies. Codex runtimes already default to `auto`.
fn unattended(body: &mut Value, runtime_adapter: Option<&str>) {
    if runtime_adapter != Some("codex") {
        body["initial_permission_mode"] = json!("bypassPermissions");
    }
}

/// Extract assistant text from a session update event.
pub fn assistant_text(entry: &Value) -> Option<AssistantText<'_>> {
    let notify = entry.get("notification")?;
    if notify.get("method")?.as_str()? != "session/update" {
        return None;
    }
    let update = notify.pointer("/params/update")?;
    let text = update.pointer("/content/text")?.as_str()?;
    match update.get("sessionUpdate")?.as_str()? {
        "agent_message_chunk" => Some(AssistantText::Chunk(text)),
        "agent_message" => Some(AssistantText::Final(text)),
        _ => None,
    }
}
