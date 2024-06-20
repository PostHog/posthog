use anyhow::Error;
use serde_json::json;
use std::sync::Arc;
use std::{fs, process::Command};
use uuid::Uuid;

use crate::{
    database::{Client as DatabaseClientTrait, PgClient},
    flag_definitions::{self, FeatureFlag, FeatureFlagRow},
    redis::{Client as RedisClientTrait, RedisClient},
    team::{self, Team},
};
use rand::{distributions::Alphanumeric, Rng};

pub fn random_string(prefix: &str, length: usize) -> String {
    let suffix: String = rand::thread_rng()
        .sample_iter(Alphanumeric)
        .take(length)
        .map(char::from)
        .collect();
    format!("{}{}", prefix, suffix)
}

pub async fn insert_new_team_in_redis(client: Arc<RedisClient>) -> Result<Team, Error> {
    let id = rand::thread_rng().gen_range(0..10_000_000);
    let token = random_string("phc_", 12);
    let team = Team {
        id,
        name: "team".to_string(),
        api_token: token,
    };

    let serialized_team = serde_json::to_string(&team)?;
    client
        .set(
            format!(
                "{}{}",
                team::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await?;

    Ok(team)
}

pub async fn insert_flags_for_team_in_redis(
    client: Arc<RedisClient>,
    team_id: i32,
    json_value: Option<String>,
) -> Result<(), Error> {
    let payload = match json_value {
        Some(value) => value,
        None => json!([{
            "id": 1,
            "key": "flag1",
            "name": "flag1 description",
            "active": true,
            "deleted": false,
            "team_id": team_id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "a@b.com",
                                "type": "person",
                            },
                        ]
                    },
                ],
            },
        }])
        .to_string(),
    };

    client
        .set(
            format!("{}{}", flag_definitions::TEAM_FLAGS_CACHE_PREFIX, team_id),
            payload,
        )
        .await?;

    Ok(())
}

pub fn setup_redis_client(url: Option<String>) -> Arc<RedisClient> {
    let redis_url = match url {
        Some(value) => value,
        None => "redis://localhost:6379/".to_string(),
    };
    let client = RedisClient::new(redis_url).expect("Failed to create redis client");
    Arc::new(client)
}

pub fn create_flag_from_json(json_value: Option<String>) -> Vec<FeatureFlag> {
    let payload = match json_value {
        Some(value) => value,
        None => json!([{
            "id": 1,
            "key": "flag1",
            "name": "flag1 description",
            "active": true,
            "deleted": false,
            "team_id": 1,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "a@b.com",
                                "type": "person",
                            },
                        ],
                        "rollout_percentage": 50,
                    },
                ],
            },
        }])
        .to_string(),
    };

    let flags: Vec<FeatureFlag> =
        serde_json::from_str(&payload).expect("Failed to parse data to flags list");
    flags
}

pub async fn setup_pg_client(url: Option<String>) -> Arc<PgClient> {
    let pg_url = match url {
        Some(value) => value,
        None => "postgres://posthog:posthog@localhost:5432/test_posthog".to_string(),
    };
    let client = PgClient::new(pg_url)
        .await
        .expect("Failed to create pg client");
    Arc::new(client)
}

/// Run the Python migration script
pub fn run_database_migrations() -> anyhow::Result<()> {
    // TODO: Make this more efficient by skipping migrations if they have already been run.
    // TODO: Potentially create a separate db, test_posthog_rs, and use here.
    // TODO: Running this in every test is too slow, can I create some setup where this runs only once, and all tests run after?
    // Seems doable easily in CI, how about local dev? Potentially just make it a manual step for now.
    // "Make sure db exists first by running this fn", and then tests will work.....

    let home_directory = fs::canonicalize("../../").expect("Failed to get home directory");
    let output = Command::new("python")
        .current_dir(home_directory)
        .arg("manage.py")
        .arg("migrate")
        .env("DEBUG", "1")
        .env(
            "DATABASE_URL",
            "postgres://posthog:posthog@localhost:5432/test_posthog",
        )
        .output()
        .expect("Failed to execute migration script");

    if !output.status.success() {
        eprintln!(
            "Migration script failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        return Err(anyhow::anyhow!("Migration script execution failed"));
    }

    println!(
        "Migration script output: {}",
        String::from_utf8_lossy(&output.stdout)
    );

    Ok(())
}

pub async fn insert_new_team_in_pg(client: Arc<PgClient>) -> Result<Team, Error> {
    const ORG_ID: &str = "019026a4be8000005bf3171d00629163";

    let result = client
        .run_query(
            "SELECT 1 FROM posthog_organization where id = $1::uuid".to_string(),
            vec![ORG_ID.to_string()],
            Some(2000),
        )
        .await?;
    if result.len() == 0 {
        client.run_query(
            r#"INSERT INTO posthog_organization
            (id, name, slug, created_at, updated_at, plugins_access_level, for_internal_metrics, is_member_join_email_enabled, enforce_2fa, is_hipaa, customer_id, available_product_features, personalization, setup_section_2_completed, domain_whitelist) 
            VALUES
            ($1::uuid, 'Test Organization', 'test-organization', '2024-06-17 14:40:49.298579+00:00', '2024-06-17 14:40:49.298593+00:00', 9, false, true, NULL, false, NULL, '{}', '{}', true, '{}')"#.to_string(),
            vec![ORG_ID.to_string()],
            Some(2000),
        ).await?;
    }

    let result = client
        .run_query(
            "SELECT 1 FROM posthog_project where organization_id = $1::uuid".to_string(),
            vec![ORG_ID.to_string()],
            Some(2000),
        )
        .await?;
    if result.len() == 0 {
        client
            .run_query(
                r#"INSERT INTO posthog_project
            (id, organization_id, name, created_at) 
            VALUES
            (1, $1::uuid, 'Test Team', '2024-06-17 14:40:51.329772+00:00')"#
                    .to_string(),
                vec![ORG_ID.to_string()],
                Some(2000),
            )
            .await?;
    }

    let id = rand::thread_rng().gen_range(0..10_000_000);
    let token = random_string("phc_", 12);
    let team = Team {
        id,
        name: "team".to_string(),
        api_token: token,
    };
    let uuid = Uuid::now_v7();

    // INSERT INTO "posthog_organization" ("id", "name", "slug", "created_at", "updated_at", "plugins_access_level", "for_internal_metrics", "is_member_join_email_enabled", "enforce_2fa", "is_hipaa", "customer_id", "available_product_features", "usage", "never_drop_data", "customer_trust_scores", "setup_section_2_completed", "personalization", "domain_whitelist") VALUES ('019026a4be8000005bf3171d00629163'::uuid, 'Test Organization', 'test-organization', '2024-06-17 14:40:49.298579+00:00'::timestamptz, '2024-06-17 14:40:49.298593+00:00'::timestamptz, 9, false, true, NULL, false, NULL,  E'{"{\\"key\\": \\"zapier\\", \\"name\\": \\"Zapier\\"}","{\\"key\\": \\"organizations_projects\\", \\"name\\": \\"Organizations_projects\\"}","{\\"key\\": \\"social_sso\\", \\"name\\": \\"Social_sso\\"}","{\\"key\\": \\"ingestion_taxonomy\\", \\"name\\": \\"Ingestion_taxonomy\\"}","{\\"key\\": \\"paths_advanced\\", \\"name\\": \\"Paths_advanced\\"}","{\\"key\\": \\"correlation_analysis\\", \\"name\\": \\"Correlation_analysis\\"}","{\\"key\\": \\"group_analytics\\", \\"name\\": \\"Group_analytics\\"}","{\\"key\\": \\"tagging\\", \\"name\\": \\"Tagging\\"}","{\\"key\\": \\"behavioral_cohort_filtering\\", \\"name\\": \\"Behavioral_cohort_filtering\\"}","{\\"key\\": \\"white_labelling\\", \\"name\\": \\"White_labelling\\"}","{\\"key\\": \\"subscriptions\\", \\"name\\": \\"Subscriptions\\"}","{\\"key\\": \\"app_metrics\\", \\"name\\": \\"App_metrics\\"}","{\\"key\\": \\"recordings_playlists\\", \\"name\\": \\"Recordings_playlists\\"}","{\\"key\\": \\"recordings_file_export\\", \\"name\\": \\"Recordings_file_export\\"}","{\\"key\\": \\"recordings_performance\\", \\"name\\": \\"Recordings_performance\\"}","{\\"key\\": \\"advanced_permissions\\", \\"name\\": \\"Advanced_permissions\\"}","{\\"key\\": \\"project_based_permissioning\\", \\"name\\": \\"Project_based_permissioning\\"}","{\\"key\\": \\"saml\\", \\"name\\": \\"Saml\\"}","{\\"key\\": \\"sso_enforcement\\", \\"name\\": \\"Sso_enforcement\\"}","{\\"key\\": \\"role_based_access\\", \\"name\\": \\"Role_based_access\\"}"}'::jsonb[]::jsonb[], NULL, false, '{}'::jsonb, true, '{}'::jsonb, '{}'::varchar(256)[])
    // INSERT INTO "posthog_project" ("id", "organization_id", "name", "created_at") VALUES (2, '019026a4be8000005bf3171d00629163'::uuid, 'Test Team', '2024-06-17 14:40:51.329772+00:00'::timestamptz)

    // INSERT INTO "posthog_team" (
    //     "id", "uuid", "organization_id", "project_id", "api_token", "app_urls", "name", "slack_incoming_webhook", "created_at", "updated_at", "anonymize_ips", "completed_snippet_onboarding", "has_completed_onboarding_for", "ingested_event", "autocapture_opt_out", "autocapture_exceptions_opt_in", "autocapture_exceptions_errors_to_ignore", "session_recording_opt_in", "session_recording_sample_rate", "session_recording_minimum_duration_milliseconds", "session_recording_linked_flag", "session_recording_network_payload_capture_config", "session_replay_config", "capture_console_log_opt_in", "capture_performance_opt_in", "surveys_opt_in", "heatmaps_opt_in", "session_recording_version", "signup_token", "is_demo", "access_control", "week_start_day", "inject_web_apps", "test_account_filters", "test_account_filters_default_checked", "path_cleaning_filters", "timezone", "data_attributes", "person_display_name_properties", "live_events_columns", "recording_domains", "primary_dashboard_id", "extra_settings", "modifiers", "correlation_config", "session_recording_retention_period_days", "plugins_opt_in", "opt_out_capture", "event_names", "event_names_with_usage", "event_properties", "event_properties_with_usage", "event_properties_numerical", "external_data_workspace_id", "external_data_workspace_last_synced_at"
    // ) VALUES (2, '019026a4c68300002ff1015e22e8aca6'::uuid, '019026a4be8000005bf3171d00629163'::uuid, 2, 'phc_rfwf8k5LWPLIGSCTtNUfpX6Bl642gNQFTmUOC1lgjlC', '{}'::varchar(200)[], 'Test Team', NULL, '2024-06-17 14:40:51.332036+00:00'::timestamptz, '2024-06-17 14:40:51.332047+00:00'::timestamptz, false, false, NULL, false, NULL, NULL, NULL, false, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, false, NULL, NULL, '[]'::jsonb, NULL, '[]'::jsonb, 'UTC', '["data-attr"]'::jsonb, NULL::varchar(400)[], NULL::text[], NULL::varchar(200)[], NULL, NULL, NULL, '{}'::jsonb, NULL, false, false, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL) RETURNING "posthog_team"."id"

    let mut conn = client.get_connection().await?;
    let res = sqlx::query(
        r#"INSERT INTO posthog_team 
        (id, uuid, organization_id, project_id, api_token, name, created_at, updated_at, app_urls, anonymize_ips, completed_snippet_onboarding, ingested_event, session_recording_opt_in, is_demo, access_control, test_account_filters, timezone, data_attributes, plugins_opt_in, opt_out_capture, event_names, event_names_with_usage, event_properties, event_properties_with_usage, event_properties_numerical) VALUES
        ($1, $5, $2::uuid, 1, $3, $4, '2024-06-17 14:40:51.332036+00:00', '2024-06-17', '{}', false, false, false, false, false, false, '{}', 'UTC', '["data-attr"]', false, false, '[]', '[]', '[]', '[]', '[]')"#
    ).bind(team.id).bind(ORG_ID).bind(&team.api_token).bind(&team.name).bind(uuid).execute(&mut *conn).await?;

    assert_eq!(res.rows_affected(), 1);

    Ok(team)
}

pub async fn insert_flags_for_team_in_pg(
    client: Arc<PgClient>,
    team_id: i32,
    flag: Option<FeatureFlagRow>,
) -> Result<FeatureFlagRow, Error> {
    let id = rand::thread_rng().gen_range(0..10_000_000);

    let payload_flag = match flag {
        Some(value) => value,
        None => FeatureFlagRow {
            id: id,
            key: "flag1".to_string(),
            name: Some("flag1 description".to_string()),
            active: true,
            deleted: false,
            ensure_experience_continuity: false,
            team_id,
            filters: json!({
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "a@b.com",
                                "type": "person",
                            },
                        ],
                        "rollout_percentage": 50,
                    },
                ],
            }),
        },
    };

    // "SELECT id, team_id, name, key, filters, deleted, active, ensure_experience_continuity FROM posthog_featureflag WHERE team_id = $1";

    let mut conn = client.get_connection().await?;
    let res = sqlx::query(
        r#"INSERT INTO posthog_featureflag
        (id, team_id, name, key, filters, deleted, active, ensure_experience_continuity, created_at) VALUES
        ($1, $2, $3, $4, $5, $6, $7, $8, '2024-06-17')"#
    ).bind(payload_flag.id).bind(team_id).bind(&payload_flag.name).bind(&payload_flag.key).bind(&payload_flag.filters).bind(payload_flag.deleted).bind(payload_flag.active).bind(payload_flag.ensure_experience_continuity).execute(&mut *conn).await?;

    assert_eq!(res.rows_affected(), 1);

    Ok(payload_flag)
}
