use std::array;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::Path;

use hdrhistogram::Histogram;
use serde::Serialize;

use super::ops::{CompletionOutcome, CompletionRecord, OpClass, PhaseId, PhaseMismatch};
use super::scheduler::{DispatchOutcome, DispatchRecord};

const HISTOGRAM_SIGNIFICANT_DIGITS: u8 = 3;
pub const DEFAULT_INTERVAL_SECS: u64 = 10;

#[derive(Debug)]
struct LatencyHistograms {
    service: Histogram<u64>,
    schedule: Histogram<u64>,
    queue: Histogram<u64>,
    dispatch_lag: Histogram<u64>,
}

impl LatencyHistograms {
    fn new() -> Self {
        Self {
            service: new_histogram(),
            schedule: new_histogram(),
            queue: new_histogram(),
            dispatch_lag: new_histogram(),
        }
    }

    fn record(&mut self, completion: &CompletionRecord) {
        record_latency(&mut self.service, completion.service_latency_nanos());
        record_latency(&mut self.schedule, completion.schedule_latency_nanos());
        record_latency(&mut self.queue, completion.queue_latency_nanos());
    }

    fn merge_from(&mut self, other: &Self) {
        self.service
            .add(&other.service)
            .expect("histograms share configuration");
        self.schedule
            .add(&other.schedule)
            .expect("histograms share configuration");
        self.queue
            .add(&other.queue)
            .expect("histograms share configuration");
        self.dispatch_lag
            .add(&other.dispatch_lag)
            .expect("histograms share configuration");
    }
}

fn new_histogram() -> Histogram<u64> {
    Histogram::new(HISTOGRAM_SIGNIFICANT_DIGITS).expect("valid benchmark histogram precision")
}

fn record_latency(histogram: &mut Histogram<u64>, nanos: u64) {
    histogram
        .record(nanos.max(1))
        .expect("auto-resizing histogram accepts all latency values");
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct OperationCounts {
    pub scheduled: u64,
    pub completed: u64,
    pub achieved: u64,
    pub shed: u64,
    pub closed: u64,
    pub errors: u64,
    pub retry_affected: u64,
    pub deadlock_affected: u64,
    pub retry_attempts: u64,
    pub deadlock_attempts: u64,
}

impl OperationCounts {
    fn merge_from(&mut self, other: Self) {
        self.scheduled = self.scheduled.saturating_add(other.scheduled);
        self.completed = self.completed.saturating_add(other.completed);
        self.achieved = self.achieved.saturating_add(other.achieved);
        self.shed = self.shed.saturating_add(other.shed);
        self.closed = self.closed.saturating_add(other.closed);
        self.errors = self.errors.saturating_add(other.errors);
        self.retry_affected = self.retry_affected.saturating_add(other.retry_affected);
        self.deadlock_affected = self
            .deadlock_affected
            .saturating_add(other.deadlock_affected);
        self.retry_attempts = self.retry_attempts.saturating_add(other.retry_attempts);
        self.deadlock_attempts = self
            .deadlock_attempts
            .saturating_add(other.deadlock_attempts);
    }

    fn record_dispatch(&mut self, dispatch: DispatchRecord) {
        self.scheduled = self.scheduled.saturating_add(1);
        match dispatch.outcome {
            DispatchOutcome::Enqueued => {}
            DispatchOutcome::Shed => self.shed = self.shed.saturating_add(1),
            DispatchOutcome::Closed => self.closed = self.closed.saturating_add(1),
        }
    }

    fn record_completion(&mut self, completion: &CompletionRecord) {
        self.completed = self.completed.saturating_add(1);
        match completion.outcome {
            CompletionOutcome::Success => self.achieved = self.achieved.saturating_add(1),
            CompletionOutcome::Error { .. } => self.errors = self.errors.saturating_add(1),
        }
        if completion.retry_affected {
            self.retry_affected = self.retry_affected.saturating_add(1);
        }
        if completion.deadlock_affected {
            self.deadlock_affected = self.deadlock_affected.saturating_add(1);
        }
        self.retry_attempts = self
            .retry_attempts
            .saturating_add(u64::from(completion.retry_attempts));
        self.deadlock_attempts = self
            .deadlock_attempts
            .saturating_add(u64::from(completion.deadlock_attempts));
    }
}

#[derive(Debug)]
struct ClassAccumulator {
    counts: OperationCounts,
    latencies: LatencyHistograms,
}

impl ClassAccumulator {
    fn new() -> Self {
        Self {
            counts: OperationCounts::default(),
            latencies: LatencyHistograms::new(),
        }
    }

    fn record_dispatch(&mut self, dispatch: DispatchRecord) {
        self.counts.record_dispatch(dispatch);
        record_latency(
            &mut self.latencies.dispatch_lag,
            dispatch.dispatch_lag_nanos(),
        );
    }

    fn record_completion(&mut self, completion: &CompletionRecord) {
        self.counts.record_completion(completion);
        self.latencies.record(completion);
    }

    fn merge_from(&mut self, other: &Self) {
        self.counts.merge_from(other.counts);
        self.latencies.merge_from(&other.latencies);
    }

    fn snapshot(&self, class: OpClass) -> ClassMetrics {
        ClassMetrics {
            class,
            counts: self.counts,
            service: LatencySummary::from_histogram(&self.latencies.service),
            schedule: LatencySummary::from_histogram(&self.latencies.schedule),
            queue: LatencySummary::from_histogram(&self.latencies.queue),
            dispatch_lag: LatencySummary::from_histogram(&self.latencies.dispatch_lag),
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize)]
pub struct LatencySummary {
    pub count: u64,
    pub min_nanos: u64,
    pub p50_nanos: u64,
    pub p95_nanos: u64,
    pub p99_nanos: u64,
    pub max_nanos: u64,
}

impl LatencySummary {
    fn from_histogram(histogram: &Histogram<u64>) -> Self {
        if histogram.is_empty() {
            return Self::default();
        }
        Self {
            count: histogram.len(),
            min_nanos: histogram.min(),
            p50_nanos: histogram.value_at_quantile(0.50),
            p95_nanos: histogram.value_at_quantile(0.95),
            p99_nanos: histogram.value_at_quantile(0.99),
            max_nanos: histogram.max(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct ClassMetrics {
    pub class: OpClass,
    pub counts: OperationCounts,
    pub service: LatencySummary,
    pub schedule: LatencySummary,
    pub queue: LatencySummary,
    pub dispatch_lag: LatencySummary,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct IntervalRecord {
    pub record_type: &'static str,
    pub phase_id: PhaseId,
    pub interval_index: u64,
    pub started_at_nanos: u64,
    pub ended_at_nanos: u64,
    pub classes: [ClassMetrics; OpClass::COUNT],
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PhaseSummaryRecord {
    pub record_type: &'static str,
    pub phase_id: PhaseId,
    pub duration_nanos: u64,
    pub drain_duration_nanos: u64,
    pub post_deadline_duration_nanos: u64,
    pub deadline_counts: [OperationCounts; OpClass::COUNT],
    pub classes: [ClassMetrics; OpClass::COUNT],
}

#[derive(Debug)]
pub struct PhaseCollector {
    phase_id: PhaseId,
    interval_index: u64,
    interval_started_at_nanos: u64,
    interval: [ClassAccumulator; OpClass::COUNT],
    totals: [ClassAccumulator; OpClass::COUNT],
    workload_deadline_nanos: u64,
    deadline_counts: [OperationCounts; OpClass::COUNT],
}

impl PhaseCollector {
    pub fn new(phase_id: PhaseId) -> Self {
        Self::with_deadline(phase_id, u64::MAX)
    }

    pub fn with_deadline(phase_id: PhaseId, workload_deadline_nanos: u64) -> Self {
        Self {
            phase_id,
            interval_index: 0,
            interval_started_at_nanos: 0,
            interval: array::from_fn(|_| ClassAccumulator::new()),
            totals: array::from_fn(|_| ClassAccumulator::new()),
            workload_deadline_nanos,
            deadline_counts: [OperationCounts::default(); OpClass::COUNT],
        }
    }

    pub fn record_dispatch(&mut self, dispatch: DispatchRecord) -> Result<(), CollectorError> {
        self.ensure_phase(dispatch.scheduled_at().phase_id())?;
        self.interval[dispatch.class.index()].record_dispatch(dispatch);
        if dispatch.scheduled_at().as_nanos() <= self.workload_deadline_nanos {
            self.deadline_counts[dispatch.class.index()].record_dispatch(dispatch);
        }
        Ok(())
    }

    pub fn record_completion(
        &mut self,
        completion: &CompletionRecord,
    ) -> Result<(), CollectorError> {
        self.ensure_phase(completion.timestamps.scheduled_at().phase_id())?;
        self.interval[completion.class.index()].record_completion(completion);
        if completion.timestamps.completed_at().as_nanos() <= self.workload_deadline_nanos {
            self.deadline_counts[completion.class.index()].record_completion(completion);
        }
        Ok(())
    }

    pub fn finish_interval(&mut self, ended_at_nanos: u64) -> IntervalRecord {
        let completed = std::mem::replace(
            &mut self.interval,
            array::from_fn(|_| ClassAccumulator::new()),
        );
        for (total, interval) in self.totals.iter_mut().zip(&completed) {
            total.merge_from(interval);
        }
        let record = IntervalRecord {
            record_type: "interval",
            phase_id: self.phase_id,
            interval_index: self.interval_index,
            started_at_nanos: self.interval_started_at_nanos,
            ended_at_nanos,
            classes: class_snapshots(&completed),
        };
        self.interval_index = self.interval_index.saturating_add(1);
        self.interval_started_at_nanos = ended_at_nanos;
        record
    }

    pub fn finish_phase(
        mut self,
        duration_nanos: u64,
        drain_duration_nanos: u64,
        post_deadline_duration_nanos: u64,
    ) -> PhaseSummaryRecord {
        for (total, interval) in self.totals.iter_mut().zip(&self.interval) {
            total.merge_from(interval);
        }
        PhaseSummaryRecord {
            record_type: "phase_summary",
            phase_id: self.phase_id,
            duration_nanos,
            drain_duration_nanos,
            post_deadline_duration_nanos,
            deadline_counts: self.deadline_counts,
            classes: class_snapshots(&self.totals),
        }
    }

    fn ensure_phase(&self, phase_id: PhaseId) -> Result<(), CollectorError> {
        if phase_id == self.phase_id {
            return Ok(());
        }
        Err(CollectorError::PhaseMismatch(PhaseMismatch {
            expected: self.phase_id,
            actual: phase_id,
        }))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CollectorError {
    PhaseMismatch(PhaseMismatch),
}

impl std::fmt::Display for CollectorError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::PhaseMismatch(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for CollectorError {}

fn class_snapshots(
    accumulators: &[ClassAccumulator; OpClass::COUNT],
) -> [ClassMetrics; OpClass::COUNT] {
    array::from_fn(|index| accumulators[index].snapshot(OpClass::ALL[index]))
}

#[derive(Debug)]
pub struct JsonlSink {
    writer: BufWriter<File>,
}

impl JsonlSink {
    pub fn create(path: impl AsRef<Path>) -> std::io::Result<Self> {
        let file = File::create(path)?;
        Ok(Self {
            writer: BufWriter::new(file),
        })
    }

    pub fn write<T: Serialize>(&mut self, record: &T) -> anyhow::Result<()> {
        serde_json::to_writer(&mut self.writer, record)?;
        self.writer.write_all(b"\n")?;
        Ok(())
    }

    pub fn flush(&mut self) -> std::io::Result<()> {
        self.writer.flush()
    }
}

#[cfg(test)]
mod tests {
    use std::num::NonZeroUsize;

    use super::*;
    use crate::benchmark::ops::{
        CanonicalReadPayload, CompletionTimestamps, NanosSincePhaseStart, OpDescriptor, OpPayload,
        OperationId, ReadExpectation,
    };
    use crate::benchmark::scheduler::BoundedDispatcher;

    fn at(nanos: u64) -> NanosSincePhaseStart {
        NanosSincePhaseStart::from_nanos(PhaseId::new(1), nanos)
    }

    fn completion(retry_attempts: u32, deadlock_attempts: u32) -> CompletionRecord {
        CompletionRecord {
            operation_id: OperationId(1),
            class: OpClass::CanonicalRead,
            timestamps: CompletionTimestamps::try_new(at(10), at(12), at(15), at(20))
                .expect("ordered timestamps"),
            outcome: CompletionOutcome::Success,
            retry_affected: retry_attempts > 0,
            deadlock_affected: deadlock_attempts > 0,
            retry_attempts,
            deadlock_attempts,
        }
    }

    #[test]
    fn interval_flush_resets_interval_and_preserves_phase_totals() {
        let mut collector = PhaseCollector::new(PhaseId::new(1));
        let (mut dispatcher, _receiver) =
            BoundedDispatcher::channel(NonZeroUsize::new(1).expect("nonzero"));
        let dispatch = dispatcher
            .try_dispatch_at(
                OpDescriptor::new(
                    OperationId(2),
                    at(10),
                    OpPayload::CanonicalRead(CanonicalReadPayload {
                        team_id: 1,
                        distinct_id: "person@example.com".into(),
                        expectation: ReadExpectation::Hit,
                    }),
                ),
                at(12),
            )
            .expect("valid dispatch");
        collector.record_dispatch(dispatch).expect("matching phase");
        collector
            .record_completion(&completion(2, 1))
            .expect("matching phase");
        let mut failed = completion(0, 0);
        failed.operation_id = OperationId(4);
        failed.outcome = CompletionOutcome::Error {
            message: "terminal".into(),
        };
        collector
            .record_completion(&failed)
            .expect("matching phase");
        let other_phase = NanosSincePhaseStart::from_nanos(PhaseId::new(2), 20);
        let mixed_phase = CompletionRecord {
            operation_id: OperationId(3),
            class: OpClass::CanonicalRead,
            timestamps: CompletionTimestamps::try_new(
                other_phase,
                other_phase,
                other_phase,
                other_phase,
            )
            .expect("ordered timestamps"),
            outcome: CompletionOutcome::Success,
            retry_affected: false,
            deadlock_affected: false,
            retry_attempts: 0,
            deadlock_attempts: 0,
        };
        assert!(matches!(
            collector.record_completion(&mixed_phase),
            Err(CollectorError::PhaseMismatch(_))
        ));

        let first = collector.finish_interval(10_000_000_000);
        let second = collector.finish_interval(20_000_000_000);
        let summary = collector.finish_phase(20_000_000_000, 0, 0);
        let class = OpClass::CanonicalRead.index();

        assert_eq!(first.classes[class].counts.achieved, 1);
        assert_eq!(first.classes[class].counts.completed, 2);
        assert_eq!(first.classes[class].counts.scheduled, 1);
        assert_eq!(first.classes[class].counts.errors, 1);
        assert_eq!(first.classes[class].counts.retry_attempts, 2);
        assert_eq!(first.classes[class].counts.deadlock_affected, 1);
        assert_eq!(first.classes[class].dispatch_lag.count, 1);
        assert_eq!(second.classes[class].counts.achieved, 0);
        assert_eq!(summary.classes[class], first.classes[class]);
        assert_eq!(summary.deadline_counts[class].achieved, 1);
    }

    #[test]
    fn deadline_counts_exclude_completions_from_the_drain_window() {
        let mut collector = PhaseCollector::with_deadline(PhaseId::new(1), 20);
        let (mut dispatcher, _receiver) =
            BoundedDispatcher::channel(NonZeroUsize::new(1).expect("nonzero"));
        let dispatch = dispatcher
            .try_dispatch_at(
                OpDescriptor::new(
                    OperationId(2),
                    at(10),
                    OpPayload::CanonicalRead(CanonicalReadPayload {
                        team_id: 1,
                        distinct_id: "person@example.com".into(),
                        expectation: ReadExpectation::Hit,
                    }),
                ),
                at(12),
            )
            .expect("valid dispatch");
        collector.record_dispatch(dispatch).expect("matching phase");
        let late_completion = CompletionRecord {
            operation_id: OperationId(2),
            class: OpClass::CanonicalRead,
            timestamps: CompletionTimestamps::try_new(at(10), at(12), at(15), at(25))
                .expect("ordered timestamps"),
            outcome: CompletionOutcome::Success,
            retry_affected: false,
            deadlock_affected: false,
            retry_attempts: 0,
            deadlock_attempts: 0,
        };
        collector
            .record_completion(&late_completion)
            .expect("matching phase");

        let summary = collector.finish_phase(20, 5, 7);
        let class = OpClass::CanonicalRead.index();
        assert_eq!(summary.deadline_counts[class].scheduled, 1);
        assert_eq!(summary.deadline_counts[class].completed, 0);
        assert_eq!(summary.deadline_counts[class].achieved, 0);
        assert_eq!(summary.classes[class].counts.achieved, 1);
        assert_eq!(summary.drain_duration_nanos, 5);
        assert_eq!(summary.post_deadline_duration_nanos, 7);
    }
}
