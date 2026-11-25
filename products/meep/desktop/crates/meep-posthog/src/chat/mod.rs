//! Incremental presentation of PostHog Desktop's public ACP session events.
mod pages;
use chrono::{DateTime, Utc};
pub use pages::PagedHistory;
use std::sync::Arc;

use meep_protocol::sessions::{AgentMessage, MessageAttachment, SessionBlock};
use serde_json::Value;
use std::collections::BTreeMap;
use uuid::Uuid;

/// A transcript row with its timestamp, speaker and rendered message.
#[derive(Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct Turn {
    /// Timestamp from the log entry or its supplied fallback.
    pub at: Option<DateTime<Utc>>,
    /// Stable row identifier used when extending the transcript.
    pub id: String,
    /// Speaker label shown in the transcript.
    pub speaker: String,
    /// Message content and its presentation blocks.
    pub message: AgentMessage,
    source: Option<(Uuid, usize, usize)>,
}

impl std::ops::Deref for Turn {
    type Target = AgentMessage;
    fn deref(&self) -> &AgentMessage {
        &self.message
    }
}
impl std::ops::DerefMut for Turn {
    fn deref_mut(&mut self) -> &mut AgentMessage {
        &mut self.message
    }
}

impl Turn {
    /// Create a transcript row for a host-supplied message.
    pub fn new(id: String, speaker: &str, text: String, at: Option<DateTime<Utc>>) -> Self {
        let role = if matches!(speaker, "Agent" | "PostHog") {
            "assistant"
        } else {
            "user"
        };
        Self {
            id,
            at,
            speaker: speaker.into(),
            source: None,
            message: AgentMessage {
                role: role.into(),
                agent_name: if speaker == "Agent" {
                    "PostHog agent"
                } else {
                    speaker
                }
                .into(),
                text,
                created_at: at.map_or(0, |v| v.timestamp_millis()),
                ..Default::default()
            },
        }
    }
    /// A partial assistant row can gain earlier blocks after backfilling a split turn.
    pub fn extends_front_of(&self, suffix: &Self) -> bool {
        match (self.source, suffix.source) {
            (Some((run, start, end)), Some((old_run, old_start, old_end))) => {
                run == old_run
                    && self.speaker == suffix.speaker
                    && start < old_start
                    && end >= old_end
            }
            _ => false,
        }
    }
}

/// Incremental transcript and control state for one run.
#[derive(Default)]
pub struct History {
    turns: Vec<Arc<Turn>>,
    /// Latest busy or idle observation, if one has arrived.
    pub busy: Option<bool>,
    /// Outstanding permission requests keyed by request ID.
    pub permissions: BTreeMap<String, Value>,
    /// Latest configuration choices advertised by the runtime.
    pub config: Vec<Value>,
    /// Number of turn-completion events received.
    pub completed_turns: usize,
    /// Whether the latest turn completed by cancellation.
    pub stopped: bool,
    cursor: usize,
    last_user: Option<(usize, u8)>,
    assistant: Option<usize>,
    tools: BTreeMap<String, (usize, usize)>,
}

/// Parse a timestamp supplied by a PostHog log entry.
pub fn timestamp(value: Option<&str>) -> Option<DateTime<Utc>> {
    value
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
        .map(|t| t.to_utc())
}

/// Project a wire event to the data used by this transcript. In particular, a
/// pasted image stays a typed attachment rather than an in-memory base64 string.
pub fn transcript_event(mut entry: Value) -> Value {
    let method = entry
        .pointer("/notification/method")
        .and_then(Value::as_str)
        .unwrap_or("");
    let Some(params) = entry.pointer("/notification/params") else {
        return Value::Null;
    };
    match method {
        "_posthog/run_started"
        | "_posthog/turn_complete"
        | "_posthog/user_message"
        | "_posthog/permission_request"
        | "_posthog/permission_resolved"
        | "session/prompt" => {}
        "session/update"
            if matches!(
                params
                    .pointer("/update/sessionUpdate")
                    .and_then(Value::as_str),
                Some(
                    "tool_call"
                        | "tool_call_update"
                        | "agent_thought_chunk"
                        | "agent_message"
                        | "agent_message_chunk"
                        | "user_message"
                        | "user_message_chunk"
                        | "config_option_update"
                )
            ) => {}
        _ => return Value::Null,
    }
    if let Some(update) = entry
        .pointer_mut("/notification/params/update")
        .and_then(Value::as_object_mut)
    {
        update.remove("_meta");
    }
    fn omit_media(value: &mut Value) {
        match value {
            Value::Array(items) => items.iter_mut().for_each(omit_media),
            Value::Object(map) => {
                if matches!(
                    map.get("type").and_then(Value::as_str),
                    Some("image" | "audio")
                ) {
                    map.remove("data");
                }
                if map.contains_key("mimeType") && map.contains_key("uri") {
                    map.remove("blob");
                }
                map.values_mut().for_each(omit_media);
            }
            _ => {}
        }
    }
    omit_media(&mut entry);
    entry
}

fn visible_part(part: &Value) -> bool {
    part.pointer("/_meta/ui/hidden").and_then(Value::as_bool) != Some(true)
}

fn display(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(s) => s.clone(),
        v => serde_json::to_string_pretty(v).unwrap_or_default(),
    }
}

impl History {
    /// Decoded turns in conversation order.
    pub fn turns(&self) -> &[Arc<Turn>] {
        &self.turns
    }

    fn turn(&mut self, run: Uuid, speaker: &str, text: String, at: Option<DateTime<Utc>>) -> usize {
        let i = self.turns.len();
        let mut turn = Turn::new(format!("{run}-{}", self.cursor), speaker, text, at);
        turn.source = Some((run, self.cursor, self.cursor));
        self.turns.push(Arc::new(turn));
        i
    }

    fn assistant(&mut self, run: Uuid, at: Option<DateTime<Utc>>) -> usize {
        if let Some(i) = self.assistant {
            if let Some(source) = &mut Arc::make_mut(&mut self.turns[i]).source {
                source.2 = self.cursor;
            }
            return i;
        }
        let i = self.turn(run, "Agent", String::new(), at);
        self.assistant = Some(i);
        i
    }

    /// Consume one log entry in order, using the fallback when its timestamp is absent.
    pub fn apply(&mut self, run: Uuid, entry: &Value, fallback: Option<DateTime<Utc>>) {
        self.cursor += 1;
        let at = timestamp(entry["timestamp"].as_str()).or(fallback);
        let n = &entry["notification"];
        let p = &n["params"];
        match n["method"].as_str().unwrap_or("") {
            "_posthog/run_started" => {
                self.busy = Some(true);
                self.assistant = None;
                self.permissions.clear();
            }
            "_posthog/turn_complete" => {
                self.busy = Some(false);
                self.assistant = None;
                self.completed_turns += 1;
                self.last_user = None;
                self.permissions.clear();
                self.stopped = matches!(p["stopReason"].as_str(), Some("cancelled" | "canceled"));
            }
            "_posthog/permission_request" => {
                if let Some(id) = p["requestId"].as_str() {
                    self.permissions.insert(id.into(), p.clone());
                }
            }
            "_posthog/permission_resolved" => {
                if let Some(id) = p["requestId"].as_str() {
                    self.permissions.remove(id);
                }
            }
            "_posthog/user_message" => {
                let contents = &p["content"];
                let text = contents
                    .as_str()
                    .or_else(|| contents["text"].as_str())
                    .map(str::to_owned)
                    .unwrap_or_else(|| {
                        contents
                            .as_array()
                            .into_iter()
                            .flatten()
                            .filter(|c| visible_part(c))
                            .filter_map(|c| c["text"].as_str())
                            .collect::<Vec<_>>()
                            .join("\n")
                    });
                if !text.is_empty() {
                    self.user(run, text, at, 1);
                }
            }
            "session/prompt" => {
                self.assistant = None;
                self.busy = Some(true);
                self.stopped = false;
                let parts = p["prompt"]
                    .as_array()
                    .map(Vec::as_slice)
                    .unwrap_or_default();
                let text = parts
                    .iter()
                    .filter(|part| part["type"] == "text" && visible_part(part))
                    .filter_map(|part| part["text"].as_str())
                    .collect::<Vec<_>>()
                    .join("\n");
                let attachments = parts
                    .iter()
                    .filter(|part| {
                        visible_part(part)
                            && matches!(
                                part["type"].as_str(),
                                Some("resource_link" | "resource" | "image" | "audio")
                            )
                    })
                    .enumerate()
                    .map(|(i, part)| {
                        let uri = part["uri"]
                            .as_str()
                            .or_else(|| part.pointer("/resource/uri").and_then(Value::as_str));
                        MessageAttachment {
                            id: format!("{run}-{}-{i}", self.cursor),
                            name: part["name"]
                                .as_str()
                                .or_else(|| uri.and_then(|v| v.rsplit('/').next()))
                                .unwrap_or("Attachment")
                                .to_owned(),
                            mime_type: part["mimeType"]
                                .as_str()
                                .unwrap_or("application/octet-stream")
                                .into(),
                            bytes: 0,
                        }
                    })
                    .collect::<Vec<_>>();
                if !text.is_empty() || !attachments.is_empty() {
                    let i = self.user(run, text, at, 2);
                    if !attachments.is_empty() {
                        Arc::make_mut(&mut self.turns[i]).attachments = attachments;
                    }
                }
            }
            "session/update" => self.update(run, &p["update"], at),
            _ => {}
        }
    }

    fn user(&mut self, run: Uuid, text: String, at: Option<DateTime<Utc>>, source: u8) -> usize {
        if let Some((ix, forms)) = self.last_user
            && forms & source == 0
            && self.turns[ix].text == text
        {
            self.last_user = Some((ix, forms | source));
            return ix;
        }
        self.assistant = None;
        self.busy = Some(true);
        self.stopped = false;
        let ix = self.turn(run, "You", text, at);
        self.last_user = Some((ix, source));
        ix
    }

    fn update(&mut self, run: Uuid, u: &Value, at: Option<DateTime<Utc>>) {
        let kind = u["sessionUpdate"].as_str().unwrap_or("");
        if matches!(kind, "user_message" | "user_message_chunk") {
            if let Some(text) = u
                .pointer("/content/text")
                .or_else(|| u.get("text"))
                .and_then(Value::as_str)
                && !text.is_empty()
                && visible_part(&u["content"])
            {
                self.user(run, text.into(), at, 4);
            }
            return;
        }
        if kind == "config_option_update" {
            if let Some(items) = u["configOptions"].as_array() {
                self.config = items.clone();
            }
            return;
        }
        if matches!(kind, "tool_call" | "tool_call_update") {
            let Some(id) = u["toolCallId"].as_str() else {
                return;
            };
            let (turn, block) = match self.tools.get(id).copied() {
                Some(pair) => pair,
                None => {
                    let turn = self.assistant(run, at);
                    let blocks = &mut Arc::make_mut(&mut self.turns[turn]).blocks;
                    let block = blocks.len();
                    blocks.push(SessionBlock {
                        id: id.into(),
                        kind: "tool".into(),
                        text: "Tool call".into(),
                        app: None,
                        status: "pending".into(),
                        input: String::new(),
                        output: String::new(),
                    });
                    self.tools.insert(id.to_owned(), (turn, block));
                    (turn, block)
                }
            };
            let turn = Arc::make_mut(&mut self.turns[turn]);
            if let Some(source) = &mut turn.source {
                source.2 = self.cursor;
            }
            let b = &mut turn.blocks[block];
            if let Some(title) = u["title"].as_str() {
                b.text = title.into();
            }
            if let Some(status) = u["status"].as_str() {
                b.status = status.into();
            }
            if let Some(input) = u.get("rawInput") {
                b.input = display(input);
            }
            if let Some(output) = u.get("rawOutput") {
                b.output = display(output);
            } else if let Some(content) = u["content"].as_array() {
                b.output = content
                    .iter()
                    .map(|v| {
                        v.pointer("/content/text")
                            .and_then(Value::as_str)
                            .map(str::to_owned)
                            .unwrap_or_else(|| display(v))
                    })
                    .collect::<Vec<_>>()
                    .join("\n");
            }
            return;
        }
        if !matches!(
            kind,
            "agent_message_chunk" | "agent_message" | "agent_thought_chunk"
        ) {
            return;
        }
        let Some(text) = u.pointer("/content/text").and_then(Value::as_str) else {
            return;
        };
        let i = self.assistant(run, at);
        let turn = Arc::make_mut(&mut self.turns[i]);
        let block_kind = if kind == "agent_thought_chunk" {
            "thinking"
        } else {
            "text"
        };
        if kind == "agent_message" && !turn.text.is_empty() && turn.text == text {
            return;
        }
        let blocks = &mut turn.message.blocks;
        let next = blocks.len();
        let block = match blocks.last_mut() {
            Some(block) if block.kind == block_kind => block,
            _ => blocks.push_mut(SessionBlock {
                id: format!("{}-{next}", turn.id),
                kind: block_kind.into(),
                text: String::new(),
                app: None,
                status: String::new(),
                input: String::new(),
                output: String::new(),
            }),
        };
        let new_text_block = block.text.is_empty();
        if kind == "agent_message" {
            if !text.is_empty() {
                block.text = text.into();
            }
        } else {
            block.text.push_str(text);
        }
        if block_kind == "text" && kind != "agent_message" {
            if new_text_block && !turn.text.is_empty() {
                turn.text.push_str("\n\n");
            }
            turn.text.push_str(text);
        } else if block_kind == "text" {
            turn.text = turn
                .blocks
                .iter()
                .filter(|b| b.kind == "text")
                .map(|b| b.text.as_str())
                .collect::<Vec<_>>()
                .join("\n\n");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn streams_finalizes_and_replays_two_distinct_turns() {
        let run = Uuid::nil();
        let mut history = History::default();
        for (prompt, answer) in [("hello?", "hello"), ("again?", "again")] {
            history.apply(run,&json!({"notification":{"method":"session/prompt","params":{"prompt":[{"type":"text","text":prompt}]}}}),None);
            for (kind, text) in [
                ("agent_message_chunk", &answer[..2]),
                ("agent_message_chunk", &answer[2..]),
                ("agent_message", answer),
            ] {
                history.apply(run,&json!({"notification":{"method":"session/update","params":{"update":{"sessionUpdate":kind,"content":{"type":"text","text":text}}}}}),None);
            }
        }
        assert_eq!(
            history
                .turns
                .iter()
                .map(|t| t.text.as_str())
                .collect::<Vec<_>>(),
            ["hello?", "hello", "again?", "again"]
        );
    }
}

#[cfg(test)]
mod activity_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn tool_updates_reasoning_permissions_and_config_stay_with_their_run() {
        let mut history = History::default();
        let run = Uuid::nil();
        let notify =
            |method: &str, params: Value| json!({"notification":{"method":method,"params":params}});
        history.apply(run, &notify("_posthog/run_started", json!({})), None);
        for update in [
            json!({"sessionUpdate":"agent_thought_chunk","content":{"type":"text","text":"Checking the file"}}),
            json!({"sessionUpdate":"tool_call","toolCallId":"call","title":"Read file","status":"in_progress","rawInput":{"path":"notes.txt"}}),
            json!({"sessionUpdate":"tool_call_update","toolCallId":"call","status":"completed","rawOutput":"Contents"}),
            json!({"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"Found it."}}),
            json!({"sessionUpdate":"config_option_update","configOptions":[{"id":"model","currentValue":"model-a"}]}),
        ] {
            history.apply(
                run,
                &notify("session/update", json!({"update":update})),
                None,
            );
        }
        history.apply(
            run,
            &notify(
                "_posthog/permission_request",
                json!({"requestId":"a","toolCall":{"title":"Read"},"options":[]}),
            ),
            None,
        );
        assert_eq!(history.permissions.len(), 1);
        history.apply(
            run,
            &notify("_posthog/permission_resolved", json!({"requestId":"a"})),
            None,
        );
        history.apply(
            run,
            &notify("_posthog/turn_complete", json!({"stopReason":"end_turn"})),
            None,
        );
        assert!(history.permissions.is_empty());
        assert_eq!(history.busy, Some(false));
        assert_eq!(history.completed_turns, 1);
        assert_eq!(history.config[0]["currentValue"], "model-a");
        let parts = &history.turns[0].blocks;
        assert_eq!(
            parts.iter().map(|b| b.kind.as_str()).collect::<Vec<_>>(),
            ["thinking", "tool", "text"]
        );
        assert_eq!(parts[1].status, "completed");
        assert_eq!(parts[1].output, "Contents");
        assert!(parts[1].input.contains("notes.txt"));
        assert_eq!(history.turns[0].text, "Found it.");
    }
}
