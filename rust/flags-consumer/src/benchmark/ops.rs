use std::fmt;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OpClass {
    PersonUpsert,
    DistinctIdAssignment,
    Merge,
    CanonicalRead,
}

impl OpClass {
    pub const COUNT: usize = 4;
    pub const ALL: [Self; Self::COUNT] = [
        Self::PersonUpsert,
        Self::DistinctIdAssignment,
        Self::Merge,
        Self::CanonicalRead,
    ];
    pub const WRITE_CLASSES: [Self; 3] =
        [Self::PersonUpsert, Self::DistinctIdAssignment, Self::Merge];

    pub const fn index(self) -> usize {
        match self {
            Self::PersonUpsert => 0,
            Self::DistinctIdAssignment => 1,
            Self::Merge => 2,
            Self::CanonicalRead => 3,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct OperationId(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(transparent)]
pub struct PhaseId(u64);

impl PhaseId {
    pub const fn new(value: u64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize)]
pub struct NanosSincePhaseStart {
    phase_id: PhaseId,
    nanos: u64,
}

impl NanosSincePhaseStart {
    pub(super) const fn from_nanos(phase_id: PhaseId, nanos: u64) -> Self {
        Self { phase_id, nanos }
    }

    pub const fn phase_id(self) -> PhaseId {
        self.phase_id
    }

    pub const fn as_nanos(self) -> u64 {
        self.nanos
    }

    pub(super) const fn checked_add(self, nanos: u64) -> Option<Self> {
        match self.nanos.checked_add(nanos) {
            Some(value) => Some(Self::from_nanos(self.phase_id, value)),
            None => None,
        }
    }

    pub fn ensure_same_phase(self, other: Self) -> Result<(), PhaseMismatch> {
        if self.phase_id == other.phase_id {
            return Ok(());
        }
        Err(PhaseMismatch {
            expected: self.phase_id,
            actual: other.phase_id,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PhaseMismatch {
    pub expected: PhaseId,
    pub actual: PhaseId,
}

impl fmt::Display for PhaseMismatch {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "phase {} does not match phase {}",
            self.actual.get(),
            self.expected.get()
        )
    }
}

impl std::error::Error for PhaseMismatch {}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PersonUpsertPayload {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub properties: Value,
    pub version: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DistinctIdAssignmentPayload {
    pub team_id: i32,
    pub person_uuid: Uuid,
    pub distinct_id: Box<str>,
    pub version: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DistinctIdMove {
    pub distinct_id: Box<str>,
    pub version: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MergeShape {
    Standard,
    Whale,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FullMergePayload {
    pub team_id: i32,
    pub source_person_uuid: Uuid,
    pub target_person_uuid: Uuid,
    pub distinct_id_moves: Box<[DistinctIdMove]>,
    pub target_properties: Value,
    pub target_version: i64,
    pub source_tombstone_version: i64,
    pub shape: MergeShape,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "result", rename_all = "snake_case")]
pub enum ReadExpectation {
    Hit,
    Miss,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CanonicalReadPayload {
    pub team_id: i32,
    pub distinct_id: Box<str>,
    pub expectation: ReadExpectation,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload", rename_all = "snake_case")]
pub enum OpPayload {
    PersonUpsert(PersonUpsertPayload),
    DistinctIdAssignment(DistinctIdAssignmentPayload),
    FullMerge(FullMergePayload),
    CanonicalRead(CanonicalReadPayload),
}

impl OpPayload {
    pub const fn class(&self) -> OpClass {
        match self {
            Self::PersonUpsert(_) => OpClass::PersonUpsert,
            Self::DistinctIdAssignment(_) => OpClass::DistinctIdAssignment,
            Self::FullMerge(_) => OpClass::Merge,
            Self::CanonicalRead(_) => OpClass::CanonicalRead,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct OpDescriptor {
    pub operation_id: OperationId,
    pub scheduled_at: NanosSincePhaseStart,
    pub payload: OpPayload,
}

impl OpDescriptor {
    pub fn new(
        operation_id: OperationId,
        scheduled_at: NanosSincePhaseStart,
        payload: OpPayload,
    ) -> Self {
        Self {
            operation_id,
            scheduled_at,
            payload,
        }
    }

    pub const fn class(&self) -> OpClass {
        self.payload.class()
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct DispatchedOperation {
    descriptor: OpDescriptor,
    dispatched_at: NanosSincePhaseStart,
}

impl DispatchedOperation {
    pub fn try_new(
        descriptor: OpDescriptor,
        dispatched_at: NanosSincePhaseStart,
    ) -> Result<Self, TimestampOrderError> {
        descriptor
            .scheduled_at
            .ensure_same_phase(dispatched_at)
            .map_err(TimestampOrderError::PhaseMismatch)?;
        if descriptor.scheduled_at.as_nanos() > dispatched_at.as_nanos() {
            return Err(TimestampOrderError::DispatchBeforeSchedule);
        }
        Ok(Self {
            descriptor,
            dispatched_at,
        })
    }

    pub const fn descriptor(&self) -> &OpDescriptor {
        &self.descriptor
    }

    pub const fn operation_id(&self) -> OperationId {
        self.descriptor.operation_id
    }

    pub const fn class(&self) -> OpClass {
        self.descriptor.class()
    }

    pub const fn scheduled_at(&self) -> NanosSincePhaseStart {
        self.descriptor.scheduled_at
    }

    pub const fn dispatched_at(&self) -> NanosSincePhaseStart {
        self.dispatched_at
    }

    pub fn into_parts(self) -> (OpDescriptor, NanosSincePhaseStart) {
        (self.descriptor, self.dispatched_at)
    }

    pub fn completion_timestamps(
        &self,
        started_at: NanosSincePhaseStart,
        completed_at: NanosSincePhaseStart,
    ) -> Result<CompletionTimestamps, TimestampOrderError> {
        CompletionTimestamps::try_new(
            self.scheduled_at(),
            self.dispatched_at,
            started_at,
            completed_at,
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct CompletionTimestamps {
    scheduled_at: NanosSincePhaseStart,
    dispatched_at: NanosSincePhaseStart,
    started_at: NanosSincePhaseStart,
    completed_at: NanosSincePhaseStart,
}

impl CompletionTimestamps {
    pub fn try_new(
        scheduled_at: NanosSincePhaseStart,
        dispatched_at: NanosSincePhaseStart,
        started_at: NanosSincePhaseStart,
        completed_at: NanosSincePhaseStart,
    ) -> Result<Self, TimestampOrderError> {
        scheduled_at
            .ensure_same_phase(dispatched_at)
            .and_then(|()| scheduled_at.ensure_same_phase(started_at))
            .and_then(|()| scheduled_at.ensure_same_phase(completed_at))
            .map_err(TimestampOrderError::PhaseMismatch)?;
        let timestamps = Self {
            scheduled_at,
            dispatched_at,
            started_at,
            completed_at,
        };
        if scheduled_at.as_nanos() > dispatched_at.as_nanos() {
            return Err(TimestampOrderError::DispatchBeforeSchedule);
        }
        if dispatched_at.as_nanos() > started_at.as_nanos() {
            return Err(TimestampOrderError::StartBeforeDispatch);
        }
        if started_at.as_nanos() > completed_at.as_nanos() {
            return Err(TimestampOrderError::CompletionBeforeStart);
        }
        Ok(timestamps)
    }

    pub const fn scheduled_at(self) -> NanosSincePhaseStart {
        self.scheduled_at
    }

    pub const fn dispatched_at(self) -> NanosSincePhaseStart {
        self.dispatched_at
    }

    pub const fn started_at(self) -> NanosSincePhaseStart {
        self.started_at
    }

    pub const fn completed_at(self) -> NanosSincePhaseStart {
        self.completed_at
    }

    pub const fn service_latency_nanos(self) -> u64 {
        self.completed_at.as_nanos() - self.started_at.as_nanos()
    }

    pub const fn schedule_latency_nanos(self) -> u64 {
        self.completed_at.as_nanos() - self.scheduled_at.as_nanos()
    }

    pub const fn queue_latency_nanos(self) -> u64 {
        self.started_at.as_nanos() - self.dispatched_at.as_nanos()
    }

    pub const fn dispatch_lag_nanos(self) -> u64 {
        self.dispatched_at.as_nanos() - self.scheduled_at.as_nanos()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimestampOrderError {
    PhaseMismatch(PhaseMismatch),
    DispatchBeforeSchedule,
    StartBeforeDispatch,
    CompletionBeforeStart,
}

impl fmt::Display for TimestampOrderError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::PhaseMismatch(error) => return error.fmt(formatter),
            Self::DispatchBeforeSchedule => "dispatch timestamp precedes schedule timestamp",
            Self::StartBeforeDispatch => "start timestamp precedes dispatch timestamp",
            Self::CompletionBeforeStart => "completion timestamp precedes start timestamp",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for TimestampOrderError {}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum CompletionOutcome {
    Success,
    Error { message: Box<str> },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CompletionRecord {
    pub operation_id: OperationId,
    pub class: OpClass,
    pub timestamps: CompletionTimestamps,
    pub outcome: CompletionOutcome,
    pub retry_affected: bool,
    pub deadlock_affected: bool,
    pub retry_attempts: u32,
    pub deadlock_attempts: u32,
}

impl CompletionRecord {
    pub const fn service_latency_nanos(&self) -> u64 {
        self.timestamps.service_latency_nanos()
    }

    pub const fn schedule_latency_nanos(&self) -> u64 {
        self.timestamps.schedule_latency_nanos()
    }

    pub const fn queue_latency_nanos(&self) -> u64 {
        self.timestamps.queue_latency_nanos()
    }

    pub const fn dispatch_lag_nanos(&self) -> u64 {
        self.timestamps.dispatch_lag_nanos()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn at(nanos: u64) -> NanosSincePhaseStart {
        NanosSincePhaseStart::from_nanos(PhaseId::new(1), nanos)
    }

    #[test]
    fn completion_timestamps_reject_every_out_of_order_boundary() {
        for (timestamps, expected) in [
            (
                (at(2), at(1), at(3), at(4)),
                TimestampOrderError::DispatchBeforeSchedule,
            ),
            (
                (at(1), at(3), at(2), at(4)),
                TimestampOrderError::StartBeforeDispatch,
            ),
            (
                (at(1), at(2), at(4), at(3)),
                TimestampOrderError::CompletionBeforeStart,
            ),
        ] {
            assert_eq!(
                CompletionTimestamps::try_new(
                    timestamps.0,
                    timestamps.1,
                    timestamps.2,
                    timestamps.3,
                ),
                Err(expected)
            );
        }

        assert!(matches!(
            CompletionTimestamps::try_new(
                at(1),
                NanosSincePhaseStart::from_nanos(PhaseId::new(2), 2),
                at(3),
                at(4),
            ),
            Err(TimestampOrderError::PhaseMismatch(_))
        ));
    }

    #[test]
    fn dispatched_operation_carries_the_validated_scheduler_timestamp() {
        let descriptor = OpDescriptor::new(
            OperationId(7),
            at(10),
            OpPayload::CanonicalRead(CanonicalReadPayload {
                team_id: 1,
                distinct_id: "person@example.com".into(),
                expectation: ReadExpectation::Hit,
            }),
        );
        let dispatched = DispatchedOperation::try_new(descriptor, at(12)).expect("valid dispatch");

        let timestamps = dispatched
            .completion_timestamps(at(15), at(20))
            .expect("ordered timestamps");

        assert_eq!(timestamps.dispatch_lag_nanos(), 2);
        assert_eq!(timestamps.queue_latency_nanos(), 3);
        assert_eq!(timestamps.service_latency_nanos(), 5);
    }
}
