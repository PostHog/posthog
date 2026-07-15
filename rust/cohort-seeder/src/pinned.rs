use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use chrono_tz::Tz;
use cohort_core::filters::tree::{BehavioralLeafConfig, BehavioralValue};
use cohort_core::filters::{CohortId, FilterError, TeamFilters, TeamFiltersBuilder, TeamId};
use cohort_core::stage1::bucket_tz::resolve_tz_or_utc;
use cohort_core::stage1::key::LeafStateKey;
use cohort_core::stage1::pick_state::EvictionWindow;
use serde::Deserialize;
use serde_json::Value;

use crate::domain::Boundary;
use crate::ids::{ConditionHash, ConditionHashError, DayIdx, RunId};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TriggerKind {
    TeamEnablement,
    CohortCreated,
    CohortEdited,
    DisasterRecovery,
}

impl TriggerKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::TeamEnablement => "team_enablement",
            Self::CohortCreated => "cohort_created",
            Self::CohortEdited => "cohort_edited",
            Self::DisasterRecovery => "disaster_recovery",
        }
    }
}

impl TryFrom<&str> for TriggerKind {
    type Error = PinnedError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        match value {
            "team_enablement" => Ok(Self::TeamEnablement),
            "cohort_created" => Ok(Self::CohortCreated),
            "cohort_edited" => Ok(Self::CohortEdited),
            "disaster_recovery" => Ok(Self::DisasterRecovery),
            other => Err(PinnedError::UnknownTrigger(other.to_string())),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Lookback {
    SlidingDays(u32),
    SubDay,
    FixedRange {
        from_day: Option<DayIdx>,
        to_day: Option<DayIdx>,
    },
    Dropped,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PinnedCondition {
    pub cohort_id: CohortId,
    pub hash: ConditionHash,
    pub event_name: Option<String>,
    pub lookback: Lookback,
}

#[derive(Debug)]
pub struct PinnedRun {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub trigger: TriggerKind,
    pub tz: Tz,
    pub boundary: Boundary,
    pub conditions: Vec<PinnedCondition>,
    pub event_names: Vec<String>,
    pub filters: TeamFilters,
}

#[derive(Debug)]
pub struct ValidatedPinnedRun {
    pub run: PinnedRun,
    pub warnings: Vec<PinnedWarning>,
}

#[derive(Debug)]
pub struct PinnedRunSnapshot {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub trigger_kind: String,
    pub timezone: String,
    pub boundary_at_ms: Option<i64>,
    pub pinned: Value,
    pub participations: Vec<PinnedParticipation>,
}

#[derive(Debug)]
pub struct PinnedParticipation {
    pub cohort_id: CohortId,
    pub pinned_filters: Value,
    pub state: PinnedParticipationState,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PinnedParticipationState {
    Active,
    Superseded,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PinnedDropReason {
    ActionKeyed,
    AbsentFromFrozenCatalog,
}

impl PinnedDropReason {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ActionKeyed => "action_keyed",
            Self::AbsentFromFrozenCatalog => "absent_from_frozen_catalog",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PinnedWarning {
    TimezoneFallback {
        configured: String,
    },
    ConditionDropped {
        cohort_id: CohortId,
        hash: ConditionHash,
        reason: PinnedDropReason,
    },
    ConditionSuperseded {
        cohort_id: CohortId,
        hash: ConditionHash,
    },
    WindowDaysMismatch {
        cohort_id: CohortId,
        hash: ConditionHash,
        pinned: u32,
        derived: u32,
    },
}

#[derive(Debug, thiserror::Error)]
pub enum PinnedError {
    #[error("invalid pinned payload: {0}")]
    Payload(#[from] serde_json::Error),
    #[error("unsupported pinned schema version {0}")]
    SchemaVersion(u32),
    #[error("unknown backfill trigger {0:?}")]
    UnknownTrigger(String),
    #[error("run has no established boundary")]
    MissingBoundary,
    #[error("invalid conditionHash {value:?}: {source}")]
    InvalidConditionHash {
        value: String,
        #[source]
        source: ConditionHashError,
    },
    #[error("cohort {0} appears more than once in the pinned participations")]
    DuplicateParticipation(i32),
    #[error("pinned condition names cohort {0}, which is not an active participation")]
    MissingParticipation(i32),
    #[error(transparent)]
    Filters(#[from] FilterError),
    #[error("frozen catalog metadata is incomplete for condition {0}")]
    IncompleteMetadata(ConditionHash),
}

#[derive(Debug, Deserialize)]
struct PinnedPayload {
    schema_version: u32,
    conditions: Vec<RawPinnedCondition>,
    #[serde(rename = "event_names")]
    _event_names: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct RawPinnedCondition {
    cohort_id: i32,
    condition_hash: String,
    value: Option<String>,
    time_value: Option<Value>,
    time_interval: Option<Value>,
    explicit_datetime: Option<Value>,
    explicit_datetime_to: Option<Value>,
    operator: Option<Value>,
    operator_value: Option<Value>,
    window_days: u32,
    event_name: Option<String>,
    is_action: bool,
}

impl PinnedRun {
    pub fn validate(snapshot: PinnedRunSnapshot) -> Result<ValidatedPinnedRun, PinnedError> {
        let payload: PinnedPayload = serde_json::from_value(snapshot.pinned)?;
        if payload.schema_version != 1 {
            return Err(PinnedError::SchemaVersion(payload.schema_version));
        }

        let trigger = TriggerKind::try_from(snapshot.trigger_kind.as_str())?;
        let tz = resolve_tz_or_utc(&snapshot.timezone);
        let mut warnings = Vec::new();
        if snapshot.timezone.parse::<Tz>().is_err() {
            warnings.push(PinnedWarning::TimezoneFallback {
                configured: snapshot.timezone,
            });
        }
        let boundary = Boundary::new(
            snapshot
                .boundary_at_ms
                .ok_or(PinnedError::MissingBoundary)?,
            tz,
        );

        let mut participant_states = HashMap::with_capacity(snapshot.participations.len());
        let mut builder = TeamFiltersBuilder::default();
        for participation in snapshot.participations {
            if participant_states
                .insert(participation.cohort_id, participation.state)
                .is_some()
            {
                return Err(PinnedError::DuplicateParticipation(
                    participation.cohort_id.0,
                ));
            }
            if participation.state == PinnedParticipationState::Active {
                builder.add_cohort(
                    participation.cohort_id,
                    snapshot.team_id,
                    &participation.pinned_filters,
                )?;
            }
        }
        let filters = builder.freeze(tz);

        let mut conditions = Vec::with_capacity(payload.conditions.len());
        for raw in payload.conditions {
            let cohort_id = CohortId(raw.cohort_id);
            let Some(participation_state) = participant_states.get(&cohort_id) else {
                return Err(PinnedError::MissingParticipation(raw.cohort_id));
            };
            let hash = ConditionHash::parse(&raw.condition_hash).map_err(|source| {
                PinnedError::InvalidConditionHash {
                    value: raw.condition_hash.clone(),
                    source,
                }
            })?;
            if *participation_state == PinnedParticipationState::Superseded {
                warnings.push(PinnedWarning::ConditionSuperseded { cohort_id, hash });
                continue;
            }
            let (lookback, drop_reason) = derive_lookback(&raw, hash, &filters)?;
            if let Some(reason) = drop_reason {
                warnings.push(PinnedWarning::ConditionDropped {
                    cohort_id,
                    hash,
                    reason,
                });
            }
            let derived_window_days = match lookback {
                Lookback::SlidingDays(days) => days,
                Lookback::SubDay | Lookback::FixedRange { .. } | Lookback::Dropped => 0,
            };
            if raw.window_days != derived_window_days && !matches!(lookback, Lookback::Dropped) {
                warnings.push(PinnedWarning::WindowDaysMismatch {
                    cohort_id,
                    hash,
                    pinned: raw.window_days,
                    derived: derived_window_days,
                });
            }
            conditions.push(PinnedCondition {
                cohort_id,
                hash,
                event_name: raw.event_name,
                lookback,
            });
        }

        let event_names = conditions
            .iter()
            .filter(|condition| !matches!(condition.lookback, Lookback::Dropped))
            .filter_map(|condition| condition.event_name.clone())
            .collect::<HashSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();
        let mut event_names = event_names;
        event_names.sort_unstable();

        Ok(ValidatedPinnedRun {
            run: PinnedRun {
                run_id: snapshot.run_id,
                team_id: snapshot.team_id,
                trigger,
                tz,
                boundary,
                conditions,
                event_names,
                filters,
            },
            warnings,
        })
    }
}

fn derive_lookback(
    raw: &RawPinnedCondition,
    hash: ConditionHash,
    filters: &TeamFilters,
) -> Result<(Lookback, Option<PinnedDropReason>), PinnedError> {
    if raw.is_action {
        return Ok((Lookback::Dropped, Some(PinnedDropReason::ActionKeyed)));
    }
    let Some(value) = raw.value.as_deref().and_then(BehavioralValue::from_wire) else {
        return Ok((
            Lookback::Dropped,
            Some(PinnedDropReason::AbsentFromFrozenCatalog),
        ));
    };
    let Some(event_name) = raw.event_name.as_ref() else {
        return Ok((
            Lookback::Dropped,
            Some(PinnedDropReason::AbsentFromFrozenCatalog),
        ));
    };
    let leaf = BehavioralLeafConfig {
        condition_hash: hash.as_bytes(),
        value,
        event_key: event_name.clone(),
        time_value: json_i32(raw.time_value.as_ref()),
        operator_value: json_i32(raw.operator_value.as_ref()),
        time_interval: json_string(raw.time_interval.as_ref()),
        operator: json_string(raw.operator.as_ref()),
        explicit_datetime: json_string(raw.explicit_datetime.as_ref()),
        explicit_datetime_to: json_string(raw.explicit_datetime_to.as_ref()),
        leaf_state_key: LeafStateKey([0; 16]),
        state_variant: None,
        bytecode: Arc::new(Vec::new()),
        negated: false,
    }
    .with_state_key();
    let Some(meta) = filters.by_lsk.get(&leaf.leaf_state_key) else {
        return Ok((
            Lookback::Dropped,
            Some(PinnedDropReason::AbsentFromFrozenCatalog),
        ));
    };
    if meta.condition_hash != hash.as_bytes() {
        return Err(PinnedError::IncompleteMetadata(hash));
    }
    let lookback = match (meta.window, meta.window_days) {
        (Some(EvictionWindow::RelativeDays { days }), _) => Lookback::SlidingDays(days),
        (Some(EvictionWindow::RelativeSeconds { .. }), _) => Lookback::SubDay,
        (Some(EvictionWindow::Explicit { from_day, to_day }), _) => {
            Lookback::FixedRange { from_day, to_day }
        }
        (None, Some(days)) => Lookback::SlidingDays(days),
        (None, None) => return Err(PinnedError::IncompleteMetadata(hash)),
    };
    Ok((lookback, None))
}

fn json_i32(value: Option<&Value>) -> Option<i32> {
    value?
        .as_i64()
        .and_then(|number| i32::try_from(number).ok())
}

fn json_string(value: Option<&Value>) -> Option<String> {
    value?.as_str().map(str::to_string)
}

#[cfg(test)]
mod tests {
    use chrono::NaiveDate;
    use chrono_tz::UTC;
    use cohort_core::stage1::bucket_tz::day_idx_of_naive_date;
    use serde_json::json;
    use uuid::Uuid;

    use super::*;

    const BYTECODE: &[Value] = &[];

    fn bytecode(event: &str) -> Value {
        json!(["_H", 1, 32, event, 32, "event", 1, 1, 11])
    }

    fn condition(
        cohort_id: i32,
        hash: &str,
        value: &str,
        event_name: Option<&str>,
        window_days: u32,
    ) -> Value {
        json!({
            "cohort_id": cohort_id,
            "condition_hash": hash,
            "value": value,
            "time_value": null,
            "time_interval": null,
            "explicit_datetime": null,
            "explicit_datetime_to": null,
            "operator": null,
            "operator_value": null,
            "window_days": window_days,
            "event_name": event_name,
            "is_action": event_name.is_none(),
        })
    }

    fn snapshot(pinned: Value, participations: Vec<PinnedParticipation>) -> PinnedRunSnapshot {
        PinnedRunSnapshot {
            run_id: RunId(Uuid::nil()),
            team_id: TeamId(2),
            trigger_kind: "team_enablement".to_string(),
            timezone: "UTC".to_string(),
            boundary_at_ms: Some(1_800_000_000_000),
            pinned,
            participations,
        }
    }

    #[test]
    fn validation_rejects_unknown_schema_and_malformed_hashes() {
        let filters = json!({ "properties": { "type": "AND", "values": [] } });
        let participation = || PinnedParticipation {
            cohort_id: CohortId(1),
            pinned_filters: filters.clone(),
            state: PinnedParticipationState::Active,
        };
        let unknown = snapshot(
            json!({ "schema_version": 2, "conditions": [], "event_names": [] }),
            vec![participation()],
        );
        assert!(matches!(
            PinnedRun::validate(unknown),
            Err(PinnedError::SchemaVersion(2))
        ));

        for malformed in ["0123456789abcde", "0123456789abcdefg"] {
            let invalid = snapshot(
                json!({
                    "schema_version": 1,
                    "conditions": [condition(1, malformed, "performed_event", Some("x"), 0)],
                    "event_names": ["x"],
                }),
                vec![participation()],
            );
            assert!(matches!(
                PinnedRun::validate(invalid),
                Err(PinnedError::InvalidConditionHash { .. })
            ));
        }
    }

    #[test]
    fn invalid_timezone_falls_back_once_and_keeps_the_run_loadable() {
        let mut input = snapshot(
            json!({ "schema_version": 1, "conditions": [], "event_names": [] }),
            vec![PinnedParticipation {
                cohort_id: CohortId(1),
                pinned_filters: json!({ "properties": { "type": "AND", "values": [] } }),
                state: PinnedParticipationState::Active,
            }],
        );
        input.timezone = "not/a-zone".to_string();
        let validated = PinnedRun::validate(input).unwrap();
        assert_eq!(validated.run.tz, UTC);
        assert_eq!(
            validated.warnings,
            vec![PinnedWarning::TimezoneFallback {
                configured: "not/a-zone".to_string(),
            }]
        );
    }

    #[test]
    fn lookbacks_come_from_the_frozen_catalog_across_all_participations() {
        let hashes = [
            "daily00000000000",
            "relative30d00000",
            "absolute00000000",
            "hourly0000000000",
            "action0000000000",
            "secondpart000000",
        ];
        assert!(hashes.iter().all(|hash| hash.len() == 16));
        let first_filters = json!({
            "properties": { "type": "AND", "values": [
                { "type": "behavioral", "value": "performed_event", "key": "daily", "conditionHash": hashes[0], "time_value": 7, "time_interval": "day", "bytecode": bytecode("daily") },
                { "type": "behavioral", "value": "performed_event", "key": "relative", "conditionHash": hashes[1], "explicit_datetime": "-30d", "bytecode": bytecode("relative") },
                { "type": "behavioral", "value": "performed_event", "key": "absolute", "conditionHash": hashes[2], "explicit_datetime": "2026-01-03", "explicit_datetime_to": "2026-01-05", "bytecode": bytecode("absolute") },
                { "type": "behavioral", "value": "performed_event", "key": "hourly", "conditionHash": hashes[3], "time_value": 5, "time_interval": "hour", "bytecode": bytecode("hourly") },
                { "type": "behavioral", "value": "performed_event", "key": 42, "conditionHash": hashes[4], "time_value": 7, "time_interval": "day", "bytecode": BYTECODE },
            ]}
        });
        let second_filters = json!({
            "properties": { "type": "AND", "values": [
                { "type": "behavioral", "value": "performed_event_multiple", "key": "second", "conditionHash": hashes[5], "time_value": 14, "time_interval": "day", "operator": "gte", "operator_value": 2, "bytecode": bytecode("second") },
            ]}
        });

        let mut conditions = vec![
            condition(1, hashes[0], "performed_event", Some("daily"), 7),
            condition(1, hashes[1], "performed_event", Some("relative"), 0),
            condition(1, hashes[2], "performed_event", Some("absolute"), 0),
            condition(1, hashes[3], "performed_event", Some("hourly"), 0),
            condition(1, hashes[4], "performed_event", None, 7),
            condition(2, hashes[5], "performed_event_multiple", Some("second"), 14),
        ];
        conditions[0]["time_value"] = json!(7);
        conditions[0]["time_interval"] = json!("day");
        conditions[1]["explicit_datetime"] = json!("-30d");
        conditions[2]["explicit_datetime"] = json!("2026-01-03");
        conditions[2]["explicit_datetime_to"] = json!("2026-01-05");
        conditions[3]["time_value"] = json!(5);
        conditions[3]["time_interval"] = json!("hour");
        conditions[5]["time_value"] = json!(14);
        conditions[5]["time_interval"] = json!("day");
        conditions[5]["operator"] = json!("gte");
        conditions[5]["operator_value"] = json!(2);

        let validated = PinnedRun::validate(snapshot(
            json!({
                "schema_version": 1,
                "conditions": conditions,
                "event_names": ["absolute", "daily", "hourly", "relative", "second"],
            }),
            vec![
                PinnedParticipation {
                    cohort_id: CohortId(1),
                    pinned_filters: first_filters,
                    state: PinnedParticipationState::Active,
                },
                PinnedParticipation {
                    cohort_id: CohortId(2),
                    pinned_filters: second_filters,
                    state: PinnedParticipationState::Active,
                },
            ],
        ))
        .unwrap();

        let day = |year, month, day| {
            day_idx_of_naive_date(NaiveDate::from_ymd_opt(year, month, day).unwrap())
        };
        let expected = [
            Lookback::SlidingDays(7),
            Lookback::SlidingDays(30),
            Lookback::FixedRange {
                from_day: Some(day(2026, 1, 3)),
                to_day: Some(day(2026, 1, 5)),
            },
            Lookback::SubDay,
            Lookback::Dropped,
            Lookback::SlidingDays(14),
        ];
        assert_eq!(
            validated
                .run
                .conditions
                .iter()
                .map(|condition| condition.lookback)
                .collect::<Vec<_>>(),
            expected,
        );
        assert!(validated
            .run
            .filters
            .behavioral_by_event_name
            .contains_key("second"));
        assert!(validated
            .warnings
            .contains(&PinnedWarning::WindowDaysMismatch {
                cohort_id: CohortId(1),
                hash: ConditionHash::parse(hashes[1]).unwrap(),
                pinned: 0,
                derived: 30,
            }));
        assert!(validated
            .warnings
            .contains(&PinnedWarning::ConditionDropped {
                cohort_id: CohortId(1),
                hash: ConditionHash::parse(hashes[4]).unwrap(),
                reason: PinnedDropReason::ActionKeyed,
            }));
    }

    #[test]
    fn superseded_participations_are_known_but_excluded_from_the_scan_catalog() {
        let active_hash = "active0000000000";
        let superseded_hash = "superseded000000";
        let filters = |event_name: &str, hash: &str| {
            json!({
                "properties": { "type": "AND", "values": [{
                    "type": "behavioral",
                    "value": "performed_event",
                    "key": event_name,
                    "conditionHash": hash,
                    "time_value": 7,
                    "time_interval": "day",
                    "bytecode": bytecode(event_name),
                }]}
            })
        };
        let mut active_condition =
            condition(1, active_hash, "performed_event", Some("active-event"), 7);
        active_condition["time_value"] = json!(7);
        active_condition["time_interval"] = json!("day");
        let mut superseded_condition = condition(
            2,
            superseded_hash,
            "performed_event",
            Some("superseded-event"),
            7,
        );
        superseded_condition["time_value"] = json!(7);
        superseded_condition["time_interval"] = json!("day");
        let payload = json!({
            "schema_version": 1,
            "conditions": [active_condition, superseded_condition],
            "event_names": ["active-event", "superseded-event"],
        });
        let participations = vec![
            PinnedParticipation {
                cohort_id: CohortId(1),
                pinned_filters: filters("active-event", active_hash),
                state: PinnedParticipationState::Active,
            },
            PinnedParticipation {
                cohort_id: CohortId(2),
                pinned_filters: filters("superseded-event", superseded_hash),
                state: PinnedParticipationState::Superseded,
            },
        ];

        let validated = PinnedRun::validate(snapshot(payload.clone(), participations)).unwrap();
        assert_eq!(validated.run.conditions.len(), 1);
        assert_eq!(validated.run.conditions[0].cohort_id, CohortId(1));
        assert_eq!(validated.run.event_names, vec!["active-event"]);
        assert!(validated
            .run
            .filters
            .behavioral_by_event_name
            .contains_key("active-event"));
        assert!(!validated
            .run
            .filters
            .behavioral_by_event_name
            .contains_key("superseded-event"));
        assert!(validated
            .warnings
            .contains(&PinnedWarning::ConditionSuperseded {
                cohort_id: CohortId(2),
                hash: ConditionHash::parse(superseded_hash).unwrap(),
            }));

        let unknown = PinnedRun::validate(snapshot(
            payload,
            vec![PinnedParticipation {
                cohort_id: CohortId(1),
                pinned_filters: filters("active-event", active_hash),
                state: PinnedParticipationState::Active,
            }],
        ));
        assert!(matches!(unknown, Err(PinnedError::MissingParticipation(2))));
    }
}
