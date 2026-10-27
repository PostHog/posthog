use std::sync::Arc;
use std::time::Duration;

use common_ingestion_warnings::registry::WarningType;
use common_ingestion_warnings::serializer::Warning;
use common_ingestion_warnings::{
    install_row_emitter, RowWarningEmitter, RowWarningsSettings, WarningSource,
};

/// Warnings emitted from the leader's admission check, ahead of the write
/// path proper. `pipeline_step` lands in the v2 table's `pipeline_step`
/// column via the row's details.
const LEADER_ADMISSION: WarningSource = WarningSource {
    service: "personhog-leader",
    path: "admission",
    pipeline_step: "personhog_admission",
};

const KAFKA_CLIENT_ID: &str = "personhog-leader-ingestion-warnings";
const SHUTDOWN_FLUSH: Duration = Duration::from_secs(2);

/// The throttle scope within a team. Admission warnings are budgeted per
/// team and type, so one person hammered with oversized updates and many
/// such persons on one team both yield one warning an hour.
const TEAM_SCOPE: &str = "";

/// An in-product ingestion warning about a person's property size —
/// emitted when admission trims an update to fit the Postgres constraint
/// or rejects one that cannot fit. Carries no property values, only
/// identifiers and sizes.
pub struct SizeViolationWarning {
    pub team_id: i64,
    /// The person's UUID — the pipeline convention for `personId` in
    /// warning details (row ids stay internal).
    pub person_uuid: String,
    pub message: String,
}

/// Sends size violation warnings so users see them in-product, with the
/// payload built by the shared ingestion-warnings crate so type and
/// classification come from the pipeline registry. Emission is
/// fire-and-forget and never blocks or fails the update that triggered it.
#[derive(Clone)]
pub struct WarningsProducer {
    emitter: Option<Arc<dyn RowWarningEmitter>>,
}

impl WarningsProducer {
    pub fn new(emitter: Arc<dyn RowWarningEmitter>) -> Self {
        Self {
            emitter: Some(emitter),
        }
    }

    pub fn disabled() -> Self {
        Self { emitter: None }
    }

    pub fn emit(&self, warning: &SizeViolationWarning) {
        let Some(emitter) = &self.emitter else {
            return;
        };
        // teamId, category, severity, and pipelineStep are injected by the
        // terminal.
        let payload = Warning::new(WarningType::PersonPropertiesSizeViolation)
            .with_detail("personId", warning.person_uuid.clone())
            .with_detail("message", warning.message.clone());
        emitter.emit(warning.team_id, TEAM_SCOPE, LEADER_ADMISSION, payload);
    }

    /// Blocking; call once the gRPC server, the only caller of `emit`, has
    /// stopped. The emitter's own component is advisory, so it cannot flush last.
    pub fn flush(&self) {
        if let Some(emitter) = &self.emitter {
            emitter.flush(SHUTDOWN_FLUSH);
        }
    }
}

pub fn install(
    settings: &RowWarningsSettings,
    handle: Option<lifecycle::Handle>,
) -> WarningsProducer {
    match install_row_emitter(settings, KAFKA_CLIENT_ID, handle) {
        Some(emitter) => WarningsProducer::new(emitter),
        None => WarningsProducer::disabled(),
    }
}
