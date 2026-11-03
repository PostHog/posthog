//! The queries, TTLs and fallbacks match their TypeScript counterparts.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use futures::future::{BoxFuture, FutureExt, Shared};
use sqlx::{PgPool, Row};

use crate::js::{json_parse, JsObject, JsValue};
use crate::metric_rules::{
    compile_metric_rules, CompiledMetricRule, MetricRuleRow, MetricRulesSource,
};
use crate::pattern::MESSAGE_KEYS;
use crate::pipeline::scenario::logs_settings;
use crate::pipeline::{
    DependencyUnavailableError, PatternMessageKeysSource, RetentionRulesSource,
    SamplingRulesSource, Team, TeamManager, TracingConfigSource,
};
use crate::retention::{
    compile_retention_rule_set, CompiledRetentionRuleSet, RetentionRuleRow,
    MAX_ENABLED_RETENTION_RULES,
};
use crate::sampling::{compile_rule_set, CompiledRuleSet, SamplingRuleRow};

use super::lazy_loader::{LazyLoader, LazyLoaderOptions};

const UNAVAILABLE_MESSAGES: &[&str] = &[
    "connection to server at",
    "could not translate host",
    "server conn crashed",
    "no more connections allowed",
    "server closed the connection unexpectedly",
    "getaddrinfo EAI_AGAIN",
    "getaddrinfo ENOTFOUND",
    "Connection terminated unexpectedly",
    "ECONNREFUSED",
    "ECONNRESET",
    "EHOSTUNREACH",
    "ETIMEDOUT",
    "query_wait_timeout",
    "server login has been failing",
    "pooler is shutting down",
    "Cannot use a pool after calling end on the pool",
    "conflict with recovery",
];

/// sqlx reports a lost connection as an I/O or pool error instead.
pub fn classify_pg_error(error: sqlx::Error) -> anyhow::Error {
    let transient = match &error {
        sqlx::Error::Io(_)
        | sqlx::Error::PoolTimedOut
        | sqlx::Error::PoolClosed
        | sqlx::Error::WorkerCrashed
        | sqlx::Error::Tls(_) => true,
        other => {
            let text = other.to_string();
            UNAVAILABLE_MESSAGES.iter().any(|m| text.contains(m))
        }
    };
    if transient {
        metrics::counter!("logs_ingestion_postgres_unavailable_total").increment(1);
        anyhow::Error::new(DependencyUnavailableError {
            message: error.to_string(),
            dependency_name: "Postgres".to_string(),
        })
    } else {
        anyhow::Error::new(error)
    }
}

fn parse_json_column(text: Option<String>) -> JsValue {
    text.and_then(|t| json_parse(&t).ok())
        .unwrap_or(JsValue::Null)
}

/// Postgres team ids are int4 and start at 1 (`isValidTeamId`).
fn team_id_key(key: &str) -> Option<Option<i32>> {
    let is_digits = !key.is_empty() && key.len() <= 10 && key.bytes().all(|b| b.is_ascii_digit());
    if !is_digits {
        return None;
    }
    Some(
        key.parse::<i64>()
            .ok()
            .filter(|n| *n >= 1 && *n <= 2_147_483_647)
            .map(|n| n as i32),
    )
}

#[derive(Debug, Clone)]
pub struct CachedTeam {
    pub team: Team,
    pub ingested_event: bool,
}

/// Without a `writer` it never writes `ingested_event`.
pub struct PgTeamManager {
    loader: LazyLoader<CachedTeam>,
    writer: Option<PgPool>,
}

impl PgTeamManager {
    pub fn new(reader: PgPool, writer: Option<PgPool>) -> Self {
        let mut options = LazyLoaderOptions::new("TeamManager", Duration::from_secs(120));
        options.jitter = Some(Duration::from_secs(30));
        let loader = LazyLoader::new(
            options,
            Arc::new(move |keys: Vec<String>| {
                let pool = reader.clone();
                async move { fetch_teams(&pool, keys).await }.boxed()
            }),
        );
        Self { loader, writer }
    }

    async fn cached(&self, key: &str) -> anyhow::Result<Option<CachedTeam>> {
        self.loader.get(key).await
    }

    async fn set_ingested_event(&self, writer: &PgPool, team: &CachedTeam) -> anyhow::Result<()> {
        if team.ingested_event {
            return Ok(());
        }
        sqlx::query(
            "UPDATE posthog_team SET ingested_event = $1 WHERE id = $2 AND NOT ingested_event",
        )
        .bind(true)
        .bind(team.team.id as i32)
        .execute(writer)
        .await
        .map_err(classify_pg_error)?;
        self.loader
            .mark_for_refresh(&[team.team.id.to_string(), team.team.api_token.clone()]);
        Ok(())
    }
}

async fn fetch_teams(
    pool: &PgPool,
    keys: Vec<String>,
) -> anyhow::Result<HashMap<String, Option<CachedTeam>>> {
    let mut ids: Vec<i32> = Vec::new();
    let mut tokens: Vec<String> = Vec::new();
    for key in &keys {
        match team_id_key(key) {
            Some(Some(id)) => ids.push(id),
            Some(None) => {}
            None => tokens.push(key.clone()),
        }
    }
    let rows = sqlx::query(
        "SELECT t.id, t.api_token, t.logs_settings::text AS logs_settings, t.ingested_event \
         FROM posthog_team t JOIN posthog_organization o ON o.id = t.organization_id \
         WHERE t.id = ANY($1) OR t.api_token = ANY($2)",
    )
    .bind(&ids)
    .bind(&tokens)
    .fetch_all(pool)
    .await
    .map_err(classify_pg_error)?;
    let mut out: HashMap<String, Option<CachedTeam>> =
        keys.into_iter().map(|k| (k, None)).collect();
    for row in rows {
        let id: i32 = row.try_get("id")?;
        let api_token: String = row.try_get("api_token")?;
        let settings = parse_json_column(row.try_get("logs_settings")?);
        let team = CachedTeam {
            team: Team {
                id: id as i64,
                api_token: api_token.clone(),
                logs_settings: logs_settings(Some(&settings)),
            },
            ingested_event: row.try_get("ingested_event")?,
        };
        out.insert(id.to_string(), Some(team.clone()));
        out.insert(api_token, Some(team));
    }
    Ok(out)
}

#[async_trait]
impl TeamManager for PgTeamManager {
    async fn get_team(&self, team_id: i64) -> anyhow::Result<Option<Team>> {
        Ok(self.cached(&team_id.to_string()).await?.map(|t| t.team))
    }

    async fn get_team_by_token(&self, token: &str) -> anyhow::Result<Option<Team>> {
        Ok(self.cached(token).await?.map(|t| t.team))
    }

    async fn set_teams_ingested_data(&self, team_ids: &[i64]) -> anyhow::Result<()> {
        let Some(writer) = &self.writer else {
            return Ok(());
        };
        let mut unique: Vec<i64> = team_ids.to_vec();
        unique.sort_unstable();
        unique.dedup();
        futures::future::join_all(unique.into_iter().map(|team_id| async move {
            let result = async {
                if let Some(team) = self.cached(&team_id.to_string()).await? {
                    self.set_ingested_event(writer, &team).await?;
                }
                anyhow::Ok(())
            }
            .await;
            if let Err(error) = result {
                tracing::error!(team_id, error = %error, "Failed to set ingested_event");
            }
        }))
        .await;
        Ok(())
    }
}

const RULES_REFRESH: Duration = Duration::from_secs(30);

struct Timed<V> {
    value: Arc<V>,
    fetched_at: Instant,
}

/// Concurrent misses each query, as in Node.
struct TtlCache<K, V>(Mutex<HashMap<K, Timed<V>>>);

impl<K: std::hash::Hash + Eq + Clone, V> TtlCache<K, V> {
    fn new() -> Self {
        Self(Mutex::new(HashMap::new()))
    }

    fn fresh(&self, key: &K) -> Option<Arc<V>> {
        let cache = self.0.lock().unwrap();
        cache
            .get(key)
            .filter(|e| e.fetched_at.elapsed() < RULES_REFRESH)
            .map(|e| e.value.clone())
    }

    fn stale(&self, key: &K) -> Option<Arc<V>> {
        self.0.lock().unwrap().get(key).map(|e| e.value.clone())
    }

    fn put(&self, key: K, value: Arc<V>, fetched_at: Instant) {
        self.0
            .lock()
            .unwrap()
            .insert(key, Timed { value, fetched_at });
    }
}

/// A fetch or compile error propagates.
pub struct PgSamplingRules {
    pool: PgPool,
    cache: TtlCache<i64, CompiledRuleSet>,
}

impl PgSamplingRules {
    pub fn new(pool: PgPool) -> Self {
        Self {
            pool,
            cache: TtlCache::new(),
        }
    }
}

#[async_trait]
impl SamplingRulesSource for PgSamplingRules {
    async fn get_compiled_rule_set(&self, team_id: i64) -> anyhow::Result<Arc<CompiledRuleSet>> {
        if let Some(v) = self.cache.fresh(&team_id) {
            return Ok(v);
        }
        let started = Instant::now();
        let rows = sqlx::query(
            "SELECT id::text AS id, rule_type, scope_service, scope_path_pattern, \
                    scope_attribute_filters::text AS scope_attribute_filters, config::text AS config, version \
             FROM logs_logsexclusionrule \
             WHERE team_id = $1 AND enabled = true \
             ORDER BY priority ASC, created_at ASC",
        )
        .bind(team_id)
        .fetch_all(&self.pool)
        .await
        .map_err(classify_pg_error)?;
        let rows: Vec<SamplingRuleRow> = rows
            .into_iter()
            .map(|r| -> anyhow::Result<SamplingRuleRow> {
                let config = match parse_json_column(r.try_get("config")?) {
                    JsValue::Null => JsValue::Object(JsObject::new()),
                    v => v,
                };
                Ok(SamplingRuleRow {
                    id: r.try_get("id")?,
                    rule_type: r.try_get("rule_type")?,
                    scope_service: r.try_get("scope_service")?,
                    scope_path_pattern: r.try_get("scope_path_pattern")?,
                    scope_attribute_filters: parse_json_column(
                        r.try_get("scope_attribute_filters")?,
                    ),
                    config,
                    version: Some(r.try_get::<i32, _>("version")? as i64),
                })
            })
            .collect::<anyhow::Result<_>>()?;
        let compiled = Arc::new(compile_rule_set(&rows).map_err(anyhow::Error::new)?);
        self.cache.put(team_id, compiled.clone(), started);
        Ok(compiled)
    }
}

/// A fetch error serves the last rules, or none.
pub struct PgRetentionRules {
    pool: PgPool,
    cache: TtlCache<(i64, String), CompiledRetentionRuleSet>,
}

impl PgRetentionRules {
    pub fn new(pool: PgPool) -> Self {
        Self {
            pool,
            cache: TtlCache::new(),
        }
    }

    async fn fetch(&self, team_id: i64, source: &str) -> anyhow::Result<Vec<RetentionRuleRow>> {
        let table = match source {
            "spans" => "tracing_tracesretentionrule",
            _ => "logs_logsretentionrule",
        };
        let sql = format!(
            "SELECT id::text AS id, config::text AS config, version FROM {table} \
             WHERE team_id = $1 AND enabled = true \
             ORDER BY priority ASC, created_at ASC LIMIT {MAX_ENABLED_RETENTION_RULES}"
        );
        let rows = sqlx::query(&sql)
            .bind(team_id)
            .fetch_all(&self.pool)
            .await
            .map_err(classify_pg_error)?;
        rows.into_iter()
            .map(|r| {
                let config = match parse_json_column(r.try_get("config")?) {
                    JsValue::Null => JsValue::Object(JsObject::new()),
                    v => v,
                };
                Ok(RetentionRuleRow {
                    id: r.try_get("id")?,
                    config,
                    version: Some(r.try_get::<i32, _>("version")? as i64),
                })
            })
            .collect()
    }
}

#[async_trait]
impl RetentionRulesSource for PgRetentionRules {
    async fn get_compiled_rule_set(
        &self,
        team_id: i64,
        source: &str,
    ) -> anyhow::Result<Arc<CompiledRetentionRuleSet>> {
        let key = (team_id, source.to_string());
        if let Some(v) = self.cache.fresh(&key) {
            return Ok(v);
        }
        let started = Instant::now();
        let rows = match self.fetch(team_id, source).await {
            Ok(rows) => rows,
            Err(error) => {
                tracing::warn!(team_id, source, error = %error, "[logs-retention] rules fetch failed — falling back");
                return match self.cache.stale(&key) {
                    Some(v) => Ok(v),
                    None => Ok(Arc::new(
                        compile_retention_rule_set(&[]).map_err(anyhow::Error::new)?,
                    )),
                };
            }
        };
        let compiled = compile_retention_rule_set(&rows).map_err(anyhow::Error::new)?;
        let dropped = rows.len().saturating_sub(compiled.rules.len());
        if dropped > 0 {
            let name = if source == "spans" {
                "traces_ingestion_retention_rules_dropped_total"
            } else {
                "logs_ingestion_retention_rules_dropped_total"
            };
            let team: Arc<str> = Arc::from(team_id.to_string());
            metrics::counter!(name, "team_id" => team).increment(dropped as u64);
            tracing::warn!(
                team_id,
                source,
                fetched = rows.len(),
                dropped,
                "[logs-retention] enabled rules discarded at compile — check retention_days tier"
            );
        }
        let compiled = Arc::new(compiled);
        self.cache.put(key, compiled.clone(), started);
        Ok(compiled)
    }
}

/// A fetch or compile error propagates, and the consumer fails open on it.
pub struct PgMetricRules {
    pool: PgPool,
    cache: TtlCache<i64, Vec<CompiledMetricRule>>,
}

impl PgMetricRules {
    pub fn new(pool: PgPool) -> Self {
        Self {
            pool,
            cache: TtlCache::new(),
        }
    }
}

#[async_trait]
impl MetricRulesSource for PgMetricRules {
    async fn get_compiled_rules(
        &self,
        team_id: i64,
    ) -> anyhow::Result<Arc<Vec<CompiledMetricRule>>> {
        if let Some(v) = self.cache.fresh(&team_id) {
            return Ok(v);
        }
        let started = Instant::now();
        let rows = sqlx::query(
            "SELECT id::text AS id, metric_name, filter_group::text AS filter_group, value_attribute, \
                    group_by::text[] AS group_by, source \
             FROM logs_logsmetricrule \
             WHERE team_id = $1 AND enabled = true \
             ORDER BY created_at ASC",
        )
        .bind(team_id)
        .fetch_all(&self.pool)
        .await
        .map_err(classify_pg_error)?;
        let rows: Vec<MetricRuleRow> = rows
            .into_iter()
            .map(|r| -> anyhow::Result<MetricRuleRow> {
                let opt_string =
                    |v: Option<String>| v.map(|s| JsValue::string(&s)).unwrap_or(JsValue::Null);
                let mut row = JsObject::new();
                row.insert_str("id", JsValue::string(&r.try_get::<String, _>("id")?));
                row.insert_str("metric_name", opt_string(r.try_get("metric_name")?));
                row.insert_str(
                    "filter_group",
                    parse_json_column(r.try_get("filter_group")?),
                );
                row.insert_str("value_attribute", opt_string(r.try_get("value_attribute")?));
                let group_by: Vec<Option<String>> = r.try_get("group_by")?;
                row.insert_str(
                    "group_by",
                    JsValue::Array(group_by.into_iter().map(opt_string).collect()),
                );
                row.insert_str("source", opt_string(r.try_get("source")?));
                Ok(MetricRuleRow::from_js(&row))
            })
            .collect::<anyhow::Result<_>>()?;
        let compiled = Arc::new(compile_metric_rules(&rows).map_err(anyhow::Error::new)?);
        self.cache.put(team_id, compiled.clone(), started);
        Ok(compiled)
    }
}

type KeysLoad = Shared<BoxFuture<'static, Result<Arc<Vec<String>>, Arc<anyhow::Error>>>>;

struct KeysEntry {
    keys: Arc<Vec<String>>,
    expires_at: Instant,
}

/// Only an outage with nothing cached propagates.
pub struct PgPatternMessageKeys {
    pool: PgPool,
    cache: Arc<Mutex<HashMap<i64, KeysEntry>>>,
    inflight: Arc<Mutex<HashMap<i64, KeysLoad>>>,
}

impl PgPatternMessageKeys {
    pub fn new(pool: PgPool) -> Self {
        Self {
            pool,
            cache: Default::default(),
            inflight: Default::default(),
        }
    }
}

fn default_message_keys() -> Arc<Vec<String>> {
    Arc::new(MESSAGE_KEYS.iter().map(|k| k.to_string()).collect())
}

async fn refresh_message_keys(
    pool: PgPool,
    cache: Arc<Mutex<HashMap<i64, KeysEntry>>>,
    team_id: i64,
) -> anyhow::Result<Arc<Vec<String>>> {
    let existing = cache.lock().unwrap().get(&team_id).map(|e| e.keys.clone());
    let fetched = sqlx::query("SELECT logs_pattern_message_keys::text[] AS keys FROM logs_teamlogsconfig WHERE team_id = $1")
        .bind(team_id)
        .fetch_optional(&pool)
        .await
        .map_err(classify_pg_error)
        .and_then(|row| match row {
            None => Ok(default_message_keys()),
            Some(row) => {
                let keys: Option<Vec<Option<String>>> = row.try_get("keys")?;
                Ok(match keys.and_then(|k| k.into_iter().collect::<Option<Vec<String>>>()) {
                    Some(keys) => Arc::new(keys),
                    None => default_message_keys(),
                })
            }
        });
    match fetched {
        Ok(keys) => {
            cache.lock().unwrap().insert(
                team_id,
                KeysEntry {
                    keys: keys.clone(),
                    expires_at: Instant::now() + RULES_REFRESH,
                },
            );
            Ok(keys)
        }
        Err(error) => {
            if existing.is_none() && crate::pipeline::errors::is_dependency_unavailable(&error) {
                return Err(error);
            }
            tracing::warn!(team_id, error = %error, "[logs-patterns] message keys fetch failed — falling back");
            let fallback = existing.unwrap_or_else(default_message_keys);
            cache.lock().unwrap().insert(
                team_id,
                KeysEntry {
                    keys: fallback.clone(),
                    expires_at: Instant::now() + Duration::from_secs(5),
                },
            );
            Ok(fallback)
        }
    }
}

#[async_trait]
impl PatternMessageKeysSource for PgPatternMessageKeys {
    async fn get_message_keys(&self, team_id: i64) -> anyhow::Result<Vec<String>> {
        if let Some(e) = self.cache.lock().unwrap().get(&team_id) {
            if Instant::now() < e.expires_at {
                return Ok(e.keys.to_vec());
            }
        }
        let load = {
            let mut inflight = self.inflight.lock().unwrap();
            inflight
                .entry(team_id)
                .or_insert_with(|| {
                    let pool = self.pool.clone();
                    let cache = self.cache.clone();
                    let inflight = self.inflight.clone();
                    let task = tokio::spawn(async move {
                        let result = refresh_message_keys(pool, cache, team_id)
                            .await
                            .map_err(Arc::new);
                        inflight.lock().unwrap().remove(&team_id);
                        result
                    });
                    async move {
                        task.await.unwrap_or_else(|e| {
                            Err(Arc::new(anyhow::anyhow!("refresh task failed: {e}")))
                        })
                    }
                    .boxed()
                    .shared()
                })
                .clone()
        };
        match load.await {
            Ok(keys) => Ok(keys.to_vec()),
            Err(error) => Err(match error.downcast_ref::<DependencyUnavailableError>() {
                Some(e) => anyhow::Error::new(e.clone()),
                None => anyhow::anyhow!("{error:#}"),
            }),
        }
    }
}

pub struct PgTracingConfig {
    pool: PgPool,
    cache: TtlCache<i64, f64>,
}

impl PgTracingConfig {
    pub fn new(pool: PgPool) -> Self {
        Self {
            pool,
            cache: TtlCache::new(),
        }
    }
}

#[async_trait]
impl TracingConfigSource for PgTracingConfig {
    async fn get_retention_days(&self, team_id: i64) -> anyhow::Result<f64> {
        if let Some(v) = self.cache.fresh(&team_id) {
            return Ok(*v);
        }
        let started = Instant::now();
        let fetched =
            sqlx::query("SELECT retention_days FROM tracing_teamtracingconfig WHERE team_id = $1")
                .bind(team_id)
                .fetch_optional(&self.pool)
                .await
                .map_err(classify_pg_error)
                .and_then(|row| {
                    let stored: Option<i32> = match row {
                        Some(r) => r.try_get("retention_days")?,
                        None => None,
                    };
                    Ok(stored
                        .filter(|d| *d > 0)
                        .map(f64::from)
                        .unwrap_or(crate::pipeline::types::DEFAULT_TRACES_RETENTION_DAYS))
                });
        match fetched {
            Ok(days) => {
                self.cache.put(team_id, Arc::new(days), started);
                Ok(days)
            }
            Err(error) => {
                let existing = self.cache.stale(&team_id);
                if existing.is_none() && crate::pipeline::errors::is_dependency_unavailable(&error)
                {
                    return Err(error);
                }
                tracing::warn!(team_id, error = %error, "[traces-retention] tracing config fetch failed — falling back");
                Ok(existing
                    .map(|v| *v)
                    .unwrap_or(crate::pipeline::types::DEFAULT_TRACES_RETENTION_DAYS))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn team_keys_split_like_fetch_teams() {
        assert_eq!(team_id_key("42"), Some(Some(42)));
        assert_eq!(team_id_key("0"), Some(None));
        assert_eq!(team_id_key("9999999999"), Some(None));
        assert_eq!(team_id_key("phc_abc"), None);
        assert_eq!(team_id_key("12345678901"), None);
    }

    #[test]
    fn connection_failures_are_dependency_unavailable() {
        let refused = classify_pg_error(sqlx::Error::Io(std::io::Error::new(
            std::io::ErrorKind::ConnectionRefused,
            "refused",
        )));
        assert!(crate::pipeline::errors::is_dependency_unavailable(&refused));
        let bad = classify_pg_error(sqlx::Error::RowNotFound);
        assert!(!crate::pipeline::errors::is_dependency_unavailable(&bad));
    }
}
