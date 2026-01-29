use std::collections::HashMap;

use async_trait::async_trait;
use sqlx::FromRow;

use super::{PostgresStorage, DB_QUERY_DURATION};
use crate::storage::error::StorageResult;
use crate::storage::traits::FeatureFlagStorage;
use crate::storage::types::{HashKeyOverride, PersonIdWithOverrideKeys, PersonIdWithOverrides};

#[derive(Debug, Clone, FromRow)]
struct PersonIdAndHashKeyOverrideRow {
    person_id: i64,
    distinct_id: String,
    feature_flag_key: Option<String>,
    hash_key: Option<String>,
}

#[derive(Debug, Clone, FromRow)]
struct PersonIdWithOverrideKeyRow {
    person_id: i64,
    feature_flag_key: Option<String>,
}

#[async_trait]
impl FeatureFlagStorage for PostgresStorage {
    async fn get_person_ids_and_hash_key_overrides(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<PersonIdWithOverrides>> {
        if distinct_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "get_person_ids_and_hash_key_overrides".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, PersonIdAndHashKeyOverrideRow>(
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
        .fetch_all(&self.pool)
        .await?;

        // Group by (person_id, distinct_id) and collect overrides
        let mut result_map: HashMap<(i64, String), Vec<HashKeyOverride>> = HashMap::new();
        for row in rows {
            let key = (row.person_id, row.distinct_id.clone());
            if let (Some(flag_key), Some(hash_key)) = (row.feature_flag_key, row.hash_key) {
                result_map.entry(key).or_default().push(HashKeyOverride {
                    feature_flag_key: flag_key,
                    hash_key,
                });
            } else {
                // Ensure the key exists even if there are no overrides
                result_map.entry(key).or_default();
            }
        }

        Ok(result_map
            .into_iter()
            .map(
                |((person_id, distinct_id), overrides)| PersonIdWithOverrides {
                    person_id,
                    distinct_id,
                    overrides,
                },
            )
            .collect())
    }

    async fn get_existing_person_ids_with_override_keys(
        &self,
        team_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<Vec<PersonIdWithOverrideKeys>> {
        if distinct_ids.is_empty() {
            return Ok(Vec::new());
        }

        let labels = [(
            "operation".to_string(),
            "get_existing_person_ids_with_override_keys".to_string(),
        )];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let rows = sqlx::query_as::<_, PersonIdWithOverrideKeyRow>(
            r#"
            SELECT DISTINCT p.person_id, existing.feature_flag_key
            FROM posthog_persondistinctid p
            LEFT JOIN posthog_featureflaghashkeyoverride existing
                ON existing.person_id = p.person_id AND existing.team_id = p.team_id
            WHERE p.team_id = $1 AND p.distinct_id = ANY($2)
                AND EXISTS (SELECT 1 FROM posthog_person WHERE id = p.person_id AND team_id = p.team_id)
            "#,
        )
        .bind(team_id)
        .bind(distinct_ids)
        .fetch_all(&self.pool)
        .await?;

        let mut result_map: HashMap<i64, Vec<String>> = HashMap::new();
        for row in rows {
            if let Some(flag_key) = row.feature_flag_key {
                result_map.entry(row.person_id).or_default().push(flag_key);
            } else {
                result_map.entry(row.person_id).or_default();
            }
        }

        Ok(result_map
            .into_iter()
            .map(
                |(person_id, existing_feature_flag_keys)| PersonIdWithOverrideKeys {
                    person_id,
                    existing_feature_flag_keys,
                },
            )
            .collect())
    }
}
