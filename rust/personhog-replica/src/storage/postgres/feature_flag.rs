use std::collections::HashMap;

use async_trait::async_trait;
use sqlx::FromRow;

use super::{ConsistencyLevel, PostgresStorage, DB_QUERY_DURATION};
use crate::storage::error::StorageResult;
use crate::storage::traits::FeatureFlagStorage;
use crate::storage::types::{HashKeyOverride, HashKeyOverrideContext, HashKeyOverrideInput};

#[derive(Debug, Clone, FromRow)]
struct HashKeyOverrideContextRow {
    person_id: i64,
    distinct_id: String,
    feature_flag_key: Option<String>,
    hash_key: Option<String>,
}

#[async_trait]
impl FeatureFlagStorage for PostgresStorage {
    async fn get_hash_key_override_context(
        &self,
        team_id: i64,
        distinct_ids: &[String],
        check_person_exists: bool,
        consistency: ConsistencyLevel,
    ) -> StorageResult<Vec<HashKeyOverrideContext>> {
        if distinct_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "get_hash_key_override_context".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        // Select the appropriate pool based on consistency requirements.
        //
        // Strong consistency is used when the caller needs read-after-write guarantees,
        // such as immediately after writing hash key overrides.
        //
        // Note: This queries the primary database directly for strong consistency.
        // When personhog-leader is implemented, person table reads will be served from
        // the leader's cache, and strong consistency will require routing to the leader
        // service instead. Before the personhog-leader is implemented, we can serve consistent read after writes
        // for person data from this service
        let pool = self.pool_for_consistency(consistency);

        let rows = if check_person_exists {
            // Query with person existence check
            sqlx::query_as::<_, HashKeyOverrideContextRow>(
                r#"
                SELECT DISTINCT p.person_id, p.distinct_id, existing.feature_flag_key, existing.hash_key
                FROM posthog_persondistinctid p
                LEFT JOIN posthog_featureflaghashkeyoverride existing
                    ON existing.person_id = p.person_id AND existing.team_id = p.team_id
                WHERE p.team_id = $1 AND p.distinct_id = ANY($2)
                    AND EXISTS (SELECT 1 FROM posthog_person WHERE id = p.person_id AND team_id = p.team_id)
                "#,
            )
            .bind(team_id)
            .bind(distinct_ids)
            .fetch_all(pool)
            .await?
        } else {
            // Query without person existence check
            sqlx::query_as::<_, HashKeyOverrideContextRow>(
                r#"
                SELECT ppd.person_id, ppd.distinct_id, fhko.feature_flag_key, fhko.hash_key
                FROM posthog_persondistinctid ppd
                LEFT JOIN posthog_featureflaghashkeyoverride fhko
                    ON fhko.person_id = ppd.person_id AND fhko.team_id = ppd.team_id
                WHERE ppd.team_id = $1 AND ppd.distinct_id = ANY($2)
                "#,
            )
            .bind(team_id)
            .bind(distinct_ids)
            .fetch_all(pool)
            .await?
        };

        // Group by (person_id, distinct_id) and collect overrides + existing keys
        let mut result_map: HashMap<(i64, String), HashKeyOverrideContext> = HashMap::new();
        for row in rows {
            let key = (row.person_id, row.distinct_id.clone());
            let entry = result_map
                .entry(key)
                .or_insert_with(|| HashKeyOverrideContext {
                    person_id: row.person_id,
                    distinct_id: row.distinct_id.clone(),
                    overrides: Vec::new(),
                    existing_feature_flag_keys: Vec::new(),
                });

            if let Some(flag_key) = row.feature_flag_key {
                // Add to existing_feature_flag_keys if not already present
                if !entry.existing_feature_flag_keys.contains(&flag_key) {
                    entry.existing_feature_flag_keys.push(flag_key.clone());
                }
                // Add to overrides if we have the hash_key
                if let Some(hash_key) = row.hash_key {
                    entry.overrides.push(HashKeyOverride {
                        feature_flag_key: flag_key,
                        hash_key,
                    });
                }
            }
        }

        Ok(result_map.into_values().collect())
    }

    async fn upsert_hash_key_overrides(
        &self,
        team_id: i64,
        overrides: &[HashKeyOverrideInput],
        hash_key: &str,
    ) -> StorageResult<i64> {
        if overrides.is_empty() {
            return Ok(0);
        }

        let labels = [(
            "operation".to_string(),
            "upsert_hash_key_overrides".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let person_ids: Vec<i64> = overrides.iter().map(|o| o.person_id).collect();
        let flag_keys: Vec<&str> = overrides
            .iter()
            .map(|o| o.feature_flag_key.as_str())
            .collect();

        let result = sqlx::query(
            r#"
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
            SELECT $1, person_id, flag_key, $2
            FROM UNNEST($3::bigint[], $4::text[]) AS t(person_id, flag_key)
            ON CONFLICT DO NOTHING
            "#,
        )
        .bind(team_id)
        .bind(hash_key)
        .bind(&person_ids)
        .bind(&flag_keys)
        .execute(&self.primary_pool)
        .await?;

        Ok(result.rows_affected() as i64)
    }

    async fn delete_hash_key_overrides_by_teams(&self, team_ids: &[i64]) -> StorageResult<i64> {
        if team_ids.is_empty() {
            return Ok(0);
        }

        let labels = [(
            "operation".to_string(),
            "delete_hash_key_overrides_by_teams".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let result = sqlx::query(
            r#"
            DELETE FROM posthog_featureflaghashkeyoverride
            WHERE team_id = ANY($1)
            "#,
        )
        .bind(team_ids)
        .execute(&self.primary_pool)
        .await?;

        Ok(result.rows_affected() as i64)
    }
}
