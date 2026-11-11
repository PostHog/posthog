//! In-product ingestion warnings for the merge verdicts this service
//! settles: a verdict warns here when it is final under retry and decided
//! by this service alone. Unsettled conflicts, the move-limit skip, and
//! call failures stay with the caller, which alone knows its retry budget
//! and merge-mode policy.

use std::sync::Arc;
use std::time::Duration;

use common_ingestion_warnings::serializer::Warning;
use common_ingestion_warnings::{
    install_row_emitter, RowWarningEmitter, RowWarningsSettings, WarningSource, WarningType,
};
use uuid::Uuid;

use crate::lifecycle::merge::{
    OUTCOME_ERROR, OUTCOME_SKIPPED_ALREADY_IDENTIFIED, OUTCOME_SKIPPED_CONFLICT,
    OUTCOME_SKIPPED_ILLEGAL, OUTCOME_SKIPPED_REFUSED,
};

pub const SERVICE: &str = "personhog-identity";
const PIPELINE_STEP: &str = "personhog_merge";

pub const MERGE_ENTRANCE: WarningSource = WarningSource {
    service: SERVICE,
    path: "merge_entrance",
    pipeline_step: PIPELINE_STEP,
};

pub const MERGE_SAGA: WarningSource = WarningSource {
    service: SERVICE,
    path: "merge_saga",
    pipeline_step: PIPELINE_STEP,
};

const KAFKA_CLIENT_ID: &str = "personhog-identity-ingestion-warnings";
/// The distinct id column's own limit: a legal id is never cut, and an
/// oversized one is cut before it is copied into details.
const MAX_DETAIL_ID_CHARS: usize = 400;
const SHUTDOWN_FLUSH: Duration = Duration::from_secs(2);

fn bounded(id: &str) -> &str {
    match id.char_indices().nth(MAX_DETAIL_ID_CHARS) {
        Some((end, _)) => &id[..end],
        None => id,
    }
}

pub fn effective_event_uuid<'a>(event_uuid: &'a str, creator_event_uuid: &'a str) -> &'a str {
    if event_uuid.is_empty() {
        creator_event_uuid
    } else {
        event_uuid
    }
}

pub struct MergePair<'a> {
    pub source_distinct_id: &'a str,
    pub target_distinct_id: &'a str,
    pub event_uuid: &'a str,
    pub source_person_id: Option<i64>,
    pub source_person_uuid: Option<Uuid>,
    pub survivor_uuid: Option<Uuid>,
}

impl MergePair<'_> {
    fn base(&self, warning: WarningType) -> Warning {
        Warning::new(warning)
            .with_detail("sourcePersonDistinctId", bounded(self.source_distinct_id))
            .with_detail("targetPersonDistinctId", bounded(self.target_distinct_id))
            .with_detail("distinctId", bounded(self.target_distinct_id))
            .with_detail("eventUuid", bounded(self.event_uuid))
    }

    fn with_person_ids(&self, mut warning: Warning) -> Warning {
        if let Some(uuid) = self.source_person_uuid {
            warning = warning.with_detail("otherPersonId", uuid.to_string());
        }
        if let Some(uuid) = self.survivor_uuid {
            warning = warning.with_detail("personId", uuid.to_string());
        }
        warning
    }

    fn illegal(&self, illegal_distinct_id: &str, other_distinct_id: &str) -> Warning {
        Warning::new(WarningType::CannotMergeWithIllegalDistinctId)
            .with_detail("illegalDistinctId", bounded(illegal_distinct_id))
            .with_detail("otherDistinctId", bounded(other_distinct_id))
            .with_detail("distinctId", bounded(self.target_distinct_id))
            .with_detail("eventUuid", bounded(self.event_uuid))
    }
}

pub fn verdict_warning(outcome: &str, settled: bool, pair: &MergePair<'_>) -> Option<Warning> {
    if !settled {
        return None;
    }
    match outcome {
        OUTCOME_SKIPPED_ILLEGAL => {
            Some(pair.illegal(pair.source_distinct_id, pair.target_distinct_id))
        }
        OUTCOME_SKIPPED_ALREADY_IDENTIFIED => {
            Some(pair.with_person_ids(pair.base(WarningType::CannotMergeAlreadyIdentified)))
        }
        OUTCOME_SKIPPED_CONFLICT => {
            Some(pair.with_person_ids(pair.base(WarningType::MergeRaceCondition)))
        }
        OUTCOME_SKIPPED_REFUSED | OUTCOME_ERROR => {
            let mut warning = pair
                .with_person_ids(pair.base(WarningType::MergeSettledFailure))
                .with_detail("outcome", outcome);
            if let Some(id) = pair.source_person_id {
                warning = warning.with_detail("sourcePersonId", id.to_string());
            }
            Some(warning)
        }
        _ => None,
    }
}

pub fn illegal_target_warning(pair: &MergePair<'_>) -> Warning {
    pair.illegal(pair.target_distinct_id, pair.source_distinct_id)
}

#[derive(Clone)]
pub struct MergeWarnings {
    emitter: Option<Arc<dyn RowWarningEmitter>>,
}

impl MergeWarnings {
    pub fn new(emitter: Arc<dyn RowWarningEmitter>) -> Self {
        Self {
            emitter: Some(emitter),
        }
    }

    pub fn disabled() -> Self {
        Self { emitter: None }
    }

    /// Lets a caller skip building warnings at all when nothing would send them.
    pub fn is_enabled(&self) -> bool {
        self.emitter.is_some()
    }

    pub fn emit_verdict(
        &self,
        team_id: i64,
        source: WarningSource,
        outcome: &str,
        settled: bool,
        pair: &MergePair<'_>,
    ) {
        let Some(emitter) = &self.emitter else {
            return;
        };
        if let Some(warning) = verdict_warning(outcome, settled, pair) {
            emitter.emit(team_id, pair.source_distinct_id, source, warning);
        }
    }

    /// Scoped by the target, the id the warning is about; scoped by the
    /// source, one bad target would hold a key per visitor and eat the budget.
    pub fn emit_illegal_target(&self, team_id: i64, source: WarningSource, pair: &MergePair<'_>) {
        if let Some(emitter) = &self.emitter {
            emitter.emit(
                team_id,
                pair.target_distinct_id,
                source,
                illegal_target_warning(pair),
            );
        }
    }

    /// Blocking; call from a blocking task once every tracked component that
    /// enqueues warnings has drained. The emitter's own task is advisory and
    /// receives shutdown alongside the gRPC server, so it cannot flush last.
    pub fn flush(&self) {
        if let Some(emitter) = &self.emitter {
            emitter.flush(SHUTDOWN_FLUSH);
        }
    }
}

pub fn install(settings: &RowWarningsSettings, handle: Option<lifecycle::Handle>) -> MergeWarnings {
    match install_row_emitter(settings, KAFKA_CLIENT_ID, handle) {
        Some(emitter) => MergeWarnings::new(emitter),
        None => MergeWarnings::disabled(),
    }
}

#[cfg(test)]
mod tests {
    use common_ingestion_warnings::test_support::CollectingRowEmitter;
    use rstest::rstest;
    use serde_json::Value;

    use super::*;
    use crate::lifecycle::merge::{
        OUTCOME_ATTACHED, OUTCOME_MERGED, OUTCOME_NOOP_SAME_PERSON, OUTCOME_SKIPPED_MOVE_LIMIT,
    };

    const SOURCE_UUID: Uuid = Uuid::from_u128(0x1111_2222_3333_4444_5555_6666_7777_8888);
    const SURVIVOR_UUID: Uuid = Uuid::from_u128(0x9999_aaaa_bbbb_cccc_dddd_eeee_ffff_0000);

    fn pair<'a>() -> MergePair<'a> {
        MergePair {
            source_distinct_id: "anon-1",
            target_distinct_id: "user-1",
            event_uuid: "evt-1",
            source_person_id: Some(42),
            source_person_uuid: Some(SOURCE_UUID),
            survivor_uuid: Some(SURVIVOR_UUID),
        }
    }

    fn details(warning: Warning) -> (WarningType, Value) {
        let warning_type = warning.warning_type();
        let row = warning.into_row(7, MERGE_SAGA);
        (
            warning_type,
            serde_json::from_str(row["details"].as_str().unwrap()).unwrap(),
        )
    }

    #[rstest]
    #[case::illegal(
        OUTCOME_SKIPPED_ILLEGAL,
        Some(WarningType::CannotMergeWithIllegalDistinctId)
    )]
    #[case::already_identified(
        OUTCOME_SKIPPED_ALREADY_IDENTIFIED,
        Some(WarningType::CannotMergeAlreadyIdentified)
    )]
    #[case::settled_conflict(OUTCOME_SKIPPED_CONFLICT, Some(WarningType::MergeRaceCondition))]
    #[case::refused(OUTCOME_SKIPPED_REFUSED, Some(WarningType::MergeSettledFailure))]
    #[case::error(OUTCOME_ERROR, Some(WarningType::MergeSettledFailure))]
    #[case::move_limit(OUTCOME_SKIPPED_MOVE_LIMIT, None)]
    #[case::merged(OUTCOME_MERGED, None)]
    #[case::attached(OUTCOME_ATTACHED, None)]
    #[case::noop(OUTCOME_NOOP_SAME_PERSON, None)]
    #[case::unknown("verdict_from_the_future", None)]
    fn each_settled_verdict_maps_to_its_warning_or_nothing(
        #[case] outcome: &str,
        #[case] expected: Option<WarningType>,
    ) {
        let warning = verdict_warning(outcome, true, &pair());
        assert_eq!(warning.as_ref().map(Warning::warning_type), expected);
    }

    #[rstest]
    #[case(OUTCOME_SKIPPED_CONFLICT)]
    #[case(OUTCOME_SKIPPED_ALREADY_IDENTIFIED)]
    #[case(OUTCOME_SKIPPED_REFUSED)]
    fn an_unsettled_verdict_never_warns(#[case] outcome: &str) {
        assert!(verdict_warning(outcome, false, &pair()).is_none());
    }

    #[test]
    fn already_identified_names_both_persons_and_the_pair() {
        let (warning_type, details) =
            details(verdict_warning(OUTCOME_SKIPPED_ALREADY_IDENTIFIED, true, &pair()).unwrap());
        assert_eq!(warning_type, WarningType::CannotMergeAlreadyIdentified);
        assert_eq!(details["sourcePersonDistinctId"], "anon-1");
        assert_eq!(details["targetPersonDistinctId"], "user-1");
        assert_eq!(details["distinctId"], "user-1");
        assert_eq!(details["eventUuid"], "evt-1");
        assert_eq!(details["otherPersonId"], SOURCE_UUID.to_string());
        assert_eq!(details["personId"], SURVIVOR_UUID.to_string());
        assert_eq!(details["category"], "merge");
        assert_eq!(details["severity"], "warning");
        assert_eq!(details["pipelineStep"], PIPELINE_STEP);
        assert_eq!(details["teamId"], 7);
    }

    #[test]
    fn unresolved_persons_leave_their_keys_out() {
        let unresolved = MergePair {
            source_person_id: None,
            source_person_uuid: None,
            survivor_uuid: None,
            ..pair()
        };
        let (_, details) =
            details(verdict_warning(OUTCOME_SKIPPED_REFUSED, true, &unresolved).unwrap());
        assert!(details.get("otherPersonId").is_none());
        assert!(details.get("personId").is_none());
        assert!(details.get("sourcePersonId").is_none());
        assert_eq!(details["outcome"], OUTCOME_SKIPPED_REFUSED);
    }

    #[test]
    fn a_settled_failure_carries_the_verdict_and_the_source_row_id() {
        let (_, details) = details(verdict_warning(OUTCOME_ERROR, true, &pair()).unwrap());
        assert_eq!(details["outcome"], OUTCOME_ERROR);
        assert_eq!(details["sourcePersonId"], "42");
        assert_eq!(details["otherPersonId"], SOURCE_UUID.to_string());
        assert_eq!(details["severity"], "error");
    }

    #[test]
    fn an_illegal_source_names_itself_and_the_target_as_the_other_side() {
        let (_, details) =
            details(verdict_warning(OUTCOME_SKIPPED_ILLEGAL, true, &pair()).unwrap());
        assert_eq!(details["illegalDistinctId"], "anon-1");
        assert_eq!(details["otherDistinctId"], "user-1");
        assert_eq!(details["distinctId"], "user-1");
        assert_eq!(details["eventUuid"], "evt-1");
        assert!(details.get("sourcePersonDistinctId").is_none());
    }

    #[test]
    fn oversized_ids_are_cut_to_the_column_limit_in_details() {
        let huge = "\u{4e16}".repeat(10_000);
        let oversized = MergePair {
            source_distinct_id: &huge,
            target_distinct_id: &huge,
            event_uuid: &huge,
            ..pair()
        };
        let (_, illegal) =
            details(verdict_warning(OUTCOME_SKIPPED_ILLEGAL, true, &oversized).unwrap());
        for key in [
            "illegalDistinctId",
            "otherDistinctId",
            "distinctId",
            "eventUuid",
        ] {
            assert_eq!(
                illegal[key].as_str().unwrap().chars().count(),
                MAX_DETAIL_ID_CHARS,
                "{key}"
            );
        }
        let (_, failure) = details(verdict_warning(OUTCOME_ERROR, true, &oversized).unwrap());
        assert_eq!(
            failure["sourcePersonDistinctId"]
                .as_str()
                .unwrap()
                .chars()
                .count(),
            MAX_DETAIL_ID_CHARS
        );
        let (_, legal) = details(verdict_warning(OUTCOME_ERROR, true, &pair()).unwrap());
        assert_eq!(legal["sourcePersonDistinctId"], "anon-1");
    }

    #[test]
    fn the_disabled_surface_reports_itself_so_callers_can_skip_the_work() {
        assert!(!MergeWarnings::disabled().is_enabled());
        assert!(MergeWarnings::new(Arc::new(CollectingRowEmitter::new())).is_enabled());
    }

    #[test]
    fn an_illegal_target_swaps_the_sides() {
        let (warning_type, details) = details(illegal_target_warning(&pair()));
        assert_eq!(warning_type, WarningType::CannotMergeWithIllegalDistinctId);
        assert_eq!(details["illegalDistinctId"], "user-1");
        assert_eq!(details["otherDistinctId"], "anon-1");
        assert_eq!(details["distinctId"], "user-1");
    }

    #[test]
    fn the_surface_scopes_each_row_by_the_distinct_id_it_is_about() {
        let emitter = Arc::new(CollectingRowEmitter::new());
        let warnings = MergeWarnings::new(emitter.clone());
        warnings.emit_verdict(7, MERGE_ENTRANCE, OUTCOME_SKIPPED_ILLEGAL, true, &pair());
        warnings.emit_verdict(7, MERGE_SAGA, OUTCOME_MERGED, true, &pair());
        warnings.emit_verdict(7, MERGE_SAGA, OUTCOME_SKIPPED_CONFLICT, false, &pair());
        warnings.emit_illegal_target(7, MERGE_ENTRANCE, &pair());

        let rows = emitter.rows();
        assert_eq!(rows.len(), 2);
        assert!(rows.iter().all(|r| r.team_id == 7));
        assert_eq!(rows[0].source, MERGE_ENTRANCE);
        assert_eq!(rows[0].row["source"], SERVICE);
        assert_eq!(rows[0].scope, "anon-1", "a verdict is about its source");
        assert_eq!(rows[1].details()["illegalDistinctId"], "user-1");
        assert_eq!(
            rows[1].scope, "user-1",
            "an illegal target is about the target"
        );
    }
}
