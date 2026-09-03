//! MCP server (streamable HTTP at /mcp). Every tool is read-only and maps onto the
//! same `queries` functions the REST API uses. Auth happens in the axum middleware
//! before requests reach here; the principal is read back from the HTTP request
//! parts for audit logging.

use crate::config::Range;
use crate::queries as q;
use crate::AppState;
use rmcp::{
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    model::*,
    schemars, tool, tool_handler, tool_router,
    transport::streamable_http_server::{
        session::local::LocalSessionManager, StreamableHttpServerConfig, StreamableHttpService,
    },
    ErrorData as McpError, ServerHandler,
};
use serde::Deserialize;
use std::sync::Arc;

#[derive(Clone)]
pub struct PgMcp {
    state: Arc<AppState>,
    #[allow(dead_code)] // referenced by the #[tool_handler] macro expansion
    tool_router: ToolRouter<Self>,
}

fn ok(v: serde_json::Value) -> Result<CallToolResult, McpError> {
    Ok(CallToolResult::success(vec![ContentBlock::text(
        serde_json::to_string_pretty(&v).unwrap_or_default(),
    )]))
}
fn err(e: anyhow::Error) -> McpError {
    McpError::internal_error(format!("{e:#}"), None)
}
fn range(
    since: &Option<String>,
) -> Result<(chrono::DateTime<chrono::Utc>, chrono::DateTime<chrono::Utc>), McpError> {
    Range {
        since: since.clone(),
        from: None,
        to: None,
    }
    .resolve()
    .map_err(err)
}

#[derive(Deserialize, schemars::JsonSchema)]
pub struct ServerArg {
    /// Server id as listed by list_servers (e.g. "cloud", "persons").
    pub server: String,
    /// Look-back window such as "15m", "1h", "24h". Default 1h.
    pub since: Option<String>,
}
#[derive(Deserialize, schemars::JsonSchema)]
pub struct TopQueriesArg {
    pub server: String,
    pub since: Option<String>,
    /// Restrict to one database.
    pub datname: Option<String>,
    /// One of total_exec_time (default), calls, mean_exec_time, rows, shared_blks_read, wal_bytes, storage_blks_read.
    pub order: Option<String>,
    pub limit: Option<i64>,
}
#[derive(Deserialize, schemars::JsonSchema)]
pub struct QueryArg {
    pub server: String,
    pub queryid: i64,
    pub since: Option<String>,
}
#[derive(Deserialize, schemars::JsonSchema)]
pub struct DbArg {
    pub server: String,
    pub datname: String,
    pub since: Option<String>,
    pub limit: Option<i64>,
}
#[derive(Deserialize, schemars::JsonSchema)]
pub struct OptDbArg {
    pub server: String,
    pub datname: Option<String>,
    pub since: Option<String>,
}
#[derive(Deserialize, schemars::JsonSchema)]
pub struct EventsArg {
    pub server: String,
    pub since: Option<String>,
    /// SQL LIKE pattern on event kind, e.g. "schema_%", "log_deadlock", "settings_changed".
    pub kind: Option<String>,
    pub limit: Option<i64>,
}
#[derive(Deserialize, schemars::JsonSchema)]
pub struct SchemaArg {
    pub server: String,
    pub datname: String,
    /// Restrict to one table.
    pub relname: Option<String>,
}
#[derive(Deserialize, schemars::JsonSchema)]
pub struct SettingsArg {
    pub server: String,
    /// Only settings whose source isn't 'default'.
    pub non_default_only: Option<bool>,
}
#[derive(Deserialize, schemars::JsonSchema)]
pub struct SqlArg {
    /// A single read-only SELECT/WITH statement against the stats database. Call describe_stats_schema first for table shapes.
    pub sql: String,
    pub limit: Option<i64>,
}

#[tool_router]
impl PgMcp {
    pub fn new(state: Arc<AppState>) -> Self {
        Self {
            state,
            tool_router: Self::tool_router(),
        }
    }

    #[tool(
        description = "List monitored Postgres servers (Aurora clusters) with version, instances, databases and collector freshness."
    )]
    async fn list_servers(&self) -> Result<CallToolResult, McpError> {
        ok(q::servers(&self.state.db).await.map_err(err)?)
    }

    #[tool(
        description = "Health overview of one server over a window: per-database throughput and cache hit, connection states, top wait events, event counts, top queries by time, tables needing vacuum."
    )]
    async fn server_overview(
        &self,
        Parameters(a): Parameters<ServerArg>,
    ) -> Result<CallToolResult, McpError> {
        let (f, t) = range(&a.since)?;
        ok(q::overview(&self.state.db, &a.server, f, t)
            .await
            .map_err(err)?)
    }
    #[tool(
        description = "Top queries by total time / calls / mean time / rows / I/O over a window, with normalized text, exact mean and stddev, and share of total time."
    )]
    async fn top_queries(
        &self,
        Parameters(a): Parameters<TopQueriesArg>,
    ) -> Result<CallToolResult, McpError> {
        let (f, t) = range(&a.since)?;
        ok(q::top_queries(
            &self.state.db,
            &a.server,
            f,
            t,
            a.datname.as_deref(),
            a.order.as_deref().unwrap_or("total_exec_time"),
            a.limit.unwrap_or(25).clamp(1, 200),
        )
        .await
        .map_err(err)?)
    }
    #[tool(
        description = "Everything about one query id: text, per-minute series, latency percentiles from sampled logs (p50/p90/p95/p99), slowest samples, execution plans (Aurora plan stats and auto_explain), wait events."
    )]
    async fn query_detail(
        &self,
        Parameters(a): Parameters<QueryArg>,
    ) -> Result<CallToolResult, McpError> {
        let (f, t) = range(&a.since)?;
        ok(q::query_detail(&self.state.db, &a.server, a.queryid, f, t)
            .await
            .map_err(err)?)
    }
    #[tool(
        description = "Wait-event breakdown over time (average active sessions by wait event, sampled every 10s) plus exact Aurora wait counts/times when available."
    )]
    async fn wait_events(
        &self,
        Parameters(a): Parameters<ServerArg>,
    ) -> Result<CallToolResult, McpError> {
        let (f, t) = range(&a.since)?;
        ok(q::wait_events(&self.state.db, &a.server, f, t, "1m")
            .await
            .map_err(err)?)
    }
    #[tool(
        description = "What is happening right now: connection counts by state, long-running / lock-waiting / idle-in-transaction sessions, blocking graph, memory-hungry backends."
    )]
    async fn current_activity(
        &self,
        Parameters(a): Parameters<ServerArg>,
    ) -> Result<CallToolResult, McpError> {
        ok(q::current_activity(&self.state.db, &a.server)
            .await
            .map_err(err)?)
    }
    #[tool(
        description = "Per-table statistics for a database: live/dead tuples, scans, tuple churn, sizes, xid age, last vacuum/analyze."
    )]
    async fn table_stats(
        &self,
        Parameters(a): Parameters<DbArg>,
    ) -> Result<CallToolResult, McpError> {
        let (f, t) = range(&a.since)?;
        ok(q::tables(
            &self.state.db,
            &a.server,
            &a.datname,
            f,
            t,
            a.limit.unwrap_or(100).clamp(1, 2000),
        )
        .await
        .map_err(err)?)
    }
    #[tool(
        description = "Index definitions with usage over the window; flags indexes with zero scans (excluding unique/primary) as unused_in_range."
    )]
    async fn index_stats(
        &self,
        Parameters(a): Parameters<DbArg>,
    ) -> Result<CallToolResult, McpError> {
        let (f, t) = range(&a.since)?;
        ok(q::indexes(&self.state.db, &a.server, &a.datname, f, t)
            .await
            .map_err(err)?)
    }
    #[tool(
        description = "Vacuum health: tables past their autovacuum thresholds (dead tuples, analyze, xid/mxid freeze ratios), recent autovacuum runs from the log, vacuums in progress, database xid age."
    )]
    async fn vacuum_status(
        &self,
        Parameters(a): Parameters<OptDbArg>,
    ) -> Result<CallToolResult, McpError> {
        let (f, t) = range(&a.since)?;
        ok(
            q::vacuum(&self.state.db, &a.server, a.datname.as_deref(), f, t)
                .await
                .map_err(err)?,
        )
    }
    #[tool(
        description = "Events: schema changes, setting changes, deadlocks, lock waits, statement cancellations, stats resets — with before/after details."
    )]
    async fn events(
        &self,
        Parameters(a): Parameters<EventsArg>,
    ) -> Result<CallToolResult, McpError> {
        let (f, t) = range(&a.since)?;
        ok(q::events(
            &self.state.db,
            &a.server,
            f,
            t,
            a.kind.as_deref(),
            a.limit.unwrap_or(100).clamp(1, 1000),
        )
        .await
        .map_err(err)?)
    }
    #[tool(description = "Postgres settings (GUCs) on a server, optionally only non-default ones.")]
    async fn settings(
        &self,
        Parameters(a): Parameters<SettingsArg>,
    ) -> Result<CallToolResult, McpError> {
        ok(q::settings(
            &self.state.db,
            &a.server,
            a.non_default_only.unwrap_or(true),
        )
        .await
        .map_err(err)?)
    }
    #[tool(
        description = "Schema of a database (or one table): columns, partitioning, indexes with definitions, constraints."
    )]
    async fn schema(
        &self,
        Parameters(a): Parameters<SchemaArg>,
    ) -> Result<CallToolResult, McpError> {
        ok(
            q::schema(&self.state.db, &a.server, &a.datname, a.relname.as_deref())
                .await
                .map_err(err)?,
        )
    }
    #[tool(
        description = "Errors and log activity over the window: grouped error summary, recent errors with statements, log counts by class, largest temp-file spills."
    )]
    async fn log_errors(
        &self,
        Parameters(a): Parameters<ServerArg>,
    ) -> Result<CallToolResult, McpError> {
        let (f, t) = range(&a.since)?;
        ok(q::log_errors(&self.state.db, &a.server, f, t, 100)
            .await
            .map_err(err)?)
    }
    #[tool(
        description = "System view: host CPU/memory (pg_proctab), top backends by CPU, checkpoints, bgwriter, Aurora replica status and per-database commit/DML latency."
    )]
    async fn system_stats(
        &self,
        Parameters(a): Parameters<ServerArg>,
    ) -> Result<CallToolResult, McpError> {
        let (f, t) = range(&a.since)?;
        ok(q::system(&self.state.db, &a.server, f, t)
            .await
            .map_err(err)?)
    }
    #[tool(
        description = "Is the collector itself healthy: ticks, errors and durations per collector/server in the last 15 minutes."
    )]
    async fn collector_health(&self) -> Result<CallToolResult, McpError> {
        ok(q::collector_health(&self.state.db).await.map_err(err)?)
    }
    #[tool(description = "Tables and columns of the stats database, for use with query_stats_db.")]
    async fn describe_stats_schema(&self) -> Result<CallToolResult, McpError> {
        ok(q::schema_of_stats_db(&self.state.db).await.map_err(err)?)
    }
    #[tool(
        description = "Run a read-only SQL query directly against the stats database (partitioned ts_* time series keyed by server_id/instance/datname/collected_at, cur_* current state, events). Use when the other tools don't answer the question."
    )]
    async fn query_stats_db(
        &self,
        Parameters(a): Parameters<SqlArg>,
    ) -> Result<CallToolResult, McpError> {
        ok(q::raw_sql(&self.state.db, &a.sql, a.limit.unwrap_or(200))
            .await
            .map_err(err)?)
    }
}

#[tool_handler]
impl ServerHandler for PgMcp {
    fn get_info(&self) -> ServerInfo {
        ServerInfo::new(ServerCapabilities::builder().enable_tools().build())
            .with_server_info(Implementation::from_build_env())
            .with_instructions("Read-only access to PostHog's Postgres telemetry (pgcollector). Start with list_servers, then server_overview; drill into top_queries / query_detail for performance, current_activity for live issues, vacuum_status and events for maintenance. query_stats_db runs arbitrary read-only SQL against the stats database.")
    }
}

pub fn service(state: Arc<AppState>) -> StreamableHttpService<PgMcp, LocalSessionManager> {
    StreamableHttpService::new(
        move || Ok(PgMcp::new(state.clone())),
        LocalSessionManager::default().into(),
        StreamableHttpServerConfig::default(),
    )
}
