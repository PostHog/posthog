use axum::{
    extract::{Path, State},
    http::HeaderMap,
    response::sse::{Event, Sse},
    Extension,
};
use futures_util::stream::Stream;
use std::convert::Infallible;
use std::time::Duration;
use uuid::Uuid;

use crate::app::AppState;
use crate::error::Result;
use crate::types::AuthContext;

const MAX_REPLAY_EVENTS: u32 = 1000;

pub async fn get_sync(
    State(state): State<AppState>,
    Path((project_id, task_id, run_id)): Path<(i64, Uuid, Uuid)>,
    headers: HeaderMap,
    Extension(auth): Extension<AuthContext>,
) -> Result<Sse<impl Stream<Item = std::result::Result<Event, Infallible>>>> {
    state
        .auth
        .authorize_run(auth.user_id, project_id, &task_id, &run_id)
        .await?;

    let last_event_id: Option<u64> = headers
        .get("Last-Event-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse().ok());

    tracing::debug!(
        project_id = project_id,
        task_id = %task_id,
        run_id = %run_id,
        user_id = auth.user_id,
        last_event_id = ?last_event_id,
        "Starting SSE stream"
    );

    let run_id_str = run_id.to_string();
    let log_store = state.log_store.clone();
    let router = state.router.clone();
    let keepalive_secs = state.sse_keepalive_secs;

    let stream = async_stream::stream! {
        if let Ok(events) = log_store.get_logs(&run_id, last_event_id, Some(MAX_REPLAY_EVENTS)).await {
            for event in events {
                let data = serde_json::to_string(&event.entry).unwrap_or_default();
                yield Ok(Event::default()
                    .id(event.sequence.to_string())
                    .data(data));
            }
        }

        let mut rx = router.subscribe(&run_id_str);

        loop {
            tokio::select! {
                result = rx.recv() => {
                    match result {
                        Some(event) => {
                            let data = serde_json::to_string(&event.entry).unwrap_or_default();
                            yield Ok(Event::default()
                                .id(event.sequence.to_string())
                                .data(data));
                        }
                        None => break,
                    }
                }
                _ = tokio::time::sleep(Duration::from_secs(keepalive_secs)) => {
                    yield Ok(Event::default().comment("keepalive"));
                }
            }
        }

        router.cleanup_closed(&run_id_str);
    };

    Ok(Sse::new(stream).keep_alive(
        axum::response::sse::KeepAlive::new()
            .interval(Duration::from_secs(keepalive_secs))
            .text("keepalive"),
    ))
}
