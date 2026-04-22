use crate::api::errors::FlagError;
use crate::cohorts::cohort_models::Cohort;
use crate::database::get_connection_with_metrics;
use crate::flags::flag_models::{
    EvaluationMetadata, FeatureFlag, FeatureFlagList, FeatureFlagRow, FlagPropertyGroup,
    HypercacheFlagsWrapper,
};
use crate::metrics::consts::TOMBSTONE_COUNTER;
use common_database::PostgresReader;
use common_types::TeamId;
use metrics::counter;

/// Parsed hypercache result: flags, evaluation metadata, optional preloaded cohorts.
type HypercacheParseResult = (Vec<FeatureFlag>, EvaluationMetadata, Option<Vec<Cohort>>);

impl FeatureFlagList {
    pub fn new(flags: Vec<FeatureFlag>) -> Self {
        Self {
            flags,
            ..Default::default()
        }
    }

    /// Pre-compiles all regex patterns in property filters across all flags.
    /// Called once after deserialization, before evaluation begins.
    pub fn prepare_regexes(&mut self) {
        for flag in &mut self.flags {
            Self::prepare_group_regexes(&mut flag.filters.groups);
            // super_groups currently only use Exact operators (early access enrollment),
            // so prepare_regex() will no-op for each filter. We walk them anyway for
            // forward-compatibility if super_groups ever gain regex-based filters.
            if let Some(super_groups) = &mut flag.filters.super_groups {
                Self::prepare_group_regexes(super_groups);
            }
        }
    }

    fn prepare_group_regexes(groups: &mut [FlagPropertyGroup]) {
        for group in groups {
            if let Some(properties) = &mut group.properties {
                for filter in properties.iter_mut() {
                    filter.prepare_regex();
                }
            }
        }
    }

    /// Validates and extracts flags from a deserialized `HypercacheFlagsWrapper`.
    /// `None` means the `__missing__` sentinel (team has no flags).
    pub fn from_wrapper(
        wrapper: Option<HypercacheFlagsWrapper>,
        team_id: TeamId,
    ) -> Result<HypercacheParseResult, FlagError> {
        let wrapper = match wrapper {
            None => {
                tracing::debug!("Hypercache sentinel (no flags) for team {}", team_id);
                return Ok((vec![], EvaluationMetadata::default(), None));
            }
            Some(w) => w,
        };

        tracing::debug!(
            "Parsed {} flags and {} cohorts for team {}",
            wrapper.flags.len(),
            wrapper.cohorts.as_ref().map_or(0, |c| c.len()),
            team_id,
        );

        let evaluation_metadata = wrapper.evaluation_metadata;
        if evaluation_metadata.dependency_stages.is_empty() && !wrapper.flags.is_empty() {
            // Every valid cache entry and PG fallback must populate dependency_stages.
            // Empty stages with non-empty flags means something went wrong upstream.
            tracing::error!(
                "evaluation_metadata.dependency_stages is empty but {} flags present for team {}",
                wrapper.flags.len(),
                team_id
            );
            return Err(FlagError::DataParsingErrorWithContext(format!(
                "evaluation_metadata.dependency_stages is empty but {} flags present for team {team_id}",
                wrapper.flags.len()
            )));
        }

        Ok((wrapper.flags, evaluation_metadata, wrapper.cohorts))
    }

    /// Returns feature flags from postgres given a team_id
    pub async fn from_pg(
        client: PostgresReader,
        team_id: TeamId,
    ) -> Result<Vec<FeatureFlag>, FlagError> {
        let mut conn = get_connection_with_metrics(&client, "non_persons_reader", "fetch_flags")
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to get database connection for team {}: {}",
                    team_id,
                    e
                );
                FlagError::DatabaseUnavailable
            })?;

        let query = r#"
            SELECT f.id,
                  f.team_id,
                  f.name,
                  f.key,
                  f.filters,
                  f.deleted,
                  f.active,
                  f.ensure_experience_continuity,
                  f.version,
                  f.evaluation_runtime,
                  COALESCE(
                      ARRAY_AGG(ctx.name) FILTER (WHERE ctx.name IS NOT NULL),
                      '{}'::text[]
                  ) AS evaluation_tags,
                  bucketing_identifier
              FROM posthog_featureflag AS f
              JOIN posthog_team AS t ON (f.team_id = t.id)
              LEFT JOIN posthog_featureflagevaluationcontext AS ec ON (f.id = ec.feature_flag_id)
              LEFT JOIN posthog_evaluationcontext AS ctx ON (ec.evaluation_context_id = ctx.id)
            WHERE t.id = $1
              AND f.deleted = false
              -- Exclude encrypted remote config flags - they can only be accessed via
              -- the dedicated /remote_config endpoint which handles decryption.
              -- Use IS TRUE to handle NULL values (NULL IS TRUE evaluates to FALSE, not NULL)
              AND NOT (f.is_remote_configuration IS TRUE AND f.has_encrypted_payloads IS TRUE)
            GROUP BY f.id, f.team_id, f.name, f.key, f.filters, f.deleted, f.active,
                     f.ensure_experience_continuity, f.version, f.evaluation_runtime
        "#;
        let flags_row = sqlx::query_as::<_, FeatureFlagRow>(query)
            .bind(team_id)
            .fetch_all(&mut *conn)
            .await
            .map_err(|e| {
                tracing::error!(
                    "Failed to fetch feature flags from database for team {}: {}",
                    team_id,
                    e
                );
                FlagError::Internal(format!("Database query error: {e}"))
            })?;

        let flags: Vec<FeatureFlag> = flags_row
            .into_iter()
            .filter_map(|row| {
                match serde_json::from_value(row.filters) {
                    Ok(filters) => Some(FeatureFlag {
                        id: row.id,
                        team_id: row.team_id,
                        name: row.name,
                        key: row.key,
                        filters,
                        deleted: row.deleted,
                        active: row.active,
                        ensure_experience_continuity: row.ensure_experience_continuity,
                        version: row.version,
                        evaluation_runtime: row.evaluation_runtime,
                        evaluation_tags: row.evaluation_tags,
                        bucketing_identifier: row.bucketing_identifier,
                    }),
                    Err(e) => {
                        // This is highly unlikely to happen, but if it does, we skip the flag.
                        tracing::warn!(
                            "Failed to deserialize filters for flag {} in team {}: {}",
                            row.key,
                            row.team_id,
                            e
                        );
                        // Also track as a tombstone - invalid data in postgres should never happen
                        // Details (team_id, flag_key) are logged above to avoid high-cardinality labels
                        counter!(
                            TOMBSTONE_COUNTER,
                            "namespace" => "feature_flags",
                            "operation" => "flag_filter_deserialization_error",
                            "component" => "feature_flag_list",
                        )
                        .increment(1);

                        None // Skip this flag, continue with others
                    }
                }
            })
            .collect();

        tracing::debug!(
            "Successfully fetched {} flags from database for team {}",
            flags.len(),
            team_id
        );

        Ok(flags)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        flags::{flag_models::FlagFilters, test_helpers::get_flags_from_redis},
        properties::property_models::{OperatorType, PropertyFilter, PropertyType},
        utils::test_utils::{
            insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_invalid_pg_client,
            setup_redis_client, TestContext,
        },
    };

    #[tokio::test]
    async fn test_fetch_flags_from_redis() {
        let redis_client = setup_redis_client(None).await;

        let team = insert_new_team_in_redis(redis_client.clone())
            .await
            .expect("Failed to insert team");

        insert_flags_for_team_in_redis(redis_client.clone(), team.id, None)
            .await
            .expect("Failed to insert flags");

        let flags_from_redis = get_flags_from_redis(redis_client.clone(), team.id)
            .await
            .expect("Failed to fetch flags from redis");
        assert_eq!(flags_from_redis.flags.len(), 1);
        let flag = flags_from_redis
            .flags
            .first()
            .expect("Empty flags in redis");
        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].properties.as_ref().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn test_fetch_invalid_team_from_redis() {
        let redis_client = setup_redis_client(None).await;

        match get_flags_from_redis(redis_client.clone(), 1234).await {
            Err(FlagError::TokenValidationError) => {
                // Expected error
            }
            _ => panic!("Expected TokenValidationError"),
        }
    }

    #[tokio::test]
    #[should_panic(expected = "Failed to create redis client")]
    async fn test_cant_connect_to_redis_error_is_not_token_validation_error() {
        // Test that client creation fails when Redis is unavailable
        setup_redis_client(Some("redis://localhost:1111/".to_string())).await;
    }

    #[tokio::test]
    async fn test_fetch_flags_from_pg() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        context
            .insert_flag(team.id, None)
            .await
            .expect("Failed to insert flag");

        let flags_from_pg = FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.id)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.len(), 1);
        let flag = flags_from_pg.first().expect("Flags should be in pg");
        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].properties.as_ref().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn test_fetch_empty_team_from_pg() {
        let context = TestContext::new(None).await;

        let flags = FeatureFlagList::from_pg(context.non_persons_reader.clone(), 1234)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags.len(), 0);
    }

    #[tokio::test]
    async fn test_fetch_nonexistent_team_from_pg() {
        let context = TestContext::new(None).await;

        match FeatureFlagList::from_pg(context.non_persons_reader.clone(), -1).await {
            Ok(flags) => assert_eq!(flags.len(), 0),
            Err(err) => panic!("Expected empty result, got error: {err:?}"),
        }
    }

    #[tokio::test]
    async fn test_fetch_flags_db_connection_failure() {
        let invalid_client = setup_invalid_pg_client().await;

        match FeatureFlagList::from_pg(invalid_client, 1).await {
            Ok(_) => panic!("Expected error for invalid database connection"),
            Err(FlagError::DatabaseUnavailable) => {
                // Expected error
            }
            Err(e) => panic!("Unexpected error: {e:?}"),
        }
    }

    #[tokio::test]
    async fn test_fetch_multiple_flags_from_pg() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        let flag1 = FeatureFlagRow {
            id: 0,
            team_id: team.id,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        };

        let flag2 = FeatureFlagRow {
            id: 0,
            team_id: team.id,
            name: Some("Test Flag 2".to_string()),
            key: "test_flag_2".to_string(),
            filters: serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}),
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        };

        // Insert multiple flags for the team
        context
            .insert_flag(team.id, Some(flag1))
            .await
            .expect("Failed to insert flags");

        context
            .insert_flag(team.id, Some(flag2))
            .await
            .expect("Failed to insert flags");

        let flags_from_pg = FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.id)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.len(), 2);
        for flag in &flags_from_pg {
            assert_eq!(flag.team_id, team.id);
        }
    }

    #[tokio::test]
    async fn test_fetch_flags_with_evaluation_tags_from_pg() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        let flag_row = context
            .insert_flag(team.id, None)
            .await
            .expect("Failed to insert flag");

        // Insert evaluation tags for the flag
        context
            .insert_evaluation_tags_for_flag(
                flag_row.id,
                team.id,
                vec!["docs-page", "marketing-site", "app"],
            )
            .await
            .expect("Failed to insert evaluation tags");

        let flags_from_pg = FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.id)
            .await
            .expect("Failed to fetch flags from pg");

        assert_eq!(flags_from_pg.len(), 1);
        let flag = flags_from_pg.first().expect("Should have one flag");
        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);

        // Check that evaluation tags were properly fetched
        let tags = flag
            .evaluation_tags
            .as_ref()
            .expect("Should have evaluation tags");
        assert_eq!(tags.len(), 3);
        assert!(tags.contains(&"docs-page".to_string()));
        assert!(tags.contains(&"marketing-site".to_string()));
        assert!(tags.contains(&"app".to_string()));
    }

    #[tokio::test]
    async fn test_encrypted_remote_config_flags_excluded_from_pg() {
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        let mut conn = context
            .non_persons_writer
            .get_connection()
            .await
            .expect("Failed to get connection");

        // Insert a regular feature flag via raw SQL (is_remote_configuration = false)
        sqlx::query(
            r#"INSERT INTO posthog_featureflag
            (team_id, name, key, filters, deleted, active, ensure_experience_continuity,
             is_remote_configuration, has_encrypted_payloads, created_at)
            VALUES ($1, $2, $3, $4, false, true, false, false, false, '2024-06-17')"#,
        )
        .bind(team.id)
        .bind("Regular Flag")
        .bind("regular_flag")
        .bind(serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}))
        .execute(&mut *conn)
        .await
        .expect("Failed to insert regular flag");

        // Insert an unencrypted remote config flag via raw SQL
        sqlx::query(
            r#"INSERT INTO posthog_featureflag
            (team_id, name, key, filters, deleted, active, ensure_experience_continuity,
             is_remote_configuration, has_encrypted_payloads, created_at)
            VALUES ($1, $2, $3, $4, false, true, false, true, false, '2024-06-17')"#,
        )
        .bind(team.id)
        .bind("Unencrypted Remote Config Flag")
        .bind("unencrypted_remote_config_flag")
        .bind(serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}))
        .execute(&mut *conn)
        .await
        .expect("Failed to insert unencrypted remote config flag");

        // Insert an encrypted remote config flag via raw SQL
        sqlx::query(
            r#"INSERT INTO posthog_featureflag
            (team_id, name, key, filters, deleted, active, ensure_experience_continuity,
             is_remote_configuration, has_encrypted_payloads, created_at)
            VALUES ($1, $2, $3, $4, false, true, false, true, true, '2024-06-17')"#,
        )
        .bind(team.id)
        .bind("Encrypted Remote Config Flag")
        .bind("encrypted_remote_config_flag")
        .bind(serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}))
        .execute(&mut *conn)
        .await
        .expect("Failed to insert encrypted remote config flag");

        let flags_from_pg = FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.id)
            .await
            .expect("Failed to fetch flags from pg");

        // Regular flag and unencrypted remote config flag should be returned
        // Encrypted remote config flag should be excluded
        assert_eq!(flags_from_pg.len(), 2);

        let flag_keys: Vec<&str> = flags_from_pg.iter().map(|f| f.key.as_str()).collect();
        assert!(flag_keys.contains(&"regular_flag"));
        assert!(flag_keys.contains(&"unencrypted_remote_config_flag"));
        assert!(!flag_keys.contains(&"encrypted_remote_config_flag"));
    }

    #[tokio::test]
    async fn test_null_values_included_in_pg_query() {
        // Verify that flags with NULL values for is_remote_configuration and/or
        // has_encrypted_payloads are correctly included (not excluded by the filter).
        // This tests the IS TRUE logic: NULL IS TRUE evaluates to FALSE, so
        // NOT (NULL IS TRUE AND ...) evaluates to TRUE, including the row.
        let context = TestContext::new(None).await;
        let team = context
            .insert_new_team(None)
            .await
            .expect("Failed to insert team");

        let mut conn = context
            .non_persons_writer
            .get_connection()
            .await
            .expect("Failed to get connection");

        // Insert flag with is_remote_configuration = NULL, has_encrypted_payloads = false
        sqlx::query(
            r#"INSERT INTO posthog_featureflag
            (team_id, name, key, filters, deleted, active, ensure_experience_continuity,
             is_remote_configuration, has_encrypted_payloads, created_at)
            VALUES ($1, $2, $3, $4, false, true, false, NULL, false, '2024-06-17')"#,
        )
        .bind(team.id)
        .bind("Null Remote Config Flag")
        .bind("null_remote_config")
        .bind(serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}))
        .execute(&mut *conn)
        .await
        .expect("Failed to insert null remote config flag");

        // Insert flag with is_remote_configuration = true, has_encrypted_payloads = NULL
        sqlx::query(
            r#"INSERT INTO posthog_featureflag
            (team_id, name, key, filters, deleted, active, ensure_experience_continuity,
             is_remote_configuration, has_encrypted_payloads, created_at)
            VALUES ($1, $2, $3, $4, false, true, false, true, NULL, '2024-06-17')"#,
        )
        .bind(team.id)
        .bind("Null Encrypted Flag")
        .bind("null_encrypted")
        .bind(serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}))
        .execute(&mut *conn)
        .await
        .expect("Failed to insert null encrypted flag");

        // Insert legacy flag with both fields NULL
        sqlx::query(
            r#"INSERT INTO posthog_featureflag
            (team_id, name, key, filters, deleted, active, ensure_experience_continuity,
             is_remote_configuration, has_encrypted_payloads, created_at)
            VALUES ($1, $2, $3, $4, false, true, false, NULL, NULL, '2024-06-17')"#,
        )
        .bind(team.id)
        .bind("Legacy Flag")
        .bind("legacy_flag")
        .bind(serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}))
        .execute(&mut *conn)
        .await
        .expect("Failed to insert legacy flag");

        // Insert flag with is_remote_configuration = NULL, has_encrypted_payloads = true
        // This should still be included because is_remote_configuration is not TRUE
        sqlx::query(
            r#"INSERT INTO posthog_featureflag
            (team_id, name, key, filters, deleted, active, ensure_experience_continuity,
             is_remote_configuration, has_encrypted_payloads, created_at)
            VALUES ($1, $2, $3, $4, false, true, false, NULL, true, '2024-06-17')"#,
        )
        .bind(team.id)
        .bind("Null Remote Encrypted True Flag")
        .bind("null_remote_encrypted_true")
        .bind(serde_json::json!({"groups": [{"properties": [], "rollout_percentage": 100}]}))
        .execute(&mut *conn)
        .await
        .expect("Failed to insert null remote encrypted true flag");

        let flags_from_pg = FeatureFlagList::from_pg(context.non_persons_reader.clone(), team.id)
            .await
            .expect("Failed to fetch flags from pg");

        // All flags with NULL values should be included
        assert_eq!(flags_from_pg.len(), 4);

        let flag_keys: Vec<&str> = flags_from_pg.iter().map(|f| f.key.as_str()).collect();
        assert!(
            flag_keys.contains(&"null_remote_config"),
            "Flag with NULL is_remote_configuration should be included"
        );
        assert!(
            flag_keys.contains(&"null_encrypted"),
            "Flag with NULL has_encrypted_payloads should be included"
        );
        assert!(
            flag_keys.contains(&"legacy_flag"),
            "Legacy flag with both NULL should be included"
        );
        assert!(
            flag_keys.contains(&"null_remote_encrypted_true"),
            "Flag with NULL is_remote_configuration and TRUE has_encrypted_payloads should be included"
        );
    }

    #[test]
    fn test_cache_format_backward_compatibility() {
        // This test verifies that the cache format (Vec<FeatureFlag>) remains stable.
        // We cache Vec<FeatureFlag> directly, and any format change would invalidate
        // all existing cache entries, causing a thundering herd of database queries.
        use crate::flags::flag_models::{FeatureFlag, FlagFilters};

        // Create test flags in the format we cache
        let cached_flags = vec![FeatureFlag {
            id: 1,
            team_id: 123,
            name: Some("Test Flag".to_string()),
            key: "test_flag".to_string(),
            filters: FlagFilters::default(),
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: Some("all".to_string()),
            evaluation_tags: None,
            bucketing_identifier: None,
        }];

        // Serialize as we do in production cache
        let cached_json =
            serde_json::to_string(&cached_flags).expect("Failed to serialize flags for cache");

        // Verify we can deserialize it back (cache read path)
        let result = serde_json::from_str::<Vec<FeatureFlag>>(&cached_json);

        assert!(
            result.is_ok(),
            "FAILED: Cannot deserialize cached flags. This indicates a cache format change \
             that will invalidate all existing cache entries, causing thundering herd. \
             Cached JSON: {}\nError: {:?}",
            cached_json,
            result.unwrap_err()
        );

        // Verify the deserialized data is correct
        let deserialized_flags = result.unwrap();
        assert_eq!(deserialized_flags.len(), 1);
        assert_eq!(deserialized_flags[0].key, "test_flag");
        assert_eq!(deserialized_flags[0].id, 1);
    }

    // =========================================================================
    // Tests for from_wrapper()
    // =========================================================================

    use serde_json::json;

    #[test]
    fn test_from_wrapper_valid_flags() {
        let wrapper: HypercacheFlagsWrapper = serde_json::from_value(json!({
            "flags": [
                {
                    "id": 1,
                    "key": "test_flag",
                    "team_id": 123,
                    "active": true,
                    "deleted": false,
                    "filters": { "groups": [] }
                },
                {
                    "id": 2,
                    "key": "another_flag",
                    "team_id": 123,
                    "active": false,
                    "deleted": false,
                    "filters": { "groups": [] }
                }
            ],
            "evaluation_metadata": {
                "dependency_stages": [[1, 2]],
                "flags_with_missing_deps": [],
                "transitive_deps": {}
            }
        }))
        .unwrap();

        let (flags, metadata, _cohorts) =
            FeatureFlagList::from_wrapper(Some(wrapper), 123).unwrap();
        assert_eq!(metadata.dependency_stages, vec![vec![1, 2]]);
        assert!(metadata.flags_with_missing_deps.is_empty());
        assert!(metadata.transitive_deps.is_empty());
        assert_eq!(flags.len(), 2);
        assert_eq!(flags[0].key, "test_flag");
        assert!(flags[0].active);
        assert_eq!(flags[1].key, "another_flag");
        assert!(!flags[1].active);
    }

    #[test]
    fn test_from_wrapper_with_evaluation_context_valid_flags() {
        let wrapper: HypercacheFlagsWrapper = serde_json::from_value(json!({
            "evaluation_metadata": {
                "dependency_stages": [
                    [766, 768, 769],
                    [765]
                ],
                "flags_with_missing_deps": [768],
                "transitive_deps": {
                    "765": [766],
                    "766": [],
                    "768": [],
                    "769": []
                }
            },
            "flags": [
                {
                    "active": true,
                    "bucketing_identifier": null,
                    "deleted": false,
                    "ensure_experience_continuity": false,
                    "evaluation_contexts": [],
                    "evaluation_runtime": "all",
                    "filters": {
                        "groups": [
                            {
                                "properties": [
                                    {
                                        "key": "766",
                                        "label": "client-only-flag",
                                        "operator": "flag_evaluates_to",
                                        "type": "flag",
                                        "value": true
                                    }
                                ],
                                "rollout_percentage": 100,
                                "variant": null
                            }
                        ],
                        "multivariate": null,
                        "payloads": {}
                    },
                    "has_encrypted_payloads": false,
                    "id": 765,
                    "key": "all-flag-with-flag-dependency",
                    "name": "",
                    "team_id": 15,
                    "version": 3
                },
                {
                    "active": true,
                    "bucketing_identifier": null,
                    "deleted": false,
                    "ensure_experience_continuity": false,
                    "evaluation_contexts": [],
                    "evaluation_runtime": "client",
                    "filters": {
                        "groups": [
                            {
                                "properties": [],
                                "rollout_percentage": 100,
                                "variant": null
                            }
                        ],
                        "multivariate": null,
                        "payloads": {}
                    },
                    "has_encrypted_payloads": false,
                    "id": 766,
                    "key": "client-only-flag",
                    "name": "",
                    "team_id": 15,
                    "version": 2
                },
                {
                    "active": true,
                    "bucketing_identifier": null,
                    "deleted": false,
                    "ensure_experience_continuity": false,
                    "evaluation_contexts": [],
                    "evaluation_runtime": "all",
                    "filters": {
                        "groups": [
                            {
                                "properties": [
                                    {
                                        "key": "9999",
                                        "label": "boolean-flag",
                                        "operator": "flag_evaluates_to",
                                        "type": "flag",
                                        "value": true
                                    }
                                ],
                                "rollout_percentage": 100,
                                "variant": null
                            }
                        ],
                        "multivariate": null,
                        "payloads": {}
                    },
                    "has_encrypted_payloads": false,
                    "id": 768,
                    "key": "flag-with-truly-missing-dependency",
                    "name": "",
                    "team_id": 15,
                    "version": 2
                },
                {
                    "active": true,
                    "bucketing_identifier": null,
                    "deleted": false,
                    "ensure_experience_continuity": false,
                    "evaluation_contexts": [],
                    "evaluation_runtime": "all",
                    "filters": {
                        "groups": [
                            {
                                "properties": [
                                    {
                                        "cohort_name": "[Test] Dependent Cohort",
                                        "key": "id",
                                        "operator": "in",
                                        "type": "cohort",
                                        "value": 5
                                    }
                                ],
                                "rollout_percentage": 100,
                                "variant": null
                            }
                        ],
                        "multivariate": null,
                        "payloads": {}
                    },
                    "has_encrypted_payloads": false,
                    "id": 769,
                    "key": "cohort-dependency-flag",
                    "name": "",
                    "team_id": 15,
                    "version": 1
                }
            ]
        }))
        .unwrap();

        let (flags, evaluation_metadata, _cohorts) =
            FeatureFlagList::from_wrapper(Some(wrapper), 123).unwrap();
        assert_eq!(evaluation_metadata.dependency_stages.len(), 2);
        assert_eq!(
            evaluation_metadata.dependency_stages[0],
            vec![766, 768, 769]
        );
        assert_eq!(evaluation_metadata.dependency_stages[1], vec![765]);
        assert_eq!(evaluation_metadata.flags_with_missing_deps, vec![768]);
        assert_eq!(evaluation_metadata.transitive_deps.len(), 4);
        assert_eq!(evaluation_metadata.transitive_deps[&765].len(), 1);
        assert!(evaluation_metadata.transitive_deps[&765].contains(&766));
        assert!(evaluation_metadata.transitive_deps[&766].is_empty());
        assert!(evaluation_metadata.transitive_deps[&768].is_empty());
        assert!(evaluation_metadata.transitive_deps[&769].is_empty());
        assert_eq!(flags.len(), 4);
        assert_eq!(flags[0].key, "all-flag-with-flag-dependency");
        assert!(flags[0].active);
        assert_eq!(flags[1].key, "client-only-flag");
        assert!(flags[1].active);
        assert_eq!(flags[2].key, "flag-with-truly-missing-dependency");
        assert!(flags[2].active);
        assert_eq!(flags[3].key, "cohort-dependency-flag");
        assert!(flags[3].active);
    }

    #[test]
    fn test_from_wrapper_none_returns_empty() {
        let (flags, metadata, cohorts) = FeatureFlagList::from_wrapper(None, 123).unwrap();
        assert!(flags.is_empty());
        assert_eq!(metadata, EvaluationMetadata::default());
        assert!(cohorts.is_none());
    }

    #[test]
    fn test_from_wrapper_empty_flags_array() {
        let wrapper: HypercacheFlagsWrapper = serde_json::from_value(json!({
            "flags": [],
            "evaluation_metadata": {
                "dependency_stages": [],
                "flags_with_missing_deps": [],
                "transitive_deps": {}
            }
        }))
        .unwrap();
        let (flags, metadata, _cohorts) =
            FeatureFlagList::from_wrapper(Some(wrapper), 123).unwrap();
        assert!(flags.is_empty());
        assert_eq!(metadata, EvaluationMetadata::default());
    }

    #[test]
    fn test_from_wrapper_with_all_optional_fields() {
        let wrapper: HypercacheFlagsWrapper = serde_json::from_value(json!({
            "flags": [
                {
                    "id": 42,
                    "key": "full_flag",
                    "team_id": 123,
                    "name": "Full Feature Flag",
                    "active": true,
                    "deleted": false,
                    "filters": {
                        "groups": [{
                            "properties": [{
                                "key": "email",
                                "value": "test@test.com",
                                "type": "person",
                                "operator": "exact"
                            }],
                            "rollout_percentage": 50
                        }]
                    },
                    "ensure_experience_continuity": true,
                    "version": 5,
                    "evaluation_runtime": "frontend"
                }
            ],
            "evaluation_metadata": {
                "dependency_stages": [[42]],
                "flags_with_missing_deps": [],
                "transitive_deps": {}
            }
        }))
        .unwrap();

        let (flags, metadata, _cohorts) =
            FeatureFlagList::from_wrapper(Some(wrapper), 123).unwrap();
        assert_eq!(metadata.dependency_stages, vec![vec![42]]);
        assert!(metadata.flags_with_missing_deps.is_empty());
        assert!(metadata.transitive_deps.is_empty());
        assert_eq!(flags.len(), 1);
        let flag = &flags[0];
        assert_eq!(flag.id, 42);
        assert_eq!(flag.key, "full_flag");
        assert_eq!(flag.name, Some("Full Feature Flag".to_string()));
        assert_eq!(flag.ensure_experience_continuity, Some(true));
        assert_eq!(flag.version, Some(5));
        assert_eq!(flag.evaluation_runtime, Some("frontend".to_string()));
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].rollout_percentage, Some(50.0));
    }

    #[test]
    fn test_from_wrapper_with_cohorts() {
        let wrapper: HypercacheFlagsWrapper = serde_json::from_value(json!({
            "flags": [],
            "evaluation_metadata": {
                "dependency_stages": [],
                "flags_with_missing_deps": [],
                "transitive_deps": {}
            },
            "cohorts": [{
                "id": 42,
                "name": "Test Cohort",
                "description": null,
                "team_id": 123,
                "deleted": false,
                "filters": {"properties": {"type": "AND", "values": []}},
                "query": null,
                "version": 1,
                "pending_version": null,
                "count": 100,
                "is_calculating": false,
                "is_static": false,
                "errors_calculating": 0,
                "groups": [],
                "created_by_id": null,
                "cohort_type": null
            }]
        }))
        .unwrap();
        let (_flags, _metadata, cohorts) =
            FeatureFlagList::from_wrapper(Some(wrapper), 123).unwrap();
        let cohorts = cohorts.expect("cohorts should be Some");
        assert_eq!(cohorts.len(), 1);
        assert_eq!(cohorts[0].id, 42);
        assert_eq!(cohorts[0].name, Some("Test Cohort".to_string()));
        assert_eq!(cohorts[0].team_id, 123);
        assert!(!cohorts[0].deleted);
    }

    #[test]
    fn test_from_wrapper_without_cohorts_defaults_to_none() {
        let wrapper: HypercacheFlagsWrapper = serde_json::from_value(json!({
            "flags": [{
                "id": 1,
                "team_id": 123,
                "name": "flag",
                "key": "flag-key",
                "filters": {"groups": []}
            }],
            "evaluation_metadata": {
                "dependency_stages": [[1]],
                "flags_with_missing_deps": [],
                "transitive_deps": {}
            }
        }))
        .unwrap();
        let (_flags, _metadata, cohorts) =
            FeatureFlagList::from_wrapper(Some(wrapper), 123).unwrap();
        assert!(cohorts.is_none());
    }

    #[test]
    fn test_from_wrapper_empty_stages_with_flags_is_error() {
        let wrapper: HypercacheFlagsWrapper = serde_json::from_value(json!({
            "flags": [
                {"id": 10, "key": "a", "team_id": 1, "active": true, "deleted": false, "filters": {"groups": []}},
                {"id": 20, "key": "b", "team_id": 1, "active": true, "deleted": false, "filters": {"groups": []}}
            ],
            "evaluation_metadata": {
                "dependency_stages": [],
                "flags_with_missing_deps": [],
                "transitive_deps": {}
            }
        }))
        .unwrap();
        let result = FeatureFlagList::from_wrapper(Some(wrapper), 1);
        assert!(matches!(
            result,
            Err(FlagError::DataParsingErrorWithContext(_))
        ));
    }

    #[test]
    fn test_single_stage_places_all_flag_ids_in_one_stage() {
        let flags: Vec<FeatureFlag> = serde_json::from_value(json!([
            {"id": 10, "key": "a", "team_id": 1, "active": true, "deleted": false, "filters": {"groups": []}},
            {"id": 20, "key": "b", "team_id": 1, "active": true, "deleted": false, "filters": {"groups": []}}
        ]))
        .unwrap();

        let meta = EvaluationMetadata::single_stage(&flags);
        assert_eq!(meta.dependency_stages, vec![vec![10, 20]]);
        assert!(meta.flags_with_missing_deps.is_empty());
        // Each flag gets an empty dep set so flag_keys filtering works for independent flags
        assert_eq!(meta.transitive_deps.len(), 2);
        assert!(meta.transitive_deps[&10].is_empty());
        assert!(meta.transitive_deps[&20].is_empty());
    }

    #[test]
    fn test_single_stage_empty_flags() {
        let meta = EvaluationMetadata::single_stage(&[]);
        assert_eq!(meta.dependency_stages, vec![Vec::<i32>::new()]);
        assert!(meta.flags_with_missing_deps.is_empty());
        assert!(meta.transitive_deps.is_empty()); // no flags → genuinely empty
    }

    /// Golden fixture contract test: verifies that Rust can deserialize the hypercache
    /// format that Python produces. If this test fails, you've changed the cache schema
    /// in a way that breaks deserialization.
    ///
    /// See the expand-and-contract process in the HYPERCACHE CONTRACT comments at:
    ///   - posthog/api/feature_flag.py (MinimalFeatureFlagSerializer)
    ///   - rust/feature-flags/src/flags/flag_models.rs (FeatureFlag struct)
    #[test]
    fn test_hypercache_contract() {
        let fixture = include_str!("../../tests/fixtures/hypercache_contract.json");
        let wrapper: HypercacheFlagsWrapper = serde_json::from_str(fixture).expect(
            "Failed to deserialize hypercache_contract.json as HypercacheFlagsWrapper. \
             The fixture file must be valid JSON matching the wrapper schema.",
        );

        let result = FeatureFlagList::from_wrapper(Some(wrapper), 99);
        let (flags, metadata, cohorts) = result.expect(
            "\n\
             ==============================================================================\n\
             WARNING: HYPERCACHE BOUNDARY CONTRACT VIOLATION\n\
             ==============================================================================\n\n\
             Rust failed to deserialize the golden fixture. This means a schema change\n\
             has broken the cache format that Python writes and Rust reads.\n\n\
             DO NOT just update the fixture or tweak the struct to make this test green.\n\
             The Python serializer is already writing this shape to production caches.\n\n\
             Before proceeding, consider:\n\
             \x20 1. Is the change backwards-compatible? (adding a new Optional/default\n\
             \x20    field is usually safe; renaming/removing a field is not)\n\
             \x20 2. Do you need a phased rollout? Schema changes must follow\n\
             \x20    expand-and-contract:\n\
             \x20    a. Add #[serde(default)] or #[serde(alias = ...)] in Rust, deploy\n\
             \x20    b. Change Python serializer, deploy, run warm_flags_cache\n\
             \x20    c. Remove compatibility shim in follow-up PR\n\
             \x20 3. Will the cache need re-warming? Old cached payloads will still\n\
             \x20    have the previous shape until they expire or are invalidated.\n\n\
             See: rust/feature-flags/tests/fixtures/hypercache_contract.json\n\
             ==============================================================================",
        );

        // Verify flags parsed correctly
        assert_eq!(flags.len(), 5, "Expected 5 flags in contract fixture");

        // Full flag with all optional fields
        let full_flag = &flags[0];
        assert_eq!(full_flag.key, "full-flag");
        assert_eq!(full_flag.id, 1);
        assert!(full_flag.active);
        assert!(!full_flag.deleted);
        assert_eq!(full_flag.ensure_experience_continuity, Some(true));
        assert_eq!(full_flag.version, Some(3));
        assert_eq!(full_flag.evaluation_runtime, Some("all".to_string()));
        assert_eq!(
            full_flag.bucketing_identifier,
            Some("device_id".to_string())
        );
        // evaluation_contexts is aliased to evaluation_tags in Rust
        let tags = full_flag
            .evaluation_tags
            .as_ref()
            .expect("evaluation_tags (aliased from evaluation_contexts) should be present");
        assert_eq!(
            tags,
            &vec!["docs-page".to_string(), "marketing-site".to_string()]
        );
        // Filter structure
        assert_eq!(full_flag.filters.groups.len(), 1);
        assert!(full_flag.filters.multivariate.is_some());
        assert!(full_flag.filters.super_groups.is_some());
        assert_eq!(full_flag.filters.feature_enrollment, Some(true));
        assert!(full_flag.filters.holdout.is_some());
        let holdout = full_flag.filters.holdout.as_ref().unwrap();
        assert_eq!(holdout.id, 42);
        assert!((holdout.exclusion_percentage - 10.0).abs() < f64::EPSILON);

        // Minimal flag: verify defaults for absent optional fields
        let minimal_flag = &flags[1];
        assert_eq!(minimal_flag.key, "minimal-flag");
        assert_eq!(minimal_flag.ensure_experience_continuity, Some(false));
        assert!(minimal_flag.bucketing_identifier.is_none());
        assert!(minimal_flag.filters.multivariate.is_none());

        // Cohort flag: verify cohort property type parsed
        let cohort_flag = &flags[2];
        assert_eq!(cohort_flag.key, "cohort-flag");
        assert_eq!(cohort_flag.filters.groups.len(), 1);

        // Flag with dependency: verify dependency property type parsed
        let dep_flag = &flags[3];
        assert_eq!(dep_flag.key, "dependent-flag");
        assert_eq!(dep_flag.filters.groups.len(), 1);
        assert_eq!(dep_flag.version, Some(2));

        // Flag with missing dependency: verify it parses despite referencing a nonexistent flag
        let missing_dep_flag = &flags[4];
        assert_eq!(missing_dep_flag.key, "missing-dep-flag");
        assert_eq!(missing_dep_flag.filters.groups.len(), 1);

        // Verify evaluation_metadata parsed correctly
        let meta = metadata;
        assert_eq!(meta.dependency_stages.len(), 2);
        assert_eq!(meta.dependency_stages[0], vec![1, 2, 3, 5]);
        assert_eq!(meta.dependency_stages[1], vec![4]);
        assert_eq!(meta.flags_with_missing_deps, vec![5]);
        assert_eq!(meta.transitive_deps.len(), 5);
        assert!(meta.transitive_deps[&4].contains(&2));

        // Verify cohorts parsed correctly
        let cohorts = cohorts.expect("cohorts should be present in contract fixture");
        assert_eq!(cohorts.len(), 1);
        assert_eq!(cohorts[0].id, 100);
        assert_eq!(cohorts[0].name, Some("Test Cohort".to_string()));
        assert_eq!(cohorts[0].team_id, 99);
        assert!(!cohorts[0].deleted);

        assert!(
            cohorts[0].last_backfill_person_properties_at.is_some(),
            "last_backfill_person_properties_at should deserialize from ISO 8601 timestamp"
        );

        // Verify cohort filters can parse into the expected CohortProperty structure
        let filters_value = cohorts[0]
            .filters
            .as_ref()
            .expect("cohort should have filters");
        let _parsed: crate::cohorts::cohort_models::CohortProperty =
            serde_json::from_value(filters_value.clone())
                .expect("Cohort filters should parse as CohortProperty");
    }

    #[test]
    fn test_prepare_regexes_compiles_regex_filters_only() {
        let mut flag_list = FeatureFlagList::new(vec![FeatureFlag {
            id: 1,
            team_id: 1,
            name: None,
            key: "test_flag".to_string(),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![
                        PropertyFilter {
                            key: "email".to_string(),
                            value: Some(json!(r"^test@.*\.com$")),
                            operator: Some(OperatorType::Regex),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                            compiled_regex: None,
                        },
                        PropertyFilter {
                            key: "name".to_string(),
                            value: Some(json!("Alice")),
                            operator: Some(OperatorType::Exact),
                            prop_type: PropertyType::Person,
                            group_type_index: None,
                            negation: None,
                            compiled_regex: None,
                        },
                    ]),
                    rollout_percentage: Some(100.0),
                    ..Default::default()
                }],
                multivariate: None,
                aggregation_group_type_index: None,
                payloads: None,
                super_groups: None,
                feature_enrollment: None,
                holdout: None,
            },
            active: true,
            deleted: false,
            ensure_experience_continuity: None,
            version: None,
            evaluation_runtime: None,
            evaluation_tags: None,
            bucketing_identifier: None,
        }]);

        flag_list.prepare_regexes();

        let props = flag_list.flags[0].filters.groups[0]
            .properties
            .as_ref()
            .unwrap();
        assert!(
            matches!(
                props[0].compiled_regex,
                Some(crate::properties::property_models::CompiledRegex::Compiled(
                    _
                ))
            ),
            "Regex filter should have compiled regex"
        );
        assert!(
            props[1].compiled_regex.is_none(),
            "Exact filter should NOT have compiled regex"
        );
    }

    // =========================================================================
    // Tests for evaluation_contexts JSON key (renamed from evaluation_tags)
    // =========================================================================

    #[test]
    fn test_deserialize_flag_with_evaluation_contexts() {
        // Cache entries use `evaluation_contexts` key (renamed from `evaluation_tags` in PR #52186)
        let data = json!({
            "id": 1,
            "key": "test_flag",
            "team_id": 123,
            "active": true,
            "deleted": false,
            "filters": { "groups": [] },
            "evaluation_contexts": ["app", "dashboard"]
        });

        let flag: FeatureFlag =
            serde_json::from_value(data).expect("Should deserialize with evaluation_contexts");
        assert_eq!(flag.key, "test_flag");
        // Rust field is still named `evaluation_tags` for internal compatibility
        let tags = flag.evaluation_tags.expect("Should have evaluation_tags");
        assert_eq!(tags.len(), 2);
        assert!(tags.contains(&"app".to_string()));
        assert!(tags.contains(&"dashboard".to_string()));
    }

    #[test]
    fn test_deserialize_flag_without_evaluation_contexts() {
        let data = json!({
            "id": 2,
            "key": "no_contexts_flag",
            "team_id": 123,
            "active": true,
            "deleted": false,
            "filters": { "groups": [] }
        });

        let flag: FeatureFlag =
            serde_json::from_value(data).expect("Should deserialize without evaluation_contexts");
        assert_eq!(flag.key, "no_contexts_flag");
        assert!(flag.evaluation_tags.is_none());
    }

    #[test]
    fn test_serialize_flag_uses_evaluation_contexts_key() {
        let flag = FeatureFlag {
            id: 3,
            team_id: 123,
            name: Some("Serialization Test".to_string()),
            key: "serialize_test".to_string(),
            filters: FlagFilters::default(),
            deleted: false,
            active: true,
            ensure_experience_continuity: None,
            version: None,
            evaluation_runtime: None,
            evaluation_tags: Some(vec!["context-1".to_string(), "context-2".to_string()]),
            bucketing_identifier: None,
        };

        let json_str = serde_json::to_string(&flag).expect("Should serialize");
        // Rust field `evaluation_tags` serializes to JSON key `evaluation_contexts`
        assert!(
            json_str.contains("evaluation_contexts"),
            "Should use evaluation_contexts key when serializing"
        );
        assert!(
            !json_str.contains("evaluation_tags"),
            "Should NOT use evaluation_tags key when serializing"
        );
    }
}
