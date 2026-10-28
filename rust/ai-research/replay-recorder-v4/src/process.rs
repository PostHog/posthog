//! What the recorder does with one Kafka message, apart from Kafka itself.
//!
//! Admission reads only the Kafka key and headers, so a message the main lane or the v3 mirror would drop is never
//! decoded. The payload is read later, at the flush.

use std::borrow::Cow;

use replay_core_v4::gate::in_sample;
use replay_core_v4::payload::{decompress_payload, is_web_replay};
use replay_core_v4::scan::message::{read_message_within, Message, ReadError};
use replay_core_v4::session::{drop_reason, DropReason};

use crate::teams::Team;

/// Why the recorder leaves a message out. The label is the metric value.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Skip {
    NotSampled,
    NoKey,
    Restricted,
    RestrictedToDlq,
    Overflowed,
    MissingHeader,
    UnknownTeam,
    NotOptedIn,
    Session(DropReason),
    Blocked,
    Undecompressable,
    Unreadable,
    SessionMismatch,
    NotWeb,
    /// The flush has no room left for the message's events.
    OverBudget,
}

impl Skip {
    pub fn as_str(self) -> &'static str {
        match self {
            Skip::NotSampled => "not_sampled",
            Skip::NoKey => "no_key",
            Skip::Restricted => "blocked_token",
            Skip::RestrictedToDlq => "restricted_to_dlq",
            Skip::Overflowed => "redirected_to_overflow",
            Skip::MissingHeader => "missing_header",
            Skip::UnknownTeam => "unknown_team",
            Skip::NotOptedIn => "not_opted_in",
            Skip::Session(reason) => reason.as_str(),
            Skip::Blocked => "session_blocked",
            Skip::Undecompressable => "undecompressable",
            Skip::Unreadable => "unreadable",
            Skip::SessionMismatch => "session_mismatch",
            Skip::NotWeb => "not_web",
            Skip::OverBudget => "over_budget",
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

/// The headers capture sets on every replay message.
#[derive(Debug, Clone, Copy, Default)]
pub struct Headers<'a> {
    pub token: Option<&'a str>,
    pub session_id: Option<&'a str>,
    pub distinct_id: Option<&'a str>,
    pub event: Option<&'a str>,
    pub uuid: Option<&'a str>,
}

/// The event ingestion restrictions that apply to a message.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Restriction {
    pub drop: bool,
    pub dlq: bool,
    pub force_overflow: bool,
}

/// A message that may be recorded: its team, and its session ID as the replay lanes key it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Admitted {
    pub team_id: i64,
    pub session_id: String,
}

/// The replay lanes lower-case a session ID that is a UUID and keep any other as it is.
pub fn normalize_session_id(session_id: &str) -> Cow<'_, str> {
    let bytes = session_id.as_bytes();
    let uuid = bytes.len() == 36
        && bytes.iter().enumerate().all(|(i, b)| match i {
            8 | 13 | 18 | 23 => *b == b'-',
            _ => b.is_ascii_hexdigit(),
        });
    if uuid && bytes.iter().any(u8::is_ascii_uppercase) {
        Cow::Owned(session_id.to_ascii_lowercase())
    } else {
        Cow::Borrowed(session_id)
    }
}

/// The main lane's and the v3 mirror's rules before the payload, in their order: restrictions, the headers capture
/// guarantees, a team with recordings and a retention period, a recent UUIDv7 session, a consenting organization.
/// `redirect_overflow` is true on the main topic when the main lane moves force-overflow messages to the overflow
/// topic.
pub fn admit(
    headers: &Headers<'_>,
    restriction: Restriction,
    redirect_overflow: bool,
    team: Option<Team>,
    now_ms: i64,
) -> Result<Admitted, Skip> {
    if restriction.drop {
        return Err(Skip::Restricted);
    }
    if restriction.dlq {
        return Err(Skip::RestrictedToDlq);
    }
    if restriction.force_overflow && redirect_overflow {
        return Err(Skip::Overflowed);
    }
    let (Some(_), Some(session_id), Some(_)) = (
        headers.token.filter(|t| !t.is_empty()),
        headers.session_id.filter(|s| !s.is_empty()),
        headers.distinct_id.filter(|d| !d.is_empty()),
    ) else {
        return Err(Skip::MissingHeader);
    };
    let team = team.ok_or(Skip::UnknownTeam)?;
    let session_id = normalize_session_id(session_id);
    if let Some(reason) = drop_reason(&session_id, now_ms) {
        return Err(Skip::Session(reason));
    }
    if !team.ai_training_opted_in {
        return Err(Skip::NotOptedIn);
    }
    Ok(Admitted {
        team_id: team.id,
        session_id: session_id.into_owned(),
    })
}

/// Decompresses and reads an admitted message.
pub fn read(payload: Vec<u8>, content_encoding: Option<&str>) -> Result<Message, Skip> {
    read_within(payload, content_encoding, usize::MAX)
}

/// As [`read`], with at most `max_events` events, so that a message of many tiny events stops before its event list
/// outgrows the flush's budget.
pub fn read_within(
    payload: Vec<u8>,
    content_encoding: Option<&str>,
    max_events: usize,
) -> Result<Message, Skip> {
    let raw = decompress_payload(payload, content_encoding).map_err(|_| Skip::Undecompressable)?;
    read_message_within(raw, max_events).map_err(|error| match error {
        ReadError::TooManyEvents => Skip::OverBudget,
        _ => Skip::Unreadable,
    })
}

/// The rules that need the payload: the session the headers named, and a web replay.
pub fn check_read(message: &Message, session_id: &str) -> Result<(), Skip> {
    if normalize_session_id(&message.session_id) != session_id {
        return Err(Skip::SessionMismatch);
    }
    if !is_web_replay(message.snapshot_source.as_deref()) {
        return Err(Skip::NotWeb);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use replay_core_v4::compression::gzip;
    use serde_json::json;

    use super::*;

    const SESSION: &str = "019a2f3e-8c00-7000-8000-000000000007";

    fn capture_message(session: &str, source: Option<&str>) -> Vec<u8> {
        let mut properties = json!({
            "$session_id": session,
            "$snapshot_items": [{"type": 3, "timestamp": 1, "data": {"source": 1}}]
        });
        if let Some(source) = source {
            properties["$snapshot_source"] = json!(source);
        }
        let inner = json!({"event": "$snapshot_items", "properties": properties});
        json!({"distinct_id": "d", "data": inner.to_string()})
            .to_string()
            .into_bytes()
    }

    fn headers(session: &str) -> Headers<'_> {
        Headers {
            token: Some("token"),
            session_id: Some(session),
            distinct_id: Some("d"),
            ..Headers::default()
        }
    }

    #[test]
    fn gates_on_the_kafka_key_before_reading() {
        let session = SESSION.as_bytes();
        assert_eq!(sampled(Some(session), 100.0), Ok(()));
        assert_eq!(sampled(Some(session), 0.0), Err(Skip::NotSampled));
        assert_eq!(sampled(None, 100.0), Err(Skip::NoKey));
        assert_eq!(sampled(Some(b""), 100.0), Err(Skip::NoKey));
    }

    #[test]
    fn reads_plain_and_gzipped_capture_messages() {
        let plain = capture_message(SESSION, Some("web"));
        for payload in [plain.clone(), gzip(&plain).unwrap()] {
            let message = read(payload, None).unwrap();
            assert_eq!(message.session_id, SESSION);
            assert_eq!(message.events.len(), 1);
        }
        assert_eq!(
            read(b"not json".to_vec(), None).unwrap_err(),
            Skip::Unreadable
        );
        // The flush's event budget stops the reader before the event list grows past it.
        assert_eq!(
            read_within(plain.clone(), None, 0).unwrap_err(),
            Skip::OverBudget
        );
        assert!(read_within(plain, None, 1).is_ok());
    }

    #[test]
    fn checks_the_payload_against_the_headers() {
        let message = |session: &str, source: Option<&str>| {
            read(capture_message(session, source), None).unwrap()
        };
        let cases = [
            (message(SESSION, Some("web")), Ok(())),
            (message(&SESSION.to_ascii_uppercase(), Some("web")), Ok(())),
            (
                message("019a2f3e-8c00-7000-8000-000000000008", Some("web")),
                Err(Skip::SessionMismatch),
            ),
            (message(SESSION, Some("mobile")), Err(Skip::NotWeb)),
            (message(SESSION, None), Err(Skip::NotWeb)),
        ];
        for (message, expected) in cases {
            assert_eq!(check_read(&message, SESSION), expected, "{message:?}");
        }
    }

    #[test]
    fn admits_only_what_the_main_lane_and_the_v3_mirror_admit() {
        // 019a2f3e8c00 is the session start in milliseconds.
        let now = 0x019a_2f3e_8c00_i64 + 60_000;
        let upper = SESSION.to_ascii_uppercase();
        let opted_in = Some(Team {
            id: 7,
            ai_training_opted_in: true,
        });
        let open = Restriction::default();
        let overflow = Restriction {
            force_overflow: true,
            ..open
        };
        let admitted = Ok(Admitted {
            team_id: 7,
            session_id: SESSION.to_owned(),
        });
        let cases = [
            (
                headers(SESSION),
                open,
                false,
                opted_in,
                now,
                admitted.clone(),
            ),
            (
                headers(&upper),
                open,
                false,
                opted_in,
                now,
                admitted.clone(),
            ),
            (headers(SESSION), overflow, false, opted_in, now, admitted),
            (
                headers(SESSION),
                overflow,
                true,
                opted_in,
                now,
                Err(Skip::Overflowed),
            ),
            (
                headers(SESSION),
                Restriction { drop: true, ..open },
                false,
                opted_in,
                now,
                Err(Skip::Restricted),
            ),
            (
                headers(SESSION),
                Restriction { dlq: true, ..open },
                false,
                opted_in,
                now,
                Err(Skip::RestrictedToDlq),
            ),
            (
                Headers {
                    distinct_id: None,
                    ..headers(SESSION)
                },
                open,
                false,
                opted_in,
                now,
                Err(Skip::MissingHeader),
            ),
            (
                headers(SESSION),
                open,
                false,
                None,
                now,
                Err(Skip::UnknownTeam),
            ),
            (
                headers(SESSION),
                open,
                false,
                Some(Team {
                    id: 7,
                    ai_training_opted_in: false,
                }),
                now,
                Err(Skip::NotOptedIn),
            ),
            (
                headers(SESSION),
                open,
                false,
                opted_in,
                now + 15 * 86_400_000,
                Err(Skip::Session(DropReason::TooOld)),
            ),
        ];
        for (headers, restriction, redirect, team, now, expected) in cases {
            assert_eq!(
                admit(&headers, restriction, redirect, team, now),
                expected,
                "{headers:?} {restriction:?} {redirect} {team:?}"
            );
        }
    }
}
