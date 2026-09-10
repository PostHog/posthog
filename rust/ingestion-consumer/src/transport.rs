//! Types shared by the worker transport: the send failure contract, the fence
//! guard, and the size-bounded chunking that keeps one frame under the
//! worker's message limit.

use crate::types::SerializedKafkaMessage;

/// Default cap on the estimated serialized size of one frame sent to a
/// worker. The worker's message limit is well above this; the headroom absorbs
/// the per-message size estimate (which ignores JSON string escaping).
pub const DEFAULT_MAX_BODY_BYTES: usize = 10 * 1024 * 1024;

/// Approximate serialized size of one message within a frame. Field names and
/// punctuation are a small constant; escaping of the embedded JSON text is
/// absorbed by the headroom between the split cap and the worker's hard limit.
fn approx_message_size(msg: &SerializedKafkaMessage) -> usize {
    const PER_MESSAGE_OVERHEAD: usize = 96;
    msg.topic.len()
        + msg.key.as_deref().map_or(0, str::len)
        + msg.value.as_deref().map_or(0, str::len)
        + msg
            .headers
            .iter()
            .map(|(k, v)| k.len() + v.len() + 8)
            .sum::<usize>()
        + PER_MESSAGE_OVERHEAD
}

/// Split a sub-batch into chunks whose estimated serialized size stays under
/// `max_body_bytes`, preserving message order. A single message estimated
/// above the cap gets its own chunk — it can't be split further.
pub(crate) fn split_by_size(
    messages: Vec<SerializedKafkaMessage>,
    max_body_bytes: usize,
) -> Vec<Vec<SerializedKafkaMessage>> {
    let mut chunks = Vec::new();
    let mut current = Vec::new();
    let mut current_size = 0usize;
    for msg in messages {
        let size = approx_message_size(&msg);
        if !current.is_empty() && current_size + size > max_body_bytes {
            chunks.push(std::mem::take(&mut current));
            current_size = 0;
        }
        current_size += size;
        current.push(msg);
    }
    if !current.is_empty() {
        chunks.push(current);
    }
    chunks
}

/// Failure from a worker stream send, carrying back the sub-batch's messages
/// so the caller can defer/replay them (the worker may have died mid-send and
/// the messages were never accepted).
#[derive(Debug)]
pub struct SendError {
    pub error: TransportError,
    pub messages: Vec<SerializedKafkaMessage>,
    /// Set on a fenced worker stream send. Hold it until `messages` are stashed: the
    /// worker stream keeps fencing new arrivals until every guard from that fence is
    /// dropped, so nothing enqueued before the stash lands can reach the
    /// worker ahead of the fenced groups on the next stream.
    pub fence_guard: Option<FenceGuard>,
}

/// Tells a fencing worker stream that one fenced send's messages are stashed.
pub struct FenceGuard {
    /// One release per fenced send this guard stands for: a split sub-batch
    /// fenced across several chunks merges their guards into one.
    released: Vec<tokio::sync::mpsc::UnboundedSender<()>>,
}

impl FenceGuard {
    pub(crate) fn new(released: tokio::sync::mpsc::UnboundedSender<()>) -> Self {
        Self {
            released: vec![released],
        }
    }

    /// Fold `other` into this guard, so both release only when this one drops.
    pub(crate) fn merge(&mut self, mut other: FenceGuard) {
        self.released.append(&mut other.released);
    }
}

impl Drop for FenceGuard {
    fn drop(&mut self) {
        for released in &self.released {
            let _ = released.send(());
        }
    }
}

impl std::fmt::Debug for FenceGuard {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("FenceGuard")
    }
}

#[derive(Debug, thiserror::Error)]
pub enum TransportError {
    #[error("Worker stream failed: {0}")]
    WorkerStreamFailed(&'static str),

    #[error("Worker stream busy: {0}")]
    WorkerStreamBusy(&'static str),

    #[error("Worker stream closed without resolving the send")]
    WorkerStreamClosed,
}

impl TransportError {
    /// Worker stream failures resolve through the deferral path and are never
    /// retried in place. A busy worker stream is transient backpressure, so the
    /// fenced work re-routes as retriable rather than as a worker fault.
    pub fn is_retriable(&self) -> bool {
        matches!(self, TransportError::WorkerStreamBusy(_))
    }

    /// Backpressure the worker signalled deliberately. Distinct from a worker
    /// fault, which must count against passive health.
    pub fn is_backpressure(&self) -> bool {
        matches!(self, TransportError::WorkerStreamBusy(_))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_only_busy_errors_are_backpressure_and_retriable() {
        assert!(TransportError::WorkerStreamBusy("busy").is_backpressure());
        assert!(TransportError::WorkerStreamBusy("busy").is_retriable());
        assert!(!TransportError::WorkerStreamFailed("nack").is_backpressure());
        assert!(!TransportError::WorkerStreamFailed("nack").is_retriable());
        assert!(!TransportError::WorkerStreamClosed.is_backpressure());
        assert!(!TransportError::WorkerStreamClosed.is_retriable());
    }

    fn message_with_value(offset: i64, value_len: usize) -> SerializedKafkaMessage {
        SerializedKafkaMessage {
            topic: "t".to_string(),
            partition: 0,
            offset,
            timestamp: 0,
            key: None,
            value: Some("x".repeat(value_len)),
            headers: std::collections::HashMap::new(),
        }
    }

    #[test]
    fn test_split_by_size_respects_cap_and_preserves_order() {
        let messages: Vec<_> = (0..10).map(|i| message_with_value(i, 1000)).collect();
        // Each message estimates to ~1100 bytes, so a 2500-byte cap fits two.
        let chunks = split_by_size(messages, 2500);

        assert!(
            chunks.len() >= 5,
            "expected >= 5 chunks, got {}",
            chunks.len()
        );
        for chunk in &chunks {
            let size: usize = chunk.iter().map(approx_message_size).sum();
            assert!(size <= 2500, "chunk exceeds cap: {size}");
        }
        let offsets: Vec<i64> = chunks.iter().flatten().map(|m| m.offset).collect();
        assert_eq!(offsets, (0..10).collect::<Vec<_>>());
    }

    #[test]
    fn test_split_by_size_isolates_oversize_message() {
        let messages = vec![
            message_with_value(0, 10),
            message_with_value(1, 5000),
            message_with_value(2, 10),
        ];
        let chunks = split_by_size(messages, 1000);

        assert_eq!(chunks.len(), 3);
        assert_eq!(chunks[1].len(), 1);
        assert_eq!(chunks[1][0].offset, 1);
    }

    #[test]
    fn test_split_by_size_single_chunk_when_under_cap() {
        let messages: Vec<_> = (0..3).map(|i| message_with_value(i, 10)).collect();
        let chunks = split_by_size(messages, DEFAULT_MAX_BODY_BYTES);
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].len(), 3);
    }
}
