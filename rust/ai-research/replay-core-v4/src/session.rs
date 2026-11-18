//! Which session IDs the recorder admits. The rules match the v3 mirror (`session-identifier-format.ts`).

/// The oldest session the recorder accepts, as v3 does.
pub const MAX_AGE_DAYS: i64 = 14;
/// How far in the future a session start may be, for clock skew.
pub const MAX_FUTURE_DAYS: i64 = 1;
const DAY_MS: i64 = 24 * 60 * 60 * 1000;
/// 10000-01-01T00:00:00Z: a later start cannot be written as a four-digit year.
const YEAR_10000_MS: i64 = 253_402_300_800_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DropReason {
    NotUuidV7,
    TooOld,
    InFuture,
}

impl DropReason {
    /// The metric label, the same as the v3 mirror's.
    pub fn as_str(self) -> &'static str {
        match self {
            DropReason::NotUuidV7 => "session_id_not_uuid_v7",
            DropReason::TooOld => "session_id_too_old",
            DropReason::InFuture => "session_id_in_future",
        }
    }
}

/// The start time in a UUIDv7 session ID, in epoch milliseconds, or `None` for any other shape.
pub fn start_ms(session_id: &str) -> Option<i64> {
    let bytes = session_id.as_bytes();
    if bytes.len() != 36 {
        return None;
    }
    for (index, &byte) in bytes.iter().enumerate() {
        let valid = match index {
            8 | 13 | 18 | 23 => byte == b'-',
            14 => byte == b'7',
            19 => matches!(byte.to_ascii_lowercase(), b'8' | b'9' | b'a' | b'b'),
            _ => byte.is_ascii_hexdigit(),
        };
        if !valid {
            return None;
        }
    }
    let hex = [&session_id[..8], &session_id[9..13]].concat();
    let timestamp = i64::from_str_radix(&hex, 16).ok()?;
    (timestamp > 0).then_some(timestamp)
}

/// Why the recorder drops a session, or `None` to admit it.
pub fn drop_reason(session_id: &str, now_ms: i64) -> Option<DropReason> {
    let Some(started_at) = start_ms(session_id).filter(|&t| t < YEAR_10000_MS) else {
        return Some(DropReason::NotUuidV7);
    };
    if started_at < now_ms - MAX_AGE_DAYS * DAY_MS {
        return Some(DropReason::TooOld);
    }
    if started_at > now_ms + MAX_FUTURE_DAYS * DAY_MS {
        return Some(DropReason::InFuture);
    }
    None
}
