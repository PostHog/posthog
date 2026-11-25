//! Backfill only re-decodes the turn that crosses a page boundary. Published complete
//! turns keep their identity and allocation when older entries arrive.
use super::{History, Turn};
use crate::tasks::ConversationPage;
use anyhow::{Result, ensure};
use serde_json::Value;
use std::{collections::VecDeque, sync::Arc};
use uuid::Uuid;

/// An incrementally loaded transcript spanning contiguous pages of a run.
#[derive(Default)]
pub struct PagedHistory {
    /// Log origin reported by the server, used to detect changes between pages.
    pub origin: Option<String>,
    /// Offset of the earliest fetched entry.
    pub oldest: usize,
    /// Exclusive offset for the next append.
    pub end: usize,
    /// Latest controls and completion state for the run.
    pub state: History,
    sections: VecDeque<History>,
    // Entries of the first, potentially incomplete, turn and preceding pages without
    // a turn boundary. Kept only until its beginning has been found.
    head: Vec<Value>,
    pending: VecDeque<Value>,
    closed: bool,
    run: Uuid,
}

fn complete(event: &Value) -> bool {
    event
        .pointer("/notification/method")
        .and_then(Value::as_str)
        == Some("_posthog/turn_complete")
}

impl PagedHistory {
    /// Start with a page from the tail of the run.
    pub fn latest(run: Uuid, page: ConversationPage) -> Self {
        let mut this = Self {
            run,
            oldest: page.offset,
            end: page.offset,
            origin: page.origin,
            ..Default::default()
        };
        for event in page.preamble {
            this.control(&event);
        }
        this.extend(page.entries);
        this
    }

    fn control(&mut self, event: &Value) {
        // Track only live controls here. Transcript data belongs to the sections.
        let method = event
            .pointer("/notification/method")
            .and_then(Value::as_str);
        let update = event
            .pointer("/notification/params/update/sessionUpdate")
            .and_then(Value::as_str);
        match (method, update) {
            (Some("session/prompt" | "_posthog/user_message"), _)
            | (_, Some("user_message" | "user_message_chunk")) => {
                self.state.busy = Some(true);
                self.state.stopped = false;
            }
            (
                Some(
                    "_posthog/run_started"
                    | "_posthog/turn_complete"
                    | "_posthog/permission_request"
                    | "_posthog/permission_resolved",
                ),
                _,
            )
            | (_, Some("config_option_update")) => self.state.apply(self.run, event, None),
            _ => {}
        }
    }

    fn extend(&mut self, entries: impl IntoIterator<Item = Value>) {
        for event in entries {
            self.control(&event);
            let section = match self.sections.back_mut() {
                Some(section) if !self.closed => section,
                _ => self.sections.push_back_mut(History {
                    cursor: self.end,
                    ..Default::default()
                }),
            };
            section.apply(self.run, &event, None);
            self.closed = complete(&event);
            if self.sections.len() == 1 && self.oldest > 0 {
                self.head.push(event);
            }
            self.end += 1;
        }
    }

    /// Apply the next page at the current end cursor.
    pub fn append(&mut self, page: ConversationPage) -> Result<()> {
        ensure!(
            page.origin == self.origin && page.offset == self.end,
            "Conversation cursor changed"
        );
        self.extend(page.entries);
        Ok(())
    }

    /// Backfill the page ending at the oldest loaded cursor.
    pub fn prepend(&mut self, page: ConversationPage) -> Result<()> {
        ensure!(
            page.origin == self.origin
                && page.offset < self.oldest
                && page.offset.checked_add(page.entries.len()) == Some(self.oldest),
            "Noncontiguous conversation history"
        );
        self.oldest = page.offset;
        let boundary = page.entries.iter().any(complete);
        for event in page.entries.into_iter().rev() {
            if self.state.config.is_empty()
                && event
                    .pointer("/notification/params/update/sessionUpdate")
                    .and_then(Value::as_str)
                    == Some("config_option_update")
            {
                self.state.apply(self.run, &event, None);
            }
            self.pending.push_front(event);
        }
        if !boundary && self.oldest > 0 {
            return Ok(());
        }
        let mut prefix = Self {
            oldest: self.oldest,
            end: self.oldest,
            run: self.run,
            ..Default::default()
        };
        self.pending.extend(self.head.drain(..));
        prefix.extend(self.pending.drain(..));
        self.sections.pop_front();
        if self.sections.is_empty() {
            self.closed = prefix.closed;
        }
        prefix.sections.append(&mut self.sections);
        self.sections = prefix.sections;
        self.head = prefix.head;
        Ok(())
    }

    /// Iterate decoded rows in chronological order across loaded pages.
    pub fn turns(&self) -> impl Iterator<Item = &Arc<Turn>> {
        self.sections.iter().flat_map(|part| &part.turns)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn event(method: &str, params: Value) -> Value {
        json!({"notification": {"method": method, "params":params}})
    }
    fn page(offset: usize, entries: &[Value], count: usize) -> ConversationPage {
        ConversationPage {
            origin: Some("chain".into()),
            offset,
            count,
            preamble: vec![],
            entries: entries.to_vec(),
        }
    }

    #[test]
    fn backfilling_and_appending_across_every_cut_recovers_the_exact_transcript() {
        let mut events = vec![];
        for i in 0..9 {
            events.extend([
                event("_posthog/user_message",json!({"content":format!("question {i}")})),
                event("session/prompt",json!({"prompt":[{"type":"text","text":format!("question {i}")}]})),
                event("session/update",json!({"update":{"sessionUpdate":"agent_thought_chunk","content":{"text":"checking"}}})),
                event("session/update",json!({"update":{"sessionUpdate":"tool_call","toolCallId":format!("tool-{i}"),"title":"Read"}})),
                event("session/update",json!({"update":{"sessionUpdate":"tool_call_update","toolCallId":format!("tool-{i}"),"rawOutput":"output","status":"completed"}})),
                event("session/update",json!({"update":{"sessionUpdate":"agent_message_chunk","content":{"text":"answer"}}})),
                event("_posthog/turn_complete",json!({"stopReason":"end_turn"})),
            ]);
        }
        let n = events.len();
        let reference = PagedHistory::latest(Uuid::nil(), page(0, &events, n));
        for cut in 1..n - 2 {
            let mut log = PagedHistory::latest(Uuid::nil(), page(cut, &events[cut..n - 2], n - 2));
            log.append(page(n - 2, &events[n - 2..], n)).unwrap();
            while log.oldest > 0 {
                let before = log.oldest;
                let offset = before.saturating_sub(4);
                log.prepend(page(offset, &events[offset..before], n))
                    .unwrap();
            }
            assert!(
                reference.turns().eq(log.turns()),
                "Cut {cut} lost or duplicated content"
            );
        }
    }
}
