//! The SSE wire format, in exactly one place (plan §2.6).
//!
//! One event type (`version`) carries the current version on all three
//! occasions — connect, change, and heartbeat — so the client rule is uniform
//! and reconnect correctness is free. Keeping the serialization here means the
//! wire contract has a single source of truth with golden tests; SDK
//! implementers read those tests, so the literals below are load-bearing.

use std::time::Duration;

use axum::response::sse::Event;
use serde::Serialize;

use crate::config::StaggerWindowSecs;
use crate::domain::{CacheKind, VersionState};

/// The SSE `event:` name for every version beacon.
pub const EVENT_NAME: &str = "version";

/// The `data:` payload shape. Field order is the wire order; `version` is
/// `null` while the gateway's view is `Unknown`/`Missing`.
#[derive(Debug, Serialize)]
struct VersionData {
    kind: &'static str,
    version: Option<String>,
    stagger_window_s: u64,
}

/// A version beacon ready to serialize to an SSE frame.
///
/// Built from `(CacheKind, VersionState, StaggerWindowSecs)` — taking the
/// clamped [`StaggerWindowSecs`] rather than a raw number means a sub-minimum
/// window is not representable on the wire. The `id:` line mirrors the etag so
/// `Last-Event-ID` arrives on reconnect for free; it is **omitted entirely**
/// when the version is `null` (never `id: null`, which would pollute
/// `Last-Event-ID` and the reconnect metrics).
pub struct StreamEvent {
    data: String,
    id: Option<String>,
}

impl StreamEvent {
    pub fn new(kind: CacheKind, state: VersionState, stagger: StaggerWindowSecs) -> Self {
        let version = state.etag().map(|etag| etag.to_string());
        let id = version.clone();
        let data = serde_json::to_string(&VersionData {
            kind: kind.wire_name(),
            version,
            stagger_window_s: stagger.get(),
        })
        .expect("VersionData serializes infallibly");
        Self { data, id }
    }

    /// The serialized `data:` JSON.
    pub fn data(&self) -> &str {
        &self.data
    }

    /// The `id:` value (the etag hex), or `None` when the version is `null`.
    pub fn id(&self) -> Option<&str> {
        self.id.as_deref()
    }

    /// Render to an axum SSE event, omitting `id:` when the version is `null`.
    pub fn to_sse(&self) -> Event {
        let mut event = Event::default().event(EVENT_NAME).data(&self.data);
        if let Some(id) = &self.id {
            event = event.id(id);
        }
        event
    }
}

/// The connect-time `retry:` field. The caller (M4) computes the jittered value;
/// this only turns the chosen milliseconds into the SSE field.
pub fn retry_event(retry_ms: u64) -> Event {
    Event::default().retry(Duration::from_millis(retry_ms))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::Etag;
    use std::str::FromStr;

    fn stagger() -> StaggerWindowSecs {
        StaggerWindowSecs::clamped(60, 5)
    }

    fn known() -> VersionState {
        VersionState::Known(Etag::from_str("0123456789abcdef").expect("valid etag"))
    }

    // Golden wire contract: these literals are what SDK implementers rely on.
    #[test]
    fn known_state_pins_data_and_id() {
        let event = StreamEvent::new(CacheKind::Definitions, known(), stagger());
        assert_eq!(
            event.data(),
            r#"{"kind":"definitions","version":"0123456789abcdef","stagger_window_s":60}"#
        );
        assert_eq!(event.id(), Some("0123456789abcdef"));
    }

    #[test]
    fn unknown_state_pins_null_version_and_omits_id() {
        let event = StreamEvent::new(CacheKind::Definitions, VersionState::Unknown, stagger());
        assert_eq!(
            event.data(),
            r#"{"kind":"definitions","version":null,"stagger_window_s":60}"#
        );
        assert_eq!(event.id(), None);
    }

    #[test]
    fn missing_state_pins_null_version_and_omits_id() {
        let event = StreamEvent::new(
            CacheKind::RemoteEval,
            VersionState::Missing,
            StaggerWindowSecs::clamped(30, 5),
        );
        assert_eq!(
            event.data(),
            r#"{"kind":"remote_eval","version":null,"stagger_window_s":30}"#
        );
        assert_eq!(event.id(), None);
    }

    #[test]
    fn remote_eval_kind_renders_wire_name() {
        let event = StreamEvent::new(
            CacheKind::RemoteEval,
            known(),
            StaggerWindowSecs::clamped(30, 5),
        );
        assert_eq!(
            event.data(),
            r#"{"kind":"remote_eval","version":"0123456789abcdef","stagger_window_s":30}"#
        );
    }

    #[test]
    fn to_sse_does_not_panic() {
        // The Event body is opaque; the data()/id() contract above is the wire
        // pin. This just guards the builder path (data + optional id).
        let _known = StreamEvent::new(CacheKind::Definitions, known(), stagger()).to_sse();
        let _null =
            StreamEvent::new(CacheKind::Definitions, VersionState::Missing, stagger()).to_sse();
        let _retry = retry_event(3000);
    }
}
