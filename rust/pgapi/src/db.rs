//! Read-only access to the stats database, returning rows as JSON objects so the
//! REST and MCP layers can share every query without per-endpoint structs.

use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use deadpool_postgres::{Manager, ManagerConfig, Pool, RecyclingMethod};
use serde_json::{json, Map, Value};
use tokio_postgres::types::{ToSql, Type};
use tokio_postgres::NoTls;

#[derive(Clone)]
pub struct Db {
    pool: Pool,
}

impl Db {
    pub async fn connect(url: &str) -> Result<Self> {
        let cfg: tokio_postgres::Config = url.parse().context("parsing PGAPI_DATABASE_URL")?;
        let mgr = Manager::from_config(
            cfg,
            NoTls,
            ManagerConfig {
                recycling_method: RecyclingMethod::Fast,
            },
        );
        let pool = Pool::builder(mgr)
            .max_size(16)
            .post_create(deadpool_postgres::Hook::async_fn(|c, _| Box::pin(async move {
                // The API is read-only by construction; make the session enforce it too.
                if let Err(e) = c.batch_execute("SET default_transaction_read_only = on; SET statement_timeout = 30000; SET application_name = 'pgapi'").await {
                    tracing::warn!(error = %e, "could not apply read-only session settings");
                }
                Ok(())
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
            Type::INT8 => r.try_get::<_, Option<i64>>(i)?.map(Value::from),
            Type::OID => r.try_get::<_, Option<u32>>(i)?.map(Value::from),
            Type::FLOAT4 => r.try_get::<_, Option<f32>>(i)?.map(|x| json!(x)),
            Type::FLOAT8 => r.try_get::<_, Option<f64>>(i)?.map(|x| json!(x)),
            Type::NUMERIC => r.try_get::<_, Option<rust_decimal::Decimal>>(i)?.map(|d| {
                let f: f64 = d.try_into().unwrap_or(f64::NAN);
                json!(f)
            }),
            Type::TIMESTAMPTZ => r.try_get::<_, Option<DateTime<Utc>>>(i)?.map(|t| json!(t)),
            Type::JSON | Type::JSONB => r.try_get::<_, Option<Value>>(i)?,
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
