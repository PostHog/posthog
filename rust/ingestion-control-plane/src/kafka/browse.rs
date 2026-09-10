use std::time::{Duration, Instant};

use anyhow::Context;
use common_types::CapturedEventHeaders;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::message::Message;
use rdkafka::{Offset, TopicPartitionList};
use serde::Serialize;

/// Why a browse scan stopped where it did.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowseStop {
    /// Collected the requested number of matching messages.
    Limit,
    /// Scanned the per-request message budget before filling the page.
    ScanBudget,
    Deadline,
    ByteBudget,
    /// Caught up with the high watermark.
    EndOfPartition,
}

/// Equality filters over message headers. No filters matches every message;
/// a message without headers only matches when no filters are set, since it
/// has no values to compare against.
#[derive(Debug, Default, Clone)]
pub struct MessageFilter {
    pub token: Option<String>,
    pub event: Option<String>,
    pub distinct_id: Option<String>,
}

impl MessageFilter {
    fn is_empty(&self) -> bool {
        self.token.is_none() && self.event.is_none() && self.distinct_id.is_none()
    }

    pub fn matches(&self, headers: Option<&CapturedEventHeaders>) -> bool {
        let Some(headers) = headers else {
            return self.is_empty();
        };
        let wants = |want: &Option<String>, got: &Option<String>| match want {
            None => true,
            Some(want) => got.as_deref() == Some(want.as_str()),
        };
        wants(&self.token, &headers.token)
            && wants(&self.event, &headers.event)
            && wants(&self.distinct_id, &headers.distinct_id)
    }
}

/// Per-message cap on payload bytes carried in a record. Kafka already
/// transferred the full record to scan its headers, so keeping a bounded
/// slice costs nothing extra on the broker side while keeping a 100-message
/// response from ballooning past a few MB.
const PAYLOAD_LIMIT: usize = 65_536;

/// One matched message: headers plus the payload, truncated to
/// [`PAYLOAD_LIMIT`] bytes.
#[derive(Debug, Clone, Serialize)]
pub struct MessageRecord {
    pub offset: i64,
    /// Broker/producer timestamp in epoch milliseconds, when present.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timestamp_ms: Option<i64>,
    pub payload_bytes: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub distinct_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub event: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub uuid: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    /// The event's own `timestamp` header, distinct from the Kafka timestamp.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub event_timestamp: Option<String>,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub missing_headers: bool,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub historical_migration: bool,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub force_disable_person_processing: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub dlq_reason: Option<String>,
    /// Payload text (lossy UTF-8; ingestion topics carry plain JSON),
    /// truncated to [`PAYLOAD_LIMIT`] bytes.
    pub payload: String,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub payload_truncated: bool,
}

impl MessageRecord {
    fn new(
        offset: i64,
        timestamp_ms: Option<i64>,
        payload: &[u8],
        headers: Option<&CapturedEventHeaders>,
    ) -> Self {
        let payload_bytes = payload.len() as u64;
        let payload_truncated = payload.len() > PAYLOAD_LIMIT;
        // Lossy conversion on a byte cut can split a UTF-8 sequence; the
        // replacement character at the cut point is fine for display.
        let payload = String::from_utf8_lossy(&payload[..payload.len().min(PAYLOAD_LIMIT)]);
        let base = Self {
            offset,
            timestamp_ms,
            payload_bytes,
            token: None,
            distinct_id: None,
            event: None,
            uuid: None,
            session_id: None,
            event_timestamp: None,
            missing_headers: true,
            historical_migration: false,
            force_disable_person_processing: false,
            dlq_reason: None,
            payload: payload.into_owned(),
            payload_truncated,
        };
        let Some(headers) = headers else {
            return base;
        };
        Self {
            token: headers.token.clone(),
            distinct_id: headers.distinct_id.clone(),
            event: headers.event.clone(),
            uuid: headers.uuid.clone(),
            session_id: headers.session_id.clone(),
            event_timestamp: headers.timestamp.clone(),
            missing_headers: false,
            historical_migration: headers.historical_migration == Some(true),
            force_disable_person_processing: headers.force_disable_person_processing == Some(true),
            dlq_reason: headers.dlq_reason.clone(),
            ..base
        }
    }
}

pub struct BrowseParams {
    pub topic: String,
    pub partition: i32,
    pub start_offset: i64,
    /// Where to stop reading (the high watermark at request time).
    pub end_offset_exclusive: i64,
    /// Matching messages to collect before returning.
    pub limit: usize,
    /// Messages to scan before returning even without a full page, so a
    /// filter that matches nothing still returns promptly with a cursor.
    pub scan_limit: u64,
    pub deadline: Duration,
    pub max_bytes: u64,
    pub poll_timeout: Duration,
}

pub struct BrowseOutcome {
    pub records: Vec<MessageRecord>,
    /// Next unread offset; the cursor for the follow-up request.
    pub next_offset: i64,
    pub scanned: u64,
    pub stop: BrowseStop,
    pub duration_ms: u64,
}

/// Scan `[start_offset, end_offset_exclusive)` on one partition, collecting
/// records for messages matching `filter` until a stop condition hits.
/// Non-matching payloads are dropped immediately; matching ones are kept,
/// truncated to [`PAYLOAD_LIMIT`]. Synchronous, so run it on the blocking
/// pool.
pub fn run_browse(
    consumer: &BaseConsumer,
    params: &BrowseParams,
    filter: &MessageFilter,
) -> anyhow::Result<BrowseOutcome> {
    let mut tpl = TopicPartitionList::new();
    tpl.add_partition_offset(
        &params.topic,
        params.partition,
        Offset::Offset(params.start_offset),
    )
    .context("build assignment")?;
    consumer.assign(&tpl).context("assign partition")?;

    let started = Instant::now();
    let mut records: Vec<MessageRecord> = Vec::new();
    let mut next_offset = params.start_offset;
    let mut scanned: u64 = 0;
    let mut bytes_read: u64 = 0;

    let stop = loop {
        if next_offset >= params.end_offset_exclusive {
            break BrowseStop::EndOfPartition;
        }
        if records.len() >= params.limit {
            break BrowseStop::Limit;
        }
        if scanned >= params.scan_limit {
            break BrowseStop::ScanBudget;
        }
        if bytes_read >= params.max_bytes {
            break BrowseStop::ByteBudget;
        }
        if started.elapsed() >= params.deadline {
            break BrowseStop::Deadline;
        }

        let Some(result) = consumer.poll(params.poll_timeout) else {
            continue;
        };
        let message = result.context("poll partition")?;
        // librdkafka prefetches; drop anything past the requested range.
        if message.offset() >= params.end_offset_exclusive {
            break BrowseStop::EndOfPartition;
        }

        let payload_size = message.payload_len() as u64;
        let headers = message
            .headers()
            .map(|h| CapturedEventHeaders::from(h.detach()));
        if filter.matches(headers.as_ref()) {
            records.push(MessageRecord::new(
                message.offset(),
                message.timestamp().to_millis(),
                message.payload().unwrap_or_default(),
                headers.as_ref(),
            ));
        }

        next_offset = message.offset() + 1;
        scanned += 1;
        bytes_read += payload_size;
    };

    Ok(BrowseOutcome {
        records,
        next_offset,
        scanned,
        stop,
        duration_ms: started.elapsed().as_millis() as u64,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn headers(token: &str, distinct_id: &str, event: &str) -> CapturedEventHeaders {
        CapturedEventHeaders {
            token: Some(token.to_string()),
            distinct_id: Some(distinct_id.to_string()),
            session_id: None,
            timestamp: None,
            event: Some(event.to_string()),
            uuid: None,
            now: None,
            force_disable_person_processing: None,
            historical_migration: None,
            skip_heatmap_processing: None,
            dlq_reason: None,
            dlq_step: None,
            dlq_timestamp: None,
            content_encoding: None,
        }
    }

    fn filter(
        token: Option<&str>,
        event: Option<&str>,
        distinct_id: Option<&str>,
    ) -> MessageFilter {
        MessageFilter {
            token: token.map(String::from),
            event: event.map(String::from),
            distinct_id: distinct_id.map(String::from),
        }
    }

    #[test]
    fn filters_are_conjunctive_equality_matches() {
        let h = headers("token_a", "user_1", "$pageview");
        let cases = [
            (filter(None, None, None), true),
            (filter(Some("token_a"), None, None), true),
            (filter(Some("token_b"), None, None), false),
            (filter(Some("token_a"), Some("$pageview"), None), true),
            (filter(Some("token_a"), Some("$identify"), None), false),
            (filter(None, None, Some("user_1")), true),
            (
                filter(Some("token_a"), Some("$pageview"), Some("user_2")),
                false,
            ),
        ];
        for (f, expected) in cases {
            assert_eq!(f.matches(Some(&h)), expected, "{f:?}");
        }
    }

    #[test]
    fn headerless_messages_match_only_the_empty_filter() {
        assert!(filter(None, None, None).matches(None));
        assert!(!filter(Some("token_a"), None, None).matches(None));
    }

    #[test]
    fn filtered_header_field_must_be_present_to_match() {
        // A filter on a field the message lacks must not match: missing is
        // not a wildcard.
        let mut h = headers("token_a", "user_1", "$pageview");
        h.event = None;
        assert!(!filter(None, Some("$pageview"), None).matches(Some(&h)));
    }

    #[test]
    fn record_carries_flags_and_payload() {
        let mut h = headers("token_a", "user_1", "$pageview");
        h.historical_migration = Some(true);
        let record = MessageRecord::new(42, Some(1_700_000_000_000), b"{\"a\":1}", Some(&h));
        assert_eq!(record.offset, 42);
        assert_eq!(record.payload_bytes, 7);
        assert_eq!(record.payload, "{\"a\":1}");
        assert!(!record.payload_truncated);
        assert_eq!(record.token.as_deref(), Some("token_a"));
        assert!(record.historical_migration);
        assert!(!record.missing_headers);

        let headerless = MessageRecord::new(43, None, b"", None);
        assert!(headerless.missing_headers);
        assert!(headerless.token.is_none());
    }

    #[test]
    fn oversized_payloads_are_truncated_with_a_flag() {
        let h = headers("token_a", "user_1", "$pageview");
        let big = vec![b'x'; PAYLOAD_LIMIT + 1];
        let record = MessageRecord::new(0, None, &big, Some(&h));
        assert_eq!(record.payload_bytes, (PAYLOAD_LIMIT + 1) as u64);
        assert_eq!(record.payload.len(), PAYLOAD_LIMIT);
        assert!(record.payload_truncated);
    }
}
