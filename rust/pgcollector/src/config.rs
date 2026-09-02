use anyhow::{Context, Result};
use serde::Deserialize;
use std::collections::{BTreeMap, HashMap};
use std::path::Path;
use std::time::Duration;

#[derive(Debug, Deserialize, Clone)]
pub struct Config {
    pub sink: SinkConfig,
    #[serde(default)]
    pub defaults: Defaults,
    #[serde(default)]
    pub http: HttpConfig,
    #[serde(default)]
    pub servers: Vec<ServerConfig>,
}

#[derive(Debug, Deserialize, Clone)]
pub struct SinkConfig {
    pub database_url: String,
    #[serde(default = "default_retention")]
    pub retention_days: u32,
}
fn default_retention() -> u32 {
    14
}

#[derive(Debug, Deserialize, Clone)]
pub struct HttpConfig {
    /// Bind address for /healthz, /readyz, /metrics.
    #[serde(default = "default_listen")]
    pub listen: String,
}
impl Default for HttpConfig {
    fn default() -> Self {
        Self {
            listen: default_listen(),
        }
    }
}
fn default_listen() -> String {
    "0.0.0.0:9187".into()
}

#[derive(Debug, Deserialize, Clone)]
pub struct Defaults {
    #[serde(with = "humantime_serde", default = "default_stmt_timeout")]
    pub statement_timeout: Duration,
    /// Databases for `scope: database` collectors. `["*"]` = discover (and keep discovering).
    #[serde(default = "default_databases")]
    pub databases: Vec<String>,
    /// How often to re-discover databases on each server.
    #[serde(with = "humantime_serde", default = "default_rediscover")]
    pub rediscover_interval: Duration,
    /// Global per-collector overrides; per-server `overrides` merge on top.
    #[serde(default)]
    pub overrides: HashMap<String, CollectorOverride>,
}
impl Default for Defaults {
    fn default() -> Self {
        Self {
            statement_timeout: default_stmt_timeout(),
            databases: default_databases(),
            rediscover_interval: default_rediscover(),
            overrides: HashMap::new(),
        }
    }
}
fn default_stmt_timeout() -> Duration {
    Duration::from_secs(5)
}
fn default_databases() -> Vec<String> {
    vec!["*".into()]
}
fn default_rediscover() -> Duration {
    Duration::from_secs(600)
}

#[derive(Debug, Deserialize, Clone)]
pub struct ServerConfig {
    /// Stable name; becomes `server_id` in every table.
    pub id: String,
    /// Writer (cluster) endpoint.
    pub url: String,
    /// Load-balanced reader endpoint. Used by `prefers_reader` collectors only.
    pub reader_url: Option<String>,
    /// Individual instance endpoints (name → url). Cluster-scope collectors run against
    /// the writer *and* each of these, tagged with `instance`. Aurora replicas keep their
    /// own pg_stat_statements / pg_stat_activity, so this is how reader workload is seen.
    #[serde(default)]
    pub instances: BTreeMap<String, String>,
    pub databases: Option<Vec<String>>,
    #[serde(default)]
    pub overrides: HashMap<String, CollectorOverride>,
    /// Where this server's Postgres log lives. None = the `logs` collector is idle.
    pub logs: Option<LogsConfig>,
}

#[derive(Debug, Deserialize, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum LogSource {
    File,
    Cloudwatch,
}

#[derive(Debug, Deserialize, Clone)]
pub struct LogsConfig {
    pub source: LogSource,
    /// `file`: globs of log files to tail.
    #[serde(default)]
    pub paths: Vec<String>,
    /// `cloudwatch`: log group, e.g. /aws/rds/cluster/<cluster-id>/postgresql
    pub log_group: Option<String>,
    pub region: Option<String>,
    /// Must match the server's `log_line_prefix`. RDS default shown.
    #[serde(default = "default_prefix")]
    pub log_line_prefix: String,
}
fn default_prefix() -> String {
    "%t:%r:%u@%d:[%p]:".into()
}

#[derive(Debug, Deserialize, Clone, Default)]
pub struct CollectorOverride {
    pub enabled: Option<bool>,
    #[serde(with = "humantime_serde", default)]
    pub interval: Option<Duration>,
}

/// Effective per-collector settings after merging defaults + server overrides.
#[derive(Debug, Clone)]
pub struct Effective {
    pub enabled: bool,
    pub interval: Option<Duration>,
}

impl Config {
    pub fn load(path: &Path) -> Result<Self> {
        let raw =
            std::fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?;
        let expanded = shellexpand::env(&raw).context("expanding ${ENV} in config")?;
        let mut cfg: Config = toml::from_str(&expanded).context("parsing config")?;
        cfg.servers.extend(servers_from_env(&cfg.servers));
        anyhow::ensure!(
            !cfg.servers.is_empty(),
            "no servers: add [[servers]] or PGCOLLECTOR_SERVER_<ID>_URL env vars"
        );
        let mut seen = std::collections::HashSet::new();
        for s in &cfg.servers {
            anyhow::ensure!(seen.insert(s.id.clone()), "duplicate server id {}", s.id);
        }
        Ok(cfg)
    }

    pub fn databases_for(&self, s: &ServerConfig) -> Vec<String> {
        s.databases
            .clone()
            .unwrap_or_else(|| self.defaults.databases.clone())
    }

    pub fn effective(&self, s: &ServerConfig, collector: &str, default_enabled: bool) -> Effective {
        let mut e = Effective {
            enabled: default_enabled,
            interval: None,
        };
        for o in [
            self.defaults.overrides.get(collector),
            s.overrides.get(collector),
        ]
        .into_iter()
        .flatten()
        {
            if let Some(en) = o.enabled {
                e.enabled = en;
            }
            if let Some(i) = o.interval {
                e.interval = Some(i);
            }
        }
        e
    }
}

/// Servers declared purely through the environment, so a Helm `psql:` entry is all it
/// takes to monitor a new cluster:
///
///   PGCOLLECTOR_SERVER_<ID>_URL          writer url (required)
///   PGCOLLECTOR_SERVER_<ID>_READER_URL   reader endpoint (optional)
///   PGCOLLECTOR_SERVER_<ID>_INSTANCE_<NAME>_URL   per-instance endpoint (optional, repeatable)
///   PGCOLLECTOR_SERVER_<ID>_LOG_GROUP             CloudWatch log group (optional)
///   PGCOLLECTOR_SERVER_<ID>_LOG_LINE_PREFIX       if not the RDS default
///
/// `<ID>` is lower-cased and `_` → `-` to form the server id. Explicit [[servers]] with
/// the same id win.
fn servers_from_env(explicit: &[ServerConfig]) -> Vec<ServerConfig> {
    const P: &str = "PGCOLLECTOR_SERVER_";
    let mut found: BTreeMap<String, ServerConfig> = BTreeMap::new();
    let vars: Vec<(String, String)> = std::env::vars().filter(|(k, _)| k.starts_with(P)).collect();
    for (k, v) in &vars {
        let rest = &k[P.len()..];
        if let Some(raw_id) = rest
            .strip_suffix("_URL")
            .filter(|r| !r.contains("_INSTANCE_") && !r.ends_with("_READER"))
        {
            let id = norm(raw_id);
            found
                .entry(id.clone())
                .or_insert_with(|| ServerConfig {
                    id,
                    url: v.clone(),
                    reader_url: None,
                    instances: BTreeMap::new(),
                    databases: None,
                    overrides: HashMap::new(),
                    logs: None,
                })
                .url = v.clone();
        }
    }
    for (k, v) in &vars {
        let rest = &k[P.len()..];
        if let Some(raw_id) = rest.strip_suffix("_READER_URL") {
            if let Some(s) = found.get_mut(&norm(raw_id)) {
                s.reader_url = Some(v.clone());
            }
        } else if let Some((raw_id, inst)) = rest
            .strip_suffix("_URL")
            .and_then(|r| r.split_once("_INSTANCE_"))
        {
            if let Some(s) = found.get_mut(&norm(raw_id)) {
                s.instances.insert(norm(inst), v.clone());
            }
        } else if let Some(raw_id) = rest.strip_suffix("_LOG_GROUP") {
            if let Some(s) = found.get_mut(&norm(raw_id)) {
                let prefix = std::env::var(format!("{P}{raw_id}_LOG_LINE_PREFIX"))
                    .unwrap_or_else(|_| default_prefix());
                s.logs = Some(LogsConfig {
                    source: LogSource::Cloudwatch,
                    paths: vec![],
                    log_group: Some(v.clone()),
                    region: None,
                    log_line_prefix: prefix,
                });
            }
        }
    }
    found
        .into_values()
        .filter(|s| !explicit.iter().any(|e| e.id == s.id))
        .collect()
}

fn norm(s: &str) -> String {
    s.to_lowercase().replace('_', "-")
}
