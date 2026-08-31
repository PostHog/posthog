//! REST surface. Handlers are thin: parse params, call `queries`, return JSON.

use crate::auth::Principal;
use crate::config::Range;
use crate::queries as q;
use crate::AppState;
use axum::{
    extract::{Extension, Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Json, Response},
    routing::get,
    Router,
};
use serde::Deserialize;
use std::sync::Arc;

type S = State<Arc<AppState>>;

pub struct ApiError(anyhow::Error);
impl<E: Into<anyhow::Error>> From<E> for ApiError {
    fn from(e: E) -> Self {
        Self(e.into())
    }
}
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let msg = format!("{:#}", self.0);
        let code = if msg.contains("range") || msg.contains("allowed") || msg.contains("only") {
            StatusCode::BAD_REQUEST
        } else {
            StatusCode::INTERNAL_SERVER_ERROR
        };
        (code, Json(serde_json::json!({ "error": msg }))).into_response()
    }
}
type R = Result<Json<serde_json::Value>, ApiError>;

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/me", get(me))
        .route("/servers", get(servers))
        .route("/servers/:server/overview", get(overview))
        .route("/servers/:server/queries", get(top_queries))
        .route("/servers/:server/queries/:queryid", get(query_detail))
        .route("/servers/:server/waits", get(waits))
        .route("/servers/:server/activity", get(activity))
        .route("/servers/:server/tables", get(tables))
        .route("/servers/:server/indexes", get(indexes))
        .route("/servers/:server/vacuum", get(vacuum))
        .route("/servers/:server/events", get(events))
        .route("/servers/:server/settings", get(settings))
        .route("/servers/:server/schema", get(schema))
        .route("/servers/:server/logs", get(logs))
        .route("/servers/:server/system", get(system))
        .route("/collector/health", get(collector_health))
        .route("/sql", get(sql))
        .route("/stats-schema", get(stats_schema))
}

async fn me(Extension(p): Extension<Principal>) -> R {
    Ok(Json(serde_json::to_value(p)?))
}
async fn servers(State(s): S) -> R {
    Ok(Json(q::servers(&s.db).await?))
}

async fn overview(State(s): S, Path(server): Path<String>, Query(r): Query<Range>) -> R {
    let (f, t) = r.resolve()?;
    Ok(Json(q::overview(&s.db, &server, f, t).await?))
}

#[derive(Deserialize)]
struct TopQ {
    #[serde(flatten)]
    range: Range,
    datname: Option<String>,
    #[serde(default = "d_order")]
    order: String,
    #[serde(default = "d_limit")]
    limit: i64,
}
fn d_order() -> String {
    "total_exec_time".into()
}
fn d_limit() -> i64 {
    50
}
async fn top_queries(State(s): S, Path(server): Path<String>, Query(p): Query<TopQ>) -> R {
    let (f, t) = p.range.resolve()?;
    Ok(Json(
        q::top_queries(
            &s.db,
            &server,
            f,
            t,
            p.datname.as_deref(),
            &p.order,
            p.limit.clamp(1, 500),
        )
        .await?,
    ))
}
async fn query_detail(
    State(s): S,
    Path((server, queryid)): Path<(String, i64)>,
    Query(r): Query<Range>,
) -> R {
    let (f, t) = r.resolve()?;
    Ok(Json(q::query_detail(&s.db, &server, queryid, f, t).await?))
}
#[derive(Deserialize)]
struct WaitsQ {
    #[serde(flatten)]
    range: Range,
    #[serde(default = "d_bucket")]
    bucket: String,
}
fn d_bucket() -> String {
    "1m".into()
}
async fn waits(State(s): S, Path(server): Path<String>, Query(p): Query<WaitsQ>) -> R {
    let (f, t) = p.range.resolve()?;
    Ok(Json(q::wait_events(&s.db, &server, f, t, &p.bucket).await?))
}
async fn activity(State(s): S, Path(server): Path<String>) -> R {
    Ok(Json(q::current_activity(&s.db, &server).await?))
}

#[derive(Deserialize)]
struct DbQ {
    #[serde(flatten)]
    range: Range,
    datname: String,
    #[serde(default = "d_limit")]
    limit: i64,
}
async fn tables(State(s): S, Path(server): Path<String>, Query(p): Query<DbQ>) -> R {
    let (f, t) = p.range.resolve()?;
    Ok(Json(
        q::tables(&s.db, &server, &p.datname, f, t, p.limit.clamp(1, 2000)).await?,
    ))
}
async fn indexes(State(s): S, Path(server): Path<String>, Query(p): Query<DbQ>) -> R {
    let (f, t) = p.range.resolve()?;
    Ok(Json(q::indexes(&s.db, &server, &p.datname, f, t).await?))
}
#[derive(Deserialize)]
struct OptDbQ {
    #[serde(flatten)]
    range: Range,
    datname: Option<String>,
    kind: Option<String>,
    relname: Option<String>,
    #[serde(default = "d_limit")]
    limit: i64,
    #[serde(default)]
    non_default: bool,
}
async fn vacuum(State(s): S, Path(server): Path<String>, Query(p): Query<OptDbQ>) -> R {
    let (f, t) = p.range.resolve()?;
    Ok(Json(
        q::vacuum(&s.db, &server, p.datname.as_deref(), f, t).await?,
    ))
}
async fn events(State(s): S, Path(server): Path<String>, Query(p): Query<OptDbQ>) -> R {
    let (f, t) = p.range.resolve()?;
    Ok(Json(
        q::events(
            &s.db,
            &server,
            f,
            t,
            p.kind.as_deref(),
            p.limit.clamp(1, 1000),
        )
        .await?,
    ))
}
async fn settings(State(s): S, Path(server): Path<String>, Query(p): Query<OptDbQ>) -> R {
    Ok(Json(q::settings(&s.db, &server, p.non_default).await?))
}
async fn schema(State(s): S, Path(server): Path<String>, Query(p): Query<OptDbQ>) -> R {
    let datname = p
        .datname
        .ok_or_else(|| anyhow::anyhow!("datname is required"))?;
    Ok(Json(
        q::schema(&s.db, &server, &datname, p.relname.as_deref()).await?,
    ))
}
async fn logs(State(s): S, Path(server): Path<String>, Query(p): Query<OptDbQ>) -> R {
    let (f, t) = p.range.resolve()?;
    Ok(Json(
        q::log_errors(&s.db, &server, f, t, p.limit.clamp(1, 1000)).await?,
    ))
}
async fn system(State(s): S, Path(server): Path<String>, Query(r): Query<Range>) -> R {
    let (f, t) = r.resolve()?;
    Ok(Json(q::system(&s.db, &server, f, t).await?))
}
async fn collector_health(State(s): S) -> R {
    Ok(Json(q::collector_health(&s.db).await?))
}

#[derive(Deserialize)]
struct SqlQ {
    sql: String,
    #[serde(default = "d_sql_limit")]
    limit: i64,
}
fn d_sql_limit() -> i64 {
    200
}
async fn sql(State(s): S, Extension(p): Extension<Principal>, Query(qs): Query<SqlQ>) -> R {
    tracing::info!(email = p.email, sql = qs.sql, "raw sql");
    Ok(Json(q::raw_sql(&s.db, &qs.sql, qs.limit).await?))
}
async fn stats_schema(State(s): S) -> R {
    Ok(Json(q::schema_of_stats_db(&s.db).await?))
}

pub async fn readyz(State(s): S) -> Response {
    if s.db.ping().await {
        (StatusCode::OK, "ready").into_response()
    } else {
        (StatusCode::SERVICE_UNAVAILABLE, "stats db unreachable").into_response()
    }
}
pub async fn metrics() -> Response {
    use prometheus::Encoder;
    let mut buf = Vec::new();
    prometheus::TextEncoder::new()
        .encode(&prometheus::gather(), &mut buf)
        .ok();
    ([("content-type", "text/plain; version=0.0.4")], buf).into_response()
}
