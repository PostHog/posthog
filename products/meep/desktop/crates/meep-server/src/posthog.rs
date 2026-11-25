mod workflow_details;
use crate::{accounts::Accounts, vault::Secrets};
use anyhow::{Context, Result, bail, ensure};
use async_trait::async_trait;
use meep_engine::{
    Agent, AgentRun, PostHogAgent, PostHogRoutines, RoutineBackend, RoutineContext, RoutineRun,
    RunHandle, RunState,
};
use meep_posthog::{
    api::ProjectEndpoint,
    oauth::{Callback, RefreshToken, Server, TokenResponse},
};
use meep_topic::{RoutineBinding, RoutineHealth, Task, Topic, TopicId};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use uuid::Uuid;
pub(crate) use workflow_details::fires_sentence;

pub(crate) struct Project {
    pub origin: String,
    pub project: u64,
    pub agent: PostHogAgent,
    pub routines: PostHogRoutines,
    health: ProjectEndpoint,
    pub(crate) token: String,
}
impl Project {
    pub fn from_secrets(values: &Secrets) -> Result<Self> {
        let token = values
            .get("access_token")
            .filter(|s| !s.trim().is_empty())
            .context("Missing PostHog access_token")?
            .clone();
        let region = values.get("region").context("Missing PostHog region")?;
        let origin = match region.as_str() {
            "us" | "US" => "https://us.posthog.com",
            "eu" | "EU" => "https://eu.posthog.com",
            value => value,
        }
        .to_owned();
        let project = values
            .get("project_id")
            .context("Missing PostHog project_id")?
            .parse()?;
        Ok(Self {
            agent: PostHogAgent::new(&origin, project, &token)?,
            routines: PostHogRoutines::new(&origin, project, &token)?,
            health: ProjectEndpoint::new(&origin, project, "tasks")?,
            origin,
            project,
            token,
        })
    }
    pub async fn mcp_store(
        &self,
        request: meep_wire::mcp_store::Operation,
    ) -> Result<meep_wire::mcp_store::Outcome> {
        meep_posthog::mcp::store::execute(&self.origin, self.project, &self.token, request).await
    }
    pub async fn user_uuid(&self) -> Result<uuid::Uuid> {
        #[derive(serde::Deserialize)]
        struct User {
            uuid: uuid::Uuid,
        }
        let user: User = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(std::time::Duration::from_secs(3))
            .build()?
            .get(format!("{}/api/users/@me/", self.origin))
            .bearer_auth(&self.token)
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        Ok(user.uuid)
    }
    pub async fn check(&self) -> Result<()> {
        self.health.get_response(&self.token, "?limit=1").await?;
        Ok(())
    }
    pub async fn refresh(&self, old: &Secrets) -> Result<Secrets> {
        let id = old
            .get("client_id")
            .context("Missing original OAuth client ID")?;
        let refresh = old.get("refresh_token").context("Missing refresh token")?;
        let server = Server::discover(&self.origin).await?;
        let client = server.client(id.clone(), &Callback::bind(0).await?)?;
        let tokens = client.refresh(&RefreshToken::new(refresh.clone())).await?;
        let mut values = old.clone();
        values.insert(
            "access_token".into(),
            tokens.access_token().secret().clone(),
        );
        if let Some(rotated) = tokens.refresh_token() {
            values.insert("refresh_token".into(), rotated.secret().clone());
        }
        Ok(values)
    }
}

#[derive(Serialize, Deserialize)]
pub(crate) struct AccountRun {
    connection: String,
    pub topic: TopicId,
    project: u64,
    origin: String,
    handle: RunHandle,
    /// Fingerprint of the topic MCP capability issued to this run.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capability: Option<String>,
}
impl AccountRun {
    pub(super) fn has_grant(&self, accounts: &Accounts) -> bool {
        accounts.get(&self.connection).is_some_and(|account| {
            account.public.grants.contains(&self.topic)
                && account
                    .project
                    .as_ref()
                    .is_some_and(|p| p.origin == self.origin && p.project == self.project)
        })
    }
    /// The project this run started in, while the topic still holds its grant.
    pub(crate) fn project(&self, accounts: &Accounts) -> Result<std::sync::Arc<Project>> {
        ensure!(
            self.has_grant(accounts),
            "This topic no longer has access to the PostHog project that ran this task"
        );
        accounts.project_for(&self.connection, self.topic)
    }
    /// The PostHog task behind this run.
    pub fn posthog_task(&self) -> Option<Uuid> {
        serde_json::from_value::<(Uuid, Uuid)>(self.handle.0.clone())
            .ok()
            .map(|(task, _)| task)
    }
}

// A mention is an explicit reference. Resolve a bracketed ID or the longest
// complete registered label. Ambiguous labels require an ID.
fn explicit_mentions(text: &str, eligible: &[Topic]) -> std::collections::BTreeSet<TopicId> {
    let mut ids = std::collections::BTreeSet::new();
    let lower = text.to_lowercase();
    for (pos, _) in lower.match_indices('@') {
        if lower[..pos]
            .chars()
            .next_back()
            .is_some_and(|c| c.is_alphanumeric() || c == '_')
        {
            continue;
        }
        let rest = &lower[pos + 1..];
        if let Some(raw) = rest
            .strip_prefix('[')
            .and_then(|s| s.split_once(']'))
            .map(|(id, _)| id)
        {
            if let Ok(id) = raw.parse()
                && eligible.iter().any(|t| t.id == id)
            {
                ids.insert(id);
            }
            continue;
        }
        let mut choices: Vec<_> = eligible
            .iter()
            .filter_map(|topic| {
                let name = topic.name.to_lowercase();
                let suffix = rest.strip_prefix(&name)?;
                (!name.is_empty() && !suffix.starts_with(|c: char| c.is_alphanumeric() || c == '_'))
                    .then_some((name.len(), topic.id))
            })
            .collect();
        choices.sort_by_key(|(len, _)| std::cmp::Reverse(*len));
        if let Some((len, id)) = choices.first()
            && choices.get(1).is_none_or(|(other, _)| other != len)
        {
            ids.insert(*id);
        }
    }
    ids
}

impl Accounts {
    pub(super) fn mentioned_context(
        &self,
        account: &str,
        topic: TopicId,
        text: &str,
    ) -> Result<String> {
        let grants = self
            .get(account)
            .context("Connection unavailable")?
            .public
            .grants
            .clone();
        let mut disputes = std::collections::BTreeSet::new();
        let topics: Vec<_> = self
            .store
            .load()?
            .into_iter()
            .filter(|r| r.state.topic.id != topic && grants.contains(&r.state.topic.id))
            .map(|r| {
                disputes.extend(r.state.disputed_facts());
                r.state.topic
            })
            .collect();
        let ids = explicit_mentions(text, &topics);
        let mut mentions = vec![];
        for other in topics {
            if ids.contains(&other.id) {
                let facts: Vec<_> = other
                    .facts
                    .iter()
                    .rev()
                    .filter(|f| f.is_current())
                    .take(16)
                    .map(|f| serde_json::json!({"id":f.id,"text":f.text,"disputed":disputes.contains(&f.id)}))
                    .collect();
                mentions.push(
                    serde_json::json!({"topic":other.name,"mission":other.mission,"facts":facts}),
                );
            }
        }
        if mentions.is_empty() {
            Ok(String::new())
        } else {
            Ok(format!(
                "\nReferenced topics from the workspace:\n{}",
                serde_json::to_string(&mentions)?
            ))
        }
    }
}
impl Accounts {
    /// Send a turn to a run: queued on it while it is open, or as a new run that
    /// resumes it when it finished or `fresh` asks for one.
    async fn continue_run(
        &self,
        handle: &RunHandle,
        text: &str,
        model: Option<&str>,
        fresh: bool,
    ) -> Result<RunHandle> {
        let mut run: AccountRun = serde_json::from_value(handle.0.clone())?;
        ensure!(run.has_grant(self), "Run project access changed");
        // A message to a finished run resumes it as a new run, which does not inherit
        // the topic tools. Mint a capability for it, as a start does.
        let capability = crate::topic_mcp::Capability::issue(self, run.topic, &run.connection);
        let resumed = self
            .project_for(&run.connection, run.topic)?
            .agent
            .continue_with_tools(
                &run.handle,
                text,
                model,
                capability
                    .as_ref()
                    .map(|c| (c.url.as_str(), c.token.as_str())),
                fresh,
            )
            .await;
        let fingerprint = capability.map(|c| c.finish(self, resumed.is_ok()));
        let resumed = resumed?;
        // Only a new run carries the new capability; a live run keeps its own.
        if resumed.0 != run.handle.0 {
            run.capability = fingerprint;
        }
        run.handle = resumed;
        Ok(RunHandle(serde_json::to_value(run)?))
    }
}

#[async_trait]
impl Agent for Accounts {
    fn can_take(&self, _: &Task) -> bool {
        false
    }
    fn can_take_for(&self, topic: TopicId, _: &Task) -> bool {
        self.project(topic).is_ok()
    }
    async fn start(&self, _: AgentRun) -> Result<RunHandle> {
        bail!("PostHog requires an owning topic")
    }
    async fn start_for(&self, topic: TopicId, mut run: AgentRun) -> Result<RunHandle> {
        let (connection, p) = self.project(topic)?;
        // Chat answers run on the model chosen in the topic's composer.
        let model = if run.task.assignment == Some(meep_topic::InboxAssignment::ChatAnswer) {
            let choice = self.chat_choice(topic)?;
            run.task.billing = choice.billing;
            choice.model
        } else {
            None
        };
        let capability = crate::topic_mcp::Capability::issue(self, topic, &connection);
        if capability.is_none() {
            run.mission
                .push_str(&self.mentioned_context(&connection, topic, &run.task.title)?);
        }
        let started = p
            .agent
            .start_on_model(
                topic,
                run,
                capability
                    .as_ref()
                    .map(|c| (c.url.as_str(), c.token.as_str())),
                model.as_deref(),
            )
            .await;
        let fingerprint = capability.map(|c| c.finish(self, started.is_ok()));
        Ok(RunHandle(serde_json::to_value(AccountRun {
            connection,
            topic,
            project: p.project,
            origin: p.origin.clone(),
            handle: started?,
            capability: fingerprint,
        })?))
    }
    async fn observe_task(
        &self,
        handle: &RunHandle,
        now: chrono::DateTime<chrono::Utc>,
    ) -> Result<(RunState, Option<meep_wire::TaskConversation>)> {
        let run: AccountRun = serde_json::from_value(handle.0.clone())?;
        ensure!(run.has_grant(self), "Run project access changed");
        self.project_for(&run.connection, run.topic)?
            .agent
            .observe_task(&run.handle, now)
            .await
    }
    async fn task_title(&self, handle: &RunHandle) -> Result<Option<String>> {
        let run: AccountRun = serde_json::from_value(handle.0.clone())?;
        ensure!(run.has_grant(self), "Run project access changed");
        self.project_for(&run.connection, run.topic)?
            .agent
            .task_title(&run.handle)
            .await
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
        self.continue_run(handle, text, model, false).await
    }
    async fn resume_task(&self, handle: &RunHandle, text: &str) -> Result<RunHandle> {
        self.continue_run(handle, text, None, true).await
    }

    async fn cancel(&self, handle: &RunHandle) -> Result<()> {
        let run: AccountRun = serde_json::from_value(handle.0.clone())?;
        let p = self.project_for(&run.connection, run.topic)?;
        ensure!(
            p.origin == run.origin && p.project == run.project,
            "Run belongs to another project"
        );
        p.agent.cancel(&run.handle).await
    }
    async fn poll(&self, handle: &RunHandle) -> Result<RunState> {
        let run: AccountRun = serde_json::from_value(handle.0.clone())?;
        let p = self.project_for(&run.connection, run.topic)?;
        ensure!(
            p.origin == run.origin && p.project == run.project,
            "The run belongs to another PostHog project"
        );
        p.agent
            .poll(&run.handle)
            .await
            .map_err(|_| anyhow::anyhow!("PostHog task status is unavailable"))
    }
    async fn execute(&self, handle: &RunHandle, task: &Task, key: Uuid) -> Result<RunHandle> {
        let mut run: AccountRun = serde_json::from_value(handle.0.clone())?;
        let project = self.project_for(&run.connection, run.topic)?;
        ensure!(
            project.origin == run.origin && project.project == run.project,
            "The proposing run belongs to another project"
        );
        run.handle = project.agent.execute(&run.handle, task, key).await?;
        Ok(RunHandle(serde_json::to_value(run)?))
    }
    async fn reply(
        &self,
        topic: TopicId,
        message: &meep_topic::Message,
        text: &str,
        key: Uuid,
    ) -> Result<String> {
        let Some(meep_topic::Source::Connection {
            connection,
            channel,
        }) = &message.reply_target()
        else {
            bail!("Missing source connection")
        };
        let account = self
            .get(connection)
            .context("Reply connection is unavailable")?;
        ensure!(
            account.public.grants.contains(&topic),
            "This topic no longer has access to the reply account"
        );
        let flow = account
            .values
            .get("reply_workflow")
            .context("Configure reply_workflow on the source account to deliver replies")?
            .parse()?;
        let provider = if account.project.is_some() {
            account
        } else {
            let id = account
                .values
                .get("reply_account")
                .context("Configure the PostHog reply_account")?;
            self.get(id)
                .context("PostHog reply account is unavailable")?
        };
        ensure!(
            provider.public.grants.contains(&topic),
            "This topic has no PostHog reply grant"
        );
        // Let the workflow endpoint decide whether these credentials can dispatch.
        let project = provider
            .project
            .as_ref()
            .context("Connect a PostHog reply account")?;
        let vars = serde_json::from_value(
            serde_json::json!({"source":connection,"channel":channel,"external_id":message.origin.as_ref().and_then(|o| o.external_id.as_ref()),"text":text}),
        )?;
        let receipt =
            meep_posthog::workflows::BoundWorkflow::new(&project.origin, project.project, flow)?
                .start_for(&project.token, &topic.to_string(), key, &vars)
                .await?;
        Ok(format!(
            "Reply dispatched to {channel} ({}).",
            receipt.invocation_id
        ))
    }
}
#[async_trait]
impl RoutineBackend for Accounts {
    fn source_ready(&self, topic: TopicId) -> Result<()> {
        ensure!(
            self.public_base.read().is_some(),
            "MEEP_PUBLIC_BASE_URL is not configured"
        );
        self.source_project(topic)?;
        Ok(())
    }

    async fn activate(&self, c: RoutineContext<'_>) -> Result<()> {
        let (_, p) = self.project(c.topic)?;
        let flow: Uuid = c.binding.external_id.parse()?;
        let api = ProjectEndpoint::new(&p.origin, p.project, "hog_flows")?;
        let confirmed: Value = api
            .patch(
                &p.token,
                &format!("{flow}/"),
                serde_json::json!({"status":"active"}),
            )
            .await?;
        ensure!(
            confirmed["status"] == "active",
            "PostHog did not confirm activation"
        );
        Ok(())
    }

    fn name(&self) -> &str {
        "posthog"
    }
    fn bind(&self, b: &RoutineBinding) -> Result<()> {
        b.external_id
            .parse::<Uuid>()
            .context("Expected a PostHog flow UUID")?;
        Ok(())
    }
    async fn start(
        &self,
        c: RoutineContext<'_>,
        vars: Map<String, Value>,
        key: Uuid,
    ) -> Result<RoutineRun> {
        self.source_project(c.topic)?
            .1
            .routines
            .start(c, vars, key)
            .await
            .map_err(|error| {
                if error.is::<meep_engine::DispatchUncertain>() {
                    error
                } else {
                    anyhow::anyhow!("PostHog workflow dispatch failed")
                }
            })
    }
    async fn status(&self, c: RoutineContext<'_>, id: Uuid) -> Result<RoutineRun> {
        self.project(c.topic)?
            .1
            .routines
            .status(c, id)
            .await
            .map_err(|_| anyhow::anyhow!("PostHog workflow status is unavailable"))
    }
    async fn find_observation(
        &self,
        c: RoutineContext<'_>,
        observation: Uuid,
    ) -> Result<Option<RoutineRun>> {
        self.project(c.topic)?
            .1
            .routines
            .find_observation(c, observation)
            .await
            .map_err(|_| anyhow::anyhow!("PostHog workflow recovery is unavailable"))
    }
    async fn health(&self, c: RoutineContext<'_>) -> Result<RoutineHealth> {
        self.project(c.topic)?.1.routines.health(c).await
    }
}
