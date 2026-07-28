pub use personhog_common::persons::Person;

/// The identity-plane view of a person: the sync-owned identity columns
/// only. Properties and version are deliberately absent — their single
/// author is the owning leader, and the Postgres copies are the writer's
/// lagging projections; exposing them here would hand callers stale data.
#[derive(Debug, Clone)]
pub struct PersonIdentity {
    pub person_id: i64,
    pub uuid: uuid::Uuid,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub is_identified: bool,
}

impl From<PersonIdentity> for personhog_proto::personhog::identity::v1::PersonIdentity {
    fn from(identity: PersonIdentity) -> Self {
        Self {
            person_id: identity.person_id,
            uuid: identity.uuid.to_string(),
            created_at: identity.created_at.timestamp_millis(),
            is_identified: identity.is_identified,
        }
    }
}

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
