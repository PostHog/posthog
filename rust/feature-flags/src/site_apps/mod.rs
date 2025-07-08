use crate::api::errors::FlagError;
use chrono::{DateTime, Utc};
use common_database::PostgresReader;
use md5;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WebJsSource {
    pub id: i32,
    pub source: String,
    pub token: String,
    pub config_schema: Vec<HashMap<String, serde_json::Value>>,
    pub config: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct WebJsUrl {
    pub id: i32,
    pub url: String,
    #[serde(rename = "type")]
    pub type_: String,
}

impl WebJsUrl {
    pub fn new(id: i32, url: String, type_: String) -> Self {
        Self { id, url, type_ }
    }
}

#[derive(sqlx::FromRow)]
struct SiteAppRow {
    id: i32,
    web_token: String,
    plugin_source_updated_at: DateTime<Utc>,
    plugin_updated_at: DateTime<Utc>,
    config_updated_at: DateTime<Utc>,
}

/// Gets site app URLs for decide endpoint, matching Python's get_decide_site_apps behavior
///
/// # Arguments
/// * `db` - Database client
/// * `team_id` - Team ID
///
/// # Returns
/// Vector of WebJsUrl for enabled site apps
pub async fn get_decide_site_apps(
    db: PostgresReader,
    team_id: i32,
) -> Result<Vec<WebJsUrl>, FlagError> {
    let mut conn = db.get_connection().await?;

    let query = r#"
        SELECT 
            pc.id,
            pc.web_token,
            psf.updated_at as plugin_source_updated_at,
            p.updated_at as plugin_updated_at,
            pc.updated_at as config_updated_at
        FROM posthog_pluginconfig pc
        JOIN posthog_plugin p ON p.id = pc.plugin_id
        JOIN posthog_pluginsourcefile psf ON psf.plugin_id = p.id
        WHERE pc.team_id = $1
        AND pc.enabled = true
        AND psf.filename = 'site.ts'
        AND psf.status = 'TRANSPILED'
    "#;

    let rows = sqlx::query_as::<_, SiteAppRow>(query)
        .bind(team_id)
        .fetch_all(&mut *conn)
        .await?;

    Ok(rows
        .into_iter()
        .map(|r| {
            let hash_input = format!(
                "{}-{}-{}",
                r.plugin_source_updated_at, r.plugin_updated_at, r.config_updated_at
            );
            let digest = md5::compute(hash_input.as_bytes());
            let hash = format!("{:x}", digest);
            let url = format!("/site_app/{}/{}/{}/", r.id, r.web_token, hash);
            WebJsUrl::new(r.id, url, "site_app".to_string())
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use common_database::PostgresWriter;

    use super::*;
    use crate::utils::test_utils::{insert_new_team_in_pg, setup_pg_reader_client};

    async fn insert_plugin_in_pg(
        client: PostgresWriter,
        organization_id: &str,
        name: &str,
    ) -> Result<i32, sqlx::Error> {
        let mut conn = client.get_connection().await.unwrap();
        // Generate a unique URL to avoid constraint violations
        let unique_url = format!(
            "test://plugin/{}/{}",
            name.replace(" ", "_"),
            uuid::Uuid::new_v4()
        );
        let plugin_id: i32 = sqlx::query_scalar(
            r#"INSERT INTO posthog_plugin 
               (name, description, url, config_schema, tag, source, plugin_type, is_global, is_preinstalled, is_stateless, capabilities, from_json, from_web, organization_id, updated_at, created_at)
               VALUES ($1, 'Test plugin', $2, '[]', '', '', 'source', false, false, false, '{}', false, false, $3::uuid, NOW(), NOW())
               RETURNING id"#,
        )
        .bind(name)
        .bind(unique_url)
        .bind(organization_id)
        .fetch_one(&mut *conn)
        .await?;
        Ok(plugin_id)
    }

    async fn insert_plugin_source_file_in_pg(
        client: PostgresWriter,
        plugin_id: i32,
        filename: &str,
        status: &str,
    ) -> Result<(), sqlx::Error> {
        let mut conn = client.get_connection().await.unwrap();
        let uuid = uuid::Uuid::new_v4().to_string();
        sqlx::query(
            r#"INSERT INTO posthog_pluginsourcefile 
               (id, plugin_id, filename, source, transpiled, status, updated_at)
               VALUES ($1::uuid, $2, $3, 'function test(){}', 'function test(){}', $4, NOW())"#,
        )
        .bind(uuid)
        .bind(plugin_id)
        .bind(filename)
        .bind(status)
        .execute(&mut *conn)
        .await?;
        Ok(())
    }

    async fn insert_posthog_pluginconfig_in_pg(
        client: PostgresWriter,
        plugin_id: i32,
        team_id: i32,
        enabled: bool,
        web_token: &str,
    ) -> Result<i32, sqlx::Error> {
        let mut conn = client.get_connection().await.unwrap();
        let config_id: i32 = sqlx::query_scalar(
            r#"INSERT INTO posthog_pluginconfig 
               (plugin_id, team_id, enabled, "order", config, web_token, updated_at, created_at)
               VALUES ($1, $2, $3, 1, '{}', $4, NOW(), NOW())
               RETURNING id"#,
        )
        .bind(plugin_id)
        .bind(team_id)
        .bind(enabled)
        .bind(web_token)
        .fetch_one(&mut *conn)
        .await?;
        Ok(config_id)
    }

    #[tokio::test]
    async fn test_get_decide_site_apps_returns_empty_for_team_with_no_apps() {
        let client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_pg(client.clone(), None).await.unwrap();

        let result = get_decide_site_apps(client, team.id).await.unwrap();

        assert!(result.is_empty());
    }

    #[tokio::test]
    async fn test_get_decide_site_apps_returns_apps_for_team() {
        let client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_pg(client.clone(), None).await.unwrap();

        // Insert plugin
        let plugin_id = insert_plugin_in_pg(
            client.clone(),
            "019026a4-be80-0000-5bf3-171d00629163", // Use same org ID as in test utils
            "Test Site App",
        )
        .await
        .unwrap();

        // Insert plugin source file with TRANSPILED status
        insert_plugin_source_file_in_pg(client.clone(), plugin_id, "site.ts", "TRANSPILED")
            .await
            .unwrap();

        // Insert enabled plugin config
        let config_id = insert_posthog_pluginconfig_in_pg(
            client.clone(),
            plugin_id,
            team.id,
            true,
            "test_token_123",
        )
        .await
        .unwrap();

        let result = get_decide_site_apps(client, team.id).await.unwrap();

        assert_eq!(result.len(), 1);
        let site_app = &result[0];
        assert_eq!(site_app.id, config_id);
        assert!(site_app.url.starts_with("/site_app/"));
        assert!(site_app.url.contains("test_token_123"));
        assert_eq!(site_app.type_, "site_app");
    }

    #[tokio::test]
    async fn test_get_decide_site_apps_ignores_disabled_configs() {
        let client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_pg(client.clone(), None).await.unwrap();

        // Insert plugin
        let plugin_id = insert_plugin_in_pg(
            client.clone(),
            "019026a4-be80-0000-5bf3-171d00629163",
            "Test Site App",
        )
        .await
        .unwrap();

        // Insert plugin source file with TRANSPILED status
        insert_plugin_source_file_in_pg(client.clone(), plugin_id, "site.ts", "TRANSPILED")
            .await
            .unwrap();

        // Insert disabled plugin config
        insert_posthog_pluginconfig_in_pg(
            client.clone(),
            plugin_id,
            team.id,
            false, // disabled
            "test_token_123",
        )
        .await
        .unwrap();

        let result = get_decide_site_apps(client, team.id).await.unwrap();

        assert!(result.is_empty());
    }

    #[tokio::test]
    async fn test_get_decide_site_apps_ignores_non_transpiled_files() {
        let client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_pg(client.clone(), None).await.unwrap();

        // Insert plugin
        let plugin_id = insert_plugin_in_pg(
            client.clone(),
            "019026a4-be80-0000-5bf3-171d00629163",
            "Test Site App",
        )
        .await
        .unwrap();

        // Insert plugin source file with ERROR status (not TRANSPILED)
        insert_plugin_source_file_in_pg(client.clone(), plugin_id, "site.ts", "ERROR")
            .await
            .unwrap();

        // Insert enabled plugin config
        insert_posthog_pluginconfig_in_pg(
            client.clone(),
            plugin_id,
            team.id,
            true,
            "test_token_123",
        )
        .await
        .unwrap();

        let result = get_decide_site_apps(client, team.id).await.unwrap();

        assert!(result.is_empty());
    }

    #[tokio::test]
    async fn test_get_decide_site_apps_ignores_non_site_files() {
        let client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_pg(client.clone(), None).await.unwrap();

        // Insert plugin
        let plugin_id = insert_plugin_in_pg(
            client.clone(),
            "019026a4-be80-0000-5bf3-171d00629163",
            "Test Site App",
        )
        .await
        .unwrap();

        // Insert plugin source file with different filename (not site.ts)
        insert_plugin_source_file_in_pg(client.clone(), plugin_id, "plugin.ts", "TRANSPILED")
            .await
            .unwrap();

        // Insert enabled plugin config
        insert_posthog_pluginconfig_in_pg(
            client.clone(),
            plugin_id,
            team.id,
            true,
            "test_token_123",
        )
        .await
        .unwrap();

        let result = get_decide_site_apps(client, team.id).await.unwrap();

        assert!(result.is_empty());
    }

    #[tokio::test]
    async fn test_get_decide_site_apps_returns_multiple_apps() {
        let client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_pg(client.clone(), None).await.unwrap();

        // Insert first plugin
        let plugin_id_1 = insert_plugin_in_pg(
            client.clone(),
            "019026a4-be80-0000-5bf3-171d00629163",
            "First Site App",
        )
        .await
        .unwrap();

        insert_plugin_source_file_in_pg(client.clone(), plugin_id_1, "site.ts", "TRANSPILED")
            .await
            .unwrap();

        let config_id_1 = insert_posthog_pluginconfig_in_pg(
            client.clone(),
            plugin_id_1,
            team.id,
            true,
            "token_1",
        )
        .await
        .unwrap();

        // Insert second plugin
        let plugin_id_2 = insert_plugin_in_pg(
            client.clone(),
            "019026a4-be80-0000-5bf3-171d00629163",
            "Second Site App",
        )
        .await
        .unwrap();

        insert_plugin_source_file_in_pg(client.clone(), plugin_id_2, "site.ts", "TRANSPILED")
            .await
            .unwrap();

        let config_id_2 = insert_posthog_pluginconfig_in_pg(
            client.clone(),
            plugin_id_2,
            team.id,
            true,
            "token_2",
        )
        .await
        .unwrap();

        let result = get_decide_site_apps(client, team.id).await.unwrap();

        assert_eq!(result.len(), 2);

        // Check that both configs are present
        let config_ids: Vec<i32> = result.iter().map(|app| app.id).collect();
        assert!(config_ids.contains(&config_id_1));
        assert!(config_ids.contains(&config_id_2));

        // Check that URLs are properly formed
        for app in &result {
            assert!(app.url.starts_with("/site_app/"));
            assert_eq!(app.type_, "site_app");
        }
    }

    #[tokio::test]
    async fn test_get_decide_site_apps_url_format() {
        let client = setup_pg_reader_client(None).await;
        let team = insert_new_team_in_pg(client.clone(), None).await.unwrap();

        // Insert plugin
        let plugin_id = insert_plugin_in_pg(
            client.clone(),
            "019026a4-be80-0000-5bf3-171d00629163",
            "Test Site App",
        )
        .await
        .unwrap();

        insert_plugin_source_file_in_pg(client.clone(), plugin_id, "site.ts", "TRANSPILED")
            .await
            .unwrap();

        let config_id = insert_posthog_pluginconfig_in_pg(
            client.clone(),
            plugin_id,
            team.id,
            true,
            "specific_token",
        )
        .await
        .unwrap();

        let result = get_decide_site_apps(client, team.id).await.unwrap();

        assert_eq!(result.len(), 1);
        let site_app = &result[0];

        // URL should be in format: /site_app/{config_id}/{web_token}/{hash}/
        let expected_prefix = format!("/site_app/{}/specific_token/", config_id);
        assert!(site_app.url.starts_with(&expected_prefix));
        assert!(site_app.url.ends_with('/'));

        // The hash should be 32 characters (MD5 hex)
        let url_parts: Vec<&str> = site_app.url.split('/').collect();
        assert_eq!(url_parts.len(), 6); // ["", "site_app", config_id, token, hash, ""]
        let hash = url_parts[4];
        assert_eq!(hash.len(), 32);
        assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[tokio::test]
    async fn test_get_decide_site_apps_filters_by_team() {
        let client = setup_pg_reader_client(None).await;
        let team1 = insert_new_team_in_pg(client.clone(), None).await.unwrap();
        let team2 = insert_new_team_in_pg(client.clone(), None).await.unwrap();

        // Insert plugin
        let plugin_id = insert_plugin_in_pg(
            client.clone(),
            "019026a4-be80-0000-5bf3-171d00629163",
            "Test Site App",
        )
        .await
        .unwrap();

        insert_plugin_source_file_in_pg(client.clone(), plugin_id, "site.ts", "TRANSPILED")
            .await
            .unwrap();

        // Insert config for team1 only
        insert_posthog_pluginconfig_in_pg(client.clone(), plugin_id, team1.id, true, "team1_token")
            .await
            .unwrap();

        // Query for team1 should return the app
        let result1 = get_decide_site_apps(client.clone(), team1.id)
            .await
            .unwrap();
        assert_eq!(result1.len(), 1);

        // Query for team2 should return empty
        let result2 = get_decide_site_apps(client, team2.id).await.unwrap();
        assert!(result2.is_empty());
    }
}
