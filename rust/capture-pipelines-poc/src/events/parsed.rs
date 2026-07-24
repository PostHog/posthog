//! The boundary event type: [`ParsedEvent`].
//!
//! This is one of the few places a concrete event type is legitimate — it is the
//! type the intake stage *creates* from a raw request. Everything downstream is
//! generic over capabilities, not over `ParsedEvent`.

use super::capabilities::{HasDistinctId, HasEventName, HasLane, HasTeamId, HasToken, Main};

/// A minimally-parsed analytics event — only the fields the demo steps read.
#[derive(Clone, Debug)]
pub struct ParsedEvent {
    /// Ingest token.
    pub token: String,
    /// Event name.
    pub event: String,
    /// Distinct id, if provided.
    pub distinct_id: Option<String>,
    /// Owning team (attribution for warnings).
    pub team_id: u64,
    /// Event timestamp (unix millis).
    pub timestamp: i64,
}

impl HasToken for ParsedEvent {
    fn token(&self) -> &str {
        &self.token
    }
}
impl HasEventName for ParsedEvent {
    fn event_name(&self) -> &str {
        &self.event
    }
}
impl HasDistinctId for ParsedEvent {
    fn distinct_id(&self) -> Option<&str> {
        self.distinct_id.as_deref()
    }
}
impl HasTeamId for ParsedEvent {
    fn team_id(&self) -> u64 {
        self.team_id
    }
}
impl HasLane for ParsedEvent {
    // Freshly-parsed events start on the main lane.
    type Lane = Main;
}
