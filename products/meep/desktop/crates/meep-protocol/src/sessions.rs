//! Agent transcript data, without a harness or transport.
use serde::{Deserialize, Serialize};

/// A selection in a particular revision of a view.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ElementReference {
    /// Identifier of this selection.
    pub id: String,
    /// View containing the selected element.
    pub view_id: String,
    /// Revision visible when the selection was made.
    pub revision: String,
    /// Identifier assigned to the element by the view.
    pub element_id: String,
    /// Display label captured with the selection.
    pub label: String,
    /// Role of the selected element.
    pub role: String,
    /// Source file for the selected element, when available.
    pub source_file: Option<String>,
    /// Line in the source file, when available.
    pub source_line: Option<u32>,
    /// Logical pixels relative to the selected view, not screen coordinates.
    pub bounds: [f32; 4],
    /// Message attached to the selection.
    pub comment: String,
    /// Whether the selection belongs to an earlier revision.
    #[serde(default)]
    pub stale: bool,
}
/// Metadata for a file sent with a message.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MessageAttachment {
    /// Attachment identifier.
    pub id: String,
    /// Display filename.
    pub name: String,
    /// Media type supplied by the host.
    pub mime_type: String,
    /// File size in bytes.
    pub bytes: usize,
}
/// One user or agent turn in a conversation.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct AgentMessage {
    /// Author role, such as `user` or `assistant`.
    pub role: String,
    /// Display name of the responding agent, when known.
    #[serde(default)]
    pub agent_name: String,
    /// Message body or plain-text summary of a structured turn.
    pub text: String,
    /// Ordered content and tool calls in the turn.
    #[serde(default)]
    pub blocks: Vec<SessionBlock>,
    /// View selections included by the sender.
    #[serde(default)]
    pub references: Vec<ElementReference>,
    /// Files included by the sender.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub attachments: Vec<MessageAttachment>,
    /// When the message was sent or the reply began, in Unix milliseconds.
    /// Zero for messages saved before timestamps were kept.
    #[serde(default)]
    pub created_at: i64,
}
/// One piece of text, reasoning, or tool activity within a turn.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct SessionBlock {
    /// Block identifier.
    pub id: String,
    /// Content kind, such as `text`, `thinking`, or `tool`.
    pub kind: String,
    /// Block text or tool name.
    pub text: String,
    /// Optional service identity for a tool row, separate from its authored title.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub app: Option<String>,
    /// Execution state for an activity block.
    #[serde(default)]
    pub status: String,
    /// Tool input as presented to the reader.
    #[serde(default)]
    pub input: String,
    /// Tool result as presented to the reader.
    #[serde(default)]
    pub output: String,
}
/// A request for a decision, anchored to a turn in the transcript.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentApproval {
    /// Index of the turn that requested approval.
    #[serde(default)]
    pub message_index: usize,
    /// Number of blocks in the turn when the request was made, so the card stays
    /// beside the tool call that asked for it. Older records fall back to the turn end.
    #[serde(default)]
    pub block_index: Option<usize>,
    /// Approval request identifier.
    pub id: String,
    /// Short description of the proposed action.
    pub title: String,
    /// Reason the agent requested approval.
    pub reason: String,
    /// Additional context for the decision.
    pub detail: String,
    /// Current state of the request, such as `pending`.
    pub status: String,
    /// Provider-specific description of the proposed change.
    pub change: serde_json::Value,
}
/// A conversation, its execution status, and outstanding or resolved approvals.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AgentSession {
    /// Session identifier.
    pub id: String,
    /// The topic that owns this conversation, when recorded.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub topic: Option<String>,
    /// The associated view in older sessions. Topic chats can omit it.
    #[serde(default)]
    pub view_id: String,
    /// Conversation title.
    pub title: String,
    /// Execution state, such as `running` or `idle`.
    pub status: String,
    /// Conversation turns in display order.
    pub messages: Vec<AgentMessage>,
    /// Session error to display, when present.
    pub error: Option<String>,
    /// Command used by a View launcher to start the agent.
    #[serde(default)]
    pub agent_command: String,
    /// Resume token recorded by the launcher.
    #[serde(default)]
    pub provider_session_id: Option<String>,
    /// Launcher protocol version recorded by View.
    #[serde(default)]
    pub secure_launcher_version: Option<u32>,
    /// Selected model, when recorded.
    #[serde(default)]
    pub model_id: Option<String>,
    /// Selected reasoning effort, when recorded.
    #[serde(default)]
    pub effort: Option<String>,
    /// Approval requests associated with the conversation.
    #[serde(default)]
    pub approvals: Vec<AgentApproval>,
}

/// Display label for a session execution state.
pub fn human_status(value: &str) -> &str {
    match value {
        "running" => "Working",
        "idle" => "Ready",
        "cancelled" => "Stopped",
        "interrupted" => "Interrupted",
        _ => "Needs attention",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{from_value, json, to_value};

    #[test]
    fn legacy_session_round_trips_the_launcher_and_selected_element() -> serde_json::Result<()> {
        let wire = json!({
            "id": "s1", "view_id": "weekly", "title": "Explain chart", "status": "idle",
            "messages": [{
                "role": "user", "agent_name": "", "text": "Why did this change?",
                "blocks": [], "created_at": 0,
                "references": [{
                    "id": "r1", "view_id": "weekly", "revision": "7", "element_id": "chart",
                    "label": "Revenue", "role": "chart", "source_file": "view.js",
                    "source_line": 10, "bounds": [1.0, 2.0, 30.0, 40.0],
                    "comment": "Compare to last week", "stale": false
                }]
            }],
            "error": null, "agent_command": "codex", "provider_session_id": "resume-1",
            "secure_launcher_version": 3, "model_id": null, "effort": null, "approvals": []
        });
        let session: AgentSession = from_value(wire.clone())?;
        assert_eq!(session.topic, None);
        assert_eq!(session.messages[0].references[0].element_id, "chart");
        assert_eq!(to_value(session)?, wire);
        Ok(())
    }

    #[test]
    fn a_topic_message_can_refer_to_an_element_in_a_specific_view_revision()
    -> serde_json::Result<()> {
        let session: AgentSession = from_value(json!({
            "id": "s3", "topic": "weekly", "title": "Chart question", "status": "idle",
            "messages": [{
                "role": "user", "text": "What changed here?",
                "references": [{
                    "id": "r3", "view_id": "dashboard", "revision": "17", "element_id": "trend",
                    "label": "Seven-day trend", "role": "chart", "bounds": [0, 0, 80, 40],
                    "comment": "The last point"
                }]
            }]
        }))?;
        let restored: AgentSession = from_value(to_value(&session)?)?;
        assert_eq!(restored, session);
        assert_eq!(restored.topic.as_deref(), Some("weekly"));
        assert!(restored.agent_command.is_empty());
        assert!(restored.view_id.is_empty());
        let selected = &restored.messages[0].references[0];
        assert_eq!(selected.view_id, "dashboard");
        assert_eq!(selected.revision, "17");
        assert_eq!(selected.element_id, "trend");
        Ok(())
    }
}
