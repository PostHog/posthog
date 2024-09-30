use std::sync::Arc;

use crate::{
    app_context::{AppContext, JanitorStatus},
    janitor::run_once,
};
use axum::{
    debug_handler,
    extract::{Query, State},
    http::StatusCode,
    response::{Html, IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use chrono::{DateTime, Duration, Utc};
use common_metrics::setup_metrics_routes;
use cyclotron_core::{Job, JobQuery, JobState};
use eyre::Result;
use serde::{Deserialize, Serialize};
use tracing::info;
use uuid::Uuid;

pub async fn listen(app: Router, bind: String) -> Result<()> {
    let listener = tokio::net::TcpListener::bind(bind).await?;

    axum::serve(listener, app).await?;

    Ok(())
}

#[debug_handler]
async fn index(State(context): State<Arc<AppContext>>) -> Html<String> {
    Html(
        include_str!("static/index.html")
            .replace("$SHARD_ID", &context.shard_id)
            .replace("$JANITOR_ID", &context.janitor_id),
    )
}

async fn liveness(State(context): State<Arc<AppContext>>) -> Response {
    context.health.get_status().into_response()
}

#[debug_handler]
async fn get_jobs(
    State(context): State<Arc<AppContext>>,
    Json(query): Json<JobQuery>,
) -> Result<Json<Vec<JobResponse>>, (StatusCode, String)> {
    info!("querying jobs: {:?}", query);
    let res = context.janitor.query_jobs(query).await;
    info!("query result: {:?}", res);

    match res {
        Ok(jobs) => Ok(Json(jobs.into_iter().map(JobResponse::new).collect())),
        Err(e) => Err((StatusCode::INTERNAL_SERVER_ERROR, e.to_string())),
    }
}

#[derive(Deserialize)]
struct PauseQuery {
    until: DateTime<Utc>,
}

#[debug_handler]
async fn pause(State(context): State<Arc<AppContext>>, Query(q): Query<PauseQuery>) {
    info!("pausing janitor until: {}", q.until);
    let mut control = context.state.get_control().await;
    control.paused_until = Some(q.until);
    context.state.set_control(control).await;
}

#[debug_handler]
async fn resume(State(context): State<Arc<AppContext>>) {
    info!("resuming janitor");
    let mut control = context.state.get_control().await;
    control.paused_until = None;
    context.state.set_control(control).await;
}

#[derive(Deserialize)]
pub struct SecondsQuery {
    seconds: u64,
}

#[debug_handler]
async fn set_cleanup_interval(
    State(context): State<Arc<AppContext>>,
    Query(q): Query<SecondsQuery>,
) {
    info!("setting cleanup interval to: {} seconds", q.seconds);
    let mut control = context.state.get_control().await;
    control.cleanup_interval = Duration::seconds(q.seconds as i64);
    context.state.set_control(control).await;
}

#[debug_handler]
async fn set_stall_timeout(State(context): State<Arc<AppContext>>, Query(q): Query<SecondsQuery>) {
    info!("setting stall timeout to: {} seconds", q.seconds);
    let mut control = context.state.get_control().await;
    control.stall_timeout = Duration::seconds(q.seconds as i64);
    context.state.set_control(control).await;
}

#[derive(Deserialize)]
pub struct MaxTouchesQuery {
    touches: i16,
}

#[debug_handler]
async fn set_max_touches(State(context): State<Arc<AppContext>>, Query(q): Query<MaxTouchesQuery>) {
    info!("setting max touches to: {}", q.touches);
    let mut control = context.state.get_control().await;
    control.max_touches = q.touches;
    context.state.set_control(control).await;
}

#[debug_handler]
async fn force_cleanup(State(context): State<Arc<AppContext>>) -> Json<JanitorStatus> {
    info!("forcing cleanup");
    Json(run_once(&context).await)
}

#[derive(Serialize)]
struct StateResponse {
    state: JanitorStatus,
    paused_until: Option<DateTime<Utc>>,
    cleanup_interval_seconds: i64,
    stall_timeout_seconds: i64,
    max_touches: i16,
}

#[derive(Serialize)]
struct JobResponse {
    pub id: Uuid,
    pub team_id: i32,
    pub function_id: Option<Uuid>,
    pub created: DateTime<Utc>,
    pub lock_id: Option<Uuid>,
    pub last_heartbeat: Option<DateTime<Utc>>,
    pub janitor_touch_count: i16,
    pub transition_count: i16,
    pub last_transition: DateTime<Utc>,
    pub queue_name: String,
    pub state: JobState,
    pub priority: i16,
    pub scheduled: DateTime<Utc>,
    pub vm_state: Option<String>,
    pub metadata: Option<String>,
    pub parameters: Option<String>,
    pub blob: Option<String>,
}

impl JobResponse {
    pub fn new(job: Job) -> Self {
        Self {
            id: job.id,
            team_id: job.team_id,
            function_id: job.function_id,
            created: job.created,
            lock_id: job.lock_id,
            last_heartbeat: job.last_heartbeat,
            janitor_touch_count: job.janitor_touch_count,
            transition_count: job.transition_count,
            last_transition: job.last_transition,
            queue_name: job.queue_name,
            state: job.state,
            priority: job.priority,
            scheduled: job.scheduled,
            vm_state: job.vm_state.map(unwrap_or_unparseable),
            metadata: job.metadata.map(unwrap_or_unparseable),
            parameters: job.parameters.map(unwrap_or_unparseable),
            blob: job.blob.map(unwrap_or_unparseable),
        }
    }
}

fn unwrap_or_unparseable(b: Vec<u8>) -> String {
    String::from_utf8(b).unwrap_or("unparseable".to_string())
}

#[debug_handler]
async fn get_state(State(context): State<Arc<AppContext>>) -> Json<StateResponse> {
    let status = context.state.get_status().await;
    let control_flags = context.state.get_control().await;

    let response = StateResponse {
        state: status,
        paused_until: control_flags.paused_until,
        cleanup_interval_seconds: control_flags.cleanup_interval.num_seconds(),
        stall_timeout_seconds: control_flags.stall_timeout.num_seconds(),
        max_touches: control_flags.max_touches,
    };

    Json(response)
}
pub fn app(context: Arc<AppContext>) -> Router {
    let metrics_enabled = context.metrics;
    let router = Router::new();

    let router = router
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(liveness));

    let router = router
        .route("/jobs", post(get_jobs))
        .route("/pause", post(pause))
        .route("/resume", post(resume))
        .route("/cleanup_interval", post(set_cleanup_interval))
        .route("/stall_timeout", post(set_stall_timeout))
        .route("/max_touches", post(set_max_touches))
        .route("/force_cleanup", post(force_cleanup))
        .route("/state", get(get_state));

    // setup_metrics_routes touches global objects, so we need to be able to selectively
    // disable it e.g. for tests
    let router = if metrics_enabled {
        setup_metrics_routes(router)
    } else {
        router
    };

    router.with_state(context)
}
