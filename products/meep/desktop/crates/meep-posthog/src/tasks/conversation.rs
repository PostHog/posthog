//! The conversation log includes the resume chain. Cursors count actual log entries,
//! excluding the repeated state preamble. The server chooses safe cuts between turns or tools.
use super::Tasks;
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

/// Select a window of the run's conversation log.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub enum LogWindow {
    /// Fetch the latest available page.
    Latest,
    /// Fetch entries preceding the supplied offset.
    Before(usize),
    /// Fetch entries starting at the supplied offset.
    From(usize),
}

/// A contiguous range of conversation entries and its control preamble.
#[derive(Debug, Serialize, Deserialize)]
pub struct ConversationPage {
    /// Log origin used to verify continuity across pages.
    pub origin: Option<String>,
    /// Index of the first entry in this page.
    pub offset: usize,
    /// Total number of entries observed on the server.
    pub count: usize,
    /// Repeated control events outside the numbered entries.
    pub preamble: Vec<Value>,
    /// Numbered entries in conversation order.
    pub entries: Vec<Value>,
}

impl Tasks {
    /// Read a conversation page without projecting its events.
    pub async fn conversation_page(
        &self,
        token: &str,
        task: Uuid,
        run: Uuid,
        window: LogWindow,
    ) -> Result<ConversationPage> {
        self.conversation_page_with(token, task, run, window, |event| event)
            .await
    }

    /// Project each JSONL record as it arrives, keeping only the data an embedding host needs.
    /// Every record still occupies its cursor position, including a projection to null.
    pub async fn conversation_page_with(
        &self,
        token: &str,
        task: Uuid,
        run: Uuid,
        window: LogWindow,
        project: impl Fn(Value) -> Value,
    ) -> Result<ConversationPage> {
        let mut path = format!("{task}/runs/{run}/logs/?view=thread&tail_bytes=65536");
        match window {
            LogWindow::Latest => {}
            LogWindow::Before(i) => path.push_str(&format!("&before={i}")),
            LogWindow::From(i) => path.push_str(&format!("&start={i}")),
        }
        let mut response = self.api.get_response(token, &path).await?;
        let headers = response.headers();
        let number = |name| -> Result<Option<usize>> {
            headers
                .get(name)
                .map(|v| Ok(v.to_str()?.parse()?))
                .transpose()
        };
        let offset = number("x-log-offset")?.unwrap_or_default();
        let total = number("x-log-count")?;
        let leading = number("x-log-preamble")?.unwrap_or_default();
        let origin = headers
            .get("x-log-origin")
            .map(|v| v.to_str().map(str::to_owned))
            .transpose()?;
        let mut preamble = Vec::new();
        let mut entries = Vec::new();
        let mut partial = Vec::new();
        let skip = match (total, window) {
            (None, LogWindow::From(start)) => start,
            _ => 0,
        };
        let mut seen = 0;
        let mut record = |line: &[u8]| -> Result<()> {
            if line.iter().all(u8::is_ascii_whitespace) {
                return Ok(());
            }
            if seen < skip {
                seen += 1;
                return Ok(());
            }
            seen += 1;
            let entry =
                project(serde_json::from_slice(line).context("Invalid conversation log entry")?);
            if preamble.len() < leading {
                preamble.push(entry);
            } else {
                entries.push(entry);
            }
            Ok(())
        };
        while let Some(chunk) = response.chunk().await? {
            for fragment in chunk.split_inclusive(|&byte| byte == b'\n') {
                if fragment.last() == Some(&b'\n') {
                    if partial.is_empty() {
                        record(fragment)?;
                    } else {
                        partial.extend_from_slice(fragment);
                        record(&partial)?;
                        partial.clear();
                    }
                } else {
                    partial.extend_from_slice(fragment);
                }
            }
        }
        if !partial.is_empty() {
            record(&partial)?;
        }
        let count = total.unwrap_or(seen);
        let offset = if total.is_none() {
            skip.min(seen)
        } else {
            offset
        };
        let end = offset
            .checked_add(entries.len())
            .context("Invalid conversation range")?;
        ensure!(
            preamble.len() == leading && end <= count,
            "Incomplete conversation page"
        );
        Ok(ConversationPage {
            origin,
            offset,
            count,
            preamble,
            entries,
        })
    }
}
