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
    conditions_active_on, diff_tiles, table_scans, ActiveConditions, AggregateError, CancelCause,
    ChunkAccumulator, ChunkDomainError, ChunkProjection, ChunkSpec, ClaimedChunk, ColumnExactKeys,
    ColumnUpgrade, ConditionAnalyses, DayIdx, Halted, MaterializedColumns, PinnedCondition,
    PinnedRun, ProjectedKeys, PropertiesSourcing, RecordOutcome, RecordStats, ScanRowFilter,
    ScanTable, ScanVolume, ScannedChunk, SeedDomain, SeedTile, SourcedProjection, TableScan,
    TileDiff, UtcMillis,
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
            || Utc::now().timestamp_millis(),
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
        clock: fn() -> i64,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<ScannedChunk, Halted<ClaimedChunk, ScanError>> {
        match self
            .scan_tiles(&chunk, run, analyses, clock, lease_cancel, shutdown)
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
        clock: fn() -> i64,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<(Vec<SeedTile>, ScanVolume), ScanHalt> {
        let timer = MetricTimer::start(CHUNK_SCAN_DURATION_SECONDS);
        let now_ms = clock();
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
        let planned = table_scans(run, &active)
            .into_iter()
            .filter_map(|(table, scan)| {
                match plan_scan(spec.team_id, &domain, &scan.event_names, spec.band, table) {
                    ScanPlan::Scan(scan_spec) => Some((table, scan, scan_spec)),
                    ScanPlan::Vacuous => None,
                }
            })
            .collect::<Vec<_>>();
        if planned.is_empty() {
            counter!(CHUNKS_VACUOUS, "reason" => "empty_scan").increment(1);
            return Ok((Vec::new(), ScanVolume::default()));
        }
        // The TTL may already have dropped some of this day's rows, so the tiles would undercount
        // and the run would still complete.
        let tables = planned.iter().map(|(table, ..)| *table).collect::<Vec<_>>();
        check_retention(&tables, &domain, spec.day, now_ms)?;
        let comment = ScanLogComment::BehavioralChunk {
            spec,
            cohort_id: run.sole_cohort_id(),
        };
        let mut queries = Vec::with_capacity(planned.len());
        for (table, scan, scan_spec) in planned {
            queries.push(
                self.narrow_table_query(
                    run,
                    analyses,
                    table,
                    &scan,
                    scan_spec,
                    comment,
                    lease_cancel,
                    shutdown,
                )
                .await?,
            );
        }

        let (tiles, volume, projected_fold) = self
            .scan_tables(
                spec,
                run,
                &domain,
                &active,
                &queries,
                ScanKind::Behavioral,
                comment,
                lease_cancel,
                shutdown,
            )
            .await?;
        // A query can run for hours, so the TTL can reach the day while the chunk scans.
        check_retention(&tables, &domain, spec.day, clock())?;
        // Closed before the diagnostic arm, which must not lengthen the chunk's reported scan.
        drop(timer);

        if self.shadow_compare {
            match CompareSkip::of(
                queries.iter().map(|query| &query.projection),
                projected_fold,
            ) {
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
                        &queries,
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

    /// Narrow one table's scan to the conditions its rows can reach: its projection, its row
    /// filter, and the materialized columns of its table.
    #[allow(clippy::too_many_arguments)]
    async fn narrow_table_query(
        &self,
        run: &PinnedRun,
        analyses: &ConditionAnalyses,
        table: ScanTable,
        scan: &TableScan,
        scan_spec: ScanSpec,
        comment: ScanLogComment,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<TableQuery, ScanHalt> {
        let projection = analyses.projection(&scan.active);
        let exact = analyses.column_exact_keys(&scan.active);
        let row_filter = analyses.row_filter(&scan.event_names, &run.filters, &scan.active);
        let columns = self
            .lookup_columns(table, &column_lookup_keys(&projection, &exact, &row_filter))
            .await;
        let sourcing = match projection.source_properties(&exact, &columns) {
            PropertiesSourcing::Upgradable(upgrade) => {
                self.probe_ambiguous_values(&scan_spec, upgrade, comment, lease_cancel, shutdown)
                    .await?
            }
            decided @ PropertiesSourcing::Decided(_) => decided,
        };
        let narrowed = narrow_scan(scan_spec, sourcing, &row_filter, &columns);
        self.record_narrowing(run.team_id, table, &narrowed);
        Ok(TableQuery {
            spec: narrowed.filtered.spec,
            projection: narrowed.sourced.into_projection(),
        })
    }

    /// One rendering of this chunk's scan: build a cursor from [`scan_sql`] for each table, fold
    /// them all through one fresh accumulator, meter the moved bytes under `kind`, and return the
    /// sorted tiles. One accumulator keeps a tile key from splitting across two tile sets.
    ///
    /// `kind` and `comment` co-vary at the two call sites. The per-row and per-chunk fold metrics
    /// are emitted for the authoritative [`ScanKind::Behavioral`] arm only, so a diagnostic
    /// re-scan of the same rows never doubles a throughput series.
    #[allow(clippy::too_many_arguments)]
    async fn scan_tables(
        &self,
        spec: ChunkSpec,
        run: &PinnedRun,
        domain: &SeedDomain,
        active: &ActiveConditions,
        queries: &[TableQuery],
        kind: ScanKind,
        comment: ScanLogComment,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<(Vec<SeedTile>, ScanVolume, FoldSummary), ScanHalt> {
        let mut accumulator =
            ChunkAccumulator::new(run.team_id, &run.filters, active).map_err(ScanError::from)?;
        let mut volume = ScanVolume::default();
        let mut summary = FoldSummary::default();
        for query in queries {
            let mut cursor = self
                .client
                .query(&scan_sql(&query.spec, &query.projection))
                .with_option(LOG_COMMENT_OPTION, comment.to_string())
                .fetch::<EventRow>()
                .map_err(ScanError::Query)?;
            // Every way out of the fold funnels back here, so the volume is metered once whether
            // the scan finished, was cancelled, or failed mid-stream.
            let folded = fold_cursor(
                &mut cursor,
                &mut accumulator,
                &mut summary,
                domain,
                run.team_id,
                kind,
                lease_cancel,
                shutdown,
            )
            .await;
            volume = volume + scan_volume::observe(kind, &cursor);
            folded?;
        }
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
        queries: &[TableQuery],
        projected_tiles: &[SeedTile],
        projected_fold: FoldSummary,
        lease_cancel: &CancellationToken,
        shutdown: &CancellationToken,
    ) -> Result<(), ScanHalt> {
        let team = team_label(&self.allowlist, run.team_id);
        // Spans the re-scan, its fold, and the diff. Records on every exit, so a cancelled or
        // failed compare still reports the time it held the chunk's slot and lease.
        let _timer = MetricTimer::start(SHADOW_COMPARE_DURATION_SECONDS);
        let wide: Vec<TableQuery> = queries
            .iter()
            .map(|query| TableQuery {
                spec: query.spec.clone(),
                projection: ChunkProjection::FullColumns,
            })
            .collect();
        let (legacy_tiles, legacy_fold) = match self
            .scan_tables(
                spec,
                run,
                domain,
                active,
                &wide,
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
    async fn lookup_columns(&self, table: ScanTable, keys: &BTreeSet<&str>) -> MaterializedColumns {
        match tokio::time::timeout(
            MATERIALIZED_LOOKUP_TIMEOUT,
            MaterializedColumns::lookup(&self.client, table, keys),
        )
        .await
        {
            Ok(Ok(columns)) => columns,
            Ok(Err(error)) => {
                warn!(table = table.as_str(), error = ?error, "materialized column lookup failed; the scan reads the properties blob");
                MaterializedColumns::default()
            }
            Err(_) => {
                warn!(
                    table = table.as_str(),
                    "materialized column lookup timed out; the scan reads the properties blob"
                );
                MaterializedColumns::default()
            }
        }
    }

    /// Publish what this chunk's scan narrowed to, so a team that stops projecting is visible
    /// before its scan cost is.
    fn record_narrowing(&self, team_id: TeamId, table: ScanTable, narrowed: &NarrowedScan) {
        let team = team_label(&self.allowlist, team_id);
        let table = table.as_str();
        let projection = narrowed.sourced.projection();
        counter!(
            CHUNKS_PROJECTED,
            "outcome" => projection.outcome(),
            "table" => table,
            "team_id" => team.clone(),
        )
        .increment(1);
        counter!(
            SCAN_PROPERTIES_SOURCE,
            "source" => narrowed.sourced.outcome().as_str(),
            "table" => table,
            "team_id" => team.clone(),
        )
        .increment(1);
        counter!(
            SCAN_ROW_FILTER,
            "outcome" => narrowed.filtered.outcome.as_str(),
            "table" => table,
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
                histogram!(
                    PROJECTION_KEYS,
                    "blob" => blob,
                    "table" => table,
                    "team_id" => team.clone(),
                )
                .record(keys as f64);
            }
        }
    }
}

/// One table's narrowed scan within a chunk.
#[derive(Debug)]
struct TableQuery {
    spec: ScanSpec,
    projection: ChunkProjection,
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
    /// The authoritative scan was already wide on every table, so `scan_sql` renders both arms
    /// identically and the verdict is `match` by construction.
    NotProjected,
}

impl CompareSkip {
    /// `None` when the compare is worth running. `projections` holds one per table the chunk read.
    fn of<'a>(
        projections: impl IntoIterator<Item = &'a ChunkProjection>,
        fold: FoldSummary,
    ) -> Option<Self> {
        if fold.rows == RowsSeen::None {
            return Some(Self::NoRows);
        }
        let projected = projections
            .into_iter()
            .any(|projection| matches!(projection, ChunkProjection::Projected(_)));
        (!projected).then_some(Self::NotProjected)
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
#[allow(clippy::too_many_arguments)]
async fn fold_cursor(
    cursor: &mut RowCursor<EventRow>,
    accumulator: &mut ChunkAccumulator,
    summary: &mut FoldSummary,
    domain: &SeedDomain,
    team_id: TeamId,
    kind: ScanKind,
    lease_cancel: &CancellationToken,
    shutdown: &CancellationToken,
) -> Result<(), ScanHalt> {
    let metered = kind == ScanKind::Behavioral;
    loop {
        let row = tokio::select! {
            biased;
            _ = shutdown.cancelled() => return Err(ScanHalt::Cancelled(CancelCause::Shutdown)),
            _ = lease_cancel.cancelled() => return Err(ScanHalt::Cancelled(CancelCause::LeaseLost)),
            row = cursor.next() => row.map_err(ScanError::Cursor)?,
        };
        let Some(row) = row else {
            return Ok(());
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

fn check_retention(
    tables: &[ScanTable],
    domain: &SeedDomain,
    day: DayIdx,
    now_ms: i64,
) -> Result<(), ScanError> {
    match tables
        .iter()
        .find(|table| table.past_retention(domain, now_ms))
    {
        Some(expired) => Err(ScanError::PastRetention {
            table: expired.as_str(),
            day,
        }),
        None => Ok(()),
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
    #[error("day {day} is past the retention of {table}, so the scan could miss rows")]
    PastRetention { table: &'static str, day: DayIdx },
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
    use crate::domain::pinned::test_runs::{run_with, RunLeaf};
    use crate::domain::{
        plan_days, BandSpec, BlobSource, Boundary, ClaimEpoch, ColumnPlan, ConditionHash,
        EventNameSet, Lookback, PlanCaps, PropertiesOutcome, PropertiesSource, RunId, SChunkMs,
        ScalarColumn,
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
            ScanTable::Events,
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
    /// unread one takes a `0`, and the outcome label follows the arm. Each series also names the
    /// table its query scanned, which is how a rollout tells the two tables apart.
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
                ScanTable::Events,
                &narrow(two_keys, &ColumnExactKeys::default(), &none),
            );
            scanner.record_narrowing(
                TeamId(2),
                ScanTable::Events,
                &narrow(
                    ChunkProjection::FullColumns,
                    &ColumnExactKeys::default(),
                    &none,
                ),
            );
            scanner.record_narrowing(
                TeamId(3),
                ScanTable::Events,
                &narrow(url, &ColumnExactKeys::exact(["$current_url"]), &url_column),
            );
            scanner.record_narrowing(
                TeamId(2),
                ScanTable::FlagEvaluations,
                &narrow(
                    ChunkProjection::FullColumns,
                    &ColumnExactKeys::default(),
                    &none,
                ),
            );
        });
        let rendered = handle.render();

        for (team, source) in [(2, "rebuilt_inexact_key"), (2, "whole"), (3, "columns")] {
            assert!(
                rendered.contains(&format!(
                    "{SCAN_PROPERTIES_SOURCE}{{source=\"{source}\",table=\"events\",team_id=\"{team}\"}} 1"
                )),
                "team {team} did not count its chunk under {source}:\n{rendered}"
            );
        }
        assert!(
            rendered.contains(&format!(
                "{SCAN_ROW_FILTER}{{outcome=\"none\",table=\"events\",team_id=\"2\"}} 2"
            )),
            "a chunk without a row filter was not counted:\n{rendered}"
        );
        assert!(
            rendered.contains(&format!(
                "{PROJECTION_KEYS}_sum{{blob=\"properties\",table=\"events\",team_id=\"3\"}} 1"
            )),
            "a column-backed key was not counted as a read key:\n{rendered}"
        );

        for outcome in ["projected", "full_columns"] {
            assert!(
                rendered.contains(&format!(
                    "{CHUNKS_PROJECTED}{{outcome=\"{outcome}\",table=\"events\",team_id=\"2\"}} 1"
                )),
                "{outcome} chunk was not counted under its own label:\n{rendered}"
            );
        }
        // Two keys read, and one blob read at nothing — the reading the whole change exists for.
        assert!(
            rendered.contains(&format!(
                "{PROJECTION_KEYS}_sum{{blob=\"properties\",table=\"events\",team_id=\"2\"}} 2"
            )),
            "the kept-key count is not the number of keys:\n{rendered}"
        );
        assert!(
            rendered.contains(&format!(
                "{PROJECTION_KEYS}_sum{{blob=\"person_properties\",table=\"events\",team_id=\"2\"}} 0"
            )),
            "an unread blob did not record a zero:\n{rendered}"
        );
        // The wide chunk's blobs take no sample, so the two series hold one reading each rather
        // than a sentinel that a dashboard would average in as a real key count.
        for blob in ["properties", "person_properties"] {
            assert!(
                rendered.contains(&format!(
                    "{PROJECTION_KEYS}_count{{blob=\"{blob}\",table=\"events\",team_id=\"2\"}} 1"
                )),
                "{blob} took a sample from the full-columns chunk:\n{rendered}"
            );
        }
        // The `flag_evaluations` query's increments carry `table="flag_evaluations"`, so they leave
        // the events series above unchanged.
        for series in [
            format!("{CHUNKS_PROJECTED}{{outcome=\"full_columns\",table=\"flag_evaluations\",team_id=\"2\"}} 1"),
            format!("{SCAN_PROPERTIES_SOURCE}{{source=\"whole\",table=\"flag_evaluations\",team_id=\"2\"}} 1"),
            format!("{SCAN_ROW_FILTER}{{outcome=\"none\",table=\"flag_evaluations\",team_id=\"2\"}} 1"),
        ] {
            assert!(rendered.contains(&series), "missing {series}:\n{rendered}");
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
        let wide = ChunkProjection::FullColumns;
        // A chunk that reads two tables projects each on its own, so one wide table must not skip
        // the compare of the other.
        let cases = [
            (
                fold(RowsSeen::None, 0),
                vec![&projected],
                Some(CompareSkip::NoRows),
            ),
            (
                fold(RowsSeen::None, 0),
                vec![&wide],
                Some(CompareSkip::NoRows),
            ),
            (
                fold(RowsSeen::Some, 0),
                vec![&wide],
                Some(CompareSkip::NotProjected),
            ),
            (fold(RowsSeen::Some, 0), vec![&projected], None),
            (
                fold(RowsSeen::Some, 0),
                vec![&wide, &wide],
                Some(CompareSkip::NotProjected),
            ),
            (fold(RowsSeen::Some, 0), vec![&wide, &projected], None),
            (fold(RowsSeen::Some, 0), vec![&projected, &wide], None),
        ];
        for (summary, projections, expected) in cases {
            assert_eq!(
                CompareSkip::of(projections.iter().copied(), summary),
                expected,
                "{summary:?} on {:?}",
                projections
                    .iter()
                    .map(|projection| projection.outcome())
                    .collect::<Vec<_>>()
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

    const PAGEVIEW_HASH: &str = "pageview00000000";
    const FLAG_CALL_HASH: &str = "flagcall00000000";
    /// This instant falls on day 101, so a day-1 chunk sits past the `flag_evaluations` TTL.
    const PAST_TTL_MS: i64 = 101 * 86_400_000;

    fn pageview_leaf() -> RunLeaf<'static> {
        use crate::domain::row_filter::test_catalog::event_is;

        RunLeaf {
            cohort_id: 1,
            hash: PAGEVIEW_HASH,
            event: "$pageview",
            body: event_is("$pageview"),
        }
    }

    fn mixed_run(window_days: u32) -> PinnedRun {
        use crate::domain::row_filter::test_catalog::event_and_property;

        run_with(
            ScanTable::FlagEvaluations,
            window_days,
            &[
                pageview_leaf(),
                RunLeaf {
                    cohort_id: 1,
                    hash: FLAG_CALL_HASH,
                    event: "$feature_flag_called",
                    body: event_and_property("$feature_flag_called", "$feature_flag", "my-flag"),
                },
            ],
        )
    }

    async fn scan_day_one(
        scanner: &ChunkScanner,
        run: &PinnedRun,
        clock: fn() -> i64,
    ) -> Result<ScannedChunk, Halted<ClaimedChunk, ScanError>> {
        use crate::domain::{AttemptCount, ChunkId, ChunkLease};

        let chunk = ClaimedChunk::new(ChunkSpec {
            lease: ChunkLease::new(ChunkId(Uuid::nil()), run.run_id, ClaimEpoch(1)),
            team_id: run.team_id,
            day: 1,
            band: BandSpec::new(0, 1).unwrap(),
            s_chunk: SChunkMs(200_000_000),
            person_range: None,
            attempt: AttemptCount::new(1),
        });
        let never = CancellationToken::new();
        scanner
            .scan_at(
                chunk,
                run,
                &ConditionAnalyses::build(&run.conditions, &run.filters),
                clock,
                &never,
                &never,
            )
            .await
    }

    fn failure_of(result: Result<ScannedChunk, Halted<ClaimedChunk, ScanError>>) -> ScanError {
        use crate::domain::HaltReason;

        match result {
            Ok(scanned) => panic!("the chunk scanned {} tiles", scanned.tiles().len()),
            Err(Halted {
                reason: HaltReason::Cancelled(cause),
                ..
            }) => panic!("the chunk was cancelled: {cause:?}"),
            Err(Halted {
                reason: HaltReason::Failed(error),
                ..
            }) => error,
        }
    }

    /// The `flag_evaluations` query comes second, so a check of the first query alone passes the
    /// chunk. The refusal comes before any query, so the client needs no server.
    #[tokio::test]
    async fn a_chunk_whose_flag_calls_are_past_retention_fails_rather_than_scanning() {
        let scanner = ChunkScanner::new(
            ClickHouseClient::new(clickhouse::Client::default(), Default::default()),
            TeamAllowlist::All,
            false,
        );
        let run = mixed_run(120);

        let error = failure_of(scan_day_one(&scanner, &run, || PAST_TTL_MS).await);

        assert!(
            matches!(error, ScanError::PastRetention { .. }),
            "the chunk failed for another reason: {error:?}"
        );
    }

    /// The fold reads rows only from a ClickHouse cursor, so only a live server shows which rows
    /// reach the chunk's tiles.
    #[cfg(feature = "ch-test-support")]
    mod live {
        use std::collections::HashSet;
        use std::sync::atomic::{AtomicUsize, Ordering};

        use envconfig::Envconfig;

        use super::*;
        use crate::clickhouse::client::build_client;
        use crate::config::Config;

        const FLAG_KEY_EXPRESSION: &str =
            r#"replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag'), '^"|"$', '')"#;

        const FLAG_EVALUATIONS_DDL: &str =
            include_str!("../../tests/fixtures/flag_evaluations.sql");

        fn connect(database: Option<&str>) -> ClickHouseClient {
            let mut config =
                Config::init_from_env().expect("the seeder config falls back to its defaults");
            if let Some(database) = database {
                config.clickhouse_database = database.to_owned();
            }
            build_client(&config).expect("the default ClickHouse client builds")
        }

        /// This instant falls on day 2, so a day-1 chunk sits inside a window of a week or more.
        const NOW_MS: i64 = 200_000_000;

        fn person(id: u128) -> Uuid {
            Uuid::from_u128(id)
        }

        fn scanned_of(
            result: Result<ScannedChunk, Halted<ClaimedChunk, ScanError>>,
        ) -> ScannedChunk {
            match result {
                Ok(scanned) => scanned,
                failed => panic!("{:?}", failure_of(failed)),
            }
        }

        fn tile_counts(scanned: &ScannedChunk) -> Vec<(Uuid, ConditionHash, u32)> {
            scanned
                .tiles()
                .iter()
                .map(|tile| (tile.person_id(), tile.condition_hash(), tile.count()))
                .collect()
        }

        /// The flag call by person 4 in `events` must not count in a run pinned to
        /// `flag_evaluations`. Each table pair backs `$feature_flag` with a column of its own name,
        /// so a query that reads the other pair's column fails. The flag call by person 5 holds a
        /// blob that is not JSON, so its `flag_key` is empty. The row filter admits an empty
        /// column value, so every scan reads the row. The row matches no condition. A scan that
        /// builds `properties` from `flag_key` never parses the blob. A scan that selects the
        /// whole blob fails to parse it and skips the row.
        async fn mixed_chunk_database(database: &str) -> ClickHouseClient {
            let events_columns = "uuid UUID, event String, properties String, \
                timestamp DateTime64(6, 'UTC'), distinct_id String, person_id UUID, \
                person_properties String, elements_chain String, team_id Int64, \
                inserted_at Nullable(DateTime64(6, 'UTC')), _timestamp DateTime";
            let event_row = |uuid: u128, event: &str, properties: &str, person_id: u128| {
                format!(
                    "(toUUID('{}'), '{event}', '{properties}', toDateTime64(100000, 6, 'UTC'), \
                     'distinct-{person_id}', toUUID('{}'), '{{}}', '', 2, toDateTime(100000, 'UTC'))",
                    person(uuid),
                    person(person_id),
                )
            };
            let flag_row = |uuid: u128, properties: &str, person_id: u128| {
                format!(
                    "(toUUID('{}'), '$feature_flag_called', '{properties}', \
                     toDateTime64(100000, 6, 'UTC'), 2, 'distinct-{person_id}', toUUID('{}'), \
                     toDateTime(100000, 'UTC'))",
                    person(uuid),
                    person(person_id),
                )
            };
            let my_flag = r#"{"$feature_flag":"my-flag"}"#;
            let admin = connect(None);
            let flag_evaluations_tables = FLAG_EVALUATIONS_DDL
                .split(';')
                .map(str::trim)
                .filter(|statement| !statement.is_empty())
                .map(|statement| statement.replace("{database}", database));
            let statements = [
                format!("DROP DATABASE IF EXISTS {database}"),
                format!("CREATE DATABASE {database}"),
                format!(
                    "CREATE TABLE {database}.sharded_events ({events_columns}, \
                     `mat_$feature_flag` String DEFAULT {FLAG_KEY_EXPRESSION}) \
                     ENGINE = MergeTree ORDER BY (team_id, toDate(timestamp), event)"
                ),
                format!(
                    "CREATE TABLE {database}.events ({events_columns}, `mat_$feature_flag` String) \
                     ENGINE = Merge('{database}', '^sharded_events$')"
                ),
                format!(
                    "CREATE TABLE {database}.person_distinct_id_overrides (\
                        team_id Int64, distinct_id String, person_id UUID, is_deleted Int8, version Int64\
                     ) ENGINE = MergeTree ORDER BY (team_id, distinct_id)"
                ),
            ]
            .into_iter()
            .chain(flag_evaluations_tables)
            .chain([
                format!(
                    "INSERT INTO {database}.sharded_events (uuid, event, properties, timestamp, \
                     distinct_id, person_id, person_properties, elements_chain, team_id, _timestamp) \
                     VALUES {}, {}",
                    event_row(10, "$pageview", "{}", 2),
                    event_row(11, "$feature_flag_called", my_flag, 4),
                ),
                format!(
                    "INSERT INTO {database}.sharded_flag_evaluations (uuid, event, properties, \
                     timestamp, team_id, distinct_id, person_id, _timestamp) VALUES {}, {}, {}, {}, {}",
                    flag_row(20, my_flag, 1),
                    flag_row(21, my_flag, 3),
                    flag_row(22, my_flag, 3),
                    flag_row(23, r#"{"$feature_flag":"other-flag"}"#, 1),
                    flag_row(24, "not json", 5),
                ),
            ]);
            for statement in statements {
                admin
                    .query(&statement)
                    .execute()
                    .await
                    .unwrap_or_else(|error| panic!("{error}\n{statement}"));
            }
            connect(Some(database))
        }

        fn scanner(client: ClickHouseClient, shadow_compare: bool) -> ChunkScanner {
            ChunkScanner::new(
                client,
                TeamAllowlist::Only(HashSet::from([2])),
                shadow_compare,
            )
        }

        /// Tiles sort by person. The expected order interleaves the tables. Two tile sets joined
        /// end to end would put person 2 out of place whichever table came first.
        #[tokio::test]
        async fn a_mixed_chunk_folds_rows_from_both_tables_into_one_tile_set() {
            let client = mixed_chunk_database("seeder_scanner_mixed_chunk").await;
            let run = mixed_run(7);

            let scanned = scanned_of(scan_day_one(&scanner(client, false), &run, || NOW_MS).await);

            let flag_call = ConditionHash::parse(FLAG_CALL_HASH).unwrap();
            let pageview = ConditionHash::parse(PAGEVIEW_HASH).unwrap();
            assert_eq!(
                tile_counts(&scanned),
                vec![
                    (person(1), flag_call, 1),
                    (person(2), pageview, 1),
                    (person(3), flag_call, 2),
                ]
            );
        }

        #[tokio::test]
        async fn a_flag_evaluations_run_scans_an_events_only_chunk_past_the_ttl() {
            let client = mixed_chunk_database("seeder_scanner_events_past_ttl").await;
            let run = run_with(ScanTable::FlagEvaluations, 120, &[pageview_leaf()]);

            let scanned =
                scanned_of(scan_day_one(&scanner(client, false), &run, || PAST_TTL_MS).await);

            let pageview = ConditionHash::parse(PAGEVIEW_HASH).unwrap();
            assert_eq!(tile_counts(&scanned), vec![(person(2), pageview, 1)]);
        }

        #[tokio::test]
        async fn a_chunk_that_crosses_the_ttl_while_it_scans_fails() {
            static CALLS: AtomicUsize = AtomicUsize::new(0);
            fn crosses_the_ttl() -> i64 {
                match CALLS.fetch_add(1, Ordering::SeqCst) {
                    0 => NOW_MS,
                    _ => PAST_TTL_MS,
                }
            }
            let recorder = metrics_exporter_prometheus::PrometheusBuilder::new().build_recorder();
            let handle = recorder.handle();
            let _recorder = metrics::set_default_local_recorder(&recorder);
            let client = mixed_chunk_database("seeder_scanner_crosses_ttl").await;
            let run = mixed_run(120);

            let error =
                failure_of(scan_day_one(&scanner(client, false), &run, crosses_the_ttl).await);

            assert!(
                matches!(error, ScanError::PastRetention { .. }),
                "the chunk failed for another reason: {error:?}"
            );
            assert!(
                handle.render().contains(ROWS_SCANNED),
                "the chunk failed before its queries read a row"
            );
        }

        /// The backfill gate reads this verdict. A compare that re-scanned one table, or read flag
        /// calls from `events`, would report a diff on every mixed chunk. A compare that sent the
        /// narrow projection would match as well, because both arms would then send the same
        /// query. The projected arm reads person 5's flag call through `flag_key` and keeps it.
        /// The wide arm skips it. The skip count is therefore 1 only when the compare sends the
        /// wide query.
        #[tokio::test]
        async fn the_shadow_compare_of_a_mixed_chunk_rescans_both_tables() {
            let recorder = metrics_exporter_prometheus::PrometheusBuilder::new().build_recorder();
            let handle = recorder.handle();
            let _recorder = metrics::set_default_local_recorder(&recorder);
            let client = mixed_chunk_database("seeder_scanner_mixed_compare").await;
            let run = mixed_run(7);

            scanned_of(scan_day_one(&scanner(client, true), &run, || NOW_MS).await);
            let rendered = handle.render();

            assert!(
                rendered.contains(&format!(
                    "{SHADOW_COMPARE}{{result=\"match\",team_id=\"2\"}} 1"
                )),
                "the mixed chunk's compare did not match:\n{rendered}"
            );
            assert!(
                rendered.contains(&format!(
                    "{SCAN_PROPERTIES_SOURCE}{{source=\"columns\",table=\"flag_evaluations\",team_id=\"2\"}} 1"
                )),
                "the projected arm did not read `properties` from `flag_key`, so it parses person \
                 5's blob too:\n{rendered}"
            );
            assert!(
                rendered.contains(&format!(
                    "{SHADOW_COMPARE_LEGACY_SKIPPED}{{team_id=\"2\"}} 1"
                )),
                "the compare did not re-scan the whole blob:\n{rendered}"
            );
        }
    }
}
