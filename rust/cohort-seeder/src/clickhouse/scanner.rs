//! The streaming ClickHouse scanner: drives one chunk's query, folds rows through the shared
//! evaluator into tiles, and emits the scan metrics. Depends on `domain`, `config`, and the sibling
//! `sql`/`row` modules; never on `store` or `kafka`.

use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use chrono_tz::Tz;
use clickhouse::query::RowCursor;
use cohort_core::clickhouse_timestamp_to_millis;
use cohort_core::day_idx_in_tz;
use cohort_core::events::CohortStreamEvent;
use cohort_core::filters::TeamId;
use cohort_core::hogvm::VmErrorClass;
use common_types::cohort::TeamAllowlist;
use metrics::{counter, histogram};
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use super::client::ClickHouseClient;
use super::log_comment::{ScanLogComment, LOG_COMMENT_OPTION};
use super::row::{row_to_event, EventRow};
use super::scan_volume::{self, ScanKind};
use super::sql::{
    ambiguous_value_probe_sql, fits_client_get, plan_scan, row_filter_sql, scan_sql, ScanPlan,
    ScanSpec,
};
use crate::domain::{
    conditions_active_on, diff_tiles, ActiveConditions, AggregateError, CancelCause,
    ChunkAccumulator, ChunkDomainError, ChunkProjection, ChunkSpec, ClaimedChunk, ColumnExactKeys,
    ColumnUpgrade, ConditionAnalyses, DayIdx, EventNameSet, Halted, MaterializedColumns,
    PinnedCondition, PinnedRun, ProjectedKeys, PropertiesSourcing, RecordOutcome, RecordStats,
    ScanRowFilter, ScanVolume, ScannedChunk, SeedDomain, SeedTile, SourcedProjection, TileDiff,
    UtcMillis,
};
use crate::observability::metrics::{
    team_label, MetricTimer, AGGREGATE_ENTRIES, CHUNKS_PROJECTED, CHUNKS_VACUOUS,
    CHUNK_SCAN_DURATION_SECONDS, CONDITIONS_EVALUATED, EVENTS_SKIPPED, HOGVM_ERRORS,
    PROJECTION_KEYS, ROWS_SCANNED, SCAN_PROPERTIES_SOURCE, SCAN_ROW_FILTER, SHADOW_COMPARE,
    SHADOW_COMPARE_DURATION_SECONDS, SHADOW_COMPARE_LEGACY_SKIPPED,
};

const MATERIALIZED_LOOKUP_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone)]
pub struct ChunkScanner {
    client: ClickHouseClient,
    /// Only what bounds the `team_id` label on the projection metrics. The scanner makes no
    /// admission decision from it — discovery already did, and re-deciding here would give one
    /// chunk a second, quieter place to be dropped.
    allowlist: TeamAllowlist,
    /// `SEEDER_SCAN_SHADOW_COMPARE`: re-scan each chunk wide and diff the tiles. On by default and
    /// diagnostic only — the projected arm's tiles are what the chunk returns either way.
    ///
    /// While it is on, a chunk's projected tiles stay live as the legacy aggregate is built, so
    /// peak scan memory roughly doubles. A `SEEDER_BANDS_PER_DAY` sized against an observed
    /// `seeder_aggregate_entries` has about half the headroom it had.
    shadow_compare: bool,
}

impl ChunkScanner {
    pub fn new(client: ClickHouseClient, allowlist: TeamAllowlist, shadow_compare: bool) -> Self {
        Self {
            client,
            allowlist,
            shadow_compare,
        }
    }

    /// `analyses` is the run's, not the chunk's: it is a pure function of the pinned bytecode, so
    /// every chunk of a run — and every retry of one, on any replica — narrows from the same answer.
    /// Only [`ConditionAnalyses::projection`] is per chunk, over the conditions active on its day.
    pub async fn scan(
        &self,
        chunk: ClaimedChunk,
        run: &PinnedRun,
        analyses: &ConditionAnalyses,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<ScannedChunk, Halted<ClaimedChunk, ScanError>> {
        self.scan_at(
            chunk,
            run,
            analyses,
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
        analyses: &ConditionAnalyses,
        now_ms: i64,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<ScannedChunk, Halted<ClaimedChunk, ScanError>> {
        match self
            .scan_tiles(&chunk, run, analyses, now_ms, lease_cancel, shutdown)
            .await
        {
            Ok((tiles, volume)) => Ok(chunk.into_scanned(tiles, volume)),
            Err(ScanHalt::Cancelled(cause)) => Err(Halted::cancelled(chunk, cause)),
            Err(ScanHalt::Failed(source)) => Err(Halted::failed(chunk, source)),
        }
    }

    async fn scan_tiles(
        &self,
        chunk: &ClaimedChunk,
        run: &PinnedRun,
        analyses: &ConditionAnalyses,
        now_ms: i64,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<(Vec<SeedTile>, ScanVolume), ScanHalt> {
        let timer = MetricTimer::start(CHUNK_SCAN_DURATION_SECONDS);
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
            return Ok((Vec::new(), ScanVolume::default()));
        }
        let event_names = active_event_names(run, &active);
        let scan_spec = match plan_scan(spec.team_id, &domain, &event_names, spec.band) {
            ScanPlan::Scan(scan_spec) => scan_spec,
            ScanPlan::Vacuous => {
                counter!(CHUNKS_VACUOUS, "reason" => "empty_scan").increment(1);
                return Ok((Vec::new(), ScanVolume::default()));
            }
        };
        let projection = analyses.projection(&active);
        let exact = analyses.column_exact_keys(&active);
        let row_filter = analyses.row_filter(&event_names, &run.filters, &active);
        let columns = self
            .lookup_columns(&column_lookup_keys(&projection, &exact, &row_filter))
            .await;
        let comment = ScanLogComment::BehavioralChunk {
            spec,
            cohort_id: run.sole_cohort_id(),
        };
        let sourcing = match projection.source_properties(&exact, &columns) {
            PropertiesSourcing::Upgradable(upgrade) => {
                self.probe_ambiguous_values(&scan_spec, upgrade, comment, lease_cancel, shutdown)
                    .await?
            }
            decided @ PropertiesSourcing::Decided(_) => decided,
        };
        let narrowed = narrow_scan(scan_spec, sourcing, &row_filter, &columns);
        self.record_narrowing(run.team_id, &narrowed);
        let scan_spec = narrowed.filtered.spec;
        let projection = narrowed.sourced.into_projection();

        let (tiles, volume, projected_fold) = self
            .scan_once(
                spec,
                run,
                &domain,
                &active,
                &scan_spec,
                &projection,
                ScanKind::Behavioral,
                comment,
                lease_cancel,
                shutdown,
            )
            .await?;
        // Closed before the diagnostic arm, which must not lengthen the chunk's reported scan.
        drop(timer);

        if self.shadow_compare {
            match CompareSkip::of(&projection, projected_fold) {
                Some(skip) => {
                    let team = team_label(&self.allowlist, run.team_id);
                    counter!(SHADOW_COMPARE, "result" => skip.as_str(), "team_id" => team)
                        .increment(1);
                }
                None => {
                    self.compare_scan(
                        spec,
                        run,
                        &domain,
                        &active,
                        &scan_spec,
                        &tiles,
                        projected_fold,
                        lease_cancel,
                        shutdown,
                    )
                    .await?;
                }
            }
        }
        Ok((tiles, volume))
    }

    /// One rendering of this chunk's scan: build the cursor from [`scan_sql`], fold it through a
    /// fresh accumulator, meter the moved bytes under `kind`, and return the sorted tiles.
    ///
    /// `kind` and `comment` co-vary at the two call sites. The per-row and per-chunk fold metrics
    /// are emitted for the authoritative [`ScanKind::Behavioral`] arm only, so a diagnostic
    /// re-scan of the same rows never doubles a throughput series.
    #[allow(clippy::too_many_arguments)]
    async fn scan_once(
        &self,
        spec: ChunkSpec,
        run: &PinnedRun,
        domain: &SeedDomain,
        active: &ActiveConditions,
        scan_spec: &ScanSpec,
        projection: &ChunkProjection,
        kind: ScanKind,
        comment: ScanLogComment,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<(Vec<SeedTile>, ScanVolume, FoldSummary), ScanHalt> {
        let mut cursor = self
            .client
            .query(&scan_sql(scan_spec, projection))
            .with_option(LOG_COMMENT_OPTION, comment.to_string())
            .fetch::<EventRow>()
            .map_err(ScanError::Query)?;
        let mut accumulator =
            ChunkAccumulator::new(run.team_id, &run.filters, active).map_err(ScanError::from)?;

        // Every way out of the fold funnels back here, so the volume is metered once whether the
        // scan finished, was cancelled, or failed mid-stream.
        let folded = fold_cursor(
            &mut cursor,
            &mut accumulator,
            domain,
            run.team_id,
            kind,
            lease_cancel,
            shutdown,
        )
        .await;
        let volume = scan_volume::observe(kind, &cursor);
        let summary = folded?;
        if kind == ScanKind::Behavioral {
            if summary.rows == RowsSeen::None {
                counter!(CHUNKS_VACUOUS, "reason" => "no_rows").increment(1);
            }
            histogram!(AGGREGATE_ENTRIES).record(accumulator.entry_count() as f64);
        }
        Ok((
            accumulator.into_tiles(domain, run.run_id, spec.lease.epoch()),
            volume,
            summary,
        ))
    }

    /// The diagnostic arm: re-scan the same chunk wide, diff the two tile vectors, meter the
    /// verdict, and drop the legacy tiles. Called only for a chunk whose authoritative scan
    /// narrowed, since a wide one would be compared against itself.
    ///
    /// A scan *failure* here is metered and swallowed: the diagnostic never fails a chunk. A
    /// *cancellation* propagates and is then handled exactly as one raised during the projected
    /// arm — so a lost lease still spends the attempt, and this arm widens the window in which
    /// that can happen to a fully computed chunk. Swallowing it is worse: another worker reclaims
    /// a `scanning` chunk once its lease expires (`store/chunks.rs`), so pressing on would produce
    /// tiles for a chunk this worker no longer owns, alongside the worker that now does. A
    /// shutdown must also stay prompt.
    #[allow(clippy::too_many_arguments)]
    async fn compare_scan(
        &self,
        spec: ChunkSpec,
        run: &PinnedRun,
        domain: &SeedDomain,
        active: &ActiveConditions,
        scan_spec: &ScanSpec,
        projected_tiles: &[SeedTile],
        projected_fold: FoldSummary,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<(), ScanHalt> {
        let team = team_label(&self.allowlist, run.team_id);
        // Spans the re-scan, its fold, and the diff. Records on every exit, so a cancelled or
        // failed compare still reports the time it held the chunk's slot and lease.
        let _timer = MetricTimer::start(SHADOW_COMPARE_DURATION_SECONDS);
        let (legacy_tiles, legacy_fold) = match self
            .scan_once(
                spec,
                run,
                domain,
                active,
                scan_spec,
                &ChunkProjection::FullColumns,
                ScanKind::BehavioralCompare,
                ScanLogComment::BehavioralCompareChunk {
                    spec,
                    cohort_id: run.sole_cohort_id(),
                },
                lease_cancel,
                shutdown,
            )
            .await
        {
            Ok((tiles, _, legacy_fold)) => (tiles, legacy_fold),
            Err(ScanHalt::Cancelled(cause)) => return Err(ScanHalt::Cancelled(cause)),
            Err(ScanHalt::Failed(error)) => {
                counter!(SHADOW_COMPARE, "result" => "error", "team_id" => team.clone())
                    .increment(1);
                // Debug, not Display: the variant's message names the stage, and only its source
                // chain carries what ClickHouse actually said.
                warn!(
                    run_id = %run.run_id.0,
                    team_id = run.team_id.0,
                    chunk = %spec.lease.chunk_id().0,
                    day = spec.day,
                    band = spec.band.band(),
                    error = ?error,
                    "shadow compare scan failed; projected tiles emitted unverified"
                );
                return Ok(());
            }
        };
        // The difference, not the wide arm's total: a blob kept whole or rebuilt from keys fails
        // the same parse on both arms and explains no divergence. Recorded whatever the verdict,
        // and at zero too, because on a blob the projection emptied this is the only count of
        // malformed rows anything will ever take.
        let diff = record_compare(
            team,
            projected_tiles,
            &legacy_tiles,
            projected_fold,
            legacy_fold,
        );
        if diff.is_match() {
            return Ok(());
        }
        warn!(
            run_id = %run.run_id.0,
            team_id = run.team_id.0,
            chunk = %spec.lease.chunk_id().0,
            day = spec.day,
            band = spec.band.band(),
            missing = diff.missing,
            extra = diff.extra,
            count_differs = diff.count_differs,
            legacy_only_globals_parse_errors = legacy_fold.legacy_only_skips(projected_fold),
            legacy_globals_parse_errors = legacy_fold.globals_parse_errors,
            projected_globals_parse_errors = projected_fold.globals_parse_errors,
            exemplars = ?diff.exemplars,
            "shadow compare diverged between the projected and legacy scans"
        );
        Ok(())
    }

    /// The column form reads a column value that trims to `false` as the boolean, which the VM
    /// equates with every exact literal, while the string `"false"` equals none. Only the blob holds
    /// the type, so a chunk with such a value keeps the rebuild.
    async fn probe_ambiguous_values(
        &self,
        spec: &ScanSpec,
        upgrade: ColumnUpgrade,
        comment: ScanLogComment,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<PropertiesSourcing, ScanHalt> {
        let sql = ambiguous_value_probe_sql(spec, upgrade.backed());
        // The column form's scan is longer than the probe, so it would not fit either.
        if !fits_client_get(&sql) {
            return Ok(PropertiesSourcing::Decided(upgrade.decline_too_long()));
        }
        let probe = self
            .client
            .query(&sql)
            .with_option(LOG_COMMENT_OPTION, comment.to_string())
            .fetch_optional::<u8>();
        let found = tokio::select! {
            biased;
            _ = shutdown.cancelled() => return Err(ScanHalt::Cancelled(CancelCause::Shutdown)),
            _ = lease_cancel.cancelled() => return Err(ScanHalt::Cancelled(CancelCause::LeaseLost)),
            found = probe => found.map_err(ScanError::Probe)?,
        };
        Ok(match found {
            Some(_) => PropertiesSourcing::Decided(upgrade.decline_ambiguous_value()),
            None => PropertiesSourcing::Upgradable(upgrade),
        })
    }

    /// A failed or timed-out lookup returns no columns, so the scan reads the blob.
    async fn lookup_columns(&self, keys: &BTreeSet<&str>) -> MaterializedColumns {
        match tokio::time::timeout(
            MATERIALIZED_LOOKUP_TIMEOUT,
            MaterializedColumns::lookup(&self.client, keys),
        )
        .await
        {
            Ok(Ok(columns)) => columns,
            Ok(Err(error)) => {
                warn!(error = ?error, "materialized column lookup failed; the scan reads the properties blob");
                MaterializedColumns::default()
            }
            Err(_) => {
                warn!("materialized column lookup timed out; the scan reads the properties blob");
                MaterializedColumns::default()
            }
        }
    }

    /// Publish what this chunk's scan narrowed to, so a team that stops projecting is visible
    /// before its scan cost is.
    fn record_narrowing(&self, team_id: TeamId, narrowed: &NarrowedScan) {
        let team = team_label(&self.allowlist, team_id);
        let projection = narrowed.sourced.projection();
        counter!(
            CHUNKS_PROJECTED,
            "outcome" => projection.outcome(),
            "team_id" => team.clone(),
        )
        .increment(1);
        counter!(
            SCAN_PROPERTIES_SOURCE,
            "source" => narrowed.sourced.outcome().as_str(),
            "team_id" => team.clone(),
        )
        .increment(1);
        counter!(
            SCAN_ROW_FILTER,
            "outcome" => narrowed.filtered.outcome.as_str(),
            "team_id" => team.clone(),
        )
        .increment(1);
        let ChunkProjection::Projected(plan) = projection else {
            return;
        };
        for (blob, keys) in [
            ("properties", plan.properties.key_count()),
            ("person_properties", plan.person_properties.key_count()),
        ] {
            if let Some(keys) = keys {
                histogram!(PROJECTION_KEYS, "blob" => blob, "team_id" => team.clone())
                    .record(keys as f64);
            }
        }
    }
}

#[derive(Debug)]
struct NarrowedScan {
    sourced: SourcedProjection,
    filtered: FilteredSpec,
}

#[derive(Debug)]
struct FilteredSpec {
    spec: ScanSpec,
    outcome: RowFilterOutcome,
}

/// Columns take the GET budget before the row filter: they keep ClickHouse off every row's blob.
fn narrow_scan(
    spec: ScanSpec,
    sourcing: PropertiesSourcing,
    row_filter: &ScanRowFilter,
    columns: &MaterializedColumns,
) -> NarrowedScan {
    let sourced = match sourcing {
        PropertiesSourcing::Decided(sourced) => sourced,
        PropertiesSourcing::Upgradable(upgrade)
            if fits_client_get(&scan_sql(&spec, &upgrade.column_form())) =>
        {
            upgrade.accept()
        }
        PropertiesSourcing::Upgradable(upgrade) => upgrade.decline_too_long(),
    };
    let filtered = fit_row_filter(spec, row_filter, columns, sourced.projection());
    NarrowedScan { sourced, filtered }
}

/// Drops the filter when the query would be too long to send, since every attempt would fail.
fn fit_row_filter(
    spec: ScanSpec,
    row_filter: &ScanRowFilter,
    columns: &MaterializedColumns,
    projection: &ChunkProjection,
) -> FilteredSpec {
    if row_filter.is_empty() {
        return FilteredSpec {
            spec,
            outcome: RowFilterOutcome::None,
        };
    }
    let filtered = spec
        .clone()
        .with_row_filter(row_filter_sql(row_filter, columns));
    // Both renderings, because the shadow compare sends the wide one with the same filter.
    let fits = [projection, &ChunkProjection::FullColumns]
        .into_iter()
        .all(|projection| fits_client_get(&scan_sql(&filtered, projection)));
    if fits {
        FilteredSpec {
            spec: filtered,
            outcome: RowFilterOutcome::reading(row_filter, columns),
        }
    } else {
        FilteredSpec {
            spec,
            outcome: RowFilterOutcome::TooLong,
        }
    }
}

fn column_lookup_keys<'a>(
    projection: &'a ChunkProjection,
    exact: &ColumnExactKeys,
    row_filter: &'a ScanRowFilter,
) -> BTreeSet<&'a str> {
    row_filter
        .keys()
        .into_iter()
        .chain(
            projection
                .column_candidates(exact)
                .into_iter()
                .flat_map(ProjectedKeys::iter),
        )
        .collect()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RowFilterOutcome {
    None,
    Materialized,
    PropertiesBlob,
    TooLong,
}

impl RowFilterOutcome {
    fn reading(row_filter: &ScanRowFilter, columns: &MaterializedColumns) -> Self {
        if columns.covers(row_filter.keys()) {
            Self::Materialized
        } else {
            Self::PropertiesBlob
        }
    }

    const fn as_str(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Materialized => "materialized",
            Self::PropertiesBlob => "properties_blob",
            Self::TooLong => "too_long",
        }
    }
}

/// Why a chunk's compare is not worth issuing, when it is not. Each case would spend a second
/// full-width ClickHouse query on a diff that can only agree, and the second query's right side is
/// an unbounded `person_distinct_id_overrides` aggregate over the whole team.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CompareSkip {
    /// The authoritative scan read no rows. Both arms build their FROM, JOIN and WHERE from the
    /// same [`ScanSpec`] and vary only in the SELECT list, so the wide arm has nothing to diff and
    /// nothing to skip. Only the unfenced overrides join could put rows on one side, which is a
    /// divergence with no projection defect behind it.
    NoRows,
    /// The authoritative scan was already wide, so `scan_sql` renders both arms identically and
    /// the verdict is `match` by construction.
    NotProjected,
}

impl CompareSkip {
    /// `None` when the compare is worth running.
    fn of(projection: &ChunkProjection, fold: FoldSummary) -> Option<Self> {
        match (fold.rows, projection) {
            (RowsSeen::None, _) => Some(Self::NoRows),
            (RowsSeen::Some, ChunkProjection::FullColumns) => Some(Self::NotProjected),
            (RowsSeen::Some, ChunkProjection::Projected(_)) => None,
        }
    }

    const fn as_str(self) -> &'static str {
        match self {
            Self::NoRows => "no_rows",
            Self::NotProjected => "not_projected",
        }
    }
}

/// Publish a chunk's compare verdict and the skips only its wide arm took, and hand back the diff
/// the caller logs. Free-standing because [`ChunkScanner::compare_scan`] needs a ClickHouse cursor
/// and this needs two tile vectors, which is what lets the verdict the backfill gate reads be
/// tested at all.
fn record_compare(
    team: Arc<str>,
    projected_tiles: &[SeedTile],
    legacy_tiles: &[SeedTile],
    projected_fold: FoldSummary,
    legacy_fold: FoldSummary,
) -> TileDiff {
    counter!(SHADOW_COMPARE_LEGACY_SKIPPED, "team_id" => team.clone())
        .increment(legacy_fold.legacy_only_skips(projected_fold));
    let diff = diff_tiles(projected_tiles, legacy_tiles);
    let result = if diff.is_match() { "match" } else { "diff" };
    counter!(SHADOW_COMPARE, "result" => result, "team_id" => team).increment(1);
    diff
}

/// Whether the cursor yielded anything, which is what separates a chunk with no matching history
/// from one that produced no tiles for another reason.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
enum RowsSeen {
    #[default]
    None,
    Some,
}

/// What a fold observed beyond the metrics it emitted.
///
/// `globals_parse_errors` is counted on every arm, metered or not. The two arms only treat a row
/// differently where the projection emptied a blob, so it is the difference between the arms'
/// counts that explains a divergence, never either count alone.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct FoldSummary {
    rows: RowsSeen,
    globals_parse_errors: u64,
}

impl FoldSummary {
    /// Count the outcomes the two arms can disagree on, which is the malformed-blob skip alone:
    /// both read the same rows with the same timestamps, and only the wide arm parses a blob the
    /// projection replaced with an empty literal.
    fn observe(&mut self, outcome: ScanEventOutcome) {
        if outcome == ScanEventOutcome::Skipped(ScanSkipReason::GlobalsParseError) {
            self.globals_parse_errors += 1;
        }
    }

    /// Rows only this wide fold skipped, against the projected fold of the same chunk. A blob the
    /// projection kept whole or rebuilt from keys fails the same parse on both arms, so the wide
    /// arm's own total explains nothing; the difference does.
    ///
    /// Saturating, because the arms resolve identity independently: an override landing between
    /// them can move a malformed row out of the scanned band and put the projected count ahead.
    fn legacy_only_skips(self, projected: Self) -> u64 {
        self.globals_parse_errors
            .saturating_sub(projected.globals_parse_errors)
    }
}

/// Drive the cursor into the accumulator until it is exhausted, cancelled, or fails. Returns rather
/// than metering, so the caller owns the single recording site.
async fn fold_cursor(
    cursor: &mut RowCursor<EventRow>,
    accumulator: &mut ChunkAccumulator,
    domain: &SeedDomain,
    team_id: TeamId,
    kind: ScanKind,
    lease_cancel: &CancellationToken,
    shutdown: &CancellationToken,
) -> Result<FoldSummary, ScanHalt> {
    let metered = kind == ScanKind::Behavioral;
    let mut summary = FoldSummary::default();
    loop {
        let row = tokio::select! {
            biased;
            _ = shutdown.cancelled() => return Err(ScanHalt::Cancelled(CancelCause::Shutdown)),
            _ = lease_cancel.cancelled() => return Err(ScanHalt::Cancelled(CancelCause::LeaseLost)),
            row = cursor.next() => row.map_err(ScanError::Cursor)?,
        };
        let Some(row) = row else {
            return Ok(summary);
        };
        summary.rows = RowsSeen::Some;
        // The per-row series describe the authoritative scan. A diagnostic re-scan walks the same
        // rows, so counting them again would double every reading a dashboard takes off these.
        if metered {
            counter!(ROWS_SCANNED).increment(1);
        }
        let outcome =
            fold_event(domain, accumulator, row_to_event(team_id, row)).map_err(ScanError::from)?;
        summary.observe(outcome);
        if metered {
            match outcome {
                ScanEventOutcome::Evaluated(stats) => record_evaluation(stats),
                ScanEventOutcome::Skipped(reason) => {
                    counter!(EVENTS_SKIPPED, "reason" => reason.as_str()).increment(1);
                }
            }
        }
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
                    .is_some_and(|bucket| {
                        bucket
                            .conditions
                            .iter()
                            .any(|hash| active.get(hash).is_some())
                    })
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

/// Why a scanned row produced no evaluation. The closed `reason` vocabulary on
/// `seeder_events_skipped_total`, which is why [`ScanSkipReason::ALL`] exists: a validation run
/// gated on `globals_parse_error` staying at zero needs the series present before it reads it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScanSkipReason {
    TimestampParse,
    DayMismatch,
    GlobalsParseError,
}

impl ScanSkipReason {
    pub const ALL: [Self; 3] = [
        Self::TimestampParse,
        Self::DayMismatch,
        Self::GlobalsParseError,
    ];

    pub const fn as_str(self) -> &'static str {
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

#[derive(Debug, thiserror::Error)]
pub enum ScanError {
    #[error("resolving the chunk seed domain")]
    Domain(#[from] ChunkDomainError),
    #[error("building ClickHouse scan cursor")]
    Query(#[source] clickhouse::error::Error),
    #[error("probing ClickHouse for ambiguous column values")]
    Probe(#[source] clickhouse::error::Error),
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
    use std::num::NonZeroU32;

    use super::super::sql::MAX_GET_QUERY_BYTES;
    use super::*;
    use crate::domain::{
        plan_days, BandSpec, BlobSource, Boundary, ClaimEpoch, ColumnPlan, ConditionHash, Lookback,
        PlanCaps, PropertiesOutcome, PropertiesSource, RunId, SChunkMs, ScalarColumn,
    };

    const HASH: &str = "aaaaaaaaaaaaaaaa";

    fn domain() -> SeedDomain {
        SeedDomain::new(1, UTC, SChunkMs(200_000_000)).unwrap()
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

    /// The same catalog, with the condition reading `properties` instead of `event`. A team whose
    /// conditions name no payload never parses one, so only this catalog can fail on a malformed
    /// `properties`.
    fn filters_reading_properties() -> TeamFilters {
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
                        // properties.x == "1"
                        "bytecode": ["_H", 1, 32, "1", 32, "x", 32, "properties", 1, 2, 11]
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
        let active = ActiveConditions::new([ConditionHash::parse(HASH).unwrap()]);
        let cases = [
            (
                filters(),
                row("not-a-timestamp"),
                ScanEventOutcome::Skipped(ScanSkipReason::TimestampParse),
            ),
            (
                filters(),
                row("1970-01-03 12:00:00.000000"),
                ScanEventOutcome::Skipped(ScanSkipReason::DayMismatch),
            ),
            (
                filters_reading_properties(),
                EventRow {
                    properties: "not-json".to_string(),
                    ..row("1970-01-02 12:00:00.000000")
                },
                ScanEventOutcome::Skipped(ScanSkipReason::GlobalsParseError),
            ),
        ];
        for (filters, row, expected) in cases {
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

    fn pageview_spec() -> ScanSpec {
        let ScanPlan::Scan(spec) = plan_scan(
            TeamId(2),
            &domain(),
            &EventNameSet::new(["$pageview".to_owned()]),
            BandSpec::new(0, 1).unwrap(),
        ) else {
            panic!("one event name on a one-day domain is a scan");
        };
        spec
    }

    fn key_names(count: usize) -> impl Iterator<Item = String> {
        (0..count).map(|index| format!("key_{index:02}"))
    }

    fn rebuilt(count: usize) -> ChunkProjection {
        ChunkProjection::Projected(ColumnPlan {
            uuid: ScalarColumn::Empty,
            elements_chain: ScalarColumn::Empty,
            properties: PropertiesSource::Blob(BlobSource::Keys(
                ProjectedKeys::new(key_names(count).collect()).expect("the counts are non-zero"),
            )),
            person_properties: BlobSource::Empty,
        })
    }

    /// `event == '$pageview' AND properties[key] == literal`.
    fn row_filter_on(key: &str, literal: &str) -> ScanRowFilter {
        use crate::domain::row_filter::test_catalog::{catalog, event_and_property, hash, Leaf};
        let leaves = [Leaf {
            cohort: 1,
            key: "$pageview",
            hash: HASH,
            body: event_and_property("$pageview", key, literal),
        }];
        let filters = catalog(&leaves);
        let conditions = [PinnedCondition {
            cohort_id: CohortId(1),
            hash: hash(HASH),
            event_name: "$pageview".to_owned(),
            lookback: Lookback::SlidingDays(7),
        }];
        ConditionAnalyses::build(&conditions, &filters).row_filter(
            &EventNameSet::new(["$pageview".to_owned()]),
            &filters,
            &ActiveConditions::new([hash(HASH)]),
        )
    }

    /// The projection metrics are the only report of what a chunk narrowed to, and a dashboard
    /// reads them by label. This pins the three sampling rules the recorder applies, which no test
    /// over the projection types themselves can see: a full blob takes no key sample at all, an
    /// unread one takes a `0`, and the outcome label follows the arm.
    ///
    /// The recorder here is a plain one, not the configured one — which ladder
    /// [`PROJECTION_KEYS`] renders under is `observability::metrics`'s question, and answering it
    /// twice would let the two answers drift.
    #[test]
    fn the_projection_metrics_report_each_blob_by_its_own_rule() {
        let scanner = ChunkScanner::new(
            ClickHouseClient::new(clickhouse::Client::default(), Default::default()),
            TeamAllowlist::Only(std::collections::HashSet::from([2, 3])),
            false,
        );
        let narrow = |projection: ChunkProjection,
                      exact: &ColumnExactKeys,
                      columns: &MaterializedColumns| {
            narrow_scan(
                pageview_spec(),
                projection.source_properties(exact, columns),
                &ScanRowFilter::default(),
                columns,
            )
        };
        let two_keys = ChunkProjection::Projected(ColumnPlan {
            uuid: ScalarColumn::Empty,
            elements_chain: ScalarColumn::Empty,
            properties: PropertiesSource::Blob(BlobSource::Keys(
                ProjectedKeys::new(BTreeSet::from([
                    "plan".to_string(),
                    "utm_source".to_string(),
                ]))
                .expect("two keys are not empty"),
            )),
            person_properties: BlobSource::Empty,
        });
        let url = ChunkProjection::Projected(ColumnPlan {
            uuid: ScalarColumn::Empty,
            elements_chain: ScalarColumn::Empty,
            properties: PropertiesSource::Blob(BlobSource::Keys(
                ProjectedKeys::new(BTreeSet::from(["$current_url".to_string()]))
                    .expect("one key is not empty"),
            )),
            person_properties: BlobSource::Full,
        });
        let url_column: MaterializedColumns =
            [("$current_url", "mat_$current_url")].into_iter().collect();
        let none = MaterializedColumns::default();
        let recorder = metrics_exporter_prometheus::PrometheusBuilder::new().build_recorder();
        let handle = recorder.handle();
        metrics::with_local_recorder(&recorder, || {
            scanner.record_narrowing(
                TeamId(2),
                &narrow(two_keys, &ColumnExactKeys::default(), &none),
            );
            scanner.record_narrowing(
                TeamId(2),
                &narrow(
                    ChunkProjection::FullColumns,
                    &ColumnExactKeys::default(),
                    &none,
                ),
            );
            scanner.record_narrowing(
                TeamId(3),
                &narrow(url, &ColumnExactKeys::exact(["$current_url"]), &url_column),
            );
        });
        let rendered = handle.render();

        for (team, source) in [(2, "rebuilt_inexact_key"), (2, "whole"), (3, "columns")] {
            assert!(
                rendered.contains(&format!(
                    "{SCAN_PROPERTIES_SOURCE}{{source=\"{source}\",team_id=\"{team}\"}} 1"
                )),
                "team {team} did not count its chunk under {source}:\n{rendered}"
            );
        }
        assert!(
            rendered.contains(&format!(
                "{SCAN_ROW_FILTER}{{outcome=\"none\",team_id=\"2\"}} 2"
            )),
            "a chunk without a row filter was not counted:\n{rendered}"
        );
        assert!(
            rendered.contains(&format!(
                "{PROJECTION_KEYS}_sum{{blob=\"properties\",team_id=\"3\"}} 1"
            )),
            "a column-backed key was not counted as a read key:\n{rendered}"
        );

        for outcome in ["projected", "full_columns"] {
            assert!(
                rendered.contains(&format!(
                    "{CHUNKS_PROJECTED}{{outcome=\"{outcome}\",team_id=\"2\"}} 1"
                )),
                "{outcome} chunk was not counted under its own label:\n{rendered}"
            );
        }
        // Two keys read, and one blob read at nothing — the reading the whole change exists for.
        assert!(
            rendered.contains(&format!(
                "{PROJECTION_KEYS}_sum{{blob=\"properties\",team_id=\"2\"}} 2"
            )),
            "the kept-key count is not the number of keys:\n{rendered}"
        );
        assert!(
            rendered.contains(&format!(
                "{PROJECTION_KEYS}_sum{{blob=\"person_properties\",team_id=\"2\"}} 0"
            )),
            "an unread blob did not record a zero:\n{rendered}"
        );
        // The wide chunk's blobs take no sample, so the two series hold one reading each rather
        // than a sentinel that a dashboard would average in as a real key count.
        for blob in ["properties", "person_properties"] {
            assert!(
                rendered.contains(&format!(
                    "{PROJECTION_KEYS}_count{{blob=\"{blob}\",team_id=\"2\"}} 1"
                )),
                "{blob} took a sample from the full-columns chunk:\n{rendered}"
            );
        }
    }

    /// The one number that separates a projection defect from the malformed-blob over-count
    /// `sql::render_blob` documents, and the only reading a fully-`Empty` projection can ever
    /// produce. It has to count the globals skip and nothing else.
    #[test]
    fn the_fold_summary_tallies_malformed_blobs_and_no_other_outcome() {
        let mut summary = FoldSummary::default();
        for outcome in [
            ScanEventOutcome::Evaluated(RecordStats::default()),
            ScanEventOutcome::Skipped(ScanSkipReason::TimestampParse),
            ScanEventOutcome::Skipped(ScanSkipReason::DayMismatch),
        ] {
            summary.observe(outcome);
        }
        assert_eq!(summary.globals_parse_errors, 0);

        summary.observe(ScanEventOutcome::Skipped(ScanSkipReason::GlobalsParseError));
        summary.observe(ScanEventOutcome::Skipped(ScanSkipReason::GlobalsParseError));
        assert_eq!(summary.globals_parse_errors, 2);
    }

    /// Publishing the wide arm's own total would attribute every shared parse failure to the
    /// projection, which is the misreading the counter exists to prevent.
    #[test]
    fn only_the_skips_the_projection_caused_reach_the_compare_counter() {
        let fold = |globals_parse_errors| FoldSummary {
            rows: RowsSeen::Some,
            globals_parse_errors,
        };
        // A blob kept whole or rebuilt from keys fails on both arms and explains no divergence.
        assert_eq!(fold(7).legacy_only_skips(fold(7)), 0);
        assert_eq!(fold(9).legacy_only_skips(fold(4)), 5);
        // Override drift can put the projected arm ahead; the count floors instead of wrapping.
        assert_eq!(fold(2).legacy_only_skips(fold(5)), 0);
    }

    fn tile(person: u128, count: u32) -> SeedTile {
        SeedTile::new(
            TeamId(2),
            Uuid::from_u128(person),
            ConditionHash::parse(HASH).unwrap(),
            NonZeroU32::new(count).expect("a tile's count is non-zero by construction"),
            20_000,
            SChunkMs(1),
            RunId(Uuid::nil()),
            ClaimEpoch(1),
        )
    }

    fn fold(rows: RowsSeen, globals_parse_errors: u64) -> FoldSummary {
        FoldSummary {
            rows,
            globals_parse_errors,
        }
    }

    /// Each skip removes a full-width ClickHouse query. Issuing one anyway is invisible in the
    /// output, since both arms agree on exactly these chunks, so nothing but this test says the
    /// gate still holds.
    #[test]
    fn the_compare_is_issued_only_where_the_two_arms_can_disagree() {
        let projected = ChunkProjection::Projected(ColumnPlan::full());
        let cases = [
            (
                fold(RowsSeen::None, 0),
                &projected,
                Some(CompareSkip::NoRows),
            ),
            (
                fold(RowsSeen::None, 0),
                &ChunkProjection::FullColumns,
                Some(CompareSkip::NoRows),
            ),
            (
                fold(RowsSeen::Some, 0),
                &ChunkProjection::FullColumns,
                Some(CompareSkip::NotProjected),
            ),
            (fold(RowsSeen::Some, 0), &projected, None),
        ];
        for (summary, projection, expected) in cases {
            assert_eq!(
                CompareSkip::of(projection, summary),
                expected,
                "{summary:?} on {}",
                projection.outcome()
            );
        }
    }

    /// The verdict the backfill gate reads. A change that inverts the match/diff choice, or drops
    /// the skip increment, produces a clean-looking signal from a run that diverged, on a rebuild
    /// no later run corrects.
    #[test]
    fn the_compare_verdict_and_the_skips_only_the_wide_arm_took_reach_prometheus() {
        let recorder = metrics_exporter_prometheus::PrometheusBuilder::new().build_recorder();
        let handle = recorder.handle();
        metrics::with_local_recorder(&recorder, || {
            let agreed = record_compare(
                Arc::from("2"),
                &[tile(1, 3)],
                &[tile(1, 3)],
                fold(RowsSeen::Some, 4),
                fold(RowsSeen::Some, 9),
            );
            assert!(agreed.is_match());
            let diverged = record_compare(
                Arc::from("3"),
                &[tile(1, 3)],
                &[tile(1, 5)],
                fold(RowsSeen::Some, 0),
                fold(RowsSeen::Some, 0),
            );
            assert_eq!(diverged.count_differs, 1);
        });
        let rendered = handle.render();

        // Each verdict is pinned to the team whose arms produced it. One shared label would let a
        // swapped match/diff choice render the very same two series.
        for (team, verdict) in [("2", "match"), ("3", "diff")] {
            assert!(
                rendered.contains(&format!(
                    "{SHADOW_COMPARE}{{result=\"{verdict}\",team_id=\"{team}\"}} 1"
                )),
                "team {team} did not publish {verdict}:\n{rendered}"
            );
        }
        // 9 wide skips against 4 projected ones: only the 5 the projection caused are published,
        // and the second call adds nothing, which is the "at zero as well" claim.
        assert!(
            rendered.contains(&format!(
                "{SHADOW_COMPARE_LEGACY_SKIPPED}{{team_id=\"2\"}} 5"
            )),
            "the published skip count is not the difference between the arms:\n{rendered}"
        );
    }

    #[test]
    fn the_lookup_covers_row_filter_keys_and_projected_keys_that_can_all_be_columns() {
        let row_filter = row_filter_on("$feature_flag", "my-flag");
        let all_exact = ColumnExactKeys::exact(key_names(2));
        let one_exact = ColumnExactKeys::exact(key_names(1));
        for (projection, exact, expected) in [
            (
                rebuilt(2),
                &all_exact,
                &["$feature_flag", "key_00", "key_01"][..],
            ),
            (rebuilt(2), &one_exact, &["$feature_flag"][..]),
            (
                ChunkProjection::FullColumns,
                &all_exact,
                &["$feature_flag"][..],
            ),
        ] {
            assert_eq!(
                column_lookup_keys(&projection, exact, &row_filter),
                expected.iter().copied().collect::<BTreeSet<_>>(),
                "{projection:?}"
            );
        }
    }

    #[test]
    fn the_column_form_keeps_the_get_budget_and_the_row_filter_gives_way() {
        let spec = pageview_spec();
        let exact = ColumnExactKeys::exact(key_names(6));
        let columns: MaterializedColumns = key_names(6)
            .map(|key| (key.clone(), format!("mat_{key}")))
            .collect();
        let PropertiesSourcing::Upgradable(upgrade) =
            rebuilt(6).source_properties(&exact, &columns)
        else {
            panic!("six exact keys with columns can be read from columns");
        };
        let column_form = upgrade.column_form();
        let filter_fits_beside = |projection: &ChunkProjection, literal_len: usize| {
            let row_filter = row_filter_on("key_00", &"x".repeat(literal_len));
            fit_row_filter(spec.clone(), &row_filter, &columns, projection).outcome
                != RowFilterOutcome::TooLong
        };
        // The longest filter that still fits beside the rebuild.
        let lengths = (0..MAX_GET_QUERY_BYTES).collect::<Vec<_>>();
        let literal_len = lengths
            .partition_point(|len| filter_fits_beside(&rebuilt(6), *len))
            .checked_sub(1)
            .expect("even an empty filter literal does not fit beside the rebuild");
        assert!(
            !filter_fits_beside(&column_form, literal_len),
            "the column form is no longer longer than the rebuild, so nothing competes"
        );

        let near_the_limit = narrow_scan(
            spec.clone(),
            rebuilt(6).source_properties(&exact, &columns),
            &row_filter_on("key_00", &"x".repeat(literal_len)),
            &columns,
        );
        assert_eq!(near_the_limit.sourced.outcome(), PropertiesOutcome::Columns);
        assert_eq!(near_the_limit.sourced.projection(), &column_form);
        assert_eq!(near_the_limit.filtered.outcome, RowFilterOutcome::TooLong);
        assert_eq!(near_the_limit.filtered.spec, spec);

        let short = narrow_scan(
            spec.clone(),
            rebuilt(6).source_properties(&exact, &columns),
            &row_filter_on("key_00", "x"),
            &columns,
        );
        assert_eq!(short.sourced.outcome(), PropertiesOutcome::Columns);
        assert_eq!(short.filtered.outcome, RowFilterOutcome::Materialized);
        assert_ne!(short.filtered.spec, spec, "the row filter was dropped");
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
    /// plan was anchored. Every planned day still inside the wall-clock window must stay admitted
    /// (the days before the boundary feed membership the live replay cannot reconstruct, and the
    /// boundary day holds events from before the replay resumed); days that slid out of every
    /// window are skipped, matching the consumer's drop-below-window apply rule.
    #[test]
    fn dr_scan_admits_every_planned_day_still_inside_the_window() {
        let hash = ConditionHash::parse(HASH).unwrap();
        let conditions = [PinnedCondition {
            cohort_id: CohortId(1),
            hash,
            event_name: "purchase".to_string(),
            lookback: Lookback::SlidingDays(7),
        }];
        let boundary = Boundary::new(UtcMillis::new(100 * 86_400_000), UTC);
        let planned = plan_days(&conditions, boundary, &PlanCaps::default());
        assert_eq!(planned, BTreeSet::from_iter(93..=100));

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
        assert_eq!(admitted_at(100), (93..=100).collect::<Vec<_>>());
        // Scanned three days later (DR shape): the window is [96, 103]; days 93-95 can no longer
        // affect any evaluation and are skipped, days 96-100 are still scanned.
        assert_eq!(admitted_at(103), (96..=100).collect::<Vec<_>>());
        // Boundary day older than the window: live replay from the boundary covers the whole
        // window, so the seed correctly has nothing left to contribute.
        assert_eq!(admitted_at(108), Vec::<DayIdx>::new());
    }
}
