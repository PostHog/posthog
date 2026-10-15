//! What the recorder does with one Kafka message, apart from Kafka itself.

use posthog_replay_anonymizer::snapshot::{decompress_payload, is_web_replay};
use replay_core_v4::gate::in_sample;
use replay_core_v4::scan::message::{read_message, Message};
use replay_core_v4::session::{drop_reason, DropReason};

use crate::teams::Team;

/// Why the recorder leaves a message out. The label is the metric value.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Skip {
    NotSampled,
    NoKey,
    Undecompressable,
    Unreadable,
    UnknownTeam,
    NotOptedIn,
    Session(DropReason),
    NotWeb,
}

impl Skip {
    pub fn as_str(self) -> &'static str {
        match self {
            Skip::NotSampled => "not_sampled",
            Skip::NoKey => "no_key",
            Skip::Undecompressable => "undecompressable",
            Skip::Unreadable => "unreadable",
            Skip::UnknownTeam => "unknown_team",
            Skip::NotOptedIn => "not_opted_in",
            Skip::Session(reason) => reason.as_str(),
            Skip::NotWeb => "not_web",
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

/// The v3 mirror's admission rules: a consenting organization, a recent UUIDv7 session, a web replay. Returns the team.
pub fn admit(message: &Message, team: Option<Team>, now_ms: i64) -> Result<i64, Skip> {
    let team = team.ok_or(Skip::UnknownTeam)?;
    if !team.ai_training_opted_in {
        return Err(Skip::NotOptedIn);
    }
    if let Some(reason) = drop_reason(&message.session_id, now_ms) {
        return Err(Skip::Session(reason));
    }
    if !is_web_replay(message.snapshot_source.as_deref()) {
        return Err(Skip::NotWeb);
    }
    Ok(team.id)
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

    #[test]
    fn admits_only_what_the_v3_mirror_admits() {
        let session = "019a2f3e-8c00-7000-8000-000000000007";
        // 019a2f3e8c00 is the session start in milliseconds.
        let now = 0x019a_2f3e_8c00_i64 + 60_000;
        let message = |source: Option<&str>| {
            let mut properties = json!({"$session_id": session, "$snapshot_items": []});
            if let Some(source) = source {
                properties["$snapshot_source"] = json!(source);
            }
            let inner = json!({"event": "$snapshot_items", "properties": properties});
            read(
                json!({"distinct_id": "d", "data": inner.to_string()})
                    .to_string()
                    .as_bytes(),
                None,
            )
            .unwrap()
        };
        let opted_in = Some(Team {
            id: 7,
            ai_training_opted_in: true,
        });
        let cases = [
            (message(Some("web")), opted_in, now, Ok(7)),
            (message(Some("web")), None, now, Err(Skip::UnknownTeam)),
            (
                message(Some("web")),
                Some(Team {
                    id: 7,
                    ai_training_opted_in: false,
                }),
                now,
                Err(Skip::NotOptedIn),
            ),
            (
                message(Some("web")),
                opted_in,
                now + 15 * 86_400_000,
                Err(Skip::Session(DropReason::TooOld)),
            ),
            (message(Some("mobile")), opted_in, now, Err(Skip::NotWeb)),
            (message(None), opted_in, now, Err(Skip::NotWeb)),
        ];
        for (message, team, now, expected) in cases {
            assert_eq!(
                admit(&message, team, now),
                expected,
                "{team:?} {:?}",
                message.snapshot_source
            );
        }
    }
}
