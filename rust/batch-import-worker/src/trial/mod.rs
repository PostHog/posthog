use std::collections::HashMap;

use common_types::InternallyCapturedEvent;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

pub mod job;
pub mod parser;
pub mod sink;

pub use job::TrialJob;

/// Cap on distinct event names tracked in the summary; everything past it is
/// folded into `other_event_names` so a pathological source can't bloat the
/// state JSON persisted to Postgres on every chunk.
const EVENT_NAME_COUNT_CAP: usize = 500;
/// Same guard for distinct error messages.
const ERROR_COUNT_CAP: usize = 100;
/// Byte cap on each summary key (event name or error message). Keys come from
/// user data and a single one can be nearly a whole source line, so without
/// this the count caps alone still let the persisted state grow unbounded.
const SUMMARY_KEY_MAX_BYTES: usize = 200;
/// Timestamps longer than this cannot be the RFC 3339 strings the transforms
/// produce; ignore them instead of cloning arbitrary payload data into state.
const TIMESTAMP_MAX_BYTES: usize = 64;

/// One source line paired with the event(s) it would produce on a real import.
/// Empty `outputs` with an `error` means the line would be dropped; empty
/// `outputs` without one means it was intentionally skipped (e.g. a Mixpanel
/// event with no distinct id, or an Amplitude session marker).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrialRecord {
    pub source: Value,
    pub outputs: Vec<TrialOutputEvent>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// A browsable projection of an [`InternallyCapturedEvent`]: the double-encoded
/// `data` payload is parsed back into JSON so the UI can render the target event
/// without unwrapping capture internals, and capture-transport fields (token,
/// now, sent_at) are dropped.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrialOutputEvent {
    pub uuid: Uuid,
    pub distinct_id: String,
    pub event: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timestamp: Option<String>,
    pub payload: Value,
}

impl From<InternallyCapturedEvent> for TrialOutputEvent {
    fn from(e: InternallyCapturedEvent) -> Self {
        let payload: Value = serde_json::from_str(&e.inner.data).unwrap_or(Value::Null);
        let event = payload
            .get("event")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let timestamp = payload
            .get("timestamp")
            .and_then(Value::as_str)
            .map(String::from);
        Self {
            uuid: e.inner.uuid,
            distinct_id: e.inner.distinct_id,
            event,
            timestamp,
            payload,
        }
    }
}

/// Trial progress persisted inside the job's `state` JSON. Written only after
/// the corresponding pages are durably in object storage, so a resumed trial
/// re-fetches at most one chunk and overwrites the same page indices.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TrialProgress {
    pub records_emitted: u64,
    pub pages_written: u32,
    pub summary: TrialSummary,
}

impl TrialProgress {
    /// Truncate one chunk's records to the remaining budget under `record_limit`.
    pub fn truncate_to_budget(&self, records: &mut Vec<TrialRecord>, record_limit: u64) {
        let remaining = record_limit.saturating_sub(self.records_emitted);
        records.truncate(remaining as usize);
    }

    /// Fold one chunk's durably written records (and the pages holding them)
    /// into the running progress.
    pub fn absorb(&mut self, records: &[TrialRecord], pages: u32) {
        for record in records {
            self.summary.record(record);
        }
        self.records_emitted += records.len() as u64;
        self.pages_written += pages;
    }
}

/// Running aggregates over the emitted records; becomes `summary.json` when the
/// trial completes.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TrialSummary {
    pub source_records: u64,
    pub output_events: u64,
    /// Records that failed to parse or transform (have an `error`).
    pub dropped_records: u64,
    /// Records intentionally producing no output (no `error`).
    pub skipped_records: u64,
    pub event_name_counts: HashMap<String, u64>,
    #[serde(default, skip_serializing_if = "is_zero")]
    pub other_event_names: u64,
    pub error_counts: HashMap<String, u64>,
    #[serde(default, skip_serializing_if = "is_zero")]
    pub other_errors: u64,
    /// Lexicographic min/max of output event timestamps; correct for the
    /// RFC 3339 strings the transforms produce.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub first_timestamp: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_timestamp: Option<String>,
}

fn is_zero(v: &u64) -> bool {
    *v == 0
}

impl TrialSummary {
    pub fn record(&mut self, record: &TrialRecord) {
        self.source_records += 1;
        self.output_events += record.outputs.len() as u64;

        match (&record.error, record.outputs.is_empty()) {
            (Some(error), _) => {
                self.dropped_records += 1;
                if !bounded_count(&mut self.error_counts, error, ERROR_COUNT_CAP) {
                    self.other_errors += 1;
                }
            }
            (None, true) => self.skipped_records += 1,
            (None, false) => {}
        }

        for output in &record.outputs {
            if !bounded_count(
                &mut self.event_name_counts,
                &output.event,
                EVENT_NAME_COUNT_CAP,
            ) {
                self.other_event_names += 1;
            }
            if let Some(ts) = &output.timestamp {
                if ts.len() > TIMESTAMP_MAX_BYTES {
                    continue;
                }
                if self.first_timestamp.as_ref().is_none_or(|f| ts < f) {
                    self.first_timestamp = Some(ts.clone());
                }
                if self.last_timestamp.as_ref().is_none_or(|l| ts > l) {
                    self.last_timestamp = Some(ts.clone());
                }
            }
        }
    }
}

/// Increment `key` in `counts`, refusing to add new keys past `cap`. Keys are
/// truncated to [`SUMMARY_KEY_MAX_BYTES`] first, so oversized names share one
/// truncated entry instead of each growing the state. Returns whether the
/// count was recorded.
fn bounded_count(counts: &mut HashMap<String, u64>, key: &str, cap: usize) -> bool {
    let key = truncate_at_char_boundary(key, SUMMARY_KEY_MAX_BYTES);
    if let Some(count) = counts.get_mut(key) {
        *count += 1;
        return true;
    }
    if counts.len() >= cap {
        return false;
    }
    counts.insert(key.to_string(), 1);
    true
}

fn truncate_at_char_boundary(s: &str, max_bytes: usize) -> &str {
    if s.len() <= max_bytes {
        return s;
    }
    let mut end = max_bytes;
    while !s.is_char_boundary(end) {
        end -= 1;
    }
    &s[..end]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn output(event: &str, timestamp: Option<&str>) -> TrialOutputEvent {
        TrialOutputEvent {
            uuid: Uuid::now_v7(),
            distinct_id: "u".to_string(),
            event: event.to_string(),
            timestamp: timestamp.map(String::from),
            payload: Value::Null,
        }
    }

    fn record(outputs: Vec<TrialOutputEvent>, error: Option<&str>) -> TrialRecord {
        TrialRecord {
            source: Value::Null,
            outputs,
            error: error.map(String::from),
        }
    }

    #[test]
    fn summary_classifies_records_and_tracks_timestamp_range() {
        let mut summary = TrialSummary::default();
        summary.record(&record(
            vec![
                output("a", Some("2024-01-02T00:00:00Z")),
                output("b", Some("2024-01-01T00:00:00Z")),
            ],
            None,
        ));
        summary.record(&record(vec![], Some("bad line")));
        summary.record(&record(vec![], Some("bad line")));
        summary.record(&record(vec![], None)); // intentionally skipped

        assert_eq!(summary.source_records, 4);
        assert_eq!(summary.output_events, 2);
        assert_eq!(summary.dropped_records, 2);
        assert_eq!(summary.skipped_records, 1);
        assert_eq!(summary.event_name_counts["a"], 1);
        assert_eq!(summary.event_name_counts["b"], 1);
        assert_eq!(summary.error_counts["bad line"], 2);
        assert_eq!(
            summary.first_timestamp.as_deref(),
            Some("2024-01-01T00:00:00Z")
        );
        assert_eq!(
            summary.last_timestamp.as_deref(),
            Some("2024-01-02T00:00:00Z")
        );
    }

    #[test]
    fn summary_bounds_key_bytes_and_ignores_oversized_timestamps() {
        let mut summary = TrialSummary::default();
        let long_a = format!("{}_a", "x".repeat(SUMMARY_KEY_MAX_BYTES));
        let long_b = format!("{}_b", "x".repeat(SUMMARY_KEY_MAX_BYTES));
        let huge_ts = "9".repeat(TIMESTAMP_MAX_BYTES + 1);
        summary.record(&record(
            vec![
                output(&long_a, Some(&huge_ts)),
                output(&long_b, Some("2024-01-01T00:00:00Z")),
            ],
            None,
        ));
        summary.record(&record(vec![], Some(&long_a)));

        // Distinct oversized names merge into one truncated key
        assert_eq!(summary.event_name_counts.len(), 1);
        let (key, count) = summary.event_name_counts.iter().next().unwrap();
        assert_eq!(key.len(), SUMMARY_KEY_MAX_BYTES);
        assert_eq!(*count, 2);

        let error_key = summary.error_counts.keys().next().unwrap();
        assert_eq!(error_key.len(), SUMMARY_KEY_MAX_BYTES);

        // The oversized timestamp is ignored; the valid one still tracks
        assert_eq!(
            summary.first_timestamp.as_deref(),
            Some("2024-01-01T00:00:00Z")
        );
        assert_eq!(
            summary.last_timestamp.as_deref(),
            Some("2024-01-01T00:00:00Z")
        );
    }

    #[test]
    fn summary_caps_distinct_event_names() {
        let mut summary = TrialSummary::default();
        let outputs: Vec<_> = (0..EVENT_NAME_COUNT_CAP + 2)
            .map(|i| output(&format!("event_{i}"), None))
            .collect();
        summary.record(&record(outputs, None));

        assert_eq!(summary.event_name_counts.len(), EVENT_NAME_COUNT_CAP);
        assert_eq!(summary.other_event_names, 2);
        assert_eq!(summary.output_events, (EVENT_NAME_COUNT_CAP + 2) as u64);
    }
}
