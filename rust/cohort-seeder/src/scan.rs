use std::num::NonZeroU32;
use std::time::Instant;

use chrono::Utc;
use chrono_tz::Tz;
use clickhouse::Row;
use cohort_core::events::CohortStreamEvent;
use cohort_core::filters::TeamId;
use cohort_core::hogvm::VmErrorClass;
use cohort_core::stage1::bucket_tz::day_idx_in_tz;
use cohort_core::stage1::time::clickhouse_timestamp_to_millis;
use metrics::{counter, histogram};
use serde::Deserialize;
use tokio_util::sync::CancellationToken;

use crate::aggregate::{AggregateError, ChunkAccumulator, RecordOutcome, RecordStats};
use crate::chunks::{ChunkError, ClaimedChunk, ScannedChunk};
use crate::domain::{conditions_active_on, ActiveConditions, SeedDomain};
use crate::ids::{Band, DayIdx};
use crate::observability::metrics::{
    AGGREGATE_ENTRIES, CHUNKS_VACUOUS, CHUNK_SCAN_DURATION_SECONDS, CONDITIONS_EVALUATED,
    EVENTS_SKIPPED, HOGVM_ERRORS, ROWS_SCANNED,
};
use crate::pinned::{PinnedCondition, PinnedRun};
use crate::tile::SeedTile;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScanSpec {
    team_id: TeamId,
    day_start_ms: i64,
    day_end_ms: i64,
    s_chunk_ms: i64,
    event_names: Vec<String>,
    band: u32,
    num_bands: NonZeroU32,
}

impl ScanSpec {
    pub fn new(
        team_id: TeamId,
        domain: &SeedDomain,
        event_names: impl IntoIterator<Item = String>,
        band: Band,
        num_bands: NonZeroU32,
    ) -> Result<Self, ScanSpecError> {
        let raw_band = band.0;
        let band = u32::try_from(raw_band).map_err(|_| ScanSpecError::InvalidBand {
            band: raw_band,
            num_bands: num_bands.get(),
        })?;
        if band >= num_bands.get() {
            return Err(ScanSpecError::InvalidBand {
                band: raw_band,
                num_bands: num_bands.get(),
            });
        }
        let mut event_names = event_names.into_iter().collect::<Vec<_>>();
        event_names.sort_unstable();
        event_names.dedup();
        if event_names.is_empty() {
            return Err(ScanSpecError::EmptyEventNames);
        }
        let (day_start_ms, day_end_ms) = domain.utc_range();
        Ok(Self {
            team_id,
            day_start_ms,
            day_end_ms,
            s_chunk_ms: domain.s_chunk().0,
            event_names,
            band,
            num_bands,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum ScanSpecError {
    #[error("ClickHouse scan requires at least one event name")]
    EmptyEventNames,
    #[error("ClickHouse scan band {band} is outside 0..{num_bands}")]
    InvalidBand { band: i16, num_bands: u32 },
}

pub fn scan_sql(spec: &ScanSpec) -> String {
    let event_names = spec
        .event_names
        .iter()
        .map(|name| clickhouse_string_literal(name))
        .collect::<Vec<_>>()
        .join(", ");
    let band_predicate = if spec.num_bands.get() > 1 {
        format!(
            "\n  AND cityHash64(toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)))\n      % {} = {}",
            spec.num_bands, spec.band
        )
    } else {
        String::new()
    };

    format!(
        "SELECT toString(e.uuid) AS uuid, e.event, e.properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       e.person_properties, e.elements_chain\nFROM events AS e\nLEFT JOIN (\n    SELECT distinct_id, argMax(person_id, version) AS person_id\n    FROM person_distinct_id_overrides\n    WHERE team_id = {}\n    GROUP BY distinct_id\n    HAVING argMax(is_deleted, version) = 0\n) AS ov ON e.distinct_id = ov.distinct_id\nWHERE e.team_id = {}\n  AND e.timestamp >= fromUnixTimestamp64Milli({})\n  AND e.timestamp < fromUnixTimestamp64Milli({})\n  AND e.event IN ({})\n  AND coalesce(e.inserted_at, e._timestamp) < fromUnixTimestamp64Milli({}){}",
        spec.team_id.0,
        spec.team_id.0,
        spec.day_start_ms,
        spec.day_end_ms,
        event_names,
        spec.s_chunk_ms,
        band_predicate,
    )
}

fn clickhouse_string_literal(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len() + 2);
    escaped.push('\'');
    for character in value.chars() {
        match character {
            '\\' => escaped.push_str("\\\\"),
            '\'' => escaped.push_str("\\'"),
            '`' => escaped.push_str("\\`"),
            '\0' => escaped.push_str("\\0"),
            '\u{0007}' => escaped.push_str("\\a"),
            '\u{0008}' => escaped.push_str("\\b"),
            '\t' => escaped.push_str("\\t"),
            '\n' => escaped.push_str("\\n"),
            '\u{000B}' => escaped.push_str("\\v"),
            '\u{000C}' => escaped.push_str("\\f"),
            '\r' => escaped.push_str("\\r"),
            character if character.is_control() => {
                let mut bytes = [0; 4];
                for byte in character.encode_utf8(&mut bytes).as_bytes() {
                    escaped.push_str(&format!("\\x{byte:02X}"));
                }
            }
            character => escaped.push(character),
        }
    }
    escaped.push('\'');
    escaped
}

#[derive(Debug, Row, Deserialize, PartialEq, Eq)]
pub struct EventRow {
    pub uuid: String,
    pub event: String,
    pub properties: String,
    pub timestamp: String,
    pub distinct_id: String,
    pub person_id: String,
    pub person_properties: String,
    pub elements_chain: String,
}

pub fn row_to_event(team_id: TeamId, row: EventRow) -> CohortStreamEvent {
    CohortStreamEvent {
        team_id: team_id.0,
        person_id: row.person_id,
        distinct_id: row.distinct_id,
        uuid: row.uuid,
        event: row.event,
        timestamp: row.timestamp,
        properties: non_empty(row.properties),
        person_properties: non_empty(row.person_properties),
        elements_chain: non_empty(row.elements_chain),
        source_offset: 0,
        source_partition: -1,
        redirected_from: None,
        redirect_hops: 0,
    }
}

fn non_empty(value: String) -> Option<String> {
    (!value.is_empty()).then_some(value)
}

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
        shutdown: &CancellationToken,
    ) -> Result<ScannedChunk, ScanFailure> {
        self.scan_at(chunk, run, Utc::now().timestamp_millis(), shutdown)
            .await
    }

    async fn scan_at(
        &self,
        chunk: ClaimedChunk,
        run: &PinnedRun,
        now_ms: i64,
        shutdown: &CancellationToken,
    ) -> Result<ScannedChunk, ScanFailure> {
        match self.scan_tiles(&chunk, run, now_ms, shutdown).await {
            Ok(tiles) => Ok(chunk.finish_scan(tiles)),
            Err(source) => Err(ScanFailure { chunk, source }),
        }
    }

    async fn scan_tiles(
        &self,
        chunk: &ClaimedChunk,
        run: &PinnedRun,
        now_ms: i64,
        shutdown: &CancellationToken,
    ) -> Result<Vec<SeedTile>, ChunkError> {
        let _timer = ScanTimer::start();
        let domain = chunk.domain(run)?;
        let active = active_conditions_at(chunk.day(), run.tz, now_ms, &run.conditions);
        let event_names = active_event_names(run, &active);
        if domain.is_empty() || active.is_empty() || event_names.is_empty() {
            counter!(CHUNKS_VACUOUS).increment(1);
            return Ok(Vec::new());
        }

        let spec = ScanSpec::new(
            chunk.team_id(),
            &domain,
            event_names,
            chunk.band(),
            chunk.num_bands(),
        )
        .map_err(ScanError::from)?;
        let cancellation = chunk.cancellation_token();
        let mut cursor = self
            .client
            .query(&scan_sql(&spec))
            .fetch::<EventRow>()
            .map_err(ScanError::Query)?;
        let mut accumulator =
            ChunkAccumulator::new(run.team_id, &run.filters, &active).map_err(ScanError::from)?;
        let mut saw_row = false;

        loop {
            let row = tokio::select! {
                biased;
                _ = shutdown.cancelled() => return Err(ScanError::Cancelled.into()),
                _ = cancellation.cancelled() => return Err(ScanError::Cancelled.into()),
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
            counter!(CHUNKS_VACUOUS).increment(1);
        }

        histogram!(AGGREGATE_ENTRIES).record(accumulator.entry_count() as f64);
        let tiles = accumulator.into_tiles(&domain, run.run_id, chunk.lease().epoch());
        Ok(tiles)
    }
}

#[derive(Debug, thiserror::Error)]
#[error("chunk scan failed: {source}")]
pub struct ScanFailure {
    chunk: ClaimedChunk,
    #[source]
    source: ChunkError,
}

impl ScanFailure {
    pub fn chunk(&self) -> &ClaimedChunk {
        &self.chunk
    }

    pub fn error(&self) -> &ChunkError {
        &self.source
    }

    pub fn into_parts(self) -> (ClaimedChunk, ChunkError) {
        (self.chunk, self.source)
    }
}

fn active_conditions_at(
    day: DayIdx,
    tz: Tz,
    now_ms: i64,
    conditions: &[PinnedCondition],
) -> ActiveConditions {
    conditions_active_on(day, day_idx_in_tz(now_ms, tz), conditions)
}

fn active_event_names(run: &PinnedRun, active: &ActiveConditions) -> Vec<String> {
    run.event_names
        .iter()
        .filter(|event_name| {
            run.filters
                .behavioral_by_event_name
                .get(*event_name)
                .is_some_and(|hashes| hashes.iter().any(|hash| active.get(hash).is_some()))
        })
        .cloned()
        .collect()
}

fn fold_event(
    domain: &SeedDomain,
    accumulator: &mut ChunkAccumulator,
    event: CohortStreamEvent,
) -> Result<ScanEventOutcome, AggregateError> {
    let Some(timestamp_ms) = clickhouse_timestamp_to_millis(&event.timestamp) else {
        return Ok(ScanEventOutcome::Skipped(ScanSkipReason::TimestampParse));
    };
    if !domain.contains(timestamp_ms) {
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
    #[error("invalid ClickHouse scan: {0}")]
    Spec(#[from] ScanSpecError),
    #[error("building ClickHouse scan cursor: {0}")]
    Query(#[source] clickhouse::error::Error),
    #[error("streaming ClickHouse scan cursor: {0}")]
    Cursor(#[source] clickhouse::error::Error),
    #[error("ClickHouse scan was cancelled after the chunk lease stopped")]
    Cancelled,
    #[error("aggregating ClickHouse scan row: {0}")]
    Aggregate(#[from] AggregateError),
}

#[cfg(test)]
mod tests {
    use chrono_tz::UTC;
    use cohort_core::filters::{CohortId, TeamFilters, TeamFiltersBuilder};
    use serde_json::json;
    use uuid::Uuid;

    use super::*;
    use crate::domain::Boundary;
    use crate::ids::{ClaimEpoch, ConditionHash, RunId, SChunkMs};
    use crate::pinned::Lookback;

    const HASH: &str = "aaaaaaaaaaaaaaaa";

    fn domain() -> SeedDomain {
        SeedDomain::new(
            1,
            Boundary::new(2 * 86_400_000, UTC),
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
    fn unbanded_scan_sql_pins_tenant_time_cutoff_and_override_semantics() {
        let spec = ScanSpec::new(
            TeamId(2),
            &domain(),
            vec!["purchase".to_string(), "$pageview".to_string()],
            Band(0),
            NonZeroU32::MIN,
        )
        .unwrap();
        assert_eq!(
            scan_sql(&spec),
            "SELECT toString(e.uuid) AS uuid, e.event, e.properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       e.person_properties, e.elements_chain\nFROM events AS e\nLEFT JOIN (\n    SELECT distinct_id, argMax(person_id, version) AS person_id\n    FROM person_distinct_id_overrides\n    WHERE team_id = 2\n    GROUP BY distinct_id\n    HAVING argMax(is_deleted, version) = 0\n) AS ov ON e.distinct_id = ov.distinct_id\nWHERE e.team_id = 2\n  AND e.timestamp >= fromUnixTimestamp64Milli(86400000)\n  AND e.timestamp < fromUnixTimestamp64Milli(172800000)\n  AND e.event IN ('$pageview', 'purchase')\n  AND coalesce(e.inserted_at, e._timestamp) < fromUnixTimestamp64Milli(200000000)"
        );
    }

    #[test]
    fn banded_scan_sql_hashes_the_resolved_person() {
        let spec = ScanSpec::new(
            TeamId(2),
            &domain(),
            vec!["purchase".to_string()],
            Band(3),
            NonZeroU32::new(8).unwrap(),
        )
        .unwrap();
        assert_eq!(
            scan_sql(&spec),
            "SELECT toString(e.uuid) AS uuid, e.event, e.properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       e.person_properties, e.elements_chain\nFROM events AS e\nLEFT JOIN (\n    SELECT distinct_id, argMax(person_id, version) AS person_id\n    FROM person_distinct_id_overrides\n    WHERE team_id = 2\n    GROUP BY distinct_id\n    HAVING argMax(is_deleted, version) = 0\n) AS ov ON e.distinct_id = ov.distinct_id\nWHERE e.team_id = 2\n  AND e.timestamp >= fromUnixTimestamp64Milli(86400000)\n  AND e.timestamp < fromUnixTimestamp64Milli(172800000)\n  AND e.event IN ('purchase')\n  AND coalesce(e.inserted_at, e._timestamp) < fromUnixTimestamp64Milli(200000000)\n  AND cityHash64(toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)))\n      % 8 = 3"
        );
    }

    #[test]
    fn scan_sql_escapes_hostile_event_names_as_literals() {
        let spec = ScanSpec::new(
            TeamId(2),
            &domain(),
            vec![
                "quote' OR 1 = 1 --".to_string(),
                "slash\\name\nnext".to_string(),
            ],
            Band(0),
            NonZeroU32::MIN,
        )
        .unwrap();
        assert_eq!(
            scan_sql(&spec),
            "SELECT toString(e.uuid) AS uuid, e.event, e.properties, toString(e.timestamp) AS timestamp,\n       e.distinct_id,\n       toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,\n       e.person_properties, e.elements_chain\nFROM events AS e\nLEFT JOIN (\n    SELECT distinct_id, argMax(person_id, version) AS person_id\n    FROM person_distinct_id_overrides\n    WHERE team_id = 2\n    GROUP BY distinct_id\n    HAVING argMax(is_deleted, version) = 0\n) AS ov ON e.distinct_id = ov.distinct_id\nWHERE e.team_id = 2\n  AND e.timestamp >= fromUnixTimestamp64Milli(86400000)\n  AND e.timestamp < fromUnixTimestamp64Milli(172800000)\n  AND e.event IN ('quote\\' OR 1 = 1 --', 'slash\\\\name\\nnext')\n  AND coalesce(e.inserted_at, e._timestamp) < fromUnixTimestamp64Milli(200000000)"
        );
    }

    #[test]
    fn row_conversion_restores_optional_fields_and_seed_sentinels() {
        let event = row_to_event(
            TeamId(2),
            EventRow {
                properties: String::new(),
                person_properties: "{\"plan\":\"paid\"}".to_string(),
                elements_chain: String::new(),
                ..row("1970-01-02 12:00:00.000000")
            },
        );
        assert_eq!(event.team_id, 2);
        assert_eq!(event.properties, None);
        assert_eq!(
            event.person_properties.as_deref(),
            Some("{\"plan\":\"paid\"}")
        );
        assert_eq!(event.elements_chain, None);
        assert_eq!(event.source_partition, -1);
        assert_eq!(event.source_offset, 0);
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
            event_name: Some("purchase".to_string()),
            lookback: Lookback::SlidingDays(1),
        }];
        assert!(active_conditions_at(1, UTC, 2 * 86_400_000, &conditions).contains(&hash));
        assert!(!active_conditions_at(1, UTC, 3 * 86_400_000, &conditions).contains(&hash));
    }
}
