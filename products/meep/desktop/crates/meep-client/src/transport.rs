use async_trait::async_trait;
use chrono::{DateTime, Utc};
use futures_util::{Stream, StreamExt};
use meep_topic::TopicId;
use meep_wire::views::{View, ViewEnvelope};
use meep_wire::{
    ApiError, ChangePage, CommandBatch, CommandResults, ConnectionGrant, ConnectionInfo,
    Connections, StreamEvent, TopicSnapshot,
};
use reqwest::{Method, RequestBuilder, Response, StatusCode, Url, header};
use serde::{Deserialize, Serialize};
use std::{pin::Pin, time::Duration};
use thiserror::Error;

/// Bytes and server-assigned revision of one topic file.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct FileRevision {
    /// Monotonic revision for this topic and path.
    pub revision: u64,
    /// Contents of that revision.
    pub bytes: Vec<u8>,
}

/// Transport failures, separate from a permanent per-command rejection.
#[derive(Debug, Error)]
pub enum TransportError {
    /// The server refused the device credential.
    #[error("device unauthorized")]
    Unauthorized,
    /// Contact was lost or the server is temporarily unavailable.
    #[error("server unavailable: {0}")]
    Unavailable(String),
    /// The remote API returned a non-success response.
    #[error("server returned HTTP {status} ({code}): {message}")]
    Api {
        /// HTTP status.
        status: u16,
        /// Stable API error code.
        code: String,
        /// Readable error detail.
        message: String,
    },
    /// A request or response violates the wire contract.
    #[error("wire protocol error: {0}")]
    Protocol(String),
}

type Result<T> = std::result::Result<T, TransportError>;

/// A live sequence of server hints. Only committed change pages advance the replica cursor.
pub type EventStream = Pin<Box<dyn Stream<Item = Result<StreamEvent>> + Send>>;

/// The remote operations used by the replica. Implementations preserve command order and IDs.
#[async_trait]
pub trait Transport: Send + Sync {
    /// Enumerate the authoritative workspace view collection.
    async fn views(&self) -> Result<Vec<View>> {
        Ok(vec![])
    }
    /// Apply a retryable view command.
    async fn push_view(&self, _: &ViewEnvelope) -> Result<View> {
        Err(protocol("View authoring unavailable"))
    }
    /// Query live data for a view.
    async fn view_source(&self, _: uuid::Uuid, _: serde_json::Value) -> Result<serde_json::Value> {
        Err(protocol("View sources unavailable"))
    }
    /// Manage the current PostHog account’s MCP servers.
    async fn mcp_store(
        &self,
        _: &meep_wire::mcp_store::Operation,
    ) -> Result<meep_wire::mcp_store::Outcome> {
        Err(protocol("MCP store unavailable"))
    }
    /// Submit a batch of commands in order.
    async fn push(&self, batch: &CommandBatch) -> Result<CommandResults>;
    /// Fetch authoritative snapshots after the exclusive cursor.
    async fn changes(&self, cursor: u64) -> Result<ChangePage>;
    /// Read current topic snapshots during initial replication.
    async fn bootstrap_page(&self, cursor: u64) -> Result<ChangePage> {
        self.changes(cursor).await
    }
    /// Register this replica for deletion notifications as it pulls each page.
    async fn replica_page(
        &self,
        _replica: uuid::Uuid,
        cursor: u64,
        bootstrap: bool,
    ) -> Result<ChangePage> {
        if bootstrap {
            self.bootstrap_page(cursor).await
        } else {
            self.changes(cursor).await
        }
    }
    /// Acknowledge a locally committed deletion to transports that retain topic history.
    async fn acknowledge_deletions(&self, _ack: &meep_wire::DeletionAck) -> Result<()> {
        Ok(())
    }
    /// Fetch the current snapshot of a single topic.
    async fn snapshot(&self, topic: TopicId) -> Result<TopicSnapshot>;
    /// Subscribe to live events from the given cursor.
    async fn stream(&self, cursor: u64) -> Result<EventStream>;
    /// Discover and rank the sources granted to this topic.
    async fn sources_for(&self, _topic: TopicId) -> Result<Vec<meep_wire::WatchableSource>> {
        Err(protocol("Topic source ranking is unavailable"))
    }
    /// Fetch the current task conversation.
    async fn task_conversation(
        &self,
        _topic: TopicId,
        _task: meep_topic::TaskId,
    ) -> Result<meep_wire::TaskConversation> {
        Err(protocol("Task conversation is unavailable"))
    }
    /// List what the topic's task runs produced, live from the server.
    async fn task_artifacts(&self, _topic: TopicId) -> Result<Vec<meep_wire::TaskArtifact>> {
        Err(protocol("Task artifacts are unavailable"))
    }
    /// Read one task artifact version.
    async fn task_artifact(
        &self,
        _topic: TopicId,
        _artifact: &meep_wire::TaskArtifact,
    ) -> Result<Vec<u8>> {
        Err(protocol("Task artifacts are unavailable"))
    }
    /// Deliver a task message.
    async fn send_task_message(
        &self,
        _topic: TopicId,
        _task: meep_topic::TaskId,
        _text: &str,
    ) -> Result<()> {
        Err(protocol("Task messaging is unavailable"))
    }
    /// Deliver a task message with an explicit model selection.
    async fn send_task_message_on_model(
        &self,
        topic: TopicId,
        task: meep_topic::TaskId,
        text: &str,
        model: Option<&str>,
    ) -> Result<()> {
        if model.is_some() {
            return Err(protocol("Task model switching is unavailable"));
        }
        self.send_task_message(topic, task, text).await
    }
    /// List the models a topic's chat can answer with and the one it uses.
    async fn chat_models(&self, _topic: TopicId) -> Result<meep_wire::ChatModels> {
        Err(protocol("This server does not offer a model choice"))
    }
    /// List the models a view can be built with.
    async fn view_models(&self) -> Result<meep_wire::ChatModels> {
        Err(protocol("This server does not offer a model choice"))
    }
    /// Stage a file for a view request before the request is sent.
    async fn put_view_file(&self, _view: uuid::Uuid, _name: &str, _bytes: Vec<u8>) -> Result<()> {
        Err(protocol("This server does not accept view files"))
    }
    /// Choose the model a topic's chat answers with, or restore the default.
    async fn set_chat_model(
        &self,
        _topic: TopicId,
        _model: Option<&str>,
    ) -> Result<meep_wire::ChatModels> {
        Err(protocol("This server does not offer a model choice"))
    }
    /// Choose the topic model and its billing option together.
    async fn set_chat_choice(
        &self,
        topic: TopicId,
        choice: &meep_wire::ChatModelChoice,
    ) -> Result<meep_wire::ChatModels> {
        if choice.billing.is_some() {
            return Err(protocol("Chat billing choice is unavailable"));
        }
        self.set_chat_model(topic, choice.model.as_deref()).await
    }
    /// Fetch the server's workflow templates.
    async fn routine_templates(&self) -> Result<Vec<meep_wire::RoutineTemplate>> {
        Err(protocol("This server does not offer routine templates"))
    }
    /// Instantiate a template in a topic.
    async fn create_template_routine(
        &self,
        _topic: TopicId,
        _req: &meep_wire::CreateTemplateRoutine,
    ) -> Result<meep_topic::RoutineInfo> {
        Err(protocol("This server does not offer routine templates"))
    }
    /// Delete this binding and its linked workflow.
    async fn delete_workflow(
        &self,
        _topic: TopicId,
        _routine: &str,
        _flow: uuid::Uuid,
    ) -> Result<()> {
        Err(protocol("This transport does not support routine deletion"))
    }
    /// Read a bound workflow or explicitly set its enabled state.
    async fn workflow(
        &self,
        _topic: TopicId,
        _routine: &str,
        _enabled: Option<&meep_wire::WorkflowSwitch>,
    ) -> Result<meep_wire::WorkflowDetails> {
        Err(protocol(
            "this transport does not support workflow inspection",
        ))
    }
    /// Enumerate logical file names in a topic.
    async fn files(&self, _topic: TopicId) -> Result<Vec<String>> {
        Err(protocol("this transport does not support file listing"))
    }
    /// Grant one topic access without replacing existing grants.
    async fn grant_topic(&self, _connection: &str, _topic: TopicId) -> Result<ConnectionInfo> {
        Err(protocol("this transport does not support topic grants"))
    }
    /// Update credentials while preserving the server's current grants and project identity.
    async fn register_connection(
        &self,
        _id: &str,
        _grant: &ConnectionGrant,
    ) -> Result<ConnectionInfo> {
        Err(protocol(
            "this transport does not support credential registration",
        ))
    }
    /// List public connection details.
    async fn connections(&self) -> Result<Connections>;
    /// Create or update one connection grant.
    async fn put_connection(&self, id: &str, grant: &ConnectionGrant) -> Result<ConnectionInfo>;
    /// Revoke a connection's stored credentials.
    async fn sign_out(&self, _id: &str) -> Result<ConnectionInfo> {
        Err(protocol("Sign out unavailable"))
    }
    /// Read a topic file at its latest revision.
    async fn get_file(&self, topic: TopicId, path: &str) -> Result<FileRevision>;
    /// Fetch one immutable file revision.
    async fn get_file_at(
        &self,
        _topic: TopicId,
        _path: &str,
        _revision: u64,
    ) -> Result<FileRevision> {
        Err(protocol("File history unavailable"))
    }
    /// Retryable file upload. Each key must append at most one revision for its file.
    async fn put_file_once(
        &self,
        topic: TopicId,
        path: &str,
        bytes: Vec<u8>,
        key: uuid::Uuid,
    ) -> Result<FileRevision>;
    /// Append from the observed revision. A second revision in the reply names the
    /// current head while the submitted version awaits a shared conflict decision.
    async fn put_file_based(
        &self,
        _topic: TopicId,
        _path: &str,
        _bytes: Vec<u8>,
        _key: uuid::Uuid,
        _base: u64,
    ) -> Result<(FileRevision, Option<u64>)> {
        Err(protocol(
            "This transport does not support conditional file writes",
        ))
    }
    /// Save a new file revision and return the confirmed bytes and revision.
    async fn put_file(&self, topic: TopicId, path: &str, bytes: Vec<u8>) -> Result<FileRevision>;
}

/// Supplies a current access token for a signed-in PostHog account.
#[async_trait]
pub trait AccessToken: Send + Sync {
    /// List passive context visible to this account through the project API.
    async fn sources(&self) -> Result<Vec<meep_wire::WatchableSource>>;
    /// Read an approved data source for a rendered view.
    async fn read_view_source(&self, _: &serde_json::Value) -> Result<serde_json::Value> {
        Err(TransportError::Protocol("View source unavailable".into()))
    }
    /// Run a user-initiated store operation against the signed-in project.
    async fn mcp_store(
        &self,
        operation: &meep_wire::mcp_store::Operation,
    ) -> Result<meep_wire::mcp_store::Outcome>;
    /// Refresh an expired token before returning it.
    async fn access_token(&self) -> std::result::Result<String, TransportError>;
}

/// Bearer-authenticated HTTP transport for the versioned Meep wire API.
#[derive(Clone)]
pub struct HttpTransport {
    account: Option<std::sync::Arc<dyn AccessToken>>,
    http: reqwest::Client,
    base: Url,
}

impl HttpTransport {
    /// Creates a transport rooted at the server base URL, optionally behind a path prefix.
    pub fn new(base: &str, token: &str) -> Result<Self> {
        let base = Url::parse(base).map_err(protocol)?;
        let loopback = base.host_str().is_some_and(|host| {
            host == "localhost"
                || host
                    .trim_matches(['[', ']'])
                    .parse::<std::net::IpAddr>()
                    .is_ok_and(|ip| ip.is_loopback())
        });
        if !(base.scheme() == "https" || (base.scheme() == "http" && loopback))
            || base.host_str().is_none()
            || base.query().is_some()
            || base.fragment().is_some()
            || !base.username().is_empty()
            || base.password().is_some()
        {
            return Err(protocol(
                "expected an HTTPS server base URL or a loopback HTTP URL",
            ));
        }
        let mut authorization = header::HeaderValue::from_str(&format!("Bearer {token}"))
            .map_err(|_| protocol("invalid bearer token"))?;
        authorization.set_sensitive(true);
        let mut headers = header::HeaderMap::new();
        headers.insert(header::AUTHORIZATION, authorization);
        let http = reqwest::Client::builder()
            .default_headers(headers)
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(10))
            .read_timeout(Duration::from_secs(90))
            .build()
            .map_err(protocol)?;
        Ok(Self {
            http,
            base,
            account: None,
        })
    }

    /// Connect the replica directly to the authenticated Meep product in a PostHog project.
    pub fn posthog(
        origin: &str,
        project: u64,
        account: std::sync::Arc<dyn AccessToken>,
    ) -> Result<Self> {
        let mut transport = Self::new(&format!("{origin}/api/projects/{project}/meep"), "")?;
        transport.account = Some(account);
        Ok(transport)
    }

    async fn change_page(
        &self,
        cursor: u64,
        bootstrap: Option<bool>,
        replica: Option<uuid::Uuid>,
    ) -> Result<ChangePage> {
        json(
            self.request(Method::GET, &["changes"])
                .await?
                .query(&[("cursor", cursor)])
                .query(&[("bootstrap", bootstrap)])
                .query(&[("replica", replica)]),
        )
        .await
    }
    async fn request(&self, method: Method, parts: &[&str]) -> Result<RequestBuilder> {
        let mut url = self.base.clone();
        let mut path = url
            .path_segments_mut()
            .map_err(|_| protocol("invalid URL base"))?;
        path.pop_if_empty().push("v1");
        for part in parts {
            if matches!(*part, "" | "." | "..") {
                return Err(protocol("expected a non-empty relative path segment"));
            }
            path.push(part);
        }
        if self.account.is_some() {
            path.push("");
        }
        drop(path);
        let request = self.http.request(method, url);
        match &self.account {
            Some(account) => Ok(request.bearer_auth(account.access_token().await?)),
            None => Ok(request),
        }
    }

    async fn file(&self, method: Method, topic: TopicId, path: &str) -> Result<RequestBuilder> {
        let topic = topic.to_string();
        let mut parts = vec!["topics", &topic, "files"];
        parts.extend(path.split('/'));
        let upload = self.account.is_some() && method == Method::PUT;
        let request = self.request(method, &parts).await?;
        Ok(if upload {
            request.header(header::CONTENT_TYPE, "application/octet-stream")
        } else {
            request
        })
    }
}

fn protocol(error: impl std::fmt::Display) -> TransportError {
    TransportError::Protocol(error.to_string())
}

fn unavailable(error: impl std::fmt::Display) -> TransportError {
    TransportError::Unavailable(error.to_string())
}

async fn send(request: RequestBuilder) -> Result<Response> {
    let response = request.send().await.map_err(unavailable)?;
    let status = response.status();
    if status.is_success() {
        return Ok(response);
    }
    if status == StatusCode::UNAUTHORIZED {
        return Err(TransportError::Unauthorized);
    }
    if status.is_server_error() || status == StatusCode::TOO_MANY_REQUESTS {
        return Err(unavailable(status));
    }
    let error = response.json::<ApiError>().await.map_err(protocol)?;
    Err(TransportError::Api {
        status: status.as_u16(),
        code: error.code,
        message: error.message,
    })
}

async fn json<T: serde::de::DeserializeOwned>(request: RequestBuilder) -> Result<T> {
    let bytes = send(request).await?.bytes().await.map_err(unavailable)?;
    serde_json::from_slice(&bytes).map_err(protocol)
}

async fn pages<B: serde::de::DeserializeOwned, T>(
    request: RequestBuilder,
    items: impl Fn(B) -> Vec<T>,
) -> Result<Vec<T>> {
    let mut all = Vec::new();
    let mut offset = 0usize;
    loop {
        let req = request
            .try_clone()
            .ok_or_else(|| protocol("invalid list request"))?
            .query(&[("offset", offset)]);
        let response = send(req).await?;
        let next = response
            .headers()
            .get("x-meep-next-offset")
            .map(|h| {
                h.to_str()
                    .map_err(protocol)?
                    .parse::<usize>()
                    .map_err(protocol)
            })
            .transpose()?;
        let bytes = response.bytes().await.map_err(unavailable)?;
        let page = items(serde_json::from_slice(&bytes).map_err(protocol)?);
        if let Some(next) = next
            && (page.is_empty() || next != offset.saturating_add(page.len()))
        {
            return Err(protocol("invalid next list offset"));
        }
        all.extend(page);
        match next {
            Some(n) => offset = n,
            None => return Ok(all),
        }
    }
}

async fn file_response(request: RequestBuilder) -> Result<FileRevision> {
    decode_file(send(request).await?).await
}
async fn decode_file(response: Response) -> Result<FileRevision> {
    let revision = response
        .headers()
        .get("x-meep-revision")
        .ok_or_else(|| protocol("missing x-meep-revision"))?
        .to_str()
        .map_err(protocol)?
        .parse()
        .map_err(protocol)?;
    let bytes = response.bytes().await.map_err(unavailable)?.to_vec();
    Ok(FileRevision { revision, bytes })
}

#[async_trait]
impl Transport for HttpTransport {
    async fn replica_page(
        &self,
        replica: uuid::Uuid,
        cursor: u64,
        bootstrap: bool,
    ) -> Result<ChangePage> {
        self.change_page(cursor, Some(bootstrap), Some(replica))
            .await
    }
    async fn acknowledge_deletions(&self, ack: &meep_wire::DeletionAck) -> Result<()> {
        json(
            self.request(Method::POST, &["deletions", "ack"])
                .await?
                .json(ack),
        )
        .await
    }
    async fn views(&self) -> Result<Vec<View>> {
        json(self.request(Method::GET, &["views"]).await?).await
    }
    async fn push_view(&self, e: &ViewEnvelope) -> Result<View> {
        json(
            self.request(Method::POST, &["views", "commands"])
                .await?
                .json(e),
        )
        .await
    }
    async fn view_source(
        &self,
        id: uuid::Uuid,
        params: serde_json::Value,
    ) -> Result<serde_json::Value> {
        if params["source"] != "topics"
            && let Some(account) = &self.account
        {
            return account.read_view_source(&params).await;
        }
        json(
            self.request(Method::POST, &["views", &id.to_string(), "sources"])
                .await?
                .json(&params),
        )
        .await
    }
    async fn mcp_store(
        &self,
        request: &meep_wire::mcp_store::Operation,
    ) -> Result<meep_wire::mcp_store::Outcome> {
        if let Some(account) = &self.account {
            return account.mcp_store(request).await;
        }
        json(
            self.request(Method::POST, &["connections", "posthog", "mcp-store"])
                .await?
                .json(request),
        )
        .await
    }
    async fn push(&self, batch: &CommandBatch) -> Result<CommandResults> {
        json(self.request(Method::POST, &["commands"]).await?.json(batch)).await
    }
    async fn bootstrap_page(&self, cursor: u64) -> Result<ChangePage> {
        self.change_page(cursor, Some(true), None).await
    }
    async fn changes(&self, cursor: u64) -> Result<ChangePage> {
        self.change_page(cursor, None, None).await
    }
    async fn snapshot(&self, topic: TopicId) -> Result<TopicSnapshot> {
        json(
            self.request(Method::GET, &["topics", &topic.to_string()])
                .await?,
        )
        .await
    }
    async fn stream(&self, cursor: u64) -> Result<EventStream> {
        if self.account.is_some() {
            let events = futures_util::stream::unfold(
                (self.clone(), cursor, 0_u8),
                |(transport, cursor, tick)| async move {
                    tokio::time::sleep(Duration::from_secs(3)).await;
                    let result = transport.change_page(cursor, None, None).await;
                    let mut next = cursor;
                    let event = result.map(|page| {
                        next = page.cursor;
                        match page.topics.first() {
                            Some(topic) => StreamEvent::Topic {
                                topic: topic.state.topic.id,
                                revision: topic.revision,
                                cursor: next,
                            },
                            None if tick == 4 => StreamEvent::Views,
                            None => StreamEvent::Heartbeat {
                                at: chrono::Utc::now(),
                            },
                        }
                    });
                    Some((event, (transport, next, (tick + 1) % 5)))
                },
            );
            return Ok(Box::pin(events));
        }
        let response = send(
            self.request(Method::GET, &["stream"])
                .await?
                .query(&[("cursor", cursor)])
                .header(header::ACCEPT, "text/event-stream"),
        )
        .await?;
        let mime = response
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|h| h.to_str().ok())
            .and_then(|s| s.split(';').next())
            .map(str::trim);
        if mime != Some("text/event-stream") {
            return Err(protocol("expected text/event-stream"));
        }
        let events = sse_stream::SseStream::from_bytes_stream(response.bytes_stream()).filter_map(
            |frame| async {
                match frame {
                    Ok(frame) => frame
                        .data
                        .map(|data| serde_json::from_str(&data).map_err(protocol)),
                    Err(error) => Some(Err(unavailable(error))),
                }
            },
        );
        Ok(Box::pin(events))
    }
    async fn task_conversation(
        &self,
        topic: TopicId,
        task: meep_topic::TaskId,
    ) -> Result<meep_wire::TaskConversation> {
        #[derive(Deserialize)]
        struct Attempt {
            id: uuid::Uuid,
            started_at: Option<DateTime<Utc>>,
            finished_at: Option<DateTime<Utc>>,
            initial: bool,
            logs: String,
            reply: Option<String>,
            followup: Option<String>,
            status: String,
        }
        #[derive(Deserialize)]
        struct Conversation {
            status: String,
            brief: String,
            attempts: Vec<Attempt>,
        }
        let request = self
            .request(
                Method::GET,
                &[
                    "topics",
                    &topic.to_string(),
                    "tasks",
                    &task.to_string(),
                    "conversation",
                ],
            )
            .await?;
        if self.account.is_none() {
            return json(request).await;
        }
        let conversation: Conversation = json(request).await?;
        let mut messages = Vec::new();
        for attempt in conversation.attempts {
            use meep_posthog::chat::{History, Turn};

            let mut history = History::default();
            for entry in attempt
                .logs
                .lines()
                .filter_map(|line| serde_json::from_str(line).ok())
            {
                history.apply(attempt.id, &entry, attempt.started_at);
            }
            let mut turns: Vec<_> = history
                .turns()
                .iter()
                .map(|turn| turn.message.clone())
                .collect();
            // The initial provider prompt also contains Meep's instructions and topic context.
            if let Some(first) = turns.first_mut().filter(|first| {
                first.role == "user"
                    && first
                        .text
                        .contains("Investigate this board task for topic ")
            }) {
                first.text.clone_from(&conversation.brief);
            } else if let Some(prompt) = attempt
                .followup
                .filter(|_| !turns.iter().any(|turn| turn.role == "user"))
                .or_else(|| attempt.initial.then(|| conversation.brief.clone()))
            {
                let brief = Turn::new(attempt.id.to_string(), "You", prompt, attempt.started_at);
                turns.insert(0, brief.message);
            }
            let outcome = match attempt.status.as_str() {
                "failed" => Some("The run failed.".to_owned()),
                "cancelled" => Some("The run was stopped.".to_owned()),
                _ => attempt.reply.filter(|reply| {
                    !turns.last().is_some_and(|turn| {
                        turn.role == "assistant"
                            && (turn.text.contains(reply)
                                || serde_json::from_str::<serde_json::Value>(turn.text.trim())
                                    .is_ok_and(|output| {
                                        output["reply"].as_str() == Some(reply.as_str())
                                    }))
                    })
                }),
            };
            if let Some(reply) = outcome {
                turns.push(
                    Turn::new(attempt.id.to_string(), "Agent", reply, attempt.finished_at).message,
                );
            }
            messages.extend(turns);
        }
        Ok(meep_wire::TaskConversation {
            status: conversation.status,
            messages,
        })
    }
    async fn task_artifacts(&self, topic: TopicId) -> Result<Vec<meep_wire::TaskArtifact>> {
        json(
            self.request(Method::GET, &["topics", &topic.to_string(), "artifacts"])
                .await?,
        )
        .await
    }
    async fn task_artifact(
        &self,
        topic: TopicId,
        artifact: &meep_wire::TaskArtifact,
    ) -> Result<Vec<u8>> {
        let request = self
            .request(
                Method::GET,
                &[
                    "topics",
                    &topic.to_string(),
                    "artifacts",
                    &artifact.task.to_string(),
                    &artifact.run,
                    &artifact.id,
                ],
            )
            .await?
            .query(&[("version", artifact.version)]);
        Ok(send(request)
            .await?
            .bytes()
            .await
            .map_err(unavailable)?
            .to_vec())
    }
    async fn send_task_message(
        &self,
        topic: TopicId,
        task: meep_topic::TaskId,
        text: &str,
    ) -> Result<()> {
        self.send_task_message_on_model(topic, task, text, None)
            .await
    }
    async fn send_task_message_on_model(
        &self,
        topic: TopicId,
        task: meep_topic::TaskId,
        text: &str,
        model: Option<&str>,
    ) -> Result<()> {
        json(
            self.request(
                Method::POST,
                &[
                    "topics",
                    &topic.to_string(),
                    "tasks",
                    &task.to_string(),
                    "messages",
                ],
            )
            .await?
            .json(&meep_wire::TaskMessage {
                text: text.into(),
                model: model.map(str::to_owned),
            }),
        )
        .await
    }
    async fn chat_models(&self, topic: TopicId) -> Result<meep_wire::ChatModels> {
        json(
            self.request(Method::GET, &["topics", &topic.to_string(), "models"])
                .await?,
        )
        .await
    }
    async fn view_models(&self) -> Result<meep_wire::ChatModels> {
        json(self.request(Method::GET, &["views", "models"]).await?).await
    }
    async fn put_view_file(&self, view: uuid::Uuid, name: &str, bytes: Vec<u8>) -> Result<()> {
        send(
            self.request(Method::PUT, &["views", &view.to_string(), "files", name])
                .await?
                .body(bytes),
        )
        .await?;
        Ok(())
    }
    async fn set_chat_model(
        &self,
        topic: TopicId,
        model: Option<&str>,
    ) -> Result<meep_wire::ChatModels> {
        self.set_chat_choice(
            topic,
            &meep_wire::ChatModelChoice {
                model: model.map(str::to_owned),
                billing: None,
            },
        )
        .await
    }
    async fn set_chat_choice(
        &self,
        topic: TopicId,
        choice: &meep_wire::ChatModelChoice,
    ) -> Result<meep_wire::ChatModels> {
        json(
            self.request(Method::PUT, &["topics", &topic.to_string(), "models"])
                .await?
                .json(choice),
        )
        .await
    }
    async fn sources_for(&self, topic: TopicId) -> Result<Vec<meep_wire::WatchableSource>> {
        if let Some(account) = &self.account {
            return account.sources().await;
        }
        pages(
            self.request(Method::GET, &["sources"])
                .await?
                .query(&[("complete", true)])
                .query(&[("topic", topic)]),
            |v| v,
        )
        .await
    }
    async fn routine_templates(&self) -> Result<Vec<meep_wire::RoutineTemplate>> {
        json(self.request(Method::GET, &["routine-templates"]).await?).await
    }
    async fn create_template_routine(
        &self,
        topic: TopicId,
        req: &meep_wire::CreateTemplateRoutine,
    ) -> Result<meep_topic::RoutineInfo> {
        json(
            self.request(Method::POST, &["topics", &topic.to_string(), "routines"])
                .await?
                .json(req),
        )
        .await
    }
    async fn delete_workflow(&self, topic: TopicId, routine: &str, flow: uuid::Uuid) -> Result<()> {
        send(
            self.request(Method::DELETE, &["routines", &topic.to_string(), routine])
                .await?
                .json(&flow),
        )
        .await?;
        Ok(())
    }
    async fn workflow(
        &self,
        topic: TopicId,
        routine: &str,
        enabled: Option<&meep_wire::WorkflowSwitch>,
    ) -> Result<meep_wire::WorkflowDetails> {
        let topic = topic.to_string();
        let path = ["routines", &topic, routine];
        let req = match enabled {
            Some(enabled) => self.request(Method::PUT, &path).await?.json(&enabled),
            None => self.request(Method::GET, &path).await?,
        };
        json(req).await
    }
    async fn files(&self, topic: TopicId) -> Result<Vec<String>> {
        pages(
            self.request(Method::GET, &["topics", &topic.to_string(), "files"])
                .await?,
            |v| v,
        )
        .await
    }
    async fn grant_topic(&self, connection: &str, topic: TopicId) -> Result<ConnectionInfo> {
        json(
            self.request(
                Method::PUT,
                &["connections", connection, "topics", &topic.to_string()],
            )
            .await?,
        )
        .await
    }
    async fn register_connection(
        &self,
        id: &str,
        grant: &ConnectionGrant,
    ) -> Result<ConnectionInfo> {
        json(
            self.request(Method::PUT, &["connections", id])
                .await?
                .query(&[("preserve_grants", true)])
                .json(grant),
        )
        .await
    }
    async fn connections(&self) -> Result<Connections> {
        Ok(Connections {
            connections: pages(
                self.request(Method::GET, &["connections"]).await?,
                |v: Connections| v.connections,
            )
            .await?,
        })
    }
    async fn put_connection(&self, id: &str, grant: &ConnectionGrant) -> Result<ConnectionInfo> {
        json(
            self.request(Method::PUT, &["connections", id])
                .await?
                .json(grant),
        )
        .await
    }
    async fn sign_out(&self, id: &str) -> Result<ConnectionInfo> {
        json(
            self.request(Method::DELETE, &["connections", id, "credentials"])
                .await?,
        )
        .await
    }
    async fn get_file(&self, topic: TopicId, path: &str) -> Result<FileRevision> {
        file_response(self.file(Method::GET, topic, path).await?).await
    }
    async fn get_file_at(&self, topic: TopicId, path: &str, revision: u64) -> Result<FileRevision> {
        let file = file_response(
            self.file(Method::GET, topic, path)
                .await?
                .query(&[("revision", revision)]),
        )
        .await?;
        if file.revision != revision {
            return Err(protocol("Unexpected file revision"));
        }
        Ok(file)
    }
    async fn put_file_once(
        &self,
        topic: TopicId,
        path: &str,
        bytes: Vec<u8>,
        key: uuid::Uuid,
    ) -> Result<FileRevision> {
        file_response(
            self.file(Method::PUT, topic, path)
                .await?
                .header("Idempotency-Key", key.to_string())
                .body(bytes),
        )
        .await
    }
    async fn put_file_based(
        &self,
        topic: TopicId,
        path: &str,
        bytes: Vec<u8>,
        key: uuid::Uuid,
        base: u64,
    ) -> Result<(FileRevision, Option<u64>)> {
        let response = send(
            self.file(Method::PUT, topic, path)
                .await?
                .header("Idempotency-Key", key.to_string())
                .header("x-meep-base-revision", base)
                .body(bytes),
        )
        .await?;
        let head = response
            .headers()
            .get("x-meep-conflict-head")
            .map(|v| {
                v.to_str()
                    .map_err(protocol)?
                    .parse::<u64>()
                    .map_err(protocol)
            })
            .transpose()?;
        Ok((decode_file(response).await?, head))
    }
    async fn put_file(&self, topic: TopicId, path: &str, bytes: Vec<u8>) -> Result<FileRevision> {
        file_response(self.file(Method::PUT, topic, path).await?.body(bytes)).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn device_credentials_require_tls_outside_loopback() {
        for (origin, accepted) in [
            ("http://example.org", false),
            ("http://localhost.example.org", false),
            ("http://[::1]", true),
            ("https://example.org", true),
        ] {
            assert_eq!(HttpTransport::new(origin, "fixture").is_ok(), accepted);
        }
    }
}
