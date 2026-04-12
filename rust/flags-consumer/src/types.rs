use uuid::Uuid;

/// Internal event after deserialization and classification.
///
/// Not `Clone` by design — events are moved through the pipeline (consumer →
/// channel → processor → storage) without copying. This prevents accidental
/// deep-cloning of `serde_json::Value` property trees.
///
/// String fields that are read-only after construction use `Box<str>` instead
/// of `String` to save 8 bytes per instance (no capacity field) and to signal
/// immutability.
#[derive(Debug)]
pub enum CdcEvent {
    PersonUpdate {
        team_id: i32,
        person_uuid: Uuid,
        properties: serde_json::Value,
        version: i64,
    },
    PersonDeletion {
        team_id: i32,
        person_uuid: Uuid,
        version: i64,
    },
    DistinctIdAssignment {
        team_id: i32,
        person_uuid: Uuid,
        distinct_id: Box<str>,
        version: i64,
    },
    DistinctIdDeletion {
        team_id: i32,
        person_uuid: Uuid,
        distinct_id: Box<str>,
        version: i64,
    },
}

impl CdcEvent {
    pub fn team_id(&self) -> i32 {
        match self {
            CdcEvent::PersonUpdate { team_id, .. }
            | CdcEvent::PersonDeletion { team_id, .. }
            | CdcEvent::DistinctIdAssignment { team_id, .. }
            | CdcEvent::DistinctIdDeletion { team_id, .. } => *team_id,
        }
    }

    pub fn operation_label(&self) -> &'static str {
        match self {
            CdcEvent::PersonUpdate { .. } => "person_upsert",
            CdcEvent::PersonDeletion { .. } => "person_delete",
            CdcEvent::DistinctIdAssignment { .. } => "did_assign",
            CdcEvent::DistinctIdDeletion { .. } => "did_delete",
        }
    }
}
