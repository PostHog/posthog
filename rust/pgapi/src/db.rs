//! Read-only access to the stats database, returning rows as JSON objects so the
//! REST and MCP layers can share every query without per-endpoint structs.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use deadpool_postgres::{Manager, ManagerConfig, Pool, RecyclingMethod};
use serde_json::{json, Map, Value};
use tokio_postgres::types::{ToSql, Type};

/// Serialised-response ceiling for raw SQL. Row count is bounded by LIMIT; this bounds
/// bytes so a wide or `repeat()`-style query can't exhaust the pod's memory.
pub const RAW_SQL_MAX_BYTES: usize = 8 * 1024 * 1024;

#[derive(Clone)]
pub struct Db {
    pool: Pool,
}

impl Db {
    pub async fn connect(url: &str) -> Result<Self> {
        let mut cfg: tokio_postgres::Config = url.parse().context("parsing PGAPI_DATABASE_URL")?;
        cfg.ssl_mode(tokio_postgres::config::SslMode::Require);
        let mut roots = rustls::RootCertStore::empty();
        let native = rustls_native_certs::load_native_certs();
        for cert in native.certs {
            drop(roots.add(cert));
        }
        if roots.is_empty() {
            roots.roots = webpki_roots::TLS_SERVER_ROOTS.to_vec();
        }
        let tls_cfg = rustls::ClientConfig::builder()
            .with_root_certificates(roots)
            .with_no_client_auth();
        let tls = tokio_postgres_rustls::MakeRustlsConnect::new(tls_cfg);
        let mgr = Manager::from_config(
            cfg,
            tls,
            ManagerConfig {
                recycling_method: RecyclingMethod::Fast,
            },
        );
        let pool = Pool::builder(mgr)
            .max_size(16)
            .post_create(deadpool_postgres::Hook::async_fn(|c, _| Box::pin(async move {
                // The API is read-only by construction; make the session enforce it too. A
                // connection that cannot be made read-only is rejected, never pooled.
                c.batch_execute("SET default_transaction_read_only = on; SET statement_timeout = 30000; SET application_name = 'pgapi'")
                    .await
                    .map_err(|e| {
                        tracing::error!(error = %e, "could not apply read-only session settings; dropping connection");
                        deadpool_postgres::HookError::Backend(e)
                    })
            })))
            .build()?;
        let db = Self { pool };
        db.query("SELECT 1", &[])
            .await
            .context("stats database unreachable")?;
        Ok(db)
    }

    pub async fn ping(&self) -> bool {
        self.query("SELECT 1", &[]).await.is_ok()
    }

    pub async fn query(&self, sql: &str, params: &[&(dyn ToSql + Sync)]) -> Result<Vec<Value>> {
        let c = self.pool.get().await?;
        let rows = c
            .query(sql, params)
            .await
            .with_context(|| format!("query failed: {}", sql.lines().next().unwrap_or("")))?;
        rows.iter().map(row_to_json).collect()
    }

    /// Run one statement in a read-only transaction with a short timeout, then reset
    /// the session with `DISCARD ALL` so nothing it did (advisory locks, temp objects,
    /// SET) outlives the request. If the reset fails the connection is dropped.
    pub async fn query_isolated(&self, sql: &str) -> Result<Value> {
        let mut c = self.pool.get().await?;
        let result = async {
            let tx = c.build_transaction().read_only(true).start().await?;
            tx.batch_execute("SET LOCAL statement_timeout = 15000; SET LOCAL lock_timeout = 1000")
                .await?;
            // Stream rows and stop once the serialised response would exceed the budget;
            // dropping the stream and rolling back cancels the server side. Row count is
            // capped by the caller's LIMIT, bytes are capped here.
            use futures_util::TryStreamExt;
            let params: [&(dyn ToSql + Sync); 0] = [];
            let stream = tx
                .query_raw(sql, params)
                .await
                .with_context(|| format!("query failed: {}", sql.lines().next().unwrap_or("")))?;
            let mut stream = std::pin::pin!(stream);
            let mut out = Vec::new();
            let mut bytes = 0usize;
            while let Some(row) = stream.try_next().await.context("query failed")? {
                let v = row_to_json(&row)?;
                bytes += serde_json::to_vec(&v).map(|b| b.len()).unwrap_or(0);
                anyhow::ensure!(
                    bytes <= RAW_SQL_MAX_BYTES,
                    "result exceeds {} MiB; narrow the query or select fewer columns",
                    RAW_SQL_MAX_BYTES / (1024 * 1024)
                );
                out.push(v);
            }
            tx.rollback().await?;
            Ok::<_, anyhow::Error>(out)
        }
        .await;
        if c.batch_execute(
            "DISCARD ALL; SET default_transaction_read_only = on; SET statement_timeout = 30000",
        )
        .await
        .is_err()
        {
            // Don't hand a dirty session back to the pool.
            drop(deadpool_postgres::Object::take(c));
        }
        Ok(json!(result?))
    }

    pub async fn query_one(&self, sql: &str, params: &[&(dyn ToSql + Sync)]) -> Result<Value> {
        Ok(self
            .query(sql, params)
            .await?
            .into_iter()
            .next()
            .unwrap_or(Value::Null))
    }
}

pub fn row_to_json(r: &tokio_postgres::Row) -> Result<Value> {
    let mut m = Map::new();
    for (i, col) in r.columns().iter().enumerate() {
        let v = match *col.type_() {
            Type::BOOL => r.try_get::<_, Option<bool>>(i)?.map(Value::from),
            Type::INT2 => r.try_get::<_, Option<i16>>(i)?.map(Value::from),
            Type::INT4 => r.try_get::<_, Option<i32>>(i)?.map(Value::from),
            // JavaScript numbers lose precision past 2^53; query/plan ids are full
            // int64 hashes, so ship those as strings.
            Type::INT8 => r.try_get::<_, Option<i64>>(i)?.map(|v| {
                if v.unsigned_abs() > (1u64 << 53) {
                    Value::from(v.to_string())
                } else {
                    Value::from(v)
                }
            }),
            Type::OID => r.try_get::<_, Option<u32>>(i)?.map(Value::from),
            Type::FLOAT4 => r.try_get::<_, Option<f32>>(i)?.map(|x| json!(x)),
            Type::FLOAT8 => r.try_get::<_, Option<f64>>(i)?.map(|x| json!(x)),
            Type::NUMERIC => r.try_get::<_, Option<rust_decimal::Decimal>>(i)?.map(|d| {
                let f: f64 = d.try_into().unwrap_or(f64::NAN);
                json!(f)
            }),
            Type::TIMESTAMPTZ => r.try_get::<_, Option<DateTime<Utc>>>(i)?.map(|t| json!(t)),
            Type::JSON | Type::JSONB => r.try_get::<_, Option<Value>>(i)?,
            // Functions returning void (raw SQL calling e.g. pg_advisory_lock) produce a
            // void column; render it as null rather than failing the whole row.
            Type::VOID => None,
            Type::TEXT_ARRAY | Type::VARCHAR_ARRAY | Type::NAME_ARRAY => {
                r.try_get::<_, Option<Vec<String>>>(i)?.map(|v| json!(v))
            }
            Type::INT8_ARRAY => r.try_get::<_, Option<Vec<i64>>>(i)?.map(|v| json!(v)),
            Type::TEXT | Type::VARCHAR | Type::NAME | Type::BPCHAR | Type::CHAR | Type::UNKNOWN => {
                r.try_get::<_, Option<String>>(i)?.map(Value::from)
            }
            _ => anyhow::bail!(
                "unsupported column type {} for {}; cast in SQL",
                col.type_(),
                col.name()
            ),
        };
        m.insert(col.name().to_string(), v.unwrap_or(Value::Null));
    }
    Ok(Value::Object(m))
}
