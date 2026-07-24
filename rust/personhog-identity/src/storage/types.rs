pub use personhog_common::persons::Person;

/// A single stub-creation request: the primary distinct id derives the
/// deterministic person UUID; extra distinct ids are mapped in the same
/// transaction.
#[derive(Debug, Clone)]
pub struct PersonStub {
    pub team_id: i64,
    pub distinct_id: String,
    pub extra_distinct_ids: Vec<String>,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub is_identified: bool,
}

/// Per-stub outcome of a stub-creation transaction.
#[derive(Debug, Clone)]
pub enum StubOutcome {
    /// The transaction committed. `created` is false when the person row
    /// already existed (a concurrent creator won the uuid insert) and only
    /// distinct id rows were attached.
    Committed { person: Person, created: bool },
    /// The primary distinct id was concurrently mapped to a different person;
    /// the transaction rolled back. The caller re-resolves to find the winner.
    LostRace,
}
