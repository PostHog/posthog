//! The streaming person scanner: the one-shot boundary scan planning tiles a run's UUID space
//! from, and the per-chunk range-scan cursor the person executor folds row by row. Depends on
//! `domain` and the sibling `person_sql`; never on `store` or `kafka`.

use std::num::NonZeroU64;

use clickhouse::query::RowCursor;
use clickhouse::Row;
use cohort_core::filters::TeamId;
use serde::Deserialize;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

use super::person_sql::{person_boundaries_sql, person_scan_sql, PersonScanSpec};
use crate::domain::UtcMillis;

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

    /// Stream the run's live person ids in ClickHouse order, keeping every `persons_per_chunk`-th
    /// as a range boundary — memory stays at K UUIDs regardless of table size.
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
        let mut boundaries = Vec::new();
        let mut seen: u64 = 0;
        loop {
            let row = tokio::select! {
                biased;
                _ = shutdown.cancelled() => return Err(PersonScanError::Cancelled),
                row = cursor.next() => row.map_err(PersonScanError::Cursor)?,
            };
            let Some(row) = row else {
                break;
            };
            seen += 1;
            if seen.is_multiple_of(persons_per_chunk.get()) {
                let boundary = Uuid::parse_str(&row.id).map_err(|source| {
                    PersonScanError::InvalidPersonBoundary {
                        value: row.id,
                        source,
                    }
                })?;
                boundaries.push(boundary);
            }
        }
        Ok(boundaries)
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
