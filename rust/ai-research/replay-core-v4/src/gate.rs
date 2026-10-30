//! The v4 session gate.

/// Whether a session is in the v4 sample at `percentage` (0 to 100).
///
/// This is the session feature recorder's rollout gate (`session-feature-recorder.ts`), down to its floating-point
/// comparison, so at the same percentage the two lanes select the same sessions. Capture keys every replay message
/// with the session ID, so the recorder calls this on the Kafka key before it reads the payload.
pub fn in_sample(session_id: &[u8], percentage: f64) -> bool {
    if percentage >= 100.0 {
        return true;
    }
    if percentage <= 0.0 {
        return false;
    }
    // Capture keeps the session ID as the SDK sent it. The feature recorder hashes the ID after the replay lanes
    // lower-case a UUID, so every casing of one session gets the same verdict.
    let digest = if is_uuid(session_id) {
        md5::compute(session_id.to_ascii_lowercase())
    } else {
        md5::compute(session_id)
    };
    // The first 8 hex digits of the digest are its first 4 bytes, read big-endian.
    let value = u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]]);
    f64::from(value % 10_000) / 100.0 < percentage
}

/// The shape `normalizeSessionId` lower-cases: 8-4-4-4-12 hex digits in any case and of any version.
fn is_uuid(id: &[u8]) -> bool {
    id.len() == 36
        && id.iter().enumerate().all(|(i, b)| match i {
            8 | 13 | 18 | 23 => *b == b'-',
            _ => b.is_ascii_hexdigit(),
        })
}
