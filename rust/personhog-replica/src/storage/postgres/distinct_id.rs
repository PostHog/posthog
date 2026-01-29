use async_trait::async_trait;
use sqlx::FromRow;

use super::{PostgresStorage, DB_QUERY_DURATION};
use crate::storage::error::StorageResult;
use crate::storage::traits::DistinctIdLookup;
use crate::storage::types::{DistinctIdMapping, DistinctIdWithVersion};

#[derive(Debug, Clone, FromRow)]
struct DistinctIdRow {
    person_id: i64,
    distinct_id: String,
}

#[derive(Debug, Clone, FromRow)]
struct DistinctIdWithVersionRow {
    distinct_id: String,
    version: Option<i64>,
}

#[async_trait]
impl DistinctIdLookup for PostgresStorage {
    async fn get_distinct_ids_for_person(
        &self,
        team_id: i64,
        person_id: i64,
    ) -> StorageResult<Vec<DistinctIdWithVersion>> {
        let labels = [(
            "operation".to_string(),
            "get_distinct_ids_for_person".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, DistinctIdWithVersionRow>(
            r#"
            SELECT distinct_id, version
            FROM posthog_persondistinctid
            WHERE team_id = $1 AND person_id = $2
            "#,
        )
        .bind(team_id)
        .bind(person_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(rows
            .into_iter()
            .map(|r| DistinctIdWithVersion {
                distinct_id: r.distinct_id,
                version: r.version,
            })
            .collect())
    }

    async fn get_distinct_ids_for_persons(
        &self,
        team_id: i64,
        person_ids: &[i64],
    ) -> StorageResult<Vec<DistinctIdMapping>> {
        if person_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "get_distinct_ids_for_persons".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, DistinctIdRow>(
            r#"
            SELECT person_id, distinct_id
            FROM posthog_persondistinctid
            WHERE team_id = $1 AND person_id = ANY($2)
            "#,
        )
        .bind(team_id)
        .bind(person_ids)
        .fetch_all(&self.pool)
        .await?;

        Ok(rows
            .into_iter()
            .map(|r| DistinctIdMapping {
                person_id: r.person_id,
                distinct_id: r.distinct_id,
            })
            .collect())
    }
}
