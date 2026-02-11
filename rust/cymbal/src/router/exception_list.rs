use std::sync::Arc;

use axum::{
    extract::{Json, Path, State},
    response::IntoResponse,
};
use futures::future::try_join_all;
use reqwest::StatusCode;
use serde_json::{json, Value};
use thiserror::Error;
use uuid::Uuid;

use crate::{
    app_context::AppContext,
    error::{ResolveError, UnhandledError},
    frames::{Frame, RawFrame},
    langs::java::RawJavaFrame,
    metric_consts::{FRAME_RESOLUTION, JAVA_EXCEPTION_REMAP_FAILED},
    symbol_store::Catalog,
    types::{Exception, ExceptionList, Stacktrace},
};

#[derive(Debug, Error)]
pub enum ProcessExceptionListError {
    #[error("Failed to parse exception list: {0}")]
    InvalidExceptionList(#[from] serde_json::Error),
    #[error("Failed to resolve exception: {0}")]
    ResolveExceptionError(#[from] ResolveExceptionError),
    #[error("Failed to resolve stack trace: {0}")]
    ResolveStackError(#[from] Arc<UnhandledError>),
}

impl IntoResponse for ExceptionList {
    fn into_response(self) -> axum::response::Response {
        (StatusCode::OK, Json(self)).into_response()
    }
}

impl ProcessExceptionListError {
    fn to_status_code(&self) -> StatusCode {
        match self {
            ProcessExceptionListError::InvalidExceptionList(_) => StatusCode::BAD_REQUEST,
            ProcessExceptionListError::ResolveExceptionError(_) => {
                StatusCode::INTERNAL_SERVER_ERROR
            }
            ProcessExceptionListError::ResolveStackError(_) => StatusCode::INTERNAL_SERVER_ERROR,
        }
    }

    fn to_json(&self) -> Json<Value> {
        match self {
            ProcessExceptionListError::InvalidExceptionList(err) => {
                Json(json!({ "error": err.to_string() }))
            }
            ProcessExceptionListError::ResolveExceptionError(err) => {
                Json(json!({ "error": err.to_string() }))
            }
            ProcessExceptionListError::ResolveStackError(err) => {
                Json(json!({ "error": err.to_string() }))
            }
        }
    }
}

impl IntoResponse for ProcessExceptionListError {
    fn into_response(self) -> axum::response::Response {
        (self.to_status_code(), self.to_json()).into_response()
    }
}

pub async fn process_exception_list(
    Path(team_id): Path<i32>,
    State(ctx): State<Arc<AppContext>>,
    Json(value): Json<Value>,
) -> Result<ExceptionList, ProcessExceptionListError> {
    let mut exception_list: ExceptionList = serde_json::from_value(value)?;
    let handles = exception_list
        .iter_mut()
        .map(|exception| process_exception(team_id, ctx.clone(), exception));
    futures::future::try_join_all(handles).await?;
    Ok(exception_list)
}

async fn process_exception(
    team_id: i32,
    ctx: Arc<AppContext>,
    exception: &mut Exception,
) -> Result<(), ProcessExceptionListError> {
    exception.exception_id = Some(Uuid::now_v7().to_string());
    resolve_exception(team_id, ctx.clone(), exception).await?;
    process_stack(team_id, ctx.clone(), &mut exception.stack).await?;
    Ok(())
}

async fn process_stack(
    team_id: i32,
    ctx: Arc<AppContext>,
    stack: &mut Option<Stacktrace>,
) -> Result<(), Arc<UnhandledError>> {
    match stack.take() {
        Some(Stacktrace::Raw { frames }) => {
            let handles = frames
                .into_iter()
                .map(|frame| resolve_frame(team_id, ctx.clone(), frame));
            let results = try_join_all(handles).await?;
            *stack = Some(Stacktrace::Resolved {
                frames: results.into_iter().flatten().collect(),
            });
        }
        Some(Stacktrace::Resolved { frames }) => {
            // This stack trace is already resolved, we have no work to do.
            *stack = Some(Stacktrace::Resolved { frames });
        }
        None => {}
    };
    Ok(())
}

async fn resolve_frame(
    team_id: i32,
    ctx: Arc<AppContext>,
    frame: RawFrame,
) -> Result<Vec<Frame>, Arc<UnhandledError>> {
    let frame = frame.clone();
    // Spawn a concurrent task for resolving every frame
    let handle = tokio::spawn(async move {
        ctx.worker_liveness.report_healthy().await;
        metrics::counter!(FRAME_RESOLUTION).increment(1);
        let res = ctx
            .resolver
            .resolve(&frame, team_id, &ctx.posthog_pool, &ctx.catalog)
            .await;
        ctx.worker_liveness.report_healthy().await;
        res
    });
    let res = handle.await.expect("failed to join handles");
    res
}

#[derive(Debug, Error)]
pub enum ResolveExceptionError {
    #[error("Invalid format: {0}")]
    InvalidFormat(String),
    #[error("Class not found: {0}")]
    ClassNotFound(String),
    #[error("Resolve error: {0}")]
    ResolveError(#[from] ResolveError),
}

async fn resolve_exception(
    team_id: i32,
    ctx: Arc<AppContext>,
    exception: &mut Exception,
) -> Result<(), ResolveExceptionError> {
    let first_frame = exception
        .stack
        .as_ref()
        .and_then(|s| s.get_raw_frames().first());

    // Only needed in java where exception type and module are minified
    if let Some(RawFrame::Java(frame)) = first_frame {
        if let Some(module) = &exception.module {
            match remap_exception_type_and_module(
                module,
                &exception.exception_type,
                team_id,
                frame,
                &ctx.catalog,
            )
            .await
            {
                Ok((remapped_module, remapped_type)) => {
                    exception.module = Some(remapped_module);
                    exception.exception_type = remapped_type;
                }
                Err(err) => {
                    metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => err.to_string())
                        .increment(1);
                }
            }
        }
    }
    Ok(())
}

async fn remap_exception_type_and_module(
    module: &str,
    exception_type: &str,
    team_id: i32,
    frame: &RawJavaFrame,
    catalog: &Catalog,
) -> Result<(String, String), ResolveExceptionError> {
    let class = format!("{module}.{exception_type}");
    let remapped = frame.remap_class(team_id, &class, catalog).await?;
    match remapped {
        Some(s) => split_last_dot(&s),
        None => Err(ResolveExceptionError::ClassNotFound(class)),
    }
}

fn split_last_dot(s: &str) -> Result<(String, String), ResolveExceptionError> {
    let mut parts = s.rsplitn(2, '.');
    let last = parts.next().unwrap();
    let before = parts.next().ok_or(ResolveExceptionError::InvalidFormat(
        "Could not split remapped module and type".to_string(),
    ))?;
    Ok((before.to_string(), last.to_string()))
}
