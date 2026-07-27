//! Domain layer: the pinned run — lenient payload parse plus `PinnedRun`'s staged validation into a
//! typed, scannable run. Depends on `chunk`, `condition`, `window`, `ids`, and `cohort-core`.

use std::collections::HashMap;
use std::str::FromStr;
use std::sync::Arc;

use chrono_tz::Tz;
use cohort_core::filters::tree::{BehavioralLeafConfig, BehavioralValue};
use cohort_core::filters::{CohortId, FilterError, TeamFilters, TeamFiltersBuilder, TeamId};
use cohort_core::resolve_tz_or_utc;
use cohort_core::EvictionWindow;
use cohort_core::LeafStateKey;
use serde::{Deserialize, Deserializer};
use serde_json::Value;

use super::chunk::{ChunkDomainError, ChunkSpec};
use super::condition::{EventNameSet, Lookback, PinnedCondition};
use super::ids::{ConditionHash, ConditionHashError, RunId, UtcMillis};
use super::window::{Boundary, SeedDomain};

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

impl FromStr for TriggerKind {
    type Err = UnknownTriggerKind;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "team_enablement" => Ok(Self::TeamEnablement),
            "cohort_created" => Ok(Self::CohortCreated),
            "cohort_edited" => Ok(Self::CohortEdited),
            "disaster_recovery" => Ok(Self::DisasterRecovery),
            other => Err(UnknownTriggerKind(other.to_string())),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("unknown backfill trigger {0:?}")]
pub struct UnknownTriggerKind(pub String);

#[derive(Debug)]
pub struct PinnedRun {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub trigger: TriggerKind,
    pub tz: Tz,
    pub boundary: Boundary,
    pub conditions: Vec<PinnedCondition>,
    pub event_names: EventNameSet,
    pub filters: TeamFilters,
}

#[derive(Debug)]
pub struct ValidatedPinnedRun {
    pub run: PinnedRun,
    pub warnings: Vec<PinnedWarning>,
}

/// A run proven `seeding` with an established boundary, ready for pinned-payload validation. The
/// `trigger`/`boundary_at_ms` are already typed and present — the store performs the sole
/// `Option`→value narrowing before building this.
#[derive(Debug)]
pub struct PinnedRunSnapshot {
    pub run_id: RunId,
    pub team_id: TeamId,
    pub trigger: TriggerKind,
    pub timezone: String,
    pub boundary_at_ms: i64,
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
}

#[derive(Debug, Deserialize)]
struct RawPinnedCondition {
    cohort_id: i32,
    condition_hash: String,
    value: Option<String>,
    #[serde(default, deserialize_with = "lenient_i32")]
    time_value: Option<i32>,
    #[serde(default, deserialize_with = "lenient_string")]
    time_interval: Option<String>,
    #[serde(default, deserialize_with = "lenient_string")]
    explicit_datetime: Option<String>,
    #[serde(default, deserialize_with = "lenient_string")]
    explicit_datetime_to: Option<String>,
    #[serde(default, deserialize_with = "lenient_string")]
    operator: Option<String>,
    #[serde(default, deserialize_with = "lenient_i32")]
    operator_value: Option<i32>,
    window_days: u32,
    event_name: Option<String>,
    is_action: bool,
}

/// Coerce a JSON scalar to `Some(i32)` only for an integer in `i32` range; anything else
/// (missing, null, string, float, bool, array, object, out-of-range) becomes `None`, never an
/// error. Replicates the former `json_i32` tolerance byte-for-byte — a plain `Option<i32>` would
/// instead reject a mistyped payload Django is allowed to send.
fn lenient_i32<'de, D>(deserializer: D) -> Result<Option<i32>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Option::<Value>::deserialize(deserializer)?;
    Ok(value
        .as_ref()
        .and_then(Value::as_i64)
        .and_then(|number| i32::try_from(number).ok()))
}

/// Coerce a JSON scalar to `Some(String)` only for a string; anything else becomes `None`, never
/// an error. Replicates the former `json_string` tolerance byte-for-byte.
fn lenient_string<'de, D>(deserializer: D) -> Result<Option<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Option::<Value>::deserialize(deserializer)?;
    Ok(value.as_ref().and_then(Value::as_str).map(str::to_string))
}

impl PinnedRun {
    pub fn validate(snapshot: PinnedRunSnapshot) -> Result<ValidatedPinnedRun, PinnedError> {
        let payload = parse_payload(snapshot.pinned)?;
        let mut warnings = Vec::new();
        let tz = resolve_timezone(&snapshot.timezone, &mut warnings);
        let boundary = Boundary::new(UtcMillis::new(snapshot.boundary_at_ms), tz);
        let participation = ParticipationSet::build(snapshot.team_id, snapshot.participations, tz)?;
        let conditions = resolve_conditions(payload.conditions, &participation, &mut warnings)?;
        let event_names = EventNameSet::from_conditions(&conditions);

        Ok(ValidatedPinnedRun {
            run: PinnedRun {
                run_id: snapshot.run_id,
                team_id: snapshot.team_id,
                trigger: snapshot.trigger,
                tz,
                boundary,
                conditions,
                event_names,
                filters: participation.into_filters(),
            },
            warnings,
        })
    }

    /// The seed domain for a claimed chunk, after proving the chunk belongs to this run/team. Named
    /// here (not in the store) so the store never references a scan/ClickHouse type — cycle break.
    pub fn domain_for(&self, spec: &ChunkSpec) -> Result<SeedDomain, ChunkDomainError> {
        if self.run_id != spec.lease.run_id() || self.team_id != spec.team_id {
            return Err(ChunkDomainError::RunMismatch {
                chunk_run_id: spec.lease.run_id(),
                chunk_team_id: spec.team_id.0,
                pinned_run_id: self.run_id,
                pinned_team_id: self.team_id.0,
            });
        }
        Ok(SeedDomain::new(
            spec.day,
            self.boundary,
            self.tz,
            spec.s_chunk,
        )?)
    }
}

fn parse_payload(pinned: Value) -> Result<PinnedPayload, PinnedError> {
    let payload: PinnedPayload = serde_json::from_value(pinned)?;
    if payload.schema_version != 1 {
        return Err(PinnedError::SchemaVersion(payload.schema_version));
    }
    Ok(payload)
}

fn resolve_timezone(configured: &str, warnings: &mut Vec<PinnedWarning>) -> Tz {
    let tz = resolve_tz_or_utc(configured);
    if configured.parse::<Tz>().is_err() {
        warnings.push(PinnedWarning::TimezoneFallback {
            configured: configured.to_string(),
        });
    }
    tz
}

/// The participations of a run, indexed for dedup-checked lookup with the frozen filter catalog
/// already built from the active cohorts.
struct ParticipationSet {
    states: HashMap<CohortId, PinnedParticipationState>,
    filters: TeamFilters,
}

impl ParticipationSet {
    fn build(
        team_id: TeamId,
        participations: Vec<PinnedParticipation>,
        tz: Tz,
    ) -> Result<Self, PinnedError> {
        let mut states = HashMap::with_capacity(participations.len());
        let mut builder = TeamFiltersBuilder::default();
        for participation in participations {
            if states
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
                    team_id,
                    &participation.pinned_filters,
                )?;
            }
        }
        Ok(Self {
            states,
            filters: builder.freeze(tz),
        })
    }

    fn state(&self, cohort_id: CohortId) -> Option<PinnedParticipationState> {
        self.states.get(&cohort_id).copied()
    }

    fn into_filters(self) -> TeamFilters {
        self.filters
    }
}

fn resolve_conditions(
    raw_conditions: Vec<RawPinnedCondition>,
    participation: &ParticipationSet,
    warnings: &mut Vec<PinnedWarning>,
) -> Result<Vec<PinnedCondition>, PinnedError> {
    let mut conditions = Vec::with_capacity(raw_conditions.len());
    for raw in raw_conditions {
        let cohort_id = CohortId(raw.cohort_id);
        let Some(state) = participation.state(cohort_id) else {
            return Err(PinnedError::MissingParticipation(raw.cohort_id));
        };
        let hash = ConditionHash::parse(&raw.condition_hash).map_err(|source| {
            PinnedError::InvalidConditionHash {
                value: raw.condition_hash.clone(),
                source,
            }
        })?;
        if state == PinnedParticipationState::Superseded {
            warnings.push(PinnedWarning::ConditionSuperseded { cohort_id, hash });
            continue;
        }
        let lookback = match derive_lookback(&raw, hash, &participation.filters)? {
            LookbackResolution::Dropped(reason) => {
                warnings.push(PinnedWarning::ConditionDropped {
                    cohort_id,
                    hash,
                    reason,
                });
                continue;
            }
            LookbackResolution::Resolved(lookback) => lookback,
        };
        let derived = derived_window_days(lookback);
        if raw.window_days != derived {
            warnings.push(PinnedWarning::WindowDaysMismatch {
                cohort_id,
                hash,
                pinned: raw.window_days,
                derived,
            });
        }
        let event_name = raw
            .event_name
            .expect("a resolved condition always carries a concrete event name");
        conditions.push(PinnedCondition {
            cohort_id,
            hash,
            event_name,
            lookback,
        });
    }
    Ok(conditions)
}

const fn derived_window_days(lookback: Lookback) -> u32 {
    match lookback {
        Lookback::SlidingDays(days) => days,
        Lookback::SubDay | Lookback::FixedRange { .. } => 0,
    }
}

/// The outcome of resolving one raw condition against the frozen catalog: either a scannable
/// [`Lookback`] to store, or a drop reason surfaced as a warning and never stored.
enum LookbackResolution {
    Resolved(Lookback),
    Dropped(PinnedDropReason),
}

fn derive_lookback(
    raw: &RawPinnedCondition,
    hash: ConditionHash,
    filters: &TeamFilters,
) -> Result<LookbackResolution, PinnedError> {
    if raw.is_action {
        return Ok(LookbackResolution::Dropped(PinnedDropReason::ActionKeyed));
    }
    let Some(value) = raw.value.as_deref().and_then(BehavioralValue::from_wire) else {
        return Ok(LookbackResolution::Dropped(
            PinnedDropReason::AbsentFromFrozenCatalog,
        ));
    };
    let Some(event_name) = raw.event_name.as_ref() else {
        return Ok(LookbackResolution::Dropped(
            PinnedDropReason::AbsentFromFrozenCatalog,
        ));
    };
    let leaf = BehavioralLeafConfig {
        condition_hash: hash.as_bytes(),
        value,
        event_key: event_name.clone(),
        time_value: raw.time_value,
        operator_value: raw.operator_value,
        time_interval: raw.time_interval.clone(),
        operator: raw.operator.clone(),
        explicit_datetime: raw.explicit_datetime.clone(),
        explicit_datetime_to: raw.explicit_datetime_to.clone(),
        leaf_state_key: LeafStateKey([0; 16]),
        state_variant: None,
        bytecode: Arc::new(Vec::new()),
        negated: false,
    }
    .with_state_key();
    let Some(meta) = filters.by_lsk.get(&leaf.leaf_state_key) else {
        return Ok(LookbackResolution::Dropped(
            PinnedDropReason::AbsentFromFrozenCatalog,
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
    Ok(LookbackResolution::Resolved(lookback))
}

#[cfg(test)]
mod tests {
    use chrono::NaiveDate;
    use chrono_tz::UTC;
    use cohort_core::day_idx_of_naive_date;
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
            trigger: TriggerKind::TeamEnablement,
            timezone: "UTC".to_string(),
            boundary_at_ms: 1_800_000_000_000,
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
        // The action-keyed condition (`hashes[4]`, no event name) resolves to a drop and is absent
        // from the stored conditions; its `ConditionDropped` warning is asserted below.
        let expected = [
            Lookback::SlidingDays(7),
            Lookback::SlidingDays(30),
            Lookback::FixedRange {
                from_day: Some(day(2026, 1, 3)),
                to_day: Some(day(2026, 1, 5)),
            },
            Lookback::SubDay,
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
        assert_eq!(validated.run.event_names.as_slice(), &["active-event"]);
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

    #[test]
    fn lenient_serde_coerces_mistyped_scalars_to_none_without_failing_validation() {
        let hash = "lenient000000000";
        let catalog = json!({
            "properties": { "type": "AND", "values": [
                { "type": "behavioral", "value": "performed_event", "key": "evt", "conditionHash": hash, "time_value": 7, "time_interval": "day", "bytecode": bytecode("evt") },
            ]}
        });
        let validate = |condition: Value| {
            PinnedRun::validate(snapshot(
                json!({ "schema_version": 1, "conditions": [condition], "event_names": ["evt"] }),
                vec![PinnedParticipation {
                    cohort_id: CohortId(1),
                    pinned_filters: catalog.clone(),
                    state: PinnedParticipationState::Active,
                }],
            ))
        };

        // Well-typed scalars resolve against the frozen catalog.
        let mut well_typed = condition(1, hash, "performed_event", Some("evt"), 7);
        well_typed["time_value"] = json!(7);
        well_typed["time_interval"] = json!("day");
        let resolved = validate(well_typed).unwrap();
        assert_eq!(
            resolved
                .run
                .conditions
                .iter()
                .map(|condition| condition.lookback)
                .collect::<Vec<_>>(),
            [Lookback::SlidingDays(7)],
        );

        // A string where an int is expected and a number where a string is expected coerce to None
        // exactly as json_i32/json_string did: validation still succeeds (a plain `Option<i32>`
        // would reject this payload), but the mistyped scalars change the leaf-state key, so the
        // condition drops out of the frozen catalog instead of erroring.
        let mut mistyped = condition(1, hash, "performed_event", Some("evt"), 7);
        mistyped["time_value"] = json!("7");
        mistyped["time_interval"] = json!(5);
        mistyped["operator_value"] = json!("2");
        let dropped = validate(mistyped).unwrap();
        assert!(dropped.run.conditions.is_empty());
        assert!(dropped.warnings.contains(&PinnedWarning::ConditionDropped {
            cohort_id: CohortId(1),
            hash: ConditionHash::parse(hash).unwrap(),
            reason: PinnedDropReason::AbsentFromFrozenCatalog,
        }));
    }
}
