use axum::{
    extract::{Host, Path, State},
    http::StatusCode,
    response::IntoResponse,
};

use crate::{
    redirect::redirect_service::{
        ExternalRedirectService, InternalRedirectService, RedirectServiceTrait,
    },
    router::AppState,
};

pub async fn internal_redirect_url(
    state: State<AppState>,
    Host(hostname): Host,
    Path(origin_key): Path<String>,
) -> impl IntoResponse {
    let redirect_service = InternalRedirectService::new(
        state.db_reader_client.clone(),
        state.internal_redis_client.clone(),
    );
    match redirect_service.redirect_url(&origin_key, &hostname).await {
        Ok(redirect_url) => {
            let redirect_url = format!("https://{redirect_url}");
            (
                StatusCode::FOUND,
                [(axum::http::header::LOCATION, redirect_url)],
            )
                .into_response()
        }
        Err(error) => {
            tracing::error!("Error: {error}");
            (StatusCode::NOT_FOUND, "Link not found").into_response()
        }
    }
}

pub async fn external_redirect_url(
    state: State<AppState>,
    Host(hostname): Host,
    Path(origin_key): Path<String>,
) -> impl IntoResponse {
    let redirect_service = ExternalRedirectService::new(state.external_redis_client.clone());
    match redirect_service.redirect_url(&origin_key, &hostname).await {
        Ok(redirect_url) => {
            let redirect_url = format!("https://{redirect_url}");
            (
                StatusCode::FOUND,
                [(axum::http::header::LOCATION, redirect_url)],
            )
                .into_response()
        }
        Err(error) => {
            tracing::error!("Error: {error}");
            (StatusCode::NOT_FOUND, "Link not found").into_response()
        }
    }
}
