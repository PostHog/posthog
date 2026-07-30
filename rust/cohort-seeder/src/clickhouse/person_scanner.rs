//! The streaming person scanner: the one-shot boundary scan planning tiles a run's UUID space
//! from, and the per-chunk range-scan cursor the person executor folds row by row. Depends on
//! `domain` and the sibling `person_sql`; never on `store` or `kafka`.

use std::num::NonZeroU64;

use clickhouse::query::RowCursor;
use clickhouse::Row;
use cohort_core::filters::TeamId;
use serde::Deserialize;
use tokio_util::sync::CancellationToken;
use tracing::warn;
use uuid::Uuid;

use super::person_sql::{person_boundaries_sql, person_scan_sql, PersonScanSpec};
use crate::domain::{UtcMillis, MAX_PERSON_CHUNKS};

/// One scanned person's latest row: the id and its `argMax(properties, version)` payload.
#[derive(Debug, Row, Deserialize)]
pub struct PersonRow {
    pub id: String,
    pub properties: String,
}

#[derive(Debug, Row, Deserialize)]
struct PersonIdRow {
    id: String,
}

#[derive(Clone)]
pub struct PersonScanner {
    client: clickhouse::Client,
}

impl PersonScanner {
    pub fn new(client: clickhouse::Client) -> Self {
        Self { client }
    }

    /// Stream the run's live person ids in ClickHouse order, keeping the first id of every new
    /// chunk as a range boundary — memory is bounded by the chunk-count ceiling, never the table
    /// size. When the ceiling saturates, the final unbounded range absorbs the remainder and the
    /// scan stops early rather than failing a run over a column-width constraint.
    pub async fn boundaries(
        &self,
        team_id: TeamId,
        scan_since: UtcMillis,
        persons_per_chunk: NonZeroU64,
        shutdown: &CancellationToken,
    ) -> Result<Vec<Uuid>, PersonScanError> {
        let mut cursor = self
            .client
            .query(&person_boundaries_sql(team_id, scan_since))
            .fetch::<PersonIdRow>()
            .map_err(PersonScanError::Query)?;
        let mut keeper = BoundaryKeeper::new(persons_per_chunk);
        loop {
            let row = tokio::select! {
                biased;
                _ = shutdown.cancelled() => return Err(PersonScanError::Cancelled),
                row = cursor.next() => row.map_err(PersonScanError::Cursor)?,
            };
            let Some(row) = row else {
                break;
            };
            if keeper.observe(row.id)? == BoundaryScanStep::Saturated {
                warn!(
                    team_id = team_id.0,
                    persons_per_chunk = persons_per_chunk.get(),
                    "person chunk ceiling saturated; the final chunk absorbs the remainder"
                );
                break;
            }
        }
        Ok(keeper.into_boundaries())
    }

    /// The streaming cursor over one chunk's UUID range; the caller owns the fold.
    pub fn scan_rows(
        &self,
        spec: &PersonScanSpec,
    ) -> Result<RowCursor<PersonRow>, PersonScanError> {
        self.client
            .query(&person_scan_sql(spec))
            .fetch::<PersonRow>()
            .map_err(PersonScanError::Query)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BoundaryScanStep {
    Continue,
    /// The chunk-count ceiling is reached: no further boundary can be kept, so the remaining rows
    /// all fall into the final unbounded range and the scan may stop.
    Saturated,
}

/// The pure boundary-selection fold: a boundary is the *first* id of each new chunk (not the last
/// of the completed one), so every chunk — including the first — holds `stride` persons.
struct BoundaryKeeper {
    stride: u64,
    seen: u64,
    boundaries: Vec<Uuid>,
}

impl BoundaryKeeper {
    fn new(stride: NonZeroU64) -> Self {
        Self {
            stride: stride.get(),
            seen: 0,
            boundaries: Vec::new(),
        }
    }

    fn observe(&mut self, id: String) -> Result<BoundaryScanStep, PersonScanError> {
        self.seen += 1;
        if self.seen > 1 && (self.seen - 1).is_multiple_of(self.stride) {
            // Ranges = boundaries + 1, and `band` is a smallint.
            if self.boundaries.len() + 1 >= MAX_PERSON_CHUNKS {
                return Ok(BoundaryScanStep::Saturated);
            }
            let boundary = Uuid::parse_str(&id)
                .map_err(|source| PersonScanError::InvalidPersonBoundary { value: id, source })?;
            self.boundaries.push(boundary);
        }
        Ok(BoundaryScanStep::Continue)
    }

    fn into_boundaries(self) -> Vec<Uuid> {
        self.boundaries
    }
}

#[derive(Debug, thiserror::Error)]
pub enum PersonScanError {
    #[error("building ClickHouse person scan cursor")]
    Query(#[source] clickhouse::error::Error),
    #[error("streaming ClickHouse person scan cursor")]
    Cursor(#[source] clickhouse::error::Error),
    #[error("person boundary id {value:?} is not a UUID: {source}")]
    InvalidPersonBoundary {
        value: String,
        #[source]
        source: uuid::Error,
    },
    #[error("person scan cancelled by shutdown")]
    Cancelled,
}

#[cfg(test)]
mod tests {
    use crate::domain::tile_ranges;

    use super::*;

    fn feed(keeper: &mut BoundaryKeeper, rows: u128) -> Vec<BoundaryScanStep> {
        (1..=rows)
            .map(|row| keeper.observe(Uuid::from_u128(row).to_string()).unwrap())
            .collect()
    }

    /// Every chunk — the first included — holds exactly `stride` persons; only the final chunk
    /// carries a remainder.
    #[test]
    fn boundaries_start_each_new_chunk_so_every_chunk_holds_the_stride() {
        // 7 rows at stride 3: boundaries are rows 4 and 7 (the first of chunks 2 and 3), giving
        // range populations 3, 3, 1.
        let mut keeper = BoundaryKeeper::new(NonZeroU64::new(3).unwrap());
        feed(&mut keeper, 7);
        assert_eq!(
            keeper.into_boundaries(),
            vec![Uuid::from_u128(4), Uuid::from_u128(7)]
        );

        // An exact multiple emits no trailing boundary: 6 rows at stride 3 → chunks of 3 and 3.
        let mut keeper = BoundaryKeeper::new(NonZeroU64::new(3).unwrap());
        feed(&mut keeper, 6);
        assert_eq!(keeper.into_boundaries(), vec![Uuid::from_u128(4)]);

        // Stride 1: the first chunk holds row 1, not zero rows.
        let mut keeper = BoundaryKeeper::new(NonZeroU64::MIN);
        feed(&mut keeper, 3);
        assert_eq!(
            keeper.into_boundaries(),
            vec![Uuid::from_u128(2), Uuid::from_u128(3)]
        );
    }

    /// The keeper saturates at the band column's ceiling instead of overflowing: the tiling stays
    /// inside `MAX_PERSON_CHUNKS` and the final unbounded range absorbs the remainder.
    #[test]
    fn boundary_count_saturates_at_the_chunk_ceiling() {
        let mut keeper = BoundaryKeeper::new(NonZeroU64::MIN);
        let rows = MAX_PERSON_CHUNKS as u128 + 5;
        let steps = feed(&mut keeper, rows);
        assert!(steps.contains(&BoundaryScanStep::Saturated));
        let boundaries = keeper.into_boundaries();
        assert_eq!(boundaries.len(), MAX_PERSON_CHUNKS - 1);
        assert_eq!(tile_ranges(&boundaries).unwrap().len(), MAX_PERSON_CHUNKS);
    }
}
