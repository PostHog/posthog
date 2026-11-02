//! The Postgres-backed dependencies against the local Django test database. Each test inserts
//! its own organization, project and team and removes everything it wrote. Skips without
//! Postgres.

use std::sync::Arc;

use logs_ingestion::metric_rules::MetricRulesSource;
use logs_ingestion::pipeline::errors::is_dependency_unavailable;
use logs_ingestion::pipeline::{
    PatternMessageKeysSource, RetentionRulesSource, SamplingRulesSource, TeamManager,
    TracingConfigSource,
};
use logs_ingestion::service::postgres::{
    PgMetricRules, PgPatternMessageKeys, PgRetentionRules, PgSamplingRules, PgTeamManager,
    PgTracingConfig,
};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;

const DATABASE_URL: &str = "postgres://posthog:posthog@localhost:5432/test_posthog";

struct SeededTeam {
    pool: PgPool,
    id: i32,
    organization_id: uuid::Uuid,
    token: String,
}

impl SeededTeam {
    /// Inserts its own organization, project and team, so it needs no existing rows.
    async fn create(pool: PgPool, logs_settings: &str) -> Self {
        let mut tx = pool.begin().await.unwrap();
        let id: i32 = sqlx::query_scalar("SELECT nextval('posthog_team_id_seq')::int")
            .fetch_one(&mut *tx)
            .await
            .unwrap();
        let organization_id = uuid::Uuid::now_v7();
        let token = format!("phc_rust_logs_test_{id}");
        sqlx::query(
            r#"INSERT INTO posthog_organization
            (id, name, slug, created_at, updated_at, plugins_access_level, for_internal_metrics, is_member_join_email_enabled, enforce_2fa, customer_id, available_product_features, personalization, setup_section_2_completed, domain_whitelist, members_can_use_personal_api_keys, allow_publicly_shared_resources, default_anonymize_ips)
            VALUES ($1, 'Rust logs test', $2, now(), now(), 9, false, true, NULL, NULL, '{}', '{}', true, '{}', true, true, false)"#,
        )
        .bind(organization_id)
        .bind(format!("rust-logs-test-{}", organization_id.simple()))
        .execute(&mut *tx)
        .await
        .unwrap();
        sqlx::query(
            "INSERT INTO posthog_project (id, organization_id, name, created_at) VALUES ($1, $2, 'Rust logs test', now())",
        )
        .bind(id)
        .bind(organization_id)
        .execute(&mut *tx)
        .await
        .unwrap();
        sqlx::query(
            r#"INSERT INTO posthog_team
            (id, uuid, organization_id, project_id, api_token, name, created_at, updated_at, app_urls, anonymize_ips, completed_snippet_onboarding, ingested_event, session_recording_opt_in, is_demo, access_control, test_account_filters, timezone, data_attributes, plugins_opt_in, opt_out_capture, event_names, event_names_with_usage, event_properties, event_properties_with_usage, event_properties_numerical, cookieless_server_hash_mode, base_currency, session_recording_retention_period, web_analytics_pre_aggregated_tables_enabled, logs_settings)
            VALUES ($1, $2, $3, $1, $4, 'Rust logs test', now(), now(), '{}', false, false, false, false, false, false, '{}', 'UTC', '["data-attr"]', false, false, '[]', '[]', '[]', '[]', '[]', 0, 'USD', '30d', false, $5::jsonb)"#,
        )
        .bind(id)
        .bind(uuid::Uuid::now_v7())
        .bind(organization_id)
        .bind(&token)
        .bind(logs_settings)
        .execute(&mut *tx)
        .await
        .unwrap();
        tx.commit().await.unwrap();
        Self {
            pool,
            id,
            organization_id,
            token,
        }
    }

    async fn cleanup(&self) {
        for table in [
            "logs_logsexclusionrule",
            "logs_logsretentionrule",
            "tracing_tracesretentionrule",
            "logs_logsmetricrule",
            "logs_teamlogsconfig",
            "tracing_teamtracingconfig",
        ] {
            sqlx::query(&format!("DELETE FROM {table} WHERE team_id = $1"))
                .bind(self.id)
                .execute(&self.pool)
                .await
                .unwrap();
        }
        for (sql, id) in [
            ("DELETE FROM posthog_team WHERE id = $1", self.id),
            ("DELETE FROM posthog_project WHERE id = $1", self.id),
        ] {
            sqlx::query(sql).bind(id).execute(&self.pool).await.unwrap();
        }
        sqlx::query("DELETE FROM posthog_organization WHERE id = $1")
            .bind(self.organization_id)
            .execute(&self.pool)
            .await
            .unwrap();
    }
}

async fn pool() -> Option<PgPool> {
    match PgPoolOptions::new()
        .max_connections(4)
        .connect(DATABASE_URL)
        .await
    {
        Ok(p) => Some(p),
        Err(e) => {
            eprintln!("skipping: no Postgres at {DATABASE_URL}: {e}");
            None
        }
    }
}

#[tokio::test]
async fn team_manager_reads_teams_and_writes_ingested_event_once() {
    let Some(pool) = pool().await else { return };
    let team = SeededTeam::create(
        pool.clone(),
        r#"{"json_parse_logs": true, "retention_days": 30}"#,
    )
    .await;
    let manager = PgTeamManager::new(pool.clone(), Some(pool.clone()));
    let by_token = manager
        .get_team_by_token(&team.token)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(by_token.id, team.id as i64);
    let settings = by_token.logs_settings.clone().unwrap();
    assert_eq!(settings.json_parse_logs, Some(true));
    assert_eq!(settings.retention_days, Some(30.0));
    assert_eq!(
        manager.get_team(team.id as i64).await.unwrap(),
        Some(by_token)
    );
    assert_eq!(
        manager
            .get_team_by_token("phc_rust_logs_no_such_token")
            .await
            .unwrap(),
        None
    );
    assert_eq!(manager.get_team(0).await.unwrap(), None);

    let read_only = PgTeamManager::new(pool.clone(), None);
    read_only
        .set_teams_ingested_data(&[team.id as i64])
        .await
        .unwrap();
    let ingested: bool =
        sqlx::query_scalar("SELECT ingested_event FROM posthog_team WHERE id = $1")
            .bind(team.id)
            .fetch_one(&pool)
            .await
            .unwrap();
    assert!(!ingested, "a manager without a writer must not write");
    manager
        .set_teams_ingested_data(&[team.id as i64, team.id as i64])
        .await
        .unwrap();
    let ingested: bool =
        sqlx::query_scalar("SELECT ingested_event FROM posthog_team WHERE id = $1")
            .bind(team.id)
            .fetch_one(&pool)
            .await
            .unwrap();
    assert!(ingested);
    team.cleanup().await;
}

#[tokio::test]
async fn rule_caches_read_the_same_rows_as_node() {
    let Some(pool) = pool().await else { return };
    let team = SeededTeam::create(pool.clone(), "null").await;
    let id = team.id;
    for (priority, rule_type, enabled) in [
        (2, "path_drop", true),
        (1, "severity_sampling", true),
        (0, "path_drop", false),
    ] {
        sqlx::query(
            "INSERT INTO logs_logsexclusionrule (id, team_id, created_at, name, enabled, priority, rule_type, \
             scope_service, scope_attribute_filters, config, version) \
             VALUES (gen_random_uuid(), $1, now(), 'r', $2, $3, $4, 'svc', '[]', $5::jsonb, 3)",
        )
        .bind(id)
        .bind(enabled)
        .bind(priority)
        .bind(rule_type)
        .bind(r#"{"actions": {"DEBUG": {"type": "drop"}}, "patterns": []}"#)
        .execute(&pool)
        .await
        .unwrap();
    }
    let sampling = PgSamplingRules::new(pool.clone());
    let set = sampling.get_compiled_rule_set(id as i64).await.unwrap();
    assert_eq!(set.rules.len(), 2, "disabled rules are skipped");
    assert!(
        Arc::ptr_eq(
            &set,
            &sampling.get_compiled_rule_set(id as i64).await.unwrap()
        ),
        "cached for 30s"
    );

    sqlx::query(
        "INSERT INTO logs_logsretentionrule (id, team_id, created_at, name, enabled, priority, config, version) \
         VALUES (gen_random_uuid(), $1, now(), 'keep', true, 0, '{\"retention_days\": 30}', 1), \
                (gen_random_uuid(), $1, now(), 'bad tier', true, 1, '{\"retention_days\": 31}', 1)",
    )
    .bind(id)
    .execute(&pool)
    .await
    .unwrap();
    let retention = PgRetentionRules::new(pool.clone());
    let logs_rules = retention
        .get_compiled_rule_set(id as i64, "logs")
        .await
        .unwrap();
    assert_eq!(logs_rules.rules.len(), 1);
    assert_eq!(logs_rules.rules[0].retention_days, 30);
    assert!(retention
        .get_compiled_rule_set(id as i64, "spans")
        .await
        .unwrap()
        .rules
        .is_empty());

    sqlx::query(
        "INSERT INTO logs_logsmetricrule (id, team_id, created_at, name, metric_name, enabled, filter_group, \
         value_attribute, group_by, source, version) \
         VALUES (gen_random_uuid(), $1, now(), 'm', 'errors_total', true, NULL, NULL, ARRAY['service_name'], 'logs', 1)",
    )
    .bind(id)
    .execute(&pool)
    .await
    .unwrap();
    let metric = PgMetricRules::new(pool.clone())
        .get_compiled_rules(id as i64)
        .await
        .unwrap();
    assert_eq!(metric.len(), 1);
    assert_eq!(metric[0].metric_name.to_string(), "errors_total");
    assert_eq!(
        metric[0]
            .group_by
            .iter()
            .map(|g| g.to_string())
            .collect::<Vec<_>>(),
        vec!["service_name"]
    );

    let keys = PgPatternMessageKeys::new(pool.clone());
    assert_eq!(
        keys.get_message_keys(id as i64).await.unwrap(),
        vec!["message", "msg", "event"]
    );
    sqlx::query("INSERT INTO logs_teamlogsconfig (team_id, logs_pattern_message_keys) VALUES ($1, ARRAY['text'])")
        .bind(id)
        .execute(&pool)
        .await
        .unwrap();
    assert_eq!(
        PgPatternMessageKeys::new(pool.clone())
            .get_message_keys(id as i64)
            .await
            .unwrap(),
        vec!["text"]
    );

    let tracing_config = PgTracingConfig::new(pool.clone());
    assert_eq!(
        tracing_config.get_retention_days(id as i64).await.unwrap(),
        14.0
    );
    sqlx::query("INSERT INTO tracing_teamtracingconfig (team_id, retention_days) VALUES ($1, 90)")
        .bind(id)
        .execute(&pool)
        .await
        .unwrap();
    assert_eq!(
        PgTracingConfig::new(pool.clone())
            .get_retention_days(id as i64)
            .await
            .unwrap(),
        90.0
    );
    team.cleanup().await;
}

#[tokio::test]
async fn an_unreachable_database_is_dependency_unavailable_where_node_throws() {
    let pool = PgPoolOptions::new()
        .acquire_timeout(std::time::Duration::from_millis(500))
        .connect_lazy("postgres://x:x@127.0.0.1:1/x")
        .unwrap();
    let teams = PgTeamManager::new(pool.clone(), None);
    assert!(is_dependency_unavailable(
        &teams.get_team_by_token("t").await.unwrap_err()
    ));
    assert!(is_dependency_unavailable(
        &PgSamplingRules::new(pool.clone())
            .get_compiled_rule_set(1)
            .await
            .unwrap_err()
    ));
    // Retention fails open; tracing config and pattern keys throw only with nothing cached.
    assert!(PgRetentionRules::new(pool.clone())
        .get_compiled_rule_set(1, "logs")
        .await
        .unwrap()
        .rules
        .is_empty());
    assert!(is_dependency_unavailable(
        &PgTracingConfig::new(pool.clone())
            .get_retention_days(1)
            .await
            .unwrap_err()
    ));
    assert!(is_dependency_unavailable(
        &PgPatternMessageKeys::new(pool.clone())
            .get_message_keys(1)
            .await
            .unwrap_err()
    ));
}
