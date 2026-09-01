//! Connection handling for target servers: TLS (RDS requires it), session safety
//! settings, version and database discovery.

use anyhow::{Context, Result};
use std::time::Duration;
use tokio_postgres::Client;

/// TLS policy for a database URL. TLS is required unless the URL says otherwise:
/// `sslmode=disable` → plaintext (local dev), `sslmode=prefer` → try TLS, fall back.
/// RDS/Aurora always offer TLS, so production URLs never need a parameter.
pub fn tls_policy(url: &str) -> tokio_postgres::config::SslMode {
    use tokio_postgres::config::SslMode;
    let lower = url.to_ascii_lowercase();
    if lower.contains("sslmode=disable") {
        SslMode::Disable
    } else if lower.contains("sslmode=prefer") {
        SslMode::Prefer
    } else {
        SslMode::Require
    }
}

pub fn tls_connector() -> tokio_postgres_rustls::MakeRustlsConnect {
    let tls_cfg = rustls::ClientConfig::builder()
        .with_root_certificates(rustls::RootCertStore {
            roots: webpki_roots::TLS_SERVER_ROOTS.to_vec(),
        })
        .with_no_client_auth();
    tokio_postgres_rustls::MakeRustlsConnect::new(tls_cfg)
}

pub async fn connect(
    url: &str,
    statement_timeout: Duration,
    dbname: Option<&str>,
) -> Result<Client> {
    let mut cfg: tokio_postgres::Config = url.parse().context("parsing server url")?;
    if let Some(db) = dbname {
        cfg.dbname(db);
    }
    cfg.application_name("pgcollector");
    cfg.connect_timeout(Duration::from_secs(10));
    cfg.ssl_mode(tls_policy(url));

    let client = match cfg.get_ssl_mode() {
        tokio_postgres::config::SslMode::Disable => {
            let (client, connection) = cfg
                .connect(tokio_postgres::NoTls)
                .await
                .context("connecting")?;
            tokio::spawn(async move {
                if let Err(e) = connection.await {
                    tracing::warn!(error = %e, "target connection closed");
                }
            });
            client
        }
        _ => {
            let (client, connection) = cfg.connect(tls_connector()).await.context("connecting")?;
            tokio::spawn(async move {
                if let Err(e) = connection.await {
                    tracing::warn!(error = %e, "target connection closed");
                }
            });
            client
        }
    };

    // Safety rails: we must never be the thing that hurts production.
    let ms = statement_timeout.as_millis();
    client
        .batch_execute(&format!(
            "SET statement_timeout = {ms}; SET lock_timeout = 1000; \
             SET default_transaction_read_only = on; SET idle_in_transaction_session_timeout = 10000;"
        ))
        .await
        .context("applying session settings")?;
    quiet_session(&client).await;

    // Refuse transaction-pooled PgBouncer: our SET session settings would be lost and
    // the stats views need a stable backend. A pooler hands consecutive statements to
    // different server connections, so pid / setting must agree across two round trips.
    // (Can pass by luck on an idle pooler; deploy with `pgbouncer: false` regardless.)
    let pid1: i32 = client
        .query_one("SELECT pg_backend_pid()", &[])
        .await?
        .get(0);
    let t: String = client
        .query_one("SELECT current_setting('statement_timeout')", &[])
        .await?
        .get(0);
    let pid2: i32 = client
        .query_one("SELECT pg_backend_pid()", &[])
        .await?
        .get(0);
    if pid1 != pid2 || t != format!("{ms}ms") && t != format!("{}s", ms / 1000) {
        anyhow::bail!(
            "session settings do not persist across statements (backend pid {pid1} -> {pid2}, statement_timeout={t}); \
             this looks like a transaction-pooling PgBouncer — point pgcollector at Postgres directly (pgbouncer: false)"
        );
    }
    Ok(client)
}

/// Best effort: keep our own statements out of the server log (they'd otherwise be
/// ingested right back by the logs collector). Needs SET privilege on these GUCs;
/// silently ignored when the role doesn't have it.
pub async fn quiet_session(client: &Client) {
    for sql in [
        "SET log_min_duration_statement = -1",
        "SET log_min_duration_sample = -1",
        "SET auto_explain.log_min_duration = -1",
        "SET log_statement = 'none'",
    ] {
        if let Err(e) = client.simple_query(sql).await {
            tracing::debug!(sql, error = %e, "quiet_session setting not applied");
        }
    }
}

/// PG_VERSION_NUM, e.g. 160003.
pub async fn server_version(client: &Client) -> Result<u32> {
    let row = client
        .query_one("SELECT current_setting('server_version_num')::int", &[])
        .await?;
    Ok(row.get::<_, i32>(0) as u32)
}

/// Connectable, non-template, non-RDS-internal databases.
pub async fn discover_databases(client: &Client) -> Result<Vec<String>> {
    let rows = client
        .query(
            "SELECT datname FROM pg_database \
             WHERE datallowconn AND NOT datistemplate AND datname NOT IN ('rdsadmin') ORDER BY 1",
            &[],
        )
        .await?;
    Ok(rows.into_iter().map(|r| r.get(0)).collect())
}

/// Probe what this connection's server/database offers.
pub async fn capabilities(client: &Client) -> Result<crate::collector::Capabilities> {
    let mut caps = crate::collector::Capabilities::default();
    // aurora_version() only exists on Aurora. Postgres resolves functions at parse time,
    // so check pg_proc first rather than guarding the call with WHERE.
    let has_fn = client
        .query_opt(
            "SELECT 1 FROM pg_proc WHERE proname = 'aurora_version'",
            &[],
        )
        .await?
        .is_some();
    if has_fn {
        if let Ok(r) = client.query_one("SELECT aurora_version()::text", &[]).await {
            caps.aurora = true;
            caps.aurora_version = Some(r.get::<_, String>(0));
        }
    }
    for r in client
        .query("SELECT extname FROM pg_extension", &[])
        .await?
    {
        caps.extensions.insert(r.get::<_, String>(0));
    }
    Ok(caps)
}
