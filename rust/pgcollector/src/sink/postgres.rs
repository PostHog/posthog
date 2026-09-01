//! Postgres sink. Tier A tables are created/extended on the fly from the shape of
//! the rows; hand-written tables live in migrations/.

use super::{Run, ServerInfo, Sink};
use crate::collector::{Kind, Snapshot, State, Target, Value};
use crate::config::SinkConfig;
use anyhow::{Context, Result};
use async_trait::async_trait;
use chrono::{Duration as CDuration, Utc};
use deadpool_postgres::{Manager, ManagerConfig, Pool, RecyclingMethod};
use std::collections::{BTreeMap, HashSet};
use std::sync::Mutex;
use tokio_postgres::types::ToSql;

pub struct PostgresSink {
    pool: Pool,
    retention_days: u32,
    /// table → known columns, so we only hit the catalog when a new column shows up.
    schema_cache: Mutex<BTreeMap<String, HashSet<String>>>,
}

/// Columns the sink owns. A collector row carrying one of these (e.g. `datname` from
/// a cluster-scoped `pg_stat_database` query) supplies the identity value instead of
/// becoming a metric column.
const RESERVED: &[&str] = &[
    "server_id",
    "instance",
    "datname",
    "collected_at",
    "interval_seconds",
    "first_seen",
    "last_seen",
];

fn metric_cols(row: &crate::collector::Row) -> Vec<String> {
    row.keys()
        .filter(|k| !RESERVED.contains(&k.as_str()))
        .cloned()
        .collect()
}

fn datname_for(snap: &Snapshot, row: &crate::collector::Row) -> Option<String> {
    snap.target
        .datname
        .clone()
        .or_else(|| match row.get("datname") {
            Some(Value::Text(s)) => Some(s.clone()),
            _ => None,
        })
}

const MIGRATIONS: &[(&str, &str)] =
    &[("0001_base", include_str!("../../migrations/0001_base.sql"))];

impl PostgresSink {
    pub async fn connect(cfg: &SinkConfig) -> Result<Self> {
        let mut pg_cfg: tokio_postgres::Config =
            cfg.database_url.parse().context("parsing sink url")?;
        // TLS required unless the URL opts out (see pg::tls_policy).
        pg_cfg.ssl_mode(crate::pg::tls_policy(&cfg.database_url));
        let mgr = Manager::from_config(
            pg_cfg,
            crate::pg::tls_connector(),
            ManagerConfig {
                recycling_method: RecyclingMethod::Fast,
            },
        );
        let pool = Pool::builder(mgr)
            .max_size(8)
            .post_create(deadpool_postgres::Hook::async_fn(|client, _| {
                Box::pin(async move {
                    crate::pg::quiet_session(client).await;
                    Ok(())
                })
            }))
            .build()?;
        let sink = Self {
            pool,
            retention_days: cfg.retention_days,
            schema_cache: Mutex::new(BTreeMap::new()),
        };
        sink.migrate().await?;
        sink.maintain().await?;
        Ok(sink)
    }

    async fn migrate(&self) -> Result<()> {
        let c = self.pool.get().await?;
        c.batch_execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())",
        )
        .await?;
        for (name, sql) in MIGRATIONS {
            let done = c
                .query_opt("SELECT 1 FROM schema_migrations WHERE name = $1", &[name])
                .await?
                .is_some();
            if !done {
                tracing::info!(migration = name, "applying");
                c.batch_execute(sql)
                    .await
                    .with_context(|| format!("migration {name}"))?;
                c.execute("INSERT INTO schema_migrations (name) VALUES ($1)", &[name])
                    .await?;
            }
        }
        Ok(())
    }

    /// Ensure `ts_<name>` / `cur_<name>` exists with every column the snapshot carries.
    async fn ensure_table(
        &self,
        c: &deadpool_postgres::Client,
        table: &str,
        snap: &Snapshot,
    ) -> Result<()> {
        let sample = match snap.rows.first() {
            Some(r) => r,
            None => return Ok(()),
        };
        let mut wanted: Vec<(String, &str)> = Vec::new();
        // (types borrowed from snap.types or inferred; both live as long as `snap`)
        for (col, v) in sample {
            if RESERVED.contains(&col.as_str()) {
                continue;
            }
            let ty = match snap.types.get(col) {
                Some(t) => t.as_str(),
                None => snap
                    .rows
                    .iter()
                    .filter_map(|r| r.get(col))
                    .find(|v| !matches!(v, Value::Null))
                    .unwrap_or(v)
                    .pg_type(),
            };
            wanted.push((col.clone(), ty));
        }

        let known = self.schema_cache.lock().unwrap().get(table).cloned();
        let known = match known {
            Some(k) if wanted.iter().all(|(c, _)| k.contains(c)) => return Ok(()),
            Some(k) => k,
            None => {
                let exists = c
                    .query_opt(
                        "SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = $1",
                        &[&table],
                    )
                    .await?
                    .is_some();
                if !exists {
                    self.create_table(c, table, snap, &wanted).await?;
                }
                let cols = c
                    .query(
                        "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
                        &[&table],
                    )
                    .await?;
                cols.into_iter().map(|r| r.get::<_, String>(0)).collect()
            }
        };

        let mut known = known;
        for (col, ty) in &wanted {
            if !known.contains(col) {
                tracing::info!(table, column = col, r#type = ty, "adding column");
                c.batch_execute(&format!(
                    "ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {} {ty}",
                    q(col)
                ))
                .await?;
                known.insert(col.clone());
            }
        }
        self.schema_cache
            .lock()
            .unwrap()
            .insert(table.to_string(), known);
        Ok(())
    }

    async fn create_table(
        &self,
        c: &deadpool_postgres::Client,
        table: &str,
        snap: &Snapshot,
        cols: &[(String, &str)],
    ) -> Result<()> {
        let col_defs: Vec<String> = cols.iter().map(|(n, t)| format!("{} {t}", q(n))).collect();
        let sql = match snap.kind {
            Kind::Snapshot => {
                let pk: Vec<String> = ["server_id".to_string(), "instance".to_string(), "datname".to_string()].iter()
                    .chain(snap.key.iter().filter(|k| !RESERVED.contains(&k.as_str()))).map(|k| q(k)).collect();
                format!(
                    "CREATE TABLE IF NOT EXISTS {table} (server_id text NOT NULL, instance text NOT NULL DEFAULT 'writer', datname text NOT NULL DEFAULT '', \
                     first_seen timestamptz NOT NULL, last_seen timestamptz NOT NULL, {}, PRIMARY KEY ({}))",
                    col_defs.join(", "),
                    pk.join(", ")
                )
            }
            _ => format!(
                "CREATE TABLE IF NOT EXISTS {table} (server_id text NOT NULL, instance text NOT NULL, datname text, collected_at timestamptz NOT NULL, \
                 interval_seconds real, {}) PARTITION BY RANGE (collected_at); \
                 CREATE INDEX IF NOT EXISTS {table}_server_time_idx ON {table} (server_id, collected_at);",
                col_defs.join(", ")
            ),
        };
        tracing::info!(table, "creating table");
        // Several collector loops can see the same table missing at once (first tick
        // of every database); serialise the DDL so the losers see IF NOT EXISTS hit.
        let sql = sql.trim_end().trim_end_matches(';');
        c.batch_execute(&format!(
            "BEGIN; SELECT pg_advisory_xact_lock(hashtext('pgcollector:{table}')); {sql}; COMMIT;"
        ))
        .await
        .with_context(|| format!("creating {table}"))?;
        if snap.kind != Kind::Snapshot {
            self.ensure_partitions(c, table).await?;
        }
        Ok(())
    }

    async fn ensure_partitions(&self, c: &deadpool_postgres::Client, table: &str) -> Result<()> {
        let today = Utc::now().date_naive();
        for d in -1..=2i64 {
            let day = today + CDuration::days(d);
            let next = day + CDuration::days(1);
            let part = format!("{table}_{}", day.format("%Y%m%d"));
            c.batch_execute(&format!(
                "CREATE TABLE IF NOT EXISTS {part} PARTITION OF {table} FOR VALUES FROM ('{day}') TO ('{next}')"
            ))
            .await?;
        }
        Ok(())
    }

    async fn write_ts(
        &self,
        c: &deadpool_postgres::Client,
        table: &str,
        snap: &Snapshot,
    ) -> Result<()> {
        let cols = metric_cols(&snap.rows[0]);
        let mut all_cols = vec![
            "server_id".to_string(),
            "instance".to_string(),
            "datname".to_string(),
            "collected_at".to_string(),
            "interval_seconds".to_string(),
        ];
        all_cols.extend(cols.iter().cloned());
        let col_list = all_cols.iter().map(|c| q(c)).collect::<Vec<_>>().join(", ");

        // Multi-row VALUES in chunks; COPY is the upgrade path if this ever matters.
        for chunk in snap.rows.chunks(500) {
            let mut params: Vec<Box<dyn ToSql + Sync + Send>> = Vec::new();
            let mut tuples = Vec::new();
            let interval = snap.interval_seconds as f32;
            for row in chunk {
                let base = params.len();
                params.push(Box::new(snap.target.server_id.clone()));
                params.push(Box::new(snap.target.instance.clone()));
                params.push(Box::new(datname_for(snap, row)));
                params.push(Box::new(snap.collected_at));
                params.push(Box::new(interval));
                for col in &cols {
                    params.push(to_sql(row.get(col).unwrap_or(&Value::Null)));
                }
                let ph: Vec<String> = (0..all_cols.len())
                    .map(|i| format!("${}", base + i + 1))
                    .collect();
                tuples.push(format!("({})", ph.join(", ")));
            }
            let sql = format!(
                "INSERT INTO {table} ({col_list}) VALUES {}",
                tuples.join(", ")
            );
            let refs: Vec<&(dyn ToSql + Sync)> = params
                .iter()
                .map(|p| -> &(dyn ToSql + Sync) { p.as_ref() })
                .collect();
            c.execute(&sql, &refs)
                .await
                .with_context(|| format!("inserting into {table}"))?;
        }
        Ok(())
    }

    async fn write_cur(
        &self,
        c: &deadpool_postgres::Client,
        table: &str,
        snap: &Snapshot,
    ) -> Result<()> {
        let cols = metric_cols(&snap.rows[0]);
        let mut all_cols = vec![
            "server_id".to_string(),
            "instance".to_string(),
            "datname".to_string(),
            "first_seen".to_string(),
            "last_seen".to_string(),
        ];
        all_cols.extend(cols.iter().cloned());
        let col_list = all_cols.iter().map(|c| q(c)).collect::<Vec<_>>().join(", ");
        let pk: Vec<String> = ["server_id", "instance", "datname"]
            .iter()
            .map(|s| s.to_string())
            .chain(
                snap.key
                    .iter()
                    .filter(|k| !RESERVED.contains(&k.as_str()))
                    .cloned(),
            )
            .map(|k| q(&k))
            .collect();
        let updates: Vec<String> = cols
            .iter()
            .filter(|c| !snap.key.contains(c))
            .map(|c| format!("{0} = EXCLUDED.{0}", q(c)))
            .collect();
        let set = std::iter::once("last_seen = EXCLUDED.last_seen".to_string())
            .chain(updates)
            .collect::<Vec<_>>()
            .join(", ");

        for row in &snap.rows {
            let mut params: Vec<Box<dyn ToSql + Sync + Send>> = vec![
                Box::new(snap.target.server_id.clone()),
                Box::new(snap.target.instance.clone()),
                Box::new(datname_for(snap, row).unwrap_or_default()),
                Box::new(snap.collected_at),
                Box::new(snap.collected_at),
            ];
            for col in &cols {
                params.push(to_sql(row.get(col).unwrap_or(&Value::Null)));
            }
            let ph: Vec<String> = (1..=all_cols.len()).map(|i| format!("${i}")).collect();
            let sql = format!(
                "INSERT INTO {table} ({col_list}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {set}",
                ph.join(", "),
                pk.join(", ")
            );
            let refs: Vec<&(dyn ToSql + Sync)> = params
                .iter()
                .map(|p| -> &(dyn ToSql + Sync) { p.as_ref() })
                .collect();
            c.execute(&sql, &refs)
                .await
                .with_context(|| format!("upserting into {table}"))?;
        }
        // Rows no longer present: mark by leaving last_seen stale; the API layer filters on it.
        Ok(())
    }
}

#[async_trait]
impl Sink for PostgresSink {
    async fn write(&self, snap: &Snapshot) -> Result<()> {
        for a in &snap.aux {
            Box::pin(self.write(a)).await?;
        }
        let c = self.pool.get().await?;
        for ev in &snap.events {
            c.execute(
                "INSERT INTO events (server_id, instance, datname, at, kind, subject, before, after) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                &[&snap.target.server_id, &snap.target.instance, &snap.target.datname, &snap.collected_at, &ev.kind, &ev.subject, &ev.before, &ev.after],
            )
            .await?;
        }
        if snap.rows.is_empty() {
            return Ok(());
        }
        let table = match snap.kind {
            Kind::Snapshot => format!("cur_{}", snap.collector),
            _ => format!("ts_{}", snap.collector),
        };
        self.ensure_table(&c, &table, snap).await?;
        match snap.kind {
            Kind::Snapshot => self.write_cur(&c, &table, snap).await,
            _ => self.write_ts(&c, &table, snap).await,
        }
    }

    async fn record_run(&self, run: &Run) -> Result<()> {
        let c = self.pool.get().await?;
        c.execute(
            "INSERT INTO collector_runs (collector, server_id, instance, datname, started_at, duration_ms, rows, error) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            &[&run.collector, &run.target.server_id, &run.target.instance, &run.target.datname, &run.started_at, &run.duration_ms, &run.rows, &run.error],
        )
        .await?;
        Ok(())
    }

    async fn save_state(&self, collector: &str, target: &Target, state: &State) -> Result<()> {
        let c = self.pool.get().await?;
        let dat = target.datname.clone().unwrap_or_default();
        c.execute(
            "INSERT INTO collector_state (collector, server_id, instance, datname, state, updated_at) VALUES ($1,$2,$3,$4,$5,now()) \
             ON CONFLICT (collector, server_id, instance, datname) DO UPDATE SET state = EXCLUDED.state, updated_at = now()",
            &[&collector, &target.server_id, &target.instance, &dat, &serde_json::to_value(state)?],
        )
        .await?;
        Ok(())
    }

    async fn load_state(&self, collector: &str, target: &Target) -> Result<Option<State>> {
        let c = self.pool.get().await?;
        let dat = target.datname.clone().unwrap_or_default();
        let row = c
            .query_opt(
                "SELECT state FROM collector_state WHERE collector = $1 AND server_id = $2 AND instance = $3 AND datname = $4",
                &[&collector, &target.server_id, &target.instance, &dat],
            )
            .await?;
        Ok(match row {
            Some(r) => Some(serde_json::from_value(r.get::<_, serde_json::Value>(0))?),
            None => None,
        })
    }

    async fn register_server(&self, info: &ServerInfo) -> Result<()> {
        let c = self.pool.get().await?;
        c.execute(
            "INSERT INTO cur_servers (server_id, system_identifier, version_num, version, aurora_version, instances, databases, first_seen, last_seen)
             VALUES ($1,$2,$3,$4,$5,$6,$7,now(),now())
             ON CONFLICT (server_id) DO UPDATE SET system_identifier = EXCLUDED.system_identifier, version_num = EXCLUDED.version_num,
               version = EXCLUDED.version, aurora_version = EXCLUDED.aurora_version, instances = EXCLUDED.instances, databases = EXCLUDED.databases, last_seen = now()",
            &[&info.server_id, &info.system_identifier, &info.version_num, &info.version, &info.aurora_version, &info.instances, &info.databases],
        ).await?;
        Ok(())
    }

    async fn maintain(&self) -> Result<()> {
        let c = self.pool.get().await?;
        let tables: Vec<String> = c
            .query(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace \
                 WHERE n.nspname = 'public' AND c.relkind = 'p' AND c.relname LIKE 'ts\\_%'",
                &[],
            )
            .await?
            .into_iter()
            .map(|r| r.get(0))
            .collect();
        let cutoff = (Utc::now().date_naive() - CDuration::days(self.retention_days as i64))
            .format("%Y%m%d")
            .to_string();
        for t in &tables {
            self.ensure_partitions(&c, t).await?;
            let parts = c
                .query(
                    "SELECT inhrelid::regclass::text FROM pg_inherits WHERE inhparent = $1::text::regclass",
                    &[t],
                )
                .await?;
            for p in parts {
                let name: String = p.get(0);
                if let Some(stamp) = name.rsplit('_').next() {
                    if stamp.len() == 8 && stamp < cutoff.as_str() {
                        tracing::info!(partition = name, "dropping expired partition");
                        c.batch_execute(&format!("DROP TABLE IF EXISTS {name}"))
                            .await?;
                    }
                }
            }
        }
        Ok(())
    }
}

fn q(ident: &str) -> String {
    format!("\"{}\"", ident.replace('"', "\"\""))
}

/// A NULL that serialises into any column type.
#[derive(Debug)]
struct NullAny;
impl ToSql for NullAny {
    fn to_sql(
        &self,
        _: &tokio_postgres::types::Type,
        _: &mut bytes::BytesMut,
    ) -> std::result::Result<tokio_postgres::types::IsNull, Box<dyn std::error::Error + Sync + Send>>
    {
        Ok(tokio_postgres::types::IsNull::Yes)
    }
    fn accepts(_: &tokio_postgres::types::Type) -> bool {
        true
    }
    tokio_postgres::types::to_sql_checked!();
}

fn to_sql(v: &Value) -> Box<dyn ToSql + Sync + Send> {
    match v {
        Value::Null => Box::new(NullAny),
        Value::Bool(b) => Box::new(*b),
        Value::Int(i) => Box::new(*i),
        Value::Float(f) => Box::new(*f),
        Value::Text(s) => Box::new(s.clone()),
        Value::Timestamp(t) => Box::new(*t),
        Value::Json(j) => Box::new(j.clone()),
    }
}
