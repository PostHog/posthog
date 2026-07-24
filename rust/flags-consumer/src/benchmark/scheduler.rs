use std::cmp::Reverse;
use std::collections::BinaryHeap;
use std::fmt;
use std::num::NonZeroUsize;
use std::time::Duration;

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use serde::Serialize;
use tokio::sync::mpsc;

use super::ops::{
    DispatchedOperation, NanosSincePhaseStart, OpClass, OpDescriptor, OperationId, PhaseId,
    PhaseMismatch, TimestampOrderError,
};
use super::rates::{FeedMode, RatePerSecond, RateSpec};

const NANOS_PER_SECOND: f64 = 1_000_000_000.0;
const CLASS_SEED_MIX: u64 = 0x9e37_79b9_7f4a_7c15;

#[derive(Debug)]
struct ClassSchedule {
    rate: RatePerSecond,
    rng: StdRng,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct HeapEntry {
    scheduled_at: NanosSincePhaseStart,
    class: OpClass,
}

impl Ord for HeapEntry {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.scheduled_at
            .as_nanos()
            .cmp(&other.scheduled_at.as_nanos())
            .then_with(|| self.class.cmp(&other.class))
    }
}

impl PartialOrd for HeapEntry {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ScheduledArrival {
    pub class: OpClass,
    pub scheduled_at: NanosSincePhaseStart,
}

#[derive(Debug)]
pub struct ArrivalSchedule {
    phase_id: PhaseId,
    classes: [Option<ClassSchedule>; OpClass::COUNT],
    heap: BinaryHeap<Reverse<HeapEntry>>,
}

impl ArrivalSchedule {
    pub fn new(phase_id: PhaseId, seed: u64, rates: &[RateSpec]) -> Result<Self, ArrivalError> {
        let mut classes: [Option<ClassSchedule>; OpClass::COUNT] = std::array::from_fn(|_| None);
        let mut heap = BinaryHeap::new();
        let mut seen = [false; OpClass::COUNT];

        for rate in rates {
            let index = rate.class.index();
            if seen[index] {
                return Err(ArrivalError::DuplicateClass(rate.class));
            }
            seen[index] = true;
            if !rate.target.get().is_finite() || rate.target.get() < 0.0 {
                return Err(ArrivalError::InvalidRate {
                    class: rate.class,
                    rate: rate.target.get(),
                });
            }
            if !rate.target.is_active() || rate.feed == FeedMode::Closed {
                continue;
            }

            let class_seed =
                seed ^ CLASS_SEED_MIX.wrapping_mul(u64::try_from(index + 1).unwrap_or(u64::MAX));
            let mut class_schedule = ClassSchedule {
                rate: rate.target,
                rng: StdRng::seed_from_u64(class_seed),
            };
            let first_at = sample_interval_nanos(&mut class_schedule.rng, rate.target);
            heap.push(Reverse(HeapEntry {
                scheduled_at: NanosSincePhaseStart::from_nanos(phase_id, first_at),
                class: rate.class,
            }));
            classes[index] = Some(class_schedule);
        }

        Ok(Self {
            phase_id,
            classes,
            heap,
        })
    }

    pub fn phase_id(&self) -> PhaseId {
        self.phase_id
    }

    pub fn peek_next_at(&self) -> Option<NanosSincePhaseStart> {
        self.heap.peek().map(|entry| entry.0.scheduled_at)
    }

    pub fn next_arrival(&mut self) -> Option<ScheduledArrival> {
        let Reverse(entry) = self.heap.pop()?;
        self.advance(entry);
        Some(ScheduledArrival {
            class: entry.class,
            scheduled_at: entry.scheduled_at,
        })
    }

    pub fn pop_due(
        &mut self,
        now: NanosSincePhaseStart,
    ) -> Result<Option<ScheduledArrival>, ArrivalError> {
        if now.phase_id() != self.phase_id {
            return Err(ArrivalError::PhaseMismatch(PhaseMismatch {
                expected: self.phase_id,
                actual: now.phase_id(),
            }));
        }
        let Some(next_at) = self.peek_next_at() else {
            return Ok(None);
        };
        if next_at.as_nanos() > now.as_nanos() {
            return Ok(None);
        }
        Ok(self.next_arrival())
    }

    fn advance(&mut self, entry: HeapEntry) {
        let class_schedule = self.classes[entry.class.index()]
            .as_mut()
            .expect("heap entries always have class state");
        let interval = sample_interval_nanos(&mut class_schedule.rng, class_schedule.rate);
        let Some(next_at) = entry.scheduled_at.checked_add(interval) else {
            self.classes[entry.class.index()] = None;
            return;
        };
        self.heap.push(Reverse(HeapEntry {
            scheduled_at: next_at,
            class: entry.class,
        }));
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum ArrivalError {
    PhaseMismatch(PhaseMismatch),
    DuplicateClass(OpClass),
    InvalidRate { class: OpClass, rate: f64 },
}

impl fmt::Display for ArrivalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::PhaseMismatch(error) => error.fmt(formatter),
            Self::DuplicateClass(class) => write!(formatter, "duplicate rate for {class:?}"),
            Self::InvalidRate { class, rate } => {
                write!(formatter, "invalid arrival rate {rate} for {class:?}")
            }
        }
    }
}

impl std::error::Error for ArrivalError {}

fn sample_interval_nanos(rng: &mut impl Rng, rate: RatePerSecond) -> u64 {
    // Inverse exponential CDF; 1 - U keeps ln's input in (0, 1].
    let open_unit_interval = 1.0 - rng.gen::<f64>();
    let nanos = -open_unit_interval.ln() / rate.get() * NANOS_PER_SECOND;
    if !nanos.is_finite() || nanos >= u64::MAX as f64 {
        return u64::MAX;
    }
    (nanos.ceil() as u64).max(1)
}

#[derive(Debug, Clone, Copy)]
pub struct PhaseClock {
    phase_id: PhaseId,
    epoch: tokio::time::Instant,
}

impl PhaseClock {
    pub fn new(phase_id: PhaseId, epoch: tokio::time::Instant) -> Self {
        Self { phase_id, epoch }
    }

    pub fn start_now(phase_id: PhaseId) -> Self {
        Self::new(phase_id, tokio::time::Instant::now())
    }

    pub fn phase_id(&self) -> PhaseId {
        self.phase_id
    }

    pub fn now(&self) -> Result<NanosSincePhaseStart, ClockError> {
        let now = tokio::time::Instant::now();
        if now < self.epoch {
            return Err(ClockError::BeforePhaseEpoch);
        }
        let elapsed = now.duration_since(self.epoch);
        let nanos = u64::try_from(elapsed.as_nanos()).map_err(|_| ClockError::OutOfRange)?;
        Ok(NanosSincePhaseStart::from_nanos(self.phase_id, nanos))
    }

    pub async fn wait_until(&self, scheduled_at: NanosSincePhaseStart) -> Result<(), ClockError> {
        if scheduled_at.phase_id() != self.phase_id {
            return Err(ClockError::PhaseMismatch(PhaseMismatch {
                expected: self.phase_id,
                actual: scheduled_at.phase_id(),
            }));
        }
        let deadline = self
            .epoch
            .checked_add(Duration::from_nanos(scheduled_at.as_nanos()))
            .ok_or(ClockError::OutOfRange)?;
        tokio::time::sleep_until(deadline).await;
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClockError {
    PhaseMismatch(PhaseMismatch),
    BeforePhaseEpoch,
    OutOfRange,
}

impl fmt::Display for ClockError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::PhaseMismatch(error) => error.fmt(formatter),
            Self::BeforePhaseEpoch => formatter.write_str("clock precedes the phase epoch"),
            Self::OutOfRange => formatter.write_str("phase timestamp is outside the timer range"),
        }
    }
}

impl std::error::Error for ClockError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DispatchOutcome {
    Enqueued,
    Shed,
    Closed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct DispatchRecord {
    pub operation_id: OperationId,
    pub class: OpClass,
    scheduled_at: NanosSincePhaseStart,
    dispatched_at: NanosSincePhaseStart,
    pub outcome: DispatchOutcome,
}

impl DispatchRecord {
    pub fn scheduled_at(self) -> NanosSincePhaseStart {
        self.scheduled_at
    }

    pub fn dispatched_at(self) -> NanosSincePhaseStart {
        self.dispatched_at
    }

    pub fn dispatch_lag_nanos(self) -> u64 {
        self.dispatched_at.as_nanos() - self.scheduled_at.as_nanos()
    }
}

#[derive(Debug)]
pub struct BoundedDispatcher {
    sender: mpsc::Sender<DispatchedOperation>,
    shed: u64,
}

impl BoundedDispatcher {
    pub fn channel(capacity: NonZeroUsize) -> (Self, mpsc::Receiver<DispatchedOperation>) {
        let (sender, receiver) = mpsc::channel(capacity.get());
        (Self { sender, shed: 0 }, receiver)
    }

    pub fn shed_count(&self) -> u64 {
        self.shed
    }

    pub fn try_dispatch_at(
        &mut self,
        descriptor: OpDescriptor,
        dispatched_at: NanosSincePhaseStart,
    ) -> Result<DispatchRecord, DispatchError> {
        let operation_id = descriptor.operation_id;
        let class = descriptor.class();
        let scheduled_at = descriptor.scheduled_at;
        let dispatched = DispatchedOperation::try_new(descriptor, dispatched_at)
            .map_err(DispatchError::Timestamp)?;
        let outcome = match self.sender.try_send(dispatched) {
            Ok(()) => DispatchOutcome::Enqueued,
            Err(mpsc::error::TrySendError::Full(_)) => {
                self.shed = self.shed.saturating_add(1);
                DispatchOutcome::Shed
            }
            Err(mpsc::error::TrySendError::Closed(_)) => DispatchOutcome::Closed,
        };
        Ok(DispatchRecord {
            operation_id,
            class,
            scheduled_at,
            dispatched_at,
            outcome,
        })
    }

    pub async fn dispatch_with_backpressure(
        &self,
        descriptor: OpDescriptor,
        clock: &PhaseClock,
    ) -> Result<DispatchRecord, DispatchError> {
        let operation_id = descriptor.operation_id;
        let class = descriptor.class();
        if class == OpClass::CanonicalRead {
            return Err(DispatchError::ClosedLoopRead);
        }
        let scheduled_at = descriptor.scheduled_at;
        clock
            .wait_until(scheduled_at)
            .await
            .map_err(DispatchError::Clock)?;
        let permit = match self.sender.reserve().await {
            Ok(permit) => permit,
            Err(_) => {
                let dispatched_at = clock.now().map_err(DispatchError::Clock)?;
                DispatchedOperation::try_new(descriptor, dispatched_at)
                    .map_err(DispatchError::Timestamp)?;
                return Ok(DispatchRecord {
                    operation_id,
                    class,
                    scheduled_at,
                    dispatched_at,
                    outcome: DispatchOutcome::Closed,
                });
            }
        };
        let dispatched_at = clock.now().map_err(DispatchError::Clock)?;
        let dispatched = DispatchedOperation::try_new(descriptor, dispatched_at)
            .map_err(DispatchError::Timestamp)?;
        permit.send(dispatched);
        Ok(DispatchRecord {
            operation_id,
            class,
            scheduled_at,
            dispatched_at,
            outcome: DispatchOutcome::Enqueued,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatchError {
    ClosedLoopRead,
    Timestamp(TimestampOrderError),
    Clock(ClockError),
}

impl fmt::Display for DispatchError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ClosedLoopRead => formatter.write_str("canonical reads must remain open-loop"),
            Self::Timestamp(error) => error.fmt(formatter),
            Self::Clock(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for DispatchError {}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;
    use crate::benchmark::ops::{OpPayload, PersonUpsertPayload};

    const PHASE: PhaseId = PhaseId::new(1);

    fn open_rate(class: OpClass, target: f64) -> RateSpec {
        RateSpec {
            class,
            target: RatePerSecond::new(target),
            feed: FeedMode::Open,
        }
    }

    fn descriptor(id: u64, scheduled_at: u64) -> OpDescriptor {
        descriptor_in_phase(PHASE, id, scheduled_at)
    }

    fn descriptor_in_phase(phase_id: PhaseId, id: u64, scheduled_at: u64) -> OpDescriptor {
        OpDescriptor::new(
            OperationId(id),
            NanosSincePhaseStart::from_nanos(phase_id, scheduled_at),
            OpPayload::PersonUpsert(PersonUpsertPayload {
                team_id: 1,
                person_uuid: uuid::Uuid::nil(),
                properties: json!({}),
                version: 1,
            }),
        )
    }

    #[test]
    fn poisson_schedule_is_monotonic_and_independent_of_wakeup_delay() {
        let rates = [open_rate(OpClass::CanonicalRead, 14_474.0)];
        let mut direct = ArrivalSchedule::new(PHASE, 42, &rates).expect("valid schedule");
        let expected = (0..512)
            .map(|_| direct.next_arrival().expect("arrival"))
            .collect::<Vec<_>>();
        assert!(expected.windows(2).all(|window| {
            window[0].scheduled_at.as_nanos() < window[1].scheduled_at.as_nanos()
        }));

        let mut delayed = ArrivalSchedule::new(PHASE, 42, &rates).expect("valid schedule");
        let wakeup = NanosSincePhaseStart::from_nanos(
            PHASE,
            expected
                .last()
                .expect("last arrival")
                .scheduled_at
                .as_nanos()
                + 1_000_000,
        );
        let mut actual = Vec::with_capacity(expected.len());
        while actual.len() < expected.len() {
            actual.push(
                delayed
                    .pop_due(wakeup)
                    .expect("same phase")
                    .expect("overdue arrival"),
            );
        }
        assert_eq!(actual, expected);
    }

    #[test]
    fn full_open_loop_channel_sheds_without_growing() {
        let capacity = NonZeroUsize::new(1).expect("nonzero");
        let (mut dispatcher, receiver) = BoundedDispatcher::channel(capacity);

        let accepted = dispatcher
            .try_dispatch_at(
                descriptor(1, 10),
                NanosSincePhaseStart::from_nanos(PHASE, 10),
            )
            .expect("on-time dispatch");
        let shed = dispatcher
            .try_dispatch_at(
                descriptor(2, 11),
                NanosSincePhaseStart::from_nanos(PHASE, 12),
            )
            .expect("late dispatch");

        assert_eq!(accepted.outcome, DispatchOutcome::Enqueued);
        assert_eq!(shed.outcome, DispatchOutcome::Shed);
        assert_eq!(shed.dispatch_lag_nanos(), 1);
        assert_eq!(dispatcher.shed_count(), 1);
        assert_eq!(receiver.len(), 1);
    }

    #[test]
    fn early_dispatch_is_rejected_before_touching_the_queue() {
        let capacity = NonZeroUsize::new(1).expect("nonzero");
        let (mut dispatcher, receiver) = BoundedDispatcher::channel(capacity);

        let result = dispatcher.try_dispatch_at(
            descriptor(1, 10),
            NanosSincePhaseStart::from_nanos(PHASE, 9),
        );

        assert!(matches!(
            result,
            Err(DispatchError::Timestamp(
                TimestampOrderError::DispatchBeforeSchedule
            ))
        ));
        assert_eq!(receiver.len(), 0);
        assert_eq!(dispatcher.shed_count(), 0);

        let mixed_phase = dispatcher.try_dispatch_at(
            descriptor(2, 10),
            NanosSincePhaseStart::from_nanos(PhaseId::new(2), 10),
        );
        assert!(matches!(
            mixed_phase,
            Err(DispatchError::Timestamp(
                TimestampOrderError::PhaseMismatch(_)
            ))
        ));
        assert_eq!(receiver.len(), 0);
    }

    #[tokio::test(start_paused = true)]
    async fn backpressured_dispatch_publishes_only_after_its_scheduled_time() {
        let phase_id = PhaseId::new(7);
        let clock = PhaseClock::start_now(phase_id);
        let capacity = NonZeroUsize::new(1).expect("nonzero");
        let (dispatcher, mut receiver) = BoundedDispatcher::channel(capacity);
        let task = tokio::spawn(async move {
            dispatcher
                .dispatch_with_backpressure(descriptor_in_phase(phase_id, 1, 10), &clock)
                .await
        });

        tokio::task::yield_now().await;
        assert!(matches!(
            receiver.try_recv(),
            Err(mpsc::error::TryRecvError::Empty)
        ));
        tokio::time::advance(Duration::from_nanos(10)).await;
        let received = receiver.recv().await.expect("published descriptor");
        let record = task.await.expect("dispatch task").expect("dispatch record");

        assert_eq!(received.operation_id(), OperationId(1));
        assert!(record.dispatched_at().as_nanos() >= record.scheduled_at().as_nanos());
    }

    #[test]
    fn invalid_arrival_rates_are_rejected_instead_of_disabled() {
        for invalid_rate in [-1.0, f64::NAN, f64::INFINITY] {
            let result = ArrivalSchedule::new(
                PHASE,
                42,
                &[open_rate(OpClass::CanonicalRead, invalid_rate)],
            );
            assert!(matches!(result, Err(ArrivalError::InvalidRate { .. })));
        }
    }
}
