use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RaiseOutcome {
    Raised,
    AtOrAbove,
    NotLive,
    Missing,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RaiseResult {
    pub uuid: Uuid,
    pub outcome: RaiseOutcome,
    /// The version the row holds after the call; 0 when missing.
    pub version: i64,
}
