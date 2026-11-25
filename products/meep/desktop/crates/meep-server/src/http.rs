mod files;
mod replication;
use crate::{
    Server,
    accounts::{WebhookFailure, info},
    queries,
};
use axum::{
    Extension, Json, Router,
    body::Bytes,
    extract::{DefaultBodyLimit, Path, Query, Request, State},
    http::{HeaderMap, StatusCode, header},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post, put},
};
use chrono::Utc;
use files::{artifact, artifacts, files, read_file, write_file};
use meep_engine::Error as EngineError;
use meep_topic::TopicId;
use meep_wire::*;
use replication::{ack_deletions, changes, snapshot, stream};
use serde::{Deserialize, Serialize};
use tokio_util::sync::CancellationToken;

const PAGE: usize = 64;
const MAX_BATCH: usize = 64;
#[derive(Clone)]
pub(super) struct App {
    pub(super) s: Server,
    stop: CancellationToken,
}
#[derive(Debug)]
pub(super) struct Failure(StatusCode, &'static str, String);
impl Failure {
    pub(super) fn auth() -> Self {
        Self(
            StatusCode::UNAUTHORIZED,
            "unauthorized",
            "Invalid or missing credential".into(),
        )
    }
    pub(super) fn bad(text: &str) -> Self {
        Self(StatusCode::BAD_REQUEST, "invalid_request", text.into())
    }
    fn connection(error: anyhow::Error, invalid: &str) -> Self {
        match error.downcast::<EngineError>() {
            Ok(error) => error.into(),
            Err(_) => Self::bad(invalid),
        }
    }
    pub(super) fn missing_view() -> Self {
        Self(StatusCode::NOT_FOUND, "unknown_view", "Unknown view".into())
    }
    pub(super) fn internal(cause: impl Into<anyhow::Error>) -> Self {
        Self(
            StatusCode::INTERNAL_SERVER_ERROR,
            "internal",
            format!("{:#}", cause.into()),
        )
    }
}
impl IntoResponse for Failure {
    fn into_response(self) -> Response {
        if self.0 == StatusCode::INTERNAL_SERVER_ERROR {
            return (self.0, axum::Extension(InternalCause(self.2))).into_response();
        }
        (
            self.0,
            Json(ApiError {
                code: self.1.into(),
                message: self.2,
            }),
        )
            .into_response()
    }
}
impl From<EngineError> for Failure {
    fn from(e: EngineError) -> Self {
        match e {
            EngineError::UnknownTopic(_) => {
                Self(StatusCode::NOT_FOUND, "unknown_topic", e.to_string())
            }
            EngineError::UnknownConnection(_) => {
                Self(StatusCode::NOT_FOUND, "unknown_connection", e.to_string())
            }
            EngineError::UnknownRoutine(_) => {
                Self(StatusCode::NOT_FOUND, "unknown_routine", e.to_string())
            }
            EngineError::InvalidRoutineSecret(_) => Self::auth(),
            EngineError::UnavailableObservation(_) => Self(
                StatusCode::CONFLICT,
                "unavailable_observation",
                e.to_string(),
            ),
            EngineError::InvalidBinding(_)
            | EngineError::Topic(_)
            | EngineError::HopLimit(_)
            | EngineError::CommandCollision(_) => Self::bad(&e.to_string()),
            _ => Self::internal(e),
        }
    }
}
type Result<T> = std::result::Result<T, Failure>;

pub(super) fn router(host: std::sync::Arc<crate::owners::Host>) -> Router {
    let implicit = App {
        s: host.implicit.clone(),
        stop: host.stop.clone(),
    };
    let device = Router::new()
        .route("/v1/views", get(crate::view_mcp::list))
        .route("/v1/views/commands", post(crate::view_mcp::command))
        .route("/v1/views/models", get(view_models))
        .route(
            "/v1/views/{id}/files/{name}",
            put(put_view_file).layer(DefaultBodyLimit::max(32 * 1024 * 1024)),
        )
        .route(
            "/v1/views/{id}/sources",
            post(crate::view_mcp::device_source),
        )
        .route("/v1/routine-templates", get(routine_templates))
        .route("/v1/topics/{id}/routines", post(create_template))
        .route("/v1/commands", post(commands))
        .route("/v1/changes", get(changes))
        .route("/v1/topics/{id}", get(snapshot))
        .route("/v1/deletions/ack", post(ack_deletions))
        .route("/v1/stream", get(stream))
        .route("/v1/needs-you", get(needs_you))
        .route("/v1/search", get(search))
        .route(
            "/v1/topics/{id}/files/{*path}",
            get(read_file)
                .put(write_file)
                .layer(DefaultBodyLimit::max(64 * 1024 * 1024)),
        )
        .route("/v1/connections", get(connections))
        .route("/v1/connections/{id}", put(put_connection))
        .route("/v1/settings/public-base-url", put(set_public_address))
        .route(
            "/v1/connections/{id}/credentials",
            axum::routing::delete(sign_out),
        )
        .route("/v1/connections/{id}/topics/{topic}", put(grant_topic))
        .route(
            "/v1/routines/{topic}/{routine}",
            get(workflow).put(toggle_workflow).delete(delete_workflow),
        )
        .route("/v1/connections/posthog/mcp-store", post(mcp_store))
        .route("/v1/sources", get(sources))
        .route("/v1/topics/{id}/files", get(files))
        .route("/v1/topics/{id}/artifacts", get(artifacts))
        .route(
            "/v1/topics/{id}/artifacts/{task}/{run}/{artifact}",
            get(artifact),
        )
        .route(
            "/v1/topics/{id}/models",
            get(chat_models).put(set_chat_model),
        )
        .route(
            "/v1/topics/{id}/tasks/{task}/conversation",
            get(task_conversation),
        )
        .route("/v1/topics/{id}/tasks/{task}/messages", post(task_message))
        .route("/v1/health", get(health))
        .route_layer(middleware::from_fn_with_state(host.clone(), authorize));
    let callbacks = Router::new()
        .route("/v1/views/{id}/mcp", post(crate::view_mcp::mcp))
        .route("/v1/topics/{id}/mcp", post(crate::topic_mcp::mcp))
        .route("/v1/routines/{topic}/{routine}/callback", post(callback))
        .route(
            "/v1/routines/{topic}/{routine}/sort-context",
            post(sort_context),
        )
        .route("/v1/ingest/{connection}", post(ingest));
    device
        .merge(callbacks.clone().layer(Extension(implicit)))
        .nest(
            "/owners/{owner}",
            callbacks.route_layer(middleware::from_fn_with_state(host, callback_owner)),
        )
        .layer(middleware::from_fn(error_body))
}
#[derive(Clone)]
struct InternalCause(String);

async fn error_body(req: Request, next: Next) -> Response {
    let route = req
        .extensions()
        .get::<axum::extract::MatchedPath>()
        .cloned();
    let mut response = next.run(req).await;
    let status = response.status();
    if status == StatusCode::INTERNAL_SERVER_ERROR {
        let route = route.as_ref().map_or("unmatched route", |r| r.as_str());
        let cause = match response.extensions_mut().remove::<InternalCause>() {
            Some(InternalCause(cause)) => cause,
            // Axum supplies plain-text diagnostics for extractor and serialization failures.
            None => match axum::body::to_bytes(response.into_body(), 65536).await {
                Ok(bytes) => String::from_utf8_lossy(&bytes).into_owned(),
                Err(error) => format!("Could not read the error response: {error}"),
            },
        };
        log::error!("HTTP 500 on {route}: {cause}");
        return (
            status,
            Json(ApiError {
                code: "internal".into(),
                message: "Meep couldn’t complete the request. Try again.".into(),
            }),
        )
            .into_response();
    }
    if (status.is_client_error() || status.is_server_error())
        && !response
            .headers()
            .get(header::CONTENT_TYPE)
            .is_some_and(|v| v == "application/json")
    {
        return Failure(
            status,
            "invalid_request",
            status
                .canonical_reason()
                .unwrap_or("Invalid request")
                .into(),
        )
        .into_response();
    }
    response
}
pub(super) fn bearer(headers: &HeaderMap) -> Result<&str> {
    let mut headers = headers.get_all(header::AUTHORIZATION).iter();
    let (scheme, token) = headers
        .next()
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.split_once(' '))
        .ok_or_else(Failure::auth)?;
    if headers.next().is_some() || !scheme.eq_ignore_ascii_case("bearer") || token.is_empty() {
        return Err(Failure::auth());
    }
    Ok(token)
}

type Hosted = std::sync::Arc<crate::owners::Host>;

async fn authorize(State(host): State<Hosted>, req: Request, next: Next) -> Result<Response> {
    let owner = device_owner(
        host.implicit.auth.clone(),
        bearer(req.headers())?.to_owned(),
    )
    .await
    .map_err(Failure::internal)?
    .ok_or_else(Failure::auth)?;
    serve_owner(host, owner, req, next).await
}

async fn device_owner(
    auth: std::sync::Arc<dyn crate::Auth>,
    token: String,
) -> anyhow::Result<Option<uuid::Uuid>> {
    tokio::task::spawn_blocking(move || auth.owner(&token)).await?
}

#[derive(Deserialize)]
struct OwnerPath {
    owner: uuid::Uuid,
}
async fn callback_owner(
    State(host): State<Hosted>,
    Path(path): Path<OwnerPath>,
    req: Request,
    next: Next,
) -> Result<Response> {
    serve_owner(host, path.owner, req, next).await
}

async fn serve_owner(
    host: Hosted,
    owner: uuid::Uuid,
    mut req: Request,
    next: Next,
) -> Result<Response> {
    let s = host
        .service(owner)
        .await
        .map_err(Failure::internal)?
        .ok_or_else(Failure::auth)?;
    req.extensions_mut().insert(App {
        s,
        stop: host.stop.clone(),
    });
    Ok(next.run(req).await)
}

#[derive(Deserialize)]
pub(super) struct ObjectPath<T> {
    pub id: T,
}

fn require_connection(s: &Server, id: &str) -> Result<()> {
    if !s
        .engine
        .connections()?
        .iter()
        .any(|account| account.id == id)
    {
        return Err(EngineError::UnknownConnection(id.to_owned()).into());
    }
    Ok(())
}

async fn grant_topic(
    Extension(a): Extension<App>,
    Path((id, topic)): Path<(String, TopicId)>,
) -> Result<Json<ConnectionInfo>> {
    a.s.engine.read_topic(topic, |_| ())?;
    require_connection(&a.s, &id)?;
    let guard = a.s.engine.connection_guard(&id).await;
    a.s.accounts
        .jobs
        .clone()
        .spawn_blocking(move || {
            let _guard = guard;
            a.s.accounts
                .grant(&id, topic)
                .map(Json)
                .map_err(|e| Failure::connection(e, "Sign in to this connection first."))
        })
        .await
        .map_err(Failure::internal)?
}

async fn routine_templates() -> Json<&'static [RoutineTemplate]> {
    Json(crate::topic_workflows::templates())
}
async fn create_template(
    Extension(a): Extension<App>,
    Path(topic): Path<TopicId>,
    Json(req): Json<CreateTemplateRoutine>,
) -> Result<Json<meep_topic::RoutineInfo>> {
    a.s.engine.read_topic(topic, |_| ())?;
    let response = crate::topic_workflows::create_template(
        &a.s,
        topic,
        req,
        meep_engine::WorkflowReview::Request(uuid::Uuid::new_v4().into()),
    )
    .await
    .map_err(|e| Failure::bad(&e.to_string()))?;
    serde_json::from_value(response["routine"].clone())
        .map(Json)
        .map_err(Failure::internal)
}

async fn workflow(
    Extension(a): Extension<App>,
    Path((topic, id)): Path<(TopicId, String)>,
) -> Result<Json<WorkflowDetails>> {
    workflow_details(a, topic, id, None).await
}
async fn delete_workflow(
    Extension(a): Extension<App>,
    Path((topic, routine)): Path<(TopicId, String)>,
    Json(flow): Json<uuid::Uuid>,
) -> Result<StatusCode> {
    let _guard = a.s.provisioning.lock().await;
    let binding = a.s.engine.read_topic(topic, |s| {
        s.topic
            .routines
            .iter()
            .find(|r| r.binding.id == routine)
            .map(|r| r.binding.clone())
    })?;
    let Some(binding) = binding else {
        return Ok(StatusCode::NO_CONTENT);
    };
    if binding.backend != "posthog" || binding.external_id.parse::<uuid::Uuid>().ok() != Some(flow)
    {
        return Err(Failure::bad(
            "The workflow binding changed. Refresh the routine before deleting it.",
        ));
    }
    let (_, project) =
        a.s.accounts
            .project(topic)
            .map_err(|e| Failure::bad(&e.to_string()))?;
    let shared = a.s.engine.read_topics(|topics| {
        topics.iter().any(|s| {
            !s.deleted
                && s.topic.routines.iter().any(|r| {
                    (s.topic.id != topic || r.binding.id != routine)
                        && r.binding.backend == "posthog"
                        && r.binding.external_id.parse::<uuid::Uuid>().ok() == Some(flow)
                })
        })
    });
    if !shared {
        let api =
            meep_posthog::api::ProjectEndpoint::new(&project.origin, project.project, "hog_flows")
                .map_err(Failure::internal)?;
        api.delete(&project.token, &format!("{flow}/"))
            .await
            .map_err(|e| {
                Failure(
                    StatusCode::BAD_GATEWAY,
                    "workflow_delete_failed",
                    format!("Could not delete the linked PostHog workflow: {e}"),
                )
            })?;
    }
    a.s.engine.remove_workflow(topic, &binding).await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn toggle_workflow(
    Extension(a): Extension<App>,
    Path((topic, id)): Path<(TopicId, String)>,
    Json(setting): Json<WorkflowSwitch>,
) -> Result<Json<WorkflowDetails>> {
    workflow_details(a, topic, id, Some(setting)).await
}
async fn workflow_details(
    a: App,
    topic: TopicId,
    id: String,
    setting: Option<WorkflowSwitch>,
) -> Result<Json<WorkflowDetails>> {
    let binding =
        a.s.engine
            .read_topic(topic, |state| {
                state
                    .topic
                    .routines
                    .iter()
                    .find(|r| r.binding.id == id && r.binding.backend == "posthog")
                    .cloned()
            })?
            .ok_or_else(|| Failure::bad("Expected a bound PostHog workflow"))?;
    if setting
        .as_ref()
        .is_some_and(|s| s.flow_id != binding.binding.external_id)
    {
        return Err(Failure::bad(
            "This routine is now bound to a different workflow.",
        ));
    }
    let flow = binding
        .binding
        .external_id
        .parse()
        .map_err(|_| Failure::bad("Invalid flow ID"))?;
    if !a
        .s
        .accounts
        .all()
        .iter()
        .any(|a| a.project.is_some() && a.public.grants.contains(&topic))
    {
        return Err(Failure::bad("Grant this topic access to PostHog first."));
    }
    let (_, project) = a.s.accounts.project(topic).map_err(|_| {
        Failure(
            StatusCode::SERVICE_UNAVAILABLE,
            "workflow_unavailable",
            "PostHog needs a successful connection check.".into(),
        )
    })?;
    let pause = match setting {
        Some(switch) if switch.enabled => {
            a.s.engine
                .request_routine_activation(
                    topic,
                    &binding.binding,
                    switch
                        .request_id
                        .unwrap_or_else(|| uuid::Uuid::new_v4().into()),
                    None,
                )
                .await?;
            false
        }
        other => other.is_some(),
    };
    let mut details = project.workflow_details(flow, pause).await.map_err(|e| {
        Failure(
            StatusCode::BAD_GATEWAY,
            "workflow_unavailable",
            format!("PostHog could not confirm the workflow state: {e}"),
        )
    })?;
    if binding.event.is_some() && details.enabled != binding.enabled {
        a.s.engine
            .set_event_delivery(topic, &binding.binding, details.enabled)
            .await?;
    }
    details.watches.clone_from(&binding.binding.watches);
    details.observations.clone_from(&binding.observations);
    // A routine bound before the engine kept its private record (or restored from
    // a snapshot) has no answer here; that leaves the choice unknown, not the page broken.
    details.manual_run_allowed = match a.s.engine.manual_run_allowed(topic, &binding.binding) {
        Ok(allowed) => Some(allowed),
        Err(EngineError::UnknownRoutine(_)) => None,
        Err(e) => return Err(e.into()),
    };
    Ok(Json(details))
}

#[derive(Default, Deserialize)]
struct ListQuery {
    topic: Option<TopicId>,
    limit: Option<usize>,
    #[serde(default)]
    offset: usize,
    /// Return sources from one discovery and ranking pass.
    #[serde(default)]
    complete: bool,
}

impl ListQuery {
    fn page<T, B: Serialize>(&self, items: Vec<T>, body: impl FnOnce(Vec<T>) -> B) -> Response {
        let limit = self.limit.unwrap_or(200).clamp(1, 200);
        let end = self.offset.saturating_add(limit);
        let more = end < items.len();
        let mut response = Json(body(
            items.into_iter().skip(self.offset).take(limit).collect(),
        ))
        .into_response();
        if more {
            response
                .headers_mut()
                .insert("x-meep-next-offset", end.into());
        }
        response
    }
}

impl ListQuery {
    fn sources(self, items: Vec<WatchableSource>) -> Response {
        if self.complete {
            Json(items).into_response()
        } else {
            self.page(items, |items| items)
        }
    }
}

async fn sources(Extension(a): Extension<App>, Query(q): Query<ListQuery>) -> Result<Response> {
    let state = q
        .topic
        .map(|id| a.s.engine.read_topic(id, |s| s.topic.clone()))
        .transpose()?;
    let items = crate::sources::discover(&a.s.accounts, state.as_ref())
        .await
        .map_err(|e| {
            Failure(
                StatusCode::BAD_GATEWAY,
                "source_discovery",
                format!("Could not discover or rank PostHog sources: {e}"),
            )
        })?;
    Ok(q.sources(items))
}

async fn commands(
    Extension(a): Extension<App>,
    Json(batch): Json<CommandBatch>,
) -> Result<Json<CommandResults>> {
    if batch.commands.len() > MAX_BATCH {
        return Err(Failure::bad("A batch accepts at most 64 commands"));
    }
    let mut results = Vec::with_capacity(batch.commands.len());
    for e in batch.commands {
        let (id, topic) = (e.id, e.topic);
        // Manual binding and hosted provisioning share the deletion check for other users of a flow.
        let _binding_guard = if matches!(e.command, meep_topic::Command::SetRoutine { .. }) {
            Some(a.s.provisioning.lock().await)
        } else {
            None
        };
        match a.s.engine.apply(e).await {
            Ok(applied) => results.push(CommandResult::Applied {
                id,
                topic,
                revision: applied.revision,
            }),
            Err(
                e @ (EngineError::InvalidBinding(_)
                | EngineError::Topic(_)
                | EngineError::UnknownTopic(_)
                | EngineError::UnknownConnection(_)
                | EngineError::UnknownRoutine(_)
                | EngineError::HopLimit(_)
                | EngineError::CommandCollision(_)),
            ) => results.push(CommandResult::Rejected {
                id,
                reason: e.to_string(),
            }),
            Err(error) => {
                log::warn!("Command {id} for {topic} will retry: {error}");
                results.push(CommandResult::Retry {
                    id,
                    reason: "The server could not complete this command. Retrying.".into(),
                });
            }
        }
    }
    Ok(Json(CommandResults { results }))
}

async fn needs_you(Extension(a): Extension<App>, Query(q): Query<ListQuery>) -> Result<Response> {
    let items = queries::needs_you(&a.s).map_err(Failure::internal)?.items;
    Ok(q.page(items, |items| NeedsYou { items }))
}
#[derive(Deserialize, Serialize)]
struct Search {
    q: String,
    limit: Option<usize>,
}
async fn search(
    Extension(a): Extension<App>,
    Query(q): Query<Search>,
) -> Result<Json<SearchResults>> {
    Ok(Json(
        queries::search(&a.s, &q.q, q.limit.unwrap_or(50).min(200)).map_err(Failure::internal)?,
    ))
}

async fn mcp_store(
    Extension(a): Extension<App>,
    Json(request): Json<mcp_store::Operation>,
) -> Result<Json<mcp_store::Outcome>> {
    let account =
        a.s.accounts
            .get("posthog")
            .ok_or_else(|| Failure::from(EngineError::UnknownConnection("posthog".into())))?;
    let project = account
        .project
        .as_ref()
        .ok_or_else(|| Failure::bad("PostHog project unavailable"))?;
    project.mcp_store(request).await.map(Json).map_err(|error| {
        let detail = if let Some(e) = error.downcast_ref::<meep_posthog::api::ApiError>() {
            if e.status == 403 { "PostHog denied access. Check project permissions and sign in again to grant project write access.".into() } else if !e.detail.is_empty() { e.detail.clone() } else {format!("PostHog returned HTTP {}", e.status)}
        } else { "Could not confirm the MCP store request. Refresh before retrying.".into() };
        Failure(StatusCode::BAD_GATEWAY,"mcp_store",detail)
    })
}

async fn connections(Extension(a): Extension<App>, Query(q): Query<ListQuery>) -> Result<Response> {
    Ok(q.page(
        a.s.engine.connections()?.iter().map(info).collect(),
        |connections| Connections { connections },
    ))
}
#[derive(Default, Deserialize)]
struct Registration {
    #[serde(default)]
    preserve_grants: bool,
}
async fn put_connection(
    Extension(a): Extension<App>,
    Path(id): Path<String>,
    Query(options): Query<Registration>,
    Json(mut grant): Json<ConnectionGrant>,
) -> Result<Json<ConnectionInfo>> {
    for topic in &grant.grants {
        a.s.engine.snapshot(*topic)?;
    }
    for name in ["webhook_secret", "secret"] {
        if let Some(secret) = grant.secrets.get(name)
            && a.s.auth.accepts(secret).map_err(Failure::internal)?
        {
            return Err(Failure::bad("Use a separate webhook credential"));
        }
    }
    let guard = a.s.engine.connection_guard(&id).await;
    if options.preserve_grants
        && let Some(existing) = a.s.accounts.get(&id)
    {
        if grant.kind != existing.public.kind
            || ["region", "project_id"]
                .iter()
                .any(|key| grant.secrets.get(*key) != existing.values.get(*key))
        {
            return Err(Failure::bad(
                "This server connection belongs to another project.",
            ));
        }
        let mut previous_user = existing.values.get("user_uuid").cloned();
        if previous_user.is_none()
            && grant.secrets.contains_key("user_uuid")
            && !existing.public.grants.is_empty()
            && let Some(project) = &existing.project
        {
            previous_user = Some(project.user_uuid().await.map_err(|_| Failure::bad(
                "Could not verify the previous PostHog account. Sign out before reconnecting."
            ))?.to_string());
        }
        if previous_user.is_some() && previous_user.as_ref() != grant.secrets.get("user_uuid") {
            return Err(Failure::bad(
                "This server connection belongs to another account. Sign out before reconnecting.",
            ));
        }
    }
    a.s.accounts.jobs.clone().spawn_blocking(move || {
        let _guard = guard;
        if options.preserve_grants {
            if let Some(existing) = a.s.accounts.get(&id) {
                grant.grants = existing.public.grants.clone();
            } else if grant.kind == "posthog" {
                grant.grants = a.s.accounts.signed_out_grants(&id, &grant).map_err(Failure::internal)?;
            }
        }
        a.s.accounts.put(&a.s.engine, &id, grant).map(Json).map_err(|e| Failure::connection(e, "Could not register the connection. Check its kind, configuration and required secrets."))
    }).await.map_err(Failure::internal)?
}
/// PostHog's catalogue is the account's; a failure to reach it is the gateway's.
fn model_failure(e: anyhow::Error) -> Failure {
    if e.is::<crate::chat_models::MissingTopicGrant>() {
        return Failure(StatusCode::CONFLICT, "missing_topic_grant", e.to_string());
    }
    if e.is::<crate::chat_models::InvalidChoice>() {
        return Failure::bad(&e.to_string());
    }
    match e.downcast::<EngineError>() {
        Ok(e) => e.into(),
        Err(e) => Failure(StatusCode::BAD_GATEWAY, "chat_models", format!("{e:#}")),
    }
}
async fn task_conversation(
    Extension(a): Extension<App>,
    Path((topic, task)): Path<(TopicId, meep_topic::TaskId)>,
) -> Result<Json<TaskConversation>> {
    Ok(Json(a.s.engine.task_conversation(topic, task)?))
}
async fn task_message(
    Extension(a): Extension<App>,
    Path((topic, task)): Path<(TopicId, meep_topic::TaskId)>,
    Json(body): Json<TaskMessage>,
) -> Result<Json<()>> {
    if body.text.trim().is_empty() {
        return Err(Failure::bad("Enter a message"));
    }
    a.s.engine
        .send_task_message_on_model(topic, task, &body.text, body.model.as_deref())
        .await?;
    Ok(Json(()))
}
async fn chat_models(
    Extension(a): Extension<App>,
    Path(topic): Path<TopicId>,
) -> Result<Json<ChatModels>> {
    a.s.engine.read_topic(topic, |_| ())?;
    a.s.accounts
        .chat_models(topic)
        .await
        .map(Json)
        .map_err(model_failure)
}
/// Models a view can be built with: Claude models that use Meep's view tools.
async fn view_models(Extension(a): Extension<App>) -> Result<Json<ChatModels>> {
    a.s.accounts
        .view_models()
        .await
        .map(Json)
        .map_err(model_failure)
}
/// Stage a file the person attached to a view request, before the request is sent.
async fn put_view_file(
    Extension(a): Extension<App>,
    Path((id, name)): Path<(uuid::Uuid, String)>,
    body: Bytes,
) -> Result<StatusCode> {
    if name.is_empty() || name.len() > 255 || name.contains(['/', '\\']) {
        return Err(Failure::bad("Attach a file with a plain name."));
    }
    a.s.engine
        .blobs()
        .put(
            crate::views::upload_scope(id),
            &crate::views::upload_name(&name),
            &body,
        )
        .map_err(Failure::internal)?;
    Ok(StatusCode::NO_CONTENT)
}
async fn set_chat_model(
    Extension(a): Extension<App>,
    Path(topic): Path<TopicId>,
    Json(body): Json<ChatModelChoice>,
) -> Result<Json<ChatModels>> {
    a.s.engine.read_topic(topic, |_| ())?;
    a.s.accounts
        .set_chat_model(topic, body)
        .await
        .map(Json)
        .map_err(model_failure)
}
async fn set_public_address(
    Extension(a): Extension<App>,
    Json(request): Json<PublicAddress>,
) -> Result<Json<PublicAddress>> {
    let base = crate::address::validate(&request.public_base_url)
        .map_err(|_| Failure::bad("Expected a public HTTPS base URL"))?;
    let result = PublicAddress {
        public_base_url: base.clone(),
    };
    let server = a.s.clone();
    a.s.accounts
        .jobs
        .clone()
        .spawn_blocking(move || a.s.set_address(base))
        .await
        .map_err(Failure::internal)?
        .map_err(Failure::internal)?;
    // Routines call back on the address they were created with; move them over.
    server.accounts.jobs.clone().spawn(async move {
        match crate::topic_workflows::retarget_callbacks(&server).await {
            Ok(0) => {}
            Ok(n) => log::info!("Pointed {n} workflows at the new public address"),
            Err(e) => log::warn!("Could not move workflows to the new public address: {e:#}"),
        }
    });
    Ok(Json(result))
}

async fn sign_out(
    Extension(a): Extension<App>,
    Path(id): Path<String>,
) -> Result<Json<ConnectionInfo>> {
    require_connection(&a.s, &id)?;
    let _guard = a.s.engine.connection_guard(&id).await;
    // Older registrations stored only project identity. Resolve the old token's user
    // before revoking it. An offline sign-out still revokes it and requires a new grant.
    let legacy_user = if let Some(account) = a.s.accounts.get(&id)
        && !account.public.grants.is_empty()
        && !account.values.contains_key("user_uuid")
        && let Some(project) = &account.project
    {
        project.user_uuid().await.ok()
    } else {
        None
    };
    a.s.accounts
        .jobs
        .clone()
        .spawn_blocking(move || {
            let _guard = _guard;
            a.s.accounts
                .sign_out(&a.s.engine, &id, legacy_user)
                .map(Json)
        })
        .await
        .map_err(Failure::internal)?
        .map_err(Failure::internal)
}

#[derive(Deserialize)]
struct RoutinePath {
    topic: TopicId,
    routine: String,
}
#[derive(Deserialize)]
struct SortContextRequest {
    secret: String,
    observation: uuid::Uuid,
}

async fn sort_context(
    Extension(a): Extension<App>,
    Path(RoutinePath { topic, routine }): Path<RoutinePath>,
    Json(req): Json<SortContextRequest>,
) -> Result<Json<serde_json::Value>> {
    let context =
        a.s.engine
            .routine_sort_input(topic, &routine, &req.secret, req.observation)?;
    Ok(Json(
        serde_json::to_value(context).map_err(Failure::internal)?,
    ))
}

async fn callback(
    Extension(a): Extension<App>,
    Path(RoutinePath { topic, routine }): Path<RoutinePath>,
    headers: HeaderMap,
    Json(cb): Json<RoutineCallback>,
) -> Result<Json<CallbackResult>> {
    let op =
        serde_json::from_value(cb.op).map_err(|_| Failure::bad("Invalid routine operation"))?;
    let key = headers
        .get("idempotency-key")
        .and_then(|h| h.to_str().ok())
        .and_then(|h| h.parse().ok())
        .ok_or_else(|| Failure::bad("A UUID Idempotency-Key is required for callbacks"))?;
    a.s.engine
        .event_callback_once(
            topic,
            &routine,
            &cb.secret,
            key,
            op,
            event_observation(&headers)?,
        )
        .await?;
    Ok(Json(CallbackResult {
        revision: a.s.engine.revision(topic)?,
    }))
}
/// A manually started event workflow has no observation and may send an empty
/// interpolated header. Non-empty values must still identify an observation.
fn event_observation(headers: &HeaderMap) -> Result<Option<uuid::Uuid>> {
    let Some(header) = headers.get("x-meep-event-observation") else {
        return Ok(None);
    };
    let value = header
        .to_str()
        .map_err(|_| Failure::bad("The event observation ID must be a UUID."))?
        .trim();
    if value.is_empty() {
        return Ok(None);
    }
    value
        .parse()
        .map(Some)
        .map_err(|_| Failure::bad("The event observation ID must be a UUID."))
}
#[derive(Deserialize)]
struct ConnectionPath {
    connection: String,
}
async fn ingest(
    Extension(a): Extension<App>,
    Path(ConnectionPath { connection: id }): Path<ConnectionPath>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<StatusCode> {
    let account = a.s.accounts.get(&id).ok_or_else(Failure::auth)?;
    let events = account.receive(&headers, &body).map_err(|e| match e {
        WebhookFailure::Unauthorized => Failure::auth(),
        WebhookFailure::Payload => Failure::bad("Invalid webhook payload"),
    })?;
    if events.len() > MAX_BATCH {
        return Err(Failure(
            StatusCode::PAYLOAD_TOO_LARGE,
            "batch_too_large",
            "A webhook accepts at most 64 events per delivery".into(),
        ));
    }
    if events.iter().any(|e| e.connection != id) {
        return Err(Failure::bad("Webhook account mismatch"));
    }
    let _guard = a.s.engine.connection_guard(&id).await;
    if !a
        .s
        .accounts
        .get(&id)
        .is_some_and(|current| current.version == account.version)
    {
        return Err(Failure::auth());
    }
    let mut received = vec![];
    for event in events {
        if a.s.engine.ingest_routed(event.clone()).await?.1 {
            received.push(event);
        } else {
            a.s.accounts
                .record_unrouted(&id)
                .map_err(Failure::internal)?;
        }
    }
    // Record receipts only after every event is durable, so a failed delivery stays retryable.
    account.acknowledge(&received).map_err(Failure::internal)?;
    Ok(StatusCode::NO_CONTENT)
}
async fn health(Extension(a): Extension<App>) -> Result<Json<ServerHealth>> {
    let cursor = a.s.accounts.store.cursor().map_err(Failure::internal)?;
    let posthog = a.s.accounts.all().iter().any(|a| {
        a.project.is_some() && matches!(a.public.health, meep_connections::Health::Ok { .. })
    });
    Ok(Json(ServerHealth {
        owner_id: a.s.owner,
        implicit_owner: a.s.owner == a.s.auth.implicit_owner(),
        version: env!("CARGO_PKG_VERSION").into(),
        cursor,
        posthog,
        create_topic_without_sort: true,
        context_sources: true,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manual_event_callbacks_accept_empty_observation_but_not_invalid_values() {
        let mut headers = HeaderMap::new();
        assert!(event_observation(&headers).unwrap().is_none());
        headers.insert("x-meep-event-observation", "".parse().unwrap());
        assert!(event_observation(&headers).unwrap().is_none());
        headers.insert("x-meep-event-observation", "not-a-uuid".parse().unwrap());
        assert!(matches!(
            event_observation(&headers),
            Err(Failure(StatusCode::BAD_REQUEST, ..))
        ));
        let id = uuid::Uuid::new_v4();
        headers.insert("x-meep-event-observation", id.to_string().parse().unwrap());
        assert_eq!(event_observation(&headers).unwrap(), Some(id));
    }

    #[tokio::test]
    async fn a_complete_discovery_returns_the_same_ranking_across_the_page_boundary()
    -> anyhow::Result<()> {
        let sources: Vec<_> = (0..205)
            .map(|n| WatchableSource {
                connection: "account".into(),
                kind: "flag".into(),
                key: n.to_string(),
                label: n.to_string(),
                supported_modes: vec![],
            })
            .collect();
        for (complete, count) in [(true, 205), (false, 200)] {
            let r = ListQuery {
                complete,
                ..ListQuery::default()
            }
            .sources(sources.clone());
            assert_eq!(r.headers().contains_key("x-meep-next-offset"), !complete);
            let body = axum::body::to_bytes(r.into_body(), 100_000).await?;
            assert_eq!(
                serde_json::from_slice::<Vec<WatchableSource>>(&body)?,
                sources[..count]
            );
        }
        Ok(())
    }
}
