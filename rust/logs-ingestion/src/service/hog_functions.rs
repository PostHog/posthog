//! `HogFunctionManagerService` for the logs server: Postgres rows, Fernet-decrypted `encrypted_inputs`,
//! two `LazyLoader` caches and the `reload-hog-functions` Redis channel.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use base64::engine::general_purpose::URL_SAFE;
use base64::Engine;
use fernet::{Fernet, MultiFernet};
use futures::{FutureExt, StreamExt};
use rand::Rng;
use sqlx::{PgPool, Row};

use crate::js::{json_parse, JsValue};
use crate::pipeline::errors::is_dependency_unavailable;
use crate::transformations::functions::{
    row_from_js, sort_hog_functions, HogFunction, HogFunctionRow, HogFunctionSource,
    TRANSFORMATION_LOG_TYPE,
};

use super::lazy_loader::{LazyLoader, LazyLoaderOptions, LoadResult};
use super::postgres::classify_pg_error;

pub const RELOAD_CHANNEL: &str = "reload-hog-functions";
/// `refreshAgeMs` default in `lazy-loader.ts`.
const REFRESH_AGE: Duration = Duration::from_secs(5 * 60);

/// `EncryptedFields`: one Fernet per `ENCRYPTION_SALT_KEYS` entry, the raw key bytes as the key.
pub struct EncryptedFields {
    fernet: Option<MultiFernet>,
}

impl EncryptedFields {
    /// Node's `new Fernet(key)` throws on a key that is not 32 bytes, which stops the server.
    pub fn new(salt_keys: &str) -> anyhow::Result<Self> {
        let mut fernets = Vec::new();
        for key in salt_keys.split(',').filter(|k| !k.is_empty()) {
            let fernet = Fernet::new(&URL_SAFE.encode(key.as_bytes())).ok_or_else(|| {
                anyhow::anyhow!("ENCRYPTION_SALT_KEYS holds a key that is not 32 bytes")
            })?;
            fernets.push(fernet);
        }
        Ok(Self {
            fernet: (!fernets.is_empty()).then(|| MultiFernet::new(fernets)),
        })
    }

    pub fn decrypt(&self, token: &str) -> anyhow::Result<String> {
        let fernet = self
            .fernet
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("Encryption keys are not set"))?;
        let bytes = fernet
            .decrypt(token)
            .map_err(|_| anyhow::anyhow!("Fernet decryption failed"))?;
        Ok(String::from_utf8(bytes)?)
    }

    pub fn encrypt(&self, value: &str) -> Option<String> {
        self.fernet.as_ref().map(|f| f.encrypt(value.as_bytes()))
    }
}

/// `sanitize`: the column holds a Fernet token, or, in older rows, the object itself.
/// A value that does not decrypt is kept as a string in Node, where the transformer then finds no inputs in it.
pub fn decrypt_encrypted_inputs(raw: Option<&str>, fields: &EncryptedFields) -> Option<JsValue> {
    let raw = raw?;
    let token = match json_parse(raw) {
        Ok(value @ JsValue::Object(_)) => return Some(value),
        Ok(JsValue::String(token)) => token.to_utf8_lossy().into_owned(),
        Ok(_) => return None,
        Err(_) => raw.to_string(),
    };
    match fields.decrypt(&token) {
        Ok(decrypted) if decrypted.is_empty() => None,
        Ok(decrypted) => match json_parse(&decrypted) {
            Ok(value @ JsValue::Object(_)) => Some(value),
            _ => None,
        },
        Err(error) => {
            tracing::warn!(error = %error, "[HogFunctionManager] Could not parse encrypted inputs - preserving original value");
            None
        }
    }
}

/// `DEFAULT_LOADER_RETRY`: a dependency outage is retried every 250 ms plus up to 250 ms of jitter for 5 s.
async fn with_loader_retry<T, F, Fut>(load: F) -> anyhow::Result<T>
where
    F: Fn() -> Fut,
    Fut: std::future::Future<Output = anyhow::Result<T>>,
{
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        match load().await {
            Ok(v) => return Ok(v),
            Err(error) if is_dependency_unavailable(&error) && Instant::now() < deadline => {
                let jitter = rand::thread_rng().gen_range(0..250);
                tokio::time::sleep(Duration::from_millis(250 + jitter)).await;
            }
            Err(error) => return Err(error),
        }
    }
}

#[derive(Clone)]
struct TeamFunction {
    id: String,
    function_type: String,
}

async fn fetch_team_functions(pool: &PgPool, keys: Vec<String>) -> LoadResult<Vec<TeamFunction>> {
    let team_ids: Vec<i32> = keys
        .iter()
        .filter_map(|k| k.parse::<i32>().ok().filter(|n| *n >= 1))
        .collect();
    let rows = sqlx::query(
        "SELECT id::text AS id, team_id, type FROM posthog_hogfunction \
         WHERE enabled = TRUE AND deleted = FALSE AND team_id = ANY($1)",
    )
    .bind(&team_ids)
    .fetch_all(pool)
    .await
    .map_err(classify_pg_error)?;
    let mut out: HashMap<String, Option<Vec<TeamFunction>>> = HashMap::new();
    for row in rows {
        let team_id: i32 = row.try_get("team_id")?;
        out.entry(team_id.to_string())
            .or_insert_with(|| Some(Vec::new()))
            .get_or_insert_with(Vec::new)
            .push(TeamFunction {
                id: row.try_get("id")?,
                function_type: row
                    .try_get::<Option<String>, _>("type")?
                    .unwrap_or_default(),
            });
    }
    Ok(out)
}

async fn fetch_functions(
    pool: &PgPool,
    fields: &EncryptedFields,
    ids: Vec<String>,
) -> LoadResult<Arc<HogFunction>> {
    let rows = sqlx::query(
        "SELECT id::text AS id, team_id, name, type, execution_order, created_at::text AS created_at, \
         bytecode::text AS bytecode, inputs::text AS inputs, encrypted_inputs::text AS encrypted_inputs \
         FROM posthog_hogfunction WHERE id::text = ANY($1) AND deleted = FALSE",
    )
    .bind(&ids)
    .fetch_all(pool)
    .await
    .map_err(classify_pg_error)?;
    let parse = |text: Option<String>| {
        text.and_then(|t| json_parse(&t).ok())
            .unwrap_or(JsValue::Null)
    };
    let mut out = HashMap::new();
    for row in rows {
        let encrypted: Option<String> = row.try_get("encrypted_inputs")?;
        let function = HogFunction::from_row(HogFunctionRow {
            id: row.try_get("id")?,
            team_id: row.try_get::<i32, _>("team_id")? as i64,
            name: row
                .try_get::<Option<String>, _>("name")?
                .unwrap_or_default(),
            function_type: row
                .try_get::<Option<String>, _>("type")?
                .unwrap_or_default(),
            execution_order: row
                .try_get::<Option<i32>, _>("execution_order")?
                .map(f64::from),
            created_at: row
                .try_get::<Option<String>, _>("created_at")?
                .unwrap_or_default(),
            bytecode: parse(row.try_get("bytecode")?),
            inputs: parse(row.try_get("inputs")?),
            encrypted_inputs: decrypt_encrypted_inputs(encrypted.as_deref(), fields),
        });
        out.insert(function.id.clone(), Some(Arc::new(function)));
    }
    Ok(out)
}

#[derive(Clone)]
pub struct PgHogFunctions {
    by_team: LazyLoader<Vec<TeamFunction>>,
    by_id: LazyLoader<Arc<HogFunction>>,
}

impl PgHogFunctions {
    pub fn new(reader: PgPool, fields: Arc<EncryptedFields>) -> Self {
        let pool = reader.clone();
        let by_team = LazyLoader::new(
            LazyLoaderOptions::new("hog_function_manager_by_team", REFRESH_AGE),
            Arc::new(move |keys: Vec<String>| {
                let pool = pool.clone();
                async move { with_loader_retry(|| fetch_team_functions(&pool, keys.clone())).await }
                    .boxed()
            }),
        );
        let by_id = LazyLoader::new(
            LazyLoaderOptions::new("hog_function_manager", REFRESH_AGE),
            Arc::new(move |ids: Vec<String>| {
                let pool = reader.clone();
                let fields = fields.clone();
                async move { with_loader_retry(|| fetch_functions(&pool, &fields, ids.clone())).await }
                    .boxed()
            }),
        );
        Self { by_team, by_id }
    }

    /// `onHogFunctionsReloaded`.
    pub fn reload(&self, team_id: &str, function_ids: &[String]) {
        self.by_team.mark_for_refresh(&[team_id.to_string()]);
        self.by_id.mark_for_refresh(function_ids);
    }

    /// The `reload-hog-functions` subscription. It reconnects until the process exits.
    pub fn spawn_reload_listener(&self, client: redis::Client) -> tokio::task::JoinHandle<()> {
        let this = self.clone();
        tokio::spawn(async move {
            loop {
                if let Err(error) = this.listen(&client).await {
                    tracing::warn!(error = %error, "reload-hog-functions subscription lost, reconnecting");
                }
                tokio::time::sleep(Duration::from_secs(1)).await;
            }
        })
    }

    async fn listen(&self, client: &redis::Client) -> anyhow::Result<()> {
        let mut pubsub = client.get_async_pubsub().await?;
        pubsub.subscribe(RELOAD_CHANNEL).await?;
        let mut messages = pubsub.on_message();
        while let Some(message) = messages.next().await {
            let payload: String = message.get_payload().unwrap_or_default();
            let parsed = json_parse(&payload).unwrap_or(JsValue::Null);
            let JsValue::Object(object) = parsed else {
                continue;
            };
            let team_id = match object.get("teamId") {
                Some(JsValue::Number(n)) => crate::js::number_to_string(*n),
                Some(JsValue::String(s)) => s.to_utf8_lossy().into_owned(),
                _ => continue,
            };
            let ids: Vec<String> = match object.get("hogFunctionIds") {
                Some(JsValue::Array(items)) => items
                    .iter()
                    .filter_map(|v| v.as_js_string().map(|s| s.to_utf8_lossy().into_owned()))
                    .collect(),
                _ => Vec::new(),
            };
            tracing::debug!(team_id, ?ids, "reloading hog functions");
            self.reload(&team_id, &ids);
        }
        anyhow::bail!("subscription stream ended")
    }
}

#[async_trait]
impl HogFunctionSource for PgHogFunctions {
    async fn transformation_ids(&self, team_id: i64) -> anyhow::Result<Vec<String>> {
        Ok(self
            .by_team
            .get(&team_id.to_string())
            .await?
            .unwrap_or_default()
            .into_iter()
            .filter(|f| f.function_type == TRANSFORMATION_LOG_TYPE)
            .map(|f| f.id)
            .collect())
    }

    async fn transformations(&self, team_id: i64) -> anyhow::Result<Vec<Arc<HogFunction>>> {
        let ids = self.transformation_ids(team_id).await?;
        let loaded = futures::future::try_join_all(ids.iter().map(|id| self.by_id.get(id))).await?;
        let mut functions: Vec<Arc<HogFunction>> = loaded
            .into_iter()
            .flatten()
            .filter(|f| f.team_id == team_id)
            .collect();
        sort_hog_functions(&mut functions);
        Ok(functions)
    }
}

/// Builds a function from the JSON row shape the parity fixtures store, decrypting a string `encrypted_inputs`.
pub fn function_from_js(value: &JsValue, fields: &EncryptedFields) -> HogFunction {
    let mut row = row_from_js(value);
    if let Some(JsValue::Object(o)) = Some(value) {
        if let Some(JsValue::String(token)) = o.get("encrypted_inputs") {
            row.encrypted_inputs = decrypt_encrypted_inputs(
                Some(&crate::js::json_stringify(&JsValue::String(token.clone()))),
                fields,
            );
        }
    }
    HogFunction::from_row(row)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::js::json_stringify;

    /// The dev and test default of `ENCRYPTION_SALT_KEYS`.
    const KEY: &str = "00beef0000beef0000beef0000beef00";
    /// `new EncryptedFields(KEY).encrypt('{"apiKey":{"value":"test-key","order":0}}')` from fernet-nodejs.
    const NODE_TOKEN: &str = "gAAAAABq7brKHRWvBDB4PkkAK5QfuvLhlNIXH2xPsrMUwpW2F5o_58MUyAlspxmFh0feDmwGx9lEqevRRedtiZ3p0zKxxLEqBvWzvJ0U4VOqgNHVgtCyB6kdby0naw8OM_7AF95Ir-8Z";

    fn text(value: Option<JsValue>) -> Option<String> {
        value.map(|v| json_stringify(&v))
    }

    #[test]
    fn encrypted_inputs_decrypt_like_hog_function_manager_sanitize() {
        let fields = EncryptedFields::new(&format!("{KEY},{}", "1".repeat(32))).unwrap();
        let expected = Some(r#"{"apiKey":{"value":"test-key","order":0}}"#.to_string());
        // A token written by Node, as a text column and as a JSON string.
        assert_eq!(
            text(decrypt_encrypted_inputs(Some(NODE_TOKEN), &fields)),
            expected
        );
        let quoted = format!("\"{NODE_TOKEN}\"");
        assert_eq!(
            text(decrypt_encrypted_inputs(Some(&quoted), &fields)),
            expected
        );
        // A value that is already an object is kept.
        let plain = r#"{"apiKey":{"value":"test-key","order":0}}"#;
        assert_eq!(
            text(decrypt_encrypted_inputs(Some(plain), &fields)),
            expected
        );
        // A token under the second key still decrypts, as MultiFernet tries each key.
        let rotated = EncryptedFields::new(&"1".repeat(32)).unwrap();
        let token = rotated.encrypt(plain).unwrap();
        assert_eq!(
            text(decrypt_encrypted_inputs(Some(&token), &fields)),
            expected
        );

        assert_eq!(decrypt_encrypted_inputs(Some("not-a-token"), &fields), None);
        assert_eq!(decrypt_encrypted_inputs(None, &fields), None);
        let no_keys = EncryptedFields::new("").unwrap();
        assert_eq!(decrypt_encrypted_inputs(Some(NODE_TOKEN), &no_keys), None);
        assert!(EncryptedFields::new("short").is_err());
    }
}
