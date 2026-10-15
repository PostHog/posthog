//! What the recorder does with one Kafka message, apart from Kafka itself.

use posthog_replay_anonymizer::snapshot::decompress_payload;
use replay_core_v4::gate::in_sample;
use replay_core_v4::scan::message::{read_message, Message};

/// Why the recorder leaves a message out. The label is the metric value.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Skip {
    NotSampled,
    NoKey,
    Undecompressable,
    Unreadable,
}

impl Skip {
    pub fn as_str(self) -> &'static str {
        match self {
            Skip::NotSampled => "not_sampled",
            Skip::NoKey => "no_key",
            Skip::Undecompressable => "undecompressable",
            Skip::Unreadable => "unreadable",
        }
    }
}

/// Capture keys every replay message with its session ID, so the gate runs before the payload is read.
pub fn sampled(key: Option<&[u8]>, percentage: f64) -> Result<(), Skip> {
    let key = key.filter(|k| !k.is_empty()).ok_or(Skip::NoKey)?;
    if in_sample(key, percentage) {
        Ok(())
    } else {
        Err(Skip::NotSampled)
    }
}

/// Decompresses and reads a sampled message.
pub fn read(payload: &[u8], content_encoding: Option<&str>) -> Result<Message, Skip> {
    let raw = decompress_payload(payload.to_vec(), content_encoding)
        .map_err(|_| Skip::Undecompressable)?;
    read_message(raw).map_err(|_| Skip::Unreadable)
}

#[cfg(test)]
mod tests {
    use posthog_replay_anonymizer::compression::gzip;
    use serde_json::json;

    use super::*;

    fn capture_message() -> Vec<u8> {
        let inner = json!({"event": "$snapshot_items", "properties": {
            "$session_id": "019a2f3e-8c00-7000-8000-000000000007",
            "$snapshot_items": [{"type": 3, "timestamp": 1, "data": {"source": 1}}]
        }});
        json!({"distinct_id": "d", "data": inner.to_string()})
            .to_string()
            .into_bytes()
    }

    #[test]
    fn gates_on_the_kafka_key_before_reading() {
        let session = b"019a2f3e-8c00-7000-8000-000000000007";
        assert_eq!(sampled(Some(session), 100.0), Ok(()));
        assert_eq!(sampled(Some(session), 0.0), Err(Skip::NotSampled));
        assert_eq!(sampled(None, 100.0), Err(Skip::NoKey));
        assert_eq!(sampled(Some(b""), 100.0), Err(Skip::NoKey));
    }

    #[test]
    fn reads_plain_and_gzipped_capture_messages() {
        let plain = capture_message();
        for payload in [plain.clone(), gzip(&plain).unwrap()] {
            let message = read(&payload, None).unwrap();
            assert_eq!(message.session_id, "019a2f3e-8c00-7000-8000-000000000007");
            assert_eq!(message.events.len(), 1);
        }
        assert_eq!(read(b"not json", None).unwrap_err(), Skip::Unreadable);
    }
}
