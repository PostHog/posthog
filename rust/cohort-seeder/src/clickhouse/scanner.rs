//! The streaming ClickHouse scanner: drives one chunk's query, folds rows through the shared
//! evaluator into tiles, and emits the scan metrics. Depends on `domain`, `config`, and the sibling
//! `sql`/`row` modules; never on `store` or `kafka`.

use std::time::Instant;

use chrono::Utc;
use chrono_tz::Tz;
use cohort_core::clickhouse_timestamp_to_millis;
use cohort_core::day_idx_in_tz;
use cohort_core::events::CohortStreamEvent;
use cohort_core::hogvm::VmErrorClass;
use metrics::{counter, histogram};
use tokio_util::sync::CancellationToken;
use tracing::info;

use super::row::{row_to_event, EventRow};
use super::sql::{plan_scan, scan_sql, ScanPlan};
use crate::domain::{
    conditions_active_on, ActiveConditions, AggregateError, CancelCause, ChunkAccumulator,
    ChunkDomainError, ClaimedChunk, DayIdx, EventNameSet, Halted, PinnedCondition, PinnedRun,
    RecordOutcome, RecordStats, ScannedChunk, SeedDomain, SeedTile, UtcMillis,
};
use crate::observability::metrics::{
    AGGREGATE_ENTRIES, CHUNKS_VACUOUS, CHUNK_SCAN_DURATION_SECONDS, CONDITIONS_EVALUATED,
    EVENTS_SKIPPED, HOGVM_ERRORS, ROWS_SCANNED,
};

#[derive(Clone)]
pub struct ChunkScanner {
    client: clickhouse::Client,
}

impl ChunkScanner {
    pub fn new(client: clickhouse::Client) -> Self {
        Self { client }
    }

    pub async fn scan(
        &self,
        chunk: ClaimedChunk,
        run: &PinnedRun,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<ScannedChunk, Halted<ClaimedChunk, ScanError>> {
        self.scan_at(
            chunk,
            run,
            Utc::now().timestamp_millis(),
            lease_cancel,
            shutdown,
        )
        .await
    }

    async fn scan_at(
        &self,
        chunk: ClaimedChunk,
        run: &PinnedRun,
        now_ms: i64,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<ScannedChunk, Halted<ClaimedChunk, ScanError>> {
        match self
            .scan_tiles(&chunk, run, now_ms, lease_cancel, shutdown)
            .await
        {
            Ok(tiles) => Ok(chunk.into_scanned(tiles)),
            Err(ScanHalt::Cancelled(cause)) => Err(Halted::cancelled(chunk, cause)),
            Err(ScanHalt::Failed(source)) => Err(Halted::failed(chunk, source)),
        }
    }

    async fn scan_tiles(
        &self,
        chunk: &ClaimedChunk,
        run: &PinnedRun,
        now_ms: i64,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<Vec<SeedTile>, ScanHalt> {
        let _timer = ScanTimer::start();
        let spec = chunk.spec();
        let domain = run.domain_for(&spec).map_err(ScanError::from)?;
        let active = active_conditions_at(spec.day, run.tz, now_ms, &run.conditions);
        if active.is_empty() {
            info!(
                day = spec.day,
                boundary_day = run.boundary.day(),
                "chunk skipped: every referencing window has slid past this day"
            );
            counter!(CHUNKS_VACUOUS, "reason" => "window_expired").increment(1);
            return Ok(Vec::new());
        }
        let event_names = active_event_names(run, &active);
        let scan_spec = match plan_scan(spec.team_id, &domain, &event_names, spec.band) {
            ScanPlan::Scan(scan_spec) => scan_spec,
            ScanPlan::Vacuous => {
                counter!(CHUNKS_VACUOUS, "reason" => "empty_scan").increment(1);
                return Ok(Vec::new());
            }
        };

        let mut cursor = self
            .client
            .query(&scan_sql(&scan_spec))
            .fetch::<EventRow>()
            .map_err(ScanError::Query)?;
        let mut accumulator =
            ChunkAccumulator::new(run.team_id, &run.filters, &active).map_err(ScanError::from)?;
        let mut saw_row = false;

        loop {
            let row = tokio::select! {
                biased;
                _ = shutdown.cancelled() => return Err(ScanHalt::Cancelled(CancelCause::Shutdown)),
                _ = lease_cancel.cancelled() => return Err(ScanHalt::Cancelled(CancelCause::LeaseLost)),
                row = cursor.next() => row.map_err(ScanError::Cursor)?,
            };
            let Some(row) = row else {
                break;
            };
            saw_row = true;
            counter!(ROWS_SCANNED).increment(1);
            match fold_event(&domain, &mut accumulator, row_to_event(run.team_id, row))
                .map_err(ScanError::from)?
            {
                ScanEventOutcome::Evaluated(stats) => record_evaluation(stats),
                ScanEventOutcome::Skipped(reason) => {
                    counter!(EVENTS_SKIPPED, "reason" => reason.as_str()).increment(1);
                }
            }
        }
        if !saw_row {
            counter!(CHUNKS_VACUOUS, "reason" => "no_rows").increment(1);
        }

        histogram!(AGGREGATE_ENTRIES).record(accumulator.entry_count() as f64);
        let tiles = accumulator.into_tiles(&domain, run.run_id, spec.lease.epoch());
        Ok(tiles)
    }
}

/// The scanner's internal stop signal, lifted to a [`Halted`] by `scan_at`: a cancellation cause or
/// a terminal [`ScanError`].
enum ScanHalt {
    Cancelled(CancelCause),
    Failed(ScanError),
}

impl From<ScanError> for ScanHalt {
    fn from(error: ScanError) -> Self {
        Self::Failed(error)
    }
}

/// The conditions still referencing `day` at scan time, gated at wall-clock now — deliberately NOT
/// at the run's boundary day. Planning anchors at the boundary pessimistically; by the time a chunk
/// is scanned, a sliding window may have moved past its day, and the consumer's apply rule slides
/// each record's window to at least the wall-clock day before evaluating, dropping below-window
/// tiles unevaluated. Scanning such a day would only produce tiles the consumer must discard.
///
/// This holds for disaster-recovery runs, whose boundary is a past instant: the boundary is the
/// timestamp the wiped processor resumes live consumption from, so every post-boundary day is
/// covered by live replay, and any pre-boundary day still inside a window anchored at the scan day
/// or later stays admitted here (window anchors only move forward, so the gate at scan time admits
/// a superset of every later evaluation's reachable days). The only skipped days are those that can
/// no longer affect membership at any evaluation from scan time on.
fn active_conditions_at(
    day: DayIdx,
    tz: Tz,
    now_ms: i64,
    conditions: &[PinnedCondition],
) -> ActiveConditions {
    conditions_active_on(day, day_idx_in_tz(now_ms, tz), conditions)
}

fn active_event_names(run: &PinnedRun, active: &ActiveConditions) -> EventNameSet {
    EventNameSet::new(
        run.event_names
            .iter()
            .filter(|event_name| {
                run.filters
                    .behavioral_by_event_name
                    .get(*event_name)
                    .is_some_and(|hashes| hashes.iter().any(|hash| active.get(hash).is_some()))
            })
            .cloned(),
    )
}

fn fold_event(
    domain: &SeedDomain,
    accumulator: &mut ChunkAccumulator,
    event: CohortStreamEvent,
) -> Result<ScanEventOutcome, AggregateError> {
    let Some(timestamp_ms) = clickhouse_timestamp_to_millis(&event.timestamp) else {
        return Ok(ScanEventOutcome::Skipped(ScanSkipReason::TimestampParse));
    };
    if !domain.contains(UtcMillis::new(timestamp_ms)) {
        return Ok(ScanEventOutcome::Skipped(ScanSkipReason::DayMismatch));
    }
    Ok(match accumulator.record_event(&event)? {
        RecordOutcome::Evaluated(stats) => ScanEventOutcome::Evaluated(stats),
        RecordOutcome::SkippedGlobals => {
            ScanEventOutcome::Skipped(ScanSkipReason::GlobalsParseError)
        }
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ScanEventOutcome {
    Evaluated(RecordStats),
    Skipped(ScanSkipReason),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ScanSkipReason {
    TimestampParse,
    DayMismatch,
    GlobalsParseError,
}

impl ScanSkipReason {
    const fn as_str(self) -> &'static str {
        match self {
            Self::TimestampParse => "timestamp_parse",
            Self::DayMismatch => "day_mismatch",
            Self::GlobalsParseError => "globals_parse_error",
        }
    }
}

fn record_evaluation(stats: RecordStats) {
    let evaluated = u64::from(stats.matched)
        + u64::from(stats.non_matched)
        + u64::from(stats.unknown_functions)
        + stats
            .vm_failures
            .iter()
            .map(|(_, count)| u64::from(count))
            .sum::<u64>();
    counter!(CONDITIONS_EVALUATED).increment(evaluated);
    if stats.unknown_functions > 0 {
        counter!(HOGVM_ERRORS, "class" => VmErrorClass::UnknownFunction.as_str())
            .increment(u64::from(stats.unknown_functions));
    }
    for (class, count) in stats.vm_failures.iter().filter(|(_, count)| *count > 0) {
        counter!(HOGVM_ERRORS, "class" => class.as_str()).increment(u64::from(count));
    }
}

struct ScanTimer(Instant);

impl ScanTimer {
    fn start() -> Self {
        Self(Instant::now())
    }
}

impl Drop for ScanTimer {
    fn drop(&mut self) {
        histogram!(CHUNK_SCAN_DURATION_SECONDS).record(self.0.elapsed().as_secs_f64());
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ScanError {
    #[error("resolving the chunk seed domain")]
    Domain(#[from] ChunkDomainError),
    #[error("building ClickHouse scan cursor")]
    Query(#[source] clickhouse::error::Error),
    #[error("streaming ClickHouse scan cursor")]
    Cursor(#[source] clickhouse::error::Error),
    #[error("aggregating ClickHouse scan row")]
    Aggregate(#[from] AggregateError),
}

#[cfg(test)]
mod tests {
    use chrono_tz::UTC;
    use cohort_core::filters::{CohortId, TeamFilters, TeamFiltersBuilder, TeamId};
    use serde_json::json;
    use uuid::Uuid;

    use std::collections::BTreeSet;

    use super::*;
    use crate::domain::{
        plan_days, Boundary, ClaimEpoch, ConditionHash, Lookback, PlanCaps, RunId, SChunkMs,
    };

    const HASH: &str = "aaaaaaaaaaaaaaaa";

    fn domain() -> SeedDomain {
        SeedDomain::new(
            1,
            Boundary::new(UtcMillis::new(2 * 86_400_000), UTC),
            UTC,
            SChunkMs(200_000_000),
        )
        .unwrap()
    }

    fn filters() -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        builder
            .add_cohort(
                CohortId(1),
                TeamId(2),
                &json!({
                    "properties": { "type": "AND", "values": [{
                        "type": "behavioral",
                        "value": "performed_event",
                        "key": "purchase",
                        "conditionHash": HASH,
                        "time_value": 7,
                        "time_interval": "day",
                        "bytecode": ["_H", 1, 32, "purchase", 32, "event", 1, 1, 11]
                    }]}
                }),
            )
            .unwrap();
        builder.freeze(UTC)
    }

    fn row(timestamp: &str) -> EventRow {
        EventRow {
            uuid: Uuid::from_u128(1).to_string(),
            event: "purchase".to_string(),
            properties: "{}".to_string(),
            timestamp: timestamp.to_string(),
            distinct_id: "distinct".to_string(),
            person_id: Uuid::from_u128(2).to_string(),
            person_properties: "{}".to_string(),
            elements_chain: String::new(),
        }
    }

    #[test]
    fn scan_fold_skips_bad_timestamps_wrong_days_and_malformed_globals() {
        let domain = domain();
        let filters = filters();
        let active = ActiveConditions::new([ConditionHash::parse(HASH).unwrap()]);
        let cases = [
            (
                row("not-a-timestamp"),
                ScanEventOutcome::Skipped(ScanSkipReason::TimestampParse),
            ),
            (
                row("1970-01-03 12:00:00.000000"),
                ScanEventOutcome::Skipped(ScanSkipReason::DayMismatch),
            ),
            (
                EventRow {
                    properties: "not-json".to_string(),
                    ..row("1970-01-02 12:00:00.000000")
                },
                ScanEventOutcome::Skipped(ScanSkipReason::GlobalsParseError),
            ),
        ];
        for (row, expected) in cases {
            let mut accumulator = ChunkAccumulator::new(TeamId(2), &filters, &active).unwrap();
            assert_eq!(
                fold_event(&domain, &mut accumulator, row_to_event(TeamId(2), row)).unwrap(),
                expected
            );
            assert_eq!(accumulator.entry_count(), 0);
        }
    }

    #[test]
    fn scan_fold_uses_the_shared_evaluator_and_accumulator() {
        let domain = domain();
        let filters = filters();
        let active = ActiveConditions::new([ConditionHash::parse(HASH).unwrap()]);
        let mut accumulator = ChunkAccumulator::new(TeamId(2), &filters, &active).unwrap();
        assert_eq!(
            fold_event(
                &domain,
                &mut accumulator,
                row_to_event(TeamId(2), row("1970-01-02 12:00:00.000000")),
            )
            .unwrap(),
            ScanEventOutcome::Evaluated(RecordStats {
                matched: 1,
                ..RecordStats::default()
            })
        );
        let tiles = accumulator.into_tiles(&domain, RunId(Uuid::nil()), ClaimEpoch(1));
        assert_eq!(tiles.len(), 1);
        assert_eq!(tiles[0].count(), 1);
    }

    #[test]
    fn scan_time_rechecks_sliding_conditions_against_the_current_day() {
        let hash = ConditionHash::parse(HASH).unwrap();
        let conditions = [PinnedCondition {
            cohort_id: CohortId(1),
            hash,
            event_name: "purchase".to_string(),
            lookback: Lookback::SlidingDays(1),
        }];
        assert!(active_conditions_at(1, UTC, 2 * 86_400_000, &conditions).contains(&hash));
        assert!(!active_conditions_at(1, UTC, 3 * 86_400_000, &conditions).contains(&hash));
    }

    /// Disaster-recovery shape: the boundary is a past instant, so the scan runs days after the
    /// plan was anchored. Every pre-boundary day still inside the wall-clock window must stay
    /// admitted (those days feed membership the live replay cannot reconstruct); days that slid
    /// out of every window are skipped, matching the consumer's drop-below-window apply rule.
    #[test]
    fn dr_scan_admits_every_pre_boundary_day_still_inside_the_window() {
        let hash = ConditionHash::parse(HASH).unwrap();
        let conditions = [PinnedCondition {
            cohort_id: CohortId(1),
            hash,
            event_name: "purchase".to_string(),
            lookback: Lookback::SlidingDays(7),
        }];
        let boundary = Boundary::new(UtcMillis::new(100 * 86_400_000), UTC);
        let planned = plan_days(&conditions, boundary, &PlanCaps::default());
        assert_eq!(planned, BTreeSet::from_iter(93..=99));

        let admitted_at = |now_day: i64| {
            planned
                .iter()
                .copied()
                .filter(|day| {
                    active_conditions_at(*day, UTC, now_day * 86_400_000, &conditions)
                        .contains(&hash)
                })
                .collect::<Vec<_>>()
        };
        // Scanned the boundary day (enablement shape): every planned day is admitted.
        assert_eq!(admitted_at(100), (93..=99).collect::<Vec<_>>());
        // Scanned three days later (DR shape): the window is [96, 103]; days 93-95 can no longer
        // affect any evaluation and are skipped, days 96-99 are still scanned.
        assert_eq!(admitted_at(103), (96..=99).collect::<Vec<_>>());
        // Boundary older than the window: live replay from the boundary covers the whole window,
        // so the seed correctly has nothing left to contribute.
        assert_eq!(admitted_at(107), Vec::<DayIdx>::new());
    }
}
