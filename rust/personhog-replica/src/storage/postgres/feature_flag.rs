use std::collections::HashMap;

use async_trait::async_trait;
use sqlx::FromRow;

use personhog_common::grpc::{current_client_name, current_method_name};

use super::{ConsistencyLevel, PostgresStorage, DB_QUERY_DURATION, DB_ROWS_RETURNED};
use crate::storage::error::StorageResult;
use crate::storage::traits::FeatureFlagStorage;
use crate::storage::types::{HashKeyOverride, HashKeyOverrideContext, COOKIELESS_SENTINEL_VALUE};

// Kept as an intermediate struct because the rows are aggregated into
// HashKeyOverrideContext via HashMap grouping logic. All field types already
// match the DB column types exactly — no widening needed.
#[derive(Debug, Clone, FromRow)]
struct HashKeyOverrideContextRow {
    person_id: i64,
    distinct_id: String,
    feature_flag_key: Option<String>,
    hash_key: Option<String>,
}

// The override queries in this impl apply the same sentinel rules as the hash key override SQL
// in `rust/feature-flags/src/flags/flag_matching_utils.rs`. Keep the two in sync.
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

        let client = current_client_name();
        let method = current_method_name();
        let pool_label = PostgresStorage::pool_label(consistency);
        let labels = [
            (
                "operation".to_string(),
                "get_hash_key_override_context".to_string(),
            ),
            ("pool".to_string(), pool_label.to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
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
        let mut conn = PostgresStorage::acquire_timed(pool, pool_label).await?;

        // Every cookieless visitor shares the sentinel, so a stored sentinel would give all of
        // them the same variant.
        let rows = if check_person_exists {
            sqlx::query_as!(
                HashKeyOverrideContextRow,
                r#"
                SELECT DISTINCT p.person_id, p.distinct_id,
                       existing.feature_flag_key as "feature_flag_key?",
                       existing.hash_key as "hash_key?"
                FROM posthog_persondistinctid p
                LEFT JOIN posthog_featureflaghashkeyoverride existing
                    ON existing.person_id = p.person_id AND existing.team_id = p.team_id
                    AND existing.hash_key <> $3
                WHERE p.team_id = $1 AND p.distinct_id = ANY($2) AND p.is_deleted = false
                    AND EXISTS (SELECT 1 FROM posthog_person WHERE id = p.person_id AND team_id = p.team_id AND is_deleted = false)
                "#,
                team_id as i32,
                distinct_ids,
                COOKIELESS_SENTINEL_VALUE
            )
            .fetch_all(&mut *conn)
            .await?
        } else {
            sqlx::query_as!(
                HashKeyOverrideContextRow,
                r#"
                SELECT ppd.person_id, ppd.distinct_id,
                       fhko.feature_flag_key as "feature_flag_key?",
                       fhko.hash_key as "hash_key?"
                FROM posthog_persondistinctid ppd
                LEFT JOIN posthog_featureflaghashkeyoverride fhko
                    ON fhko.person_id = ppd.person_id AND fhko.team_id = ppd.team_id
                    AND fhko.hash_key <> $3
                WHERE ppd.team_id = $1 AND ppd.distinct_id = ANY($2) AND ppd.is_deleted = false
                "#,
                team_id as i32,
                distinct_ids,
                COOKIELESS_SENTINEL_VALUE
            )
            .fetch_all(&mut *conn)
            .await?
        };

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "get_hash_key_override_context".to_string(),
                ),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), method.to_string()),
            ],
            rows.len() as f64,
        );

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
        distinct_ids: &[String],
        feature_flag_keys: &[String],
        hash_key: &str,
    ) -> StorageResult<i64> {
        if distinct_ids.is_empty() || feature_flag_keys.is_empty() {
            return Ok(0);
        }

        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            (
                "operation".to_string(),
                "upsert_hash_key_overrides".to_string(),
            ),
            ("pool".to_string(), "primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let mut conn = PostgresStorage::acquire_timed(&self.primary_pool, "primary").await?;
        let mut tx = sqlx::Connection::begin(&mut *conn).await?;
        // The foreign key from posthog_featureflaghashkeyoverride to posthog_person is deferred.
        // Postgres checks deferred keys at COMMIT. statement_timeout does not cover COMMIT. A
        // person delete or merge holds FOR UPDATE on the person row until its transaction ends.
        // Until then, the commit waits. This statement moves the check into the INSERT, where
        // statement_timeout applies.
        sqlx::query("SET CONSTRAINTS ALL IMMEDIATE")
            .execute(&mut *tx)
            .await?;
        // lock_timeout bounds the wait on one held row. The INSERT can wait on several held rows
        // in turn, so statement_timeout caps the total wait. Both limits stay under the caller's
        // deadline, so the INSERT can fail with its own error before the caller gives up. The
        // limits cover only the INSERT. The pool acquire above runs before them and can still use
        // up the caller's deadline. The settings are local to the transaction, so PgBouncer does
        // not pass them to the next client of the server connection.
        sqlx::query(
            "SELECT set_config('lock_timeout', '2s', true), set_config('statement_timeout', $1, true)",
        )
        .bind(self.hash_key_override_statement_timeout_ms.to_string())
        .execute(&mut *tx)
        .await?;

        // DO UPDATE locks each conflicting row even when its WHERE is false, so NOT EXISTS
        // skips the pairs that already hold a real key. The WHERE still keeps a real key that a
        // concurrent write commits after NOT EXISTS reads its snapshot. DO UPDATE also fails
        // when two distinct ids of one person produce the same row twice, so DISTINCT removes
        // the duplicates. ORDER BY makes concurrent upserts lock rows in the same order.
        let result = sqlx::query!(
            r#"
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
            SELECT DISTINCT $1::integer, p.person_id, f.flag_key, $2::text
            FROM posthog_persondistinctid p
            CROSS JOIN UNNEST($4::text[]) AS f(flag_key)
            WHERE p.team_id = $1 AND p.distinct_id = ANY($3) AND p.is_deleted = false
              AND EXISTS (SELECT 1 FROM posthog_person WHERE id = p.person_id AND team_id = p.team_id AND is_deleted = false)
              AND NOT EXISTS (
                  SELECT 1 FROM posthog_featureflaghashkeyoverride o
                  WHERE o.team_id = p.team_id AND o.person_id = p.person_id
                    AND o.feature_flag_key = f.flag_key AND o.hash_key <> $5
              )
            ORDER BY p.person_id, f.flag_key
            ON CONFLICT (team_id, person_id, feature_flag_key) DO UPDATE
                SET hash_key = EXCLUDED.hash_key
                WHERE posthog_featureflaghashkeyoverride.hash_key = $5
            "#,
            team_id as i32,
            hash_key,
            distinct_ids,
            feature_flag_keys,
            COOKIELESS_SENTINEL_VALUE
        )
        .execute(&mut *tx)
        .await?;
        tx.commit().await?;

        Ok(result.rows_affected() as i64)
    }

    async fn delete_hash_key_overrides_by_teams(
        &self,
        team_ids: &[i64],
        batch_size: i64,
    ) -> StorageResult<i64> {
        if team_ids.is_empty() || batch_size <= 0 {
            return Ok(0);
        }

        let client = current_client_name();
        let method = current_method_name();
        let labels = [
            (
                "operation".to_string(),
                "delete_hash_key_overrides_by_teams".to_string(),
            ),
            ("pool".to_string(), "bulk_primary".to_string()),
            ("client".to_string(), client.to_string()),
            ("method".to_string(), method.to_string()),
        ];
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);

        let team_ids_i32: Vec<i32> = team_ids.iter().map(|&id| id as i32).collect();

        let result = sqlx::query!(
            r#"
            DELETE FROM posthog_featureflaghashkeyoverride
            WHERE id IN (
                SELECT id FROM posthog_featureflaghashkeyoverride
                WHERE team_id = ANY($1)
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            "#,
            &team_ids_i32,
            batch_size
        )
        .execute(&self.bulk_primary_pool)
        .await?;

        common_metrics::histogram(
            DB_ROWS_RETURNED,
            &[
                (
                    "operation".to_string(),
                    "delete_hash_key_overrides_by_teams".to_string(),
                ),
                ("pool".to_string(), "bulk_primary".to_string()),
                ("client".to_string(), client.to_string()),
                ("method".to_string(), method.to_string()),
            ],
            result.rows_affected() as f64,
        );

        Ok(result.rows_affected() as i64)
    }
}
