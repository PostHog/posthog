//! In-product ingestion warnings for the merge verdicts this service
//! settles: a verdict warns here when it is final under retry and decided
//! by this service alone. Unsettled conflicts, the move-limit skip, and
//! call failures stay with the caller, which alone knows its retry budget
//! and merge-mode policy.

use std::num::NonZeroU32;
use std::sync::Arc;
use std::time::Duration;

use common_ingestion_warnings::serializer::Warning;
use common_ingestion_warnings::throttle::{WarningThrottle, DEFAULT_MAX_TRACKED_KEYS};
use common_ingestion_warnings::{
    observe_delivery, KafkaRowWarningEmitter, RowWarningEmitter, WarningSource, WarningType,
    INGESTION_WARNINGS_EMITTER_ENABLED,
};
use common_kafka::config::KafkaConfig;
use common_kafka::kafka_producer::create_threaded_kafka_producer_no_ping;
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
const KAFKA_ACKS: &str = "1";
const KAFKA_RETRIES: u32 = 0;
const KAFKA_LINGER_MS: u32 = 100;
const KAFKA_QUEUE_MESSAGES: u32 = 10_000;
const KAFKA_MESSAGE_TIMEOUT_MS: u32 = 5_000;
const TYPE_BUDGET_PER_SECOND: NonZeroU32 = NonZeroU32::new(60).unwrap();
/// Keys are per distinct id, so the crate default (sized for capture's
/// per-token keys) would fill within the hour a key lives and silence every
/// team on the pod. The type budgets admit well under this many keys an hour.
const MAX_TRACKED_SCOPES: usize = 1_000_000;
const _: () = assert!(MAX_TRACKED_SCOPES > DEFAULT_MAX_TRACKED_KEYS);
const THROTTLE_SWEEP_INTERVAL: Duration = Duration::from_secs(60);
/// The distinct id column's own limit: a legal id is never cut, and an
/// oversized one is cut before it is copied into details.
const MAX_DETAIL_ID_CHARS: usize = 400;
const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(10);
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

    /// Scoped by the target: it is the id the warning is about, and an SDK
    /// that identifies every visitor as "undefined" would otherwise hold one
    /// key per visitor and spend the pod's whole budget for this type.
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WarningsSettings {
    pub enabled: bool,
    pub kafka_hosts: String,
    pub kafka_tls: bool,
    pub topic: String,
    pub kafka_queue_mib: u32,
    pub kafka_message_max_bytes: u32,
}

impl WarningsSettings {
    pub fn kafka_config(&self) -> KafkaConfig {
        KafkaConfig {
            kafka_hosts: self.kafka_hosts.clone(),
            kafka_tls: self.kafka_tls,
            kafka_client_id: KAFKA_CLIENT_ID.to_string(),
            kafka_producer_acks: Some(KAFKA_ACKS.to_string()),
            kafka_producer_retries: Some(KAFKA_RETRIES),
            kafka_producer_linger_ms: KAFKA_LINGER_MS,
            kafka_producer_queue_messages: KAFKA_QUEUE_MESSAGES,
            kafka_message_timeout_ms: KAFKA_MESSAGE_TIMEOUT_MS,
            kafka_producer_queue_mib: self.kafka_queue_mib,
            kafka_producer_message_max_bytes: Some(self.kafka_message_max_bytes),
            ..Default::default()
        }
    }

    pub fn disabled_reason(&self) -> Option<&'static str> {
        if !self.enabled {
            return Some("disabled");
        }
        if self.kafka_hosts.is_empty() {
            return Some("hosts_unset");
        }
        if self.topic.is_empty() {
            return Some("topic_unset");
        }
        None
    }
}

fn report_emitter_enabled(reason: &'static str, enabled: bool) {
    common_metrics::gauge(
        INGESTION_WARNINGS_EMITTER_ENABLED,
        &[("reason".to_string(), reason.to_string())],
        if enabled { 1.0 } else { 0.0 },
    );
}

fn throttle() -> WarningThrottle {
    WarningThrottle::default()
        .with_max_tracked_keys(MAX_TRACKED_SCOPES)
        .with_type_budget(
            Duration::from_secs(1) / TYPE_BUDGET_PER_SECOND.get(),
            TYPE_BUDGET_PER_SECOND,
        )
}

pub fn install(settings: &WarningsSettings, handle: Option<lifecycle::Handle>) -> MergeWarnings {
    if !settings.enabled {
        return MergeWarnings::disabled();
    }
    if let Some(reason) = settings.disabled_reason() {
        tracing::warn!(
            reason,
            "ingestion warnings enabled but unusable; emitter disabled"
        );
        report_emitter_enabled(reason, false);
        return MergeWarnings::disabled();
    }
    let Some(handle) = handle else {
        tracing::warn!(
            "ingestion warnings enabled but no lifecycle handle was registered; emitter disabled"
        );
        report_emitter_enabled("no_handle", false);
        return MergeWarnings::disabled();
    };
    let producer = match create_threaded_kafka_producer_no_ping(
        &settings.kafka_config(),
        handle.clone(),
        observe_delivery,
    ) {
        Ok(producer) => producer,
        Err(e) => {
            tracing::error!(error = %e, "failed to create ingestion warnings producer; emitter disabled");
            report_emitter_enabled("producer_create_failed", false);
            return MergeWarnings::disabled();
        }
    };
    let emitter = Arc::new(KafkaRowWarningEmitter::with_throttle(
        producer,
        settings.topic.clone(),
        throttle(),
    ));

    let background = emitter.clone();
    tokio::spawn(async move {
        let mut heartbeat = tokio::time::interval(HEARTBEAT_INTERVAL);
        let mut sweep = tokio::time::interval(THROTTLE_SWEEP_INTERVAL);
        loop {
            tokio::select! {
                _ = heartbeat.tick() => handle.report_healthy(),
                _ = sweep.tick() => background.sweep_throttle(),
                _ = handle.shutdown_recv() => break,
            }
        }
    });

    report_emitter_enabled("ok", true);
    tracing::info!(
        topic = settings.topic.as_str(),
        "ingestion warnings emitter enabled"
    );
    MergeWarnings::new(emitter)
}

#[cfg(test)]
mod tests {
    use common_ingestion_warnings::row::throttle_key;
    use common_ingestion_warnings::test_support::CollectingRowEmitter;
    use common_ingestion_warnings::throttle::ThrottleDecision;
    use metrics_util::debugging::{DebugValue, DebuggingRecorder};
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

    fn settings(enabled: bool, hosts: &str, topic: &str) -> WarningsSettings {
        WarningsSettings {
            enabled,
            kafka_hosts: hosts.to_string(),
            kafka_tls: false,
            topic: topic.to_string(),
            kafka_queue_mib: 16,
            kafka_message_max_bytes: 1_048_576,
        }
    }

    #[rstest]
    #[case::off(false, "broker:9092", "topic", Some("disabled"))]
    #[case::no_hosts(true, "", "topic", Some("hosts_unset"))]
    #[case::no_topic(true, "broker:9092", "", Some("topic_unset"))]
    #[case::usable(true, "broker:9092", "topic", None)]
    fn unusable_settings_name_their_reason(
        #[case] enabled: bool,
        #[case] hosts: &str,
        #[case] topic: &str,
        #[case] expected: Option<&'static str>,
    ) {
        assert_eq!(settings(enabled, hosts, topic).disabled_reason(), expected);
    }

    #[test]
    fn the_producer_config_is_fire_and_forget_and_isolated() {
        let config = settings(true, "broker:9092", "topic").kafka_config();
        assert_eq!(config.kafka_hosts, "broker:9092");
        assert_eq!(config.kafka_client_id, KAFKA_CLIENT_ID);
        assert_eq!(config.kafka_producer_acks.as_deref(), Some(KAFKA_ACKS));
        assert_eq!(config.kafka_producer_retries, Some(KAFKA_RETRIES));
        assert_eq!(config.kafka_producer_linger_ms, KAFKA_LINGER_MS);
        assert_eq!(config.kafka_producer_queue_messages, KAFKA_QUEUE_MESSAGES);
        assert_eq!(config.kafka_message_timeout_ms, KAFKA_MESSAGE_TIMEOUT_MS);
        assert_eq!(config.kafka_producer_queue_mib, 16);
        assert_eq!(config.kafka_producer_message_max_bytes, Some(1_048_576));
        assert!(config.kafka_producer_enable_idempotence.is_none());
        assert!(config.kafka_producer_batch_size.is_none());
    }

    #[rstest]
    #[case::hosts_unset("", "hosts_unset")]
    #[case::no_handle("broker:9092", "no_handle")]
    fn an_unusable_install_reports_its_reason_on_the_gauge(
        #[case] hosts: &str,
        #[case] reason: &str,
    ) {
        let recorder = DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        let warnings = metrics::with_local_recorder(&recorder, || {
            install(&settings(true, hosts, "topic"), None)
        });
        assert!(!warnings.is_enabled());
        let gauges: Vec<(String, f64)> = snapshotter
            .snapshot()
            .into_vec()
            .into_iter()
            .filter(|(key, _, _, _)| key.key().name() == INGESTION_WARNINGS_EMITTER_ENABLED)
            .map(|(key, _, _, value)| {
                let reason = key
                    .key()
                    .labels()
                    .find(|label| label.key() == "reason")
                    .expect("reason label")
                    .value()
                    .to_string();
                let DebugValue::Gauge(value) = value else {
                    panic!("emitter enabled is a gauge");
                };
                (reason, value.into_inner())
            })
            .collect();
        assert_eq!(gauges, vec![(reason.to_string(), 0.0)]);
    }

    #[test]
    fn the_throttle_tracks_only_admitted_scopes_and_caps_above_the_shared_default() {
        let throttle = throttle();
        let warning = WarningType::CannotMergeAlreadyIdentified;
        let mut admitted = 0;
        for n in 0..=DEFAULT_MAX_TRACKED_KEYS {
            match throttle.check(&throttle_key(7, &n.to_string()), warning) {
                ThrottleDecision::Emit => admitted += 1,
                ThrottleDecision::TypeBudgetExhausted => {}
                other => panic!("scope {n}: {other:?}"),
            }
        }
        assert!(admitted >= TYPE_BUDGET_PER_SECOND.get() as usize);
        assert_eq!(
            throttle.tracked_keys(),
            admitted,
            "a scope the budget refused must not hold a key"
        );
    }

    #[test]
    fn the_type_budget_refills_at_the_stated_rate() {
        let throttle = throttle();
        let warning = WarningType::MergeRaceCondition;
        for n in 0..TYPE_BUDGET_PER_SECOND.get() {
            assert_eq!(
                throttle.check(&throttle_key(7, &n.to_string()), warning),
                ThrottleDecision::Emit,
                "scope {n}"
            );
        }
        assert_eq!(
            throttle.check(&throttle_key(7, "over"), warning),
            ThrottleDecision::TypeBudgetExhausted
        );
        std::thread::sleep(Duration::from_millis(100));
        // A budget that refilled one permit a second would still refuse.
        assert_eq!(
            throttle.check(&throttle_key(7, "later"), warning),
            ThrottleDecision::Emit
        );
    }
}
