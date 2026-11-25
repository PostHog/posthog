#![doc = include_str!("../README.md")]
//!
//! ## HTTP endpoints
//!
//! Paths are relative to the server's base URL.
//!
//! | Method | Path | Request | Response |
//! | --- | --- | --- | --- |
//! | `POST` | `/v1/commands` | [`CommandBatch`] | [`CommandResults`] |
//! | `GET` | `/v1/changes?cursor=N` | none | [`ChangePage`] |
//! | `GET` | `/v1/topics/{id}` | none | [`TopicSnapshot`] |
//! | `GET` | `/v1/stream?cursor=N` | none | server-sent events, each `data:` a [`StreamEvent`] |
//! | `GET` | `/v1/topics/{id}/tasks/{task}/conversation` | none | [`TaskConversation`] |
//! | `POST` | `/v1/topics/{id}/tasks/{task}/messages` | [`TaskMessage`] | JSON null after acknowledgement |
//! | `GET` | `/v1/topics/{id}/artifacts` | none | a list of [`TaskArtifact`] |
//! | `GET` | `/v1/topics/{id}/artifacts/{task}/{run}/{artifact}?version=N` | none | bytes; `413` past the preview limit |
//! | `GET` | `/v1/needs-you` | none | [`NeedsYou`] |
//! | `GET` | `/v1/search?q=...&limit=N` | none | [`SearchResults`] |
//! | `GET`/`PUT` | `/v1/topics/{id}/files/{path}` | bytes | bytes, with header `x-meep-revision` |
//! | `GET` | `/v1/sources` | none | a list of [`WatchableSource`] |
//! | `GET` | `/v1/topics/{id}/files` | none | a list of file names |
//! | `GET` | `/v1/connections` | none | [`Connections`] |
//! | `PUT` | `/v1/connections/{id}` | [`ConnectionGrant`] | [`ConnectionInfo`] |
//! | `PUT` | `/v1/connections/{id}?preserve_grants=true` | [`ConnectionGrant`] | credentials updated with existing project grants |
//! | `PUT` | `/v1/connections/{id}/topics/{topic}` | none | [`ConnectionInfo`] |
//! | `GET` / `PUT` | `/v1/routines/{topic}/{routine}` | none / [`WorkflowSwitch`] | [`WorkflowDetails`] |
//! | `POST` | `/v1/routines/{topic}/{routine}/callback` | [`RoutineCallback`] | [`CallbackResult`] |
//! | `POST` | `/v1/ingest/{connection}` | connector-specific JSON | `204` |
//! | `GET` | `/v1/health` | none | [`ServerHealth`] |
//!
//! Requests other than routine callbacks and ingest carry `Authorization: Bearer <device token>`.
//! Errors use a non-2xx status with an [`ApiError`] body.
#![deny(missing_docs)]
mod needs_you;
pub mod table;
pub use meep_views as views;

use chrono::{DateTime, Utc};
use meep_topic::{CommandId, Envelope, TopicId, TopicState};
use serde::{Deserialize, Serialize};

/// MCP store requests and public responses shared with the desktop.
pub mod mcp_store {
    pub use meep_posthog::mcp::store::{
        Installed, Operation, Outcome, Policy, Template, ToolPolicy,
    };
}

/// Commands sent from a replica's outbox, in the order they were issued.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct CommandBatch {
    /// Envelopes in issue order.
    pub commands: Vec<Envelope>,
}

/// One result per submitted envelope, in the same order.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct CommandResults {
    /// Outcome for each envelope.
    pub results: Vec<CommandResult>,
}

/// What happened to one command.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "camelCase")]
pub enum CommandResult {
    /// A transient failure. Retain the original command for retry.
    Retry {
        /// Original command ID.
        id: meep_topic::CommandId,
        /// Reason recorded for the pending command.
        reason: String,
    },
    /// Applied now, or already applied earlier (idempotent retry).
    Applied {
        /// The command.
        id: CommandId,
        /// Topic the command changed.
        topic: TopicId,
        /// Topic revision after the command.
        revision: u64,
    },
    /// Refused permanently; the client drops it and tells the person why.
    Rejected {
        /// The command.
        id: CommandId,
        /// Readable reason.
        reason: String,
    },
}

/// Result of applying or retrying a command.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Applied {
    /// Current topic revision at the command's serialization point.
    pub revision: u64,
    /// Empty for an already-applied command.
    pub changes: meep_topic::Changes,
}

/// Identifies a topic snapshot advanced in the global change stream.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TopicRevision {
    /// Topic to refresh.
    pub topic: TopicId,
    /// Revision committed at this cursor.
    pub revision: u64,
}

/// Reachable HTTPS origin and optional path prefix used for new cloud callbacks.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PublicAddress {
    /// Public server address.
    pub public_base_url: String,
}

/// Authoritative state of one topic.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TopicSnapshot {
    /// Monotonically increasing topic revision.
    pub revision: u64,
    /// Replicated topic state.
    pub state: TopicState,
}

/// Confirmation sent after a replica has durably removed deleted topics.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DeletionAck {
    /// Random identifier persisted in this owner-scoped replica.
    pub replica: uuid::Uuid,
    /// Applied tombstone revisions by topic.
    pub topics: std::collections::BTreeMap<TopicId, u64>,
}

/// Topics that changed after a cursor, with their latest snapshots.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ChangePage {
    /// Latest snapshot of each changed topic.
    pub topics: Vec<TopicSnapshot>,
    /// Pass this as `cursor` next time.
    pub cursor: u64,
    /// More changes are waiting; request again immediately.
    pub more: bool,
}

/// One event on the live stream.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum StreamEvent {
    /// A topic reached a new revision; pull `/v1/changes` from `cursor`.
    Topic {
        /// Changed topic.
        topic: TopicId,
        /// Its new revision.
        revision: u64,
        /// Stream position after this event.
        cursor: u64,
    },
    /// A connection's health changed. Its descriptor is nested under `connection`
    /// so the account kind and the event kind have distinct JSON fields.
    Connection(#[serde(with = "connection_event")] ConnectionInfo),
    /// The workspace view collection changed.
    Views,
    /// Sent periodically so idle connections stay open.
    Heartbeat {
        /// Server time.
        at: DateTime<Utc>,
    },
}

mod connection_event {
    use super::ConnectionInfo;
    use serde::{Deserialize, Deserializer, Serialize, Serializer};

    #[derive(Serialize, Deserialize)]
    struct Payload<T> {
        connection: T,
    }

    pub(super) fn serialize<S: Serializer>(
        connection: &ConnectionInfo,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        Payload { connection }.serialize(serializer)
    }

    pub(super) fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<ConnectionInfo, D::Error> {
        Ok(Payload::deserialize(deserializer)?.connection)
    }
}

/// Something across all topics that needs the person.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NeedsYou {
    /// Ordered newest first.
    pub items: Vec<NeedsYouItem>,
}

/// One decision, approval or problem.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum NeedsYouItem {
    /// An inbox thread waiting for a decision.
    Decide {
        /// Owning topic.
        topic: TopicId,
        /// Thread id as a string.
        thread: String,
        /// Thread subject.
        title: String,
        /// The topic's summary.
        detail: String,
    },
    /// A task waiting for approval.
    Approve {
        /// Owning topic.
        topic: TopicId,
        /// Task id as a string.
        task: String,
        /// Task title.
        title: String,
        /// Result or draft preview.
        detail: String,
        /// Button label, such as "Merge PR 2318".
        action: Option<String>,
    },
    /// A connection a topic depends on is unhealthy.
    Problem {
        /// Affected topics.
        topics: Vec<TopicId>,
        /// Connection id.
        connection: String,
        /// Readable summary, such as "Can't see Slack".
        title: String,
        /// What stopped working.
        detail: String,
    },
}

/// Ranked search results across topics.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SearchResults {
    /// Best match first.
    pub hits: Vec<SearchHit>,
}

/// One search match.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SearchHit {
    /// Owning topic.
    pub topic: TopicId,
    /// `topic`, `thread`, `task` or `fact`.
    pub kind: String,
    /// Item id as a string.
    pub id: String,
    /// Plain-text snippet.
    pub snippet: String,
}

/// Latest observed transcript of a task run.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct TaskConversation {
    /// Current provider or worker status.
    pub status: String,
    /// Chronological transcript including tool calls.
    pub messages: Vec<meep_protocol::sessions::AgentMessage>,
}
/// A file one of a topic's task runs produced in PostHog. Listed live, never synced.
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct TaskArtifact {
    /// Meep task whose run produced it.
    pub task: meep_topic::TaskId,
    /// Provider run that holds it.
    pub run: String,
    /// Provider artifact id, stable across versions.
    pub id: String,
    /// File name.
    pub name: String,
    /// Format such as `document`, `spreadsheet`, `file`, `slack_canvas` or `output`.
    pub kind: String,
    /// Version to read; `0` for a run file that has no versions.
    pub version: u64,
    /// Size in bytes, when known.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub size: Option<u64>,
    /// MIME type, when known.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content_type: Option<String>,
    /// Where it was delivered outside PostHog, such as a Slack canvas.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
    /// Last change.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub updated_at: Option<String>,
}

impl TaskArtifact {
    /// Identifies these exact bytes. Versions never change once written.
    pub fn cache_key(&self) -> String {
        format!("{}/{}/{}", self.run, self.id, self.version)
    }
}

/// A user turn for a task investigation.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TaskMessage {
    /// Optional model for a new turn on this task.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
    /// Message sent to the run.
    pub text: String,
}

/// A model the topic's PostHog account offers for its chat answers.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ChatModel {
    /// Whether this model can use the topic MCP at the configured public address.
    #[serde(default)]
    pub meep_tools: bool,
    /// Efforts advertised by PostHog.
    #[serde(default)]
    pub supported_efforts: Vec<String>,
    /// Model ID PostHog Tasks accepts when starting a run.
    pub id: String,
    /// Human-readable model name.
    pub name: String,
    /// Runtime adapter that runs the model, such as `claude` or `codex`.
    #[serde(default)]
    pub runtime: Option<String>,
}

/// Models a topic's chat can answer with, and the one it uses.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct ChatModels {
    /// Optional Codex billing choice (posthog-gateway or own-subscription).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub billing: Option<String>,
    /// Effective PostHog default; absent when no preference is configured.
    #[serde(default)]
    pub default_model: Option<ChatModel>,
    /// Effective default reasoning effort.
    #[serde(default)]
    pub default_effort: Option<String>,
    /// Models runs for this topic can use.
    pub models: Vec<ChatModel>,
    /// Model chosen for the topic's chat answers. `None` uses the service default.
    #[serde(default)]
    pub selected: Option<String>,
}

/// Choose the model a topic's chat answers with. `None` restores the default.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct ChatModelChoice {
    /// Optional Codex billing choice (posthog-gateway or own-subscription).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub billing: Option<String>,
    /// A model ID from [`ChatModels::models`].
    #[serde(default)]
    pub model: Option<String>,
}

/// Connected services.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Connections {
    /// Every connection.
    pub connections: Vec<ConnectionInfo>,
}

/// A connection as the client sees it. Secrets never cross the wire in this direction.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ConnectionInfo {
    /// Webhook arrivals which matched no topic binding.
    #[serde(default)]
    pub unrouted: u64,
    /// Stable id, such as `posthog` or `slack`.
    pub id: String,
    /// Service kind.
    pub kind: String,
    /// Display name.
    pub label: String,
    /// Account shown to the person.
    pub account: Option<String>,
    /// `ok`, `expired` or `failing`.
    pub health: String,
    /// Server-observed UTC start of the current outage, when available.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unhealthy_since: Option<chrono::DateTime<chrono::Utc>>,
    /// Readable health, such as "Can't see Slack".
    pub summary: String,
    /// Topics allowed to use it.
    pub grants: Vec<TopicId>,
}

/// Create or update a connection, optionally handing the server credentials it needs
/// to work while the Mac is closed.
#[derive(Clone, PartialEq, Serialize, Deserialize)]
pub struct ConnectionGrant {
    /// Service kind.
    pub kind: String,
    /// Display name.
    pub label: String,
    /// Account shown to the person.
    pub account: Option<String>,
    /// Secrets by name, such as `access_token`, `refresh_token`, `region`.
    #[serde(default)]
    pub secrets: std::collections::BTreeMap<String, String>,
    /// Topics allowed to use it.
    #[serde(default)]
    pub grants: Vec<TopicId>,
}

/// A routine running elsewhere (for example in PostHog) changing its topic.
#[derive(Clone, PartialEq, Serialize, Deserialize)]
pub struct RoutineCallback {
    /// Per-routine secret issued when the routine was bound.
    pub secret: String,
    /// Operation to perform, in the engine's `RoutineOp` JSON form.
    pub op: serde_json::Value,
}

/// A server-provided workflow definition ready to instantiate.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct RoutineTemplate {
    /// Stable template identifier.
    pub id: String,
    /// Workflow display name.
    pub name: String,
    /// One-line purpose.
    pub description: String,
    /// Trigger in create_routine format.
    pub trigger: serde_json::Value,
    /// Ordered workflow steps in create_routine format.
    pub steps: Vec<serde_json::Value>,
}

/// Create a topic workflow from a named template.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CreateTemplateRoutine {
    /// Registry identifier.
    pub template: String,
    /// Exact source keys to assign.
    #[serde(default)]
    pub sources: Vec<String>,
}

impl std::fmt::Debug for ConnectionGrant {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ConnectionGrant")
            .field("kind", &self.kind)
            .field("label", &self.label)
            .field("account", &self.account)
            .field("grants", &self.grants)
            .finish_non_exhaustive()
    }
}

impl std::fmt::Debug for RoutineCallback {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RoutineCallback").finish_non_exhaustive()
    }
}

/// Result of a routine callback.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct CallbackResult {
    /// Topic revision after the operation.
    pub revision: u64,
}

/// Stable identity of a private user namespace on the server.
pub type OwnerId = uuid::Uuid;

/// Server status for the client's connection indicator.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ServerHealth {
    /// Private namespace of the authenticated device.
    pub owner_id: OwnerId,
    /// Build version.
    pub version: String,
    /// Current stream cursor.
    pub cursor: u64,
    /// Whether the server holds working PostHog credentials.
    pub posthog: bool,
}

/// Error body for any non-2xx response.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ApiError {
    /// Stable machine-readable code, such as `unknown_topic` or `unauthorized`.
    pub code: String,
    /// Readable message.
    #[serde(alias = "detail")]
    pub message: String,
}

/// A resource the signed-in account can offer when setting up a topic's watch list.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WatchableSource {
    /// The registered connection receiving events for this resource.
    pub connection: String,
    /// Service-defined watch kind.
    pub kind: String,
    /// Stable key used to route incoming observations.
    pub key: String,
    /// Display name supplied by the service.
    pub label: String,
    /// Available delivery methods (push through a workflow or pull through MCP).
    pub supported_modes: Vec<String>,
}

/// The current PostHog definition and recent invocations for a bound workflow.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkflowDetails {
    /// Whether Meep can start this workflow without a source observation.
    /// Older hosts omit this capability.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub manual_run_allowed: Option<bool>,
    /// Sources assigned to this topic binding.
    #[serde(default)]
    pub watches: Vec<meep_topic::Watch>,
    /// Recent source deliveries and their disposition in this topic.
    #[serde(default)]
    pub observations: Vec<meep_topic::ObservationReport>,
    /// Whether PostHog has activated the workflow.
    pub enabled: bool,
    /// Step names in definition order.
    pub steps: Vec<String>,
    /// Short status labels for replicas that predate structured history.
    pub runs: Vec<String>,
    /// Observed execution details in the same order as the upstream history.
    #[serde(default)]
    pub run_history: Vec<WorkflowRun>,
    /// Name given to the flow in PostHog.
    #[serde(default)]
    pub name: Option<String>,
    /// What starts the flow, as a sentence.
    #[serde(default)]
    pub trigger: Option<String>,
    /// The flow's steps in reading order, branches nested under the step that splits.
    #[serde(default)]
    pub graph: Vec<WorkflowStep>,
    /// Flow-wide outcomes over the last seven days.
    #[serde(default)]
    pub week: Option<StepCounts>,
    /// Where the flow can be edited in PostHog.
    #[serde(default)]
    pub url: Option<String>,
}

/// One step of a PostHog workflow as the topic shows it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkflowStep {
    /// Upstream action identifier.
    pub id: String,
    /// Upstream action type, e.g. `trigger`, `function`, `delay`, `conditional_branch`, `exit`.
    pub kind: String,
    /// Step name from the workflow.
    pub name: String,
    /// What the step does, derived from its configuration.
    pub detail: Option<String>,
    /// Branch label when this step starts a branch.
    pub branch: Option<String>,
    /// Nesting depth below a branching step.
    pub depth: u8,
    /// Outcomes for this step over the last seven days, when PostHog reports them.
    pub counts: Option<StepCounts>,
}

/// Successful and failed executions.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct StepCounts {
    /// Successful executions.
    pub succeeded: u64,
    /// Failed executions.
    pub failed: u64,
}

/// One execution of a bound workflow.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkflowRun {
    /// Start time, or the scheduled time if execution has not begun.
    pub at: Option<chrono::DateTime<chrono::Utc>>,
    /// Execution status observed by PostHog.
    pub status: String,
    /// Latest workflow-authored log message for this invocation or its reported error.
    pub result: Option<String>,
    /// Elapsed execution time when reported by the service.
    pub duration_ms: Option<u64>,
}

/// Set the status of the specific flow the user saw, even if a routine has since been rebound.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkflowSwitch {
    /// Stable identity for replaying an activation from a device.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request_id: Option<meep_topic::TaskId>,
    /// External flow identifier from the observed routine binding.
    pub flow_id: String,
    /// Requested active state in PostHog.
    pub enabled: bool,
}

/// Canonical searchable text and identifiers for the server and offline replica.
pub fn search_documents(
    state: Option<&meep_topic::TopicState>,
) -> std::collections::BTreeMap<(&'static str, String), String> {
    let mut docs = std::collections::BTreeMap::new();
    if let Some(state) = state.filter(|s| !s.archived && !s.deleted) {
        let topic = &state.topic;
        let mut insert = |kind, id, text| {
            docs.insert((kind, format!("{}/{id}", topic.id)), text);
        };
        insert(
            "topic",
            topic.id.to_string(),
            format!("{}\n{}", topic.name, topic.mission),
        );
        for t in state
            .threads
            .iter()
            .filter(|t| !state.archived_threads.contains(&t.id))
        {
            let mut text = format!("{}\n{}", t.subject, t.summary);
            if let Some(sources) = &t.report_sources {
                for reference in &sources.references {
                    text.push('\n');
                    text.push_str(reference);
                }
                if let Some(o) = &sources.observation {
                    text.push_str(&format!(
                        "\n{} {} {}",
                        o.connection,
                        o.channel,
                        o.external_id.as_deref().unwrap_or_default()
                    ));
                }
            }
            for message in &t.messages {
                text.push('\n');
                text.push_str(&message.text);
            }
            insert("thread", t.id.to_string(), text);
        }
        for t in &state.tasks {
            insert(
                "task",
                t.id.to_string(),
                format!(
                    "{}\n{}\n{}",
                    t.title,
                    t.result.as_deref().unwrap_or_default(),
                    t.draft.as_deref().unwrap_or_default()
                ),
            );
        }
        for f in topic.facts.iter().filter(|f| f.is_current()) {
            insert("fact", f.id.to_string(), f.text.clone());
        }
    }
    docs
}

#[cfg(test)]
mod credential_tests {
    use super::*;
    #[test]
    fn older_workflow_details_have_unknown_manual_run_capability() -> serde_json::Result<()> {
        let old = serde_json::json!({"enabled":true,"steps":[],"runs":[]});
        let details: WorkflowDetails = serde_json::from_value(old)?;
        assert_eq!(details.manual_run_allowed, None);
        assert!(
            serde_json::to_value(details)?
                .get("manual_run_allowed")
                .is_none()
        );
        Ok(())
    }
    #[test]
    fn credentials_round_trip_on_the_wire_and_stay_out_of_diagnostics() -> serde_json::Result<()> {
        let grant: ConnectionGrant = serde_json::from_value(
            serde_json::json!({"kind":"posthog","label":"Work","secrets":{"access_token":"private-value"}}),
        )?;
        let callback = RoutineCallback {
            secret: "private-value".into(),
            op: serde_json::Value::Null,
        };
        assert_eq!(
            serde_json::from_slice::<ConnectionGrant>(&serde_json::to_vec(&grant)?)?,
            grant
        );
        assert_eq!(
            serde_json::from_slice::<RoutineCallback>(&serde_json::to_vec(&callback)?)?,
            callback
        );
        assert!(!format!("{grant:?} {callback:#?}").contains("private-value"));
        Ok(())
    }
}
