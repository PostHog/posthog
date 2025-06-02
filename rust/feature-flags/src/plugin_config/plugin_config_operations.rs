use crate::api::errors::FlagError;
use chrono::{DateTime, Utc};
use common_database::Client as DatabaseClient;
use md5;
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, sync::Arc};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WebJsSource {
    pub id: i32,
    pub source: String,
    pub token: String,
    pub config_schema: Vec<HashMap<String, serde_json::Value>>,
    pub config: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
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
    db: Arc<dyn DatabaseClient + Send + Sync>,
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
        FROM plugin_config pc
        JOIN plugin p ON p.id = pc.plugin_id
        JOIN plugin_source_file psf ON psf.plugin_id = p.id
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
