use axum::{
    extract::{Host, Path, State},
    http::StatusCode,
    response::IntoResponse,
    Json,
};

use crate::{
    redirect::redirect_service::{
        ExternalRedirectService, InternalRedirectService, RedirectError, RedirectServiceTrait,
    },
    router::AppState,
    utils::generator::generate_base62_string,
};

pub async fn internal_redirect_url(
    state: State<AppState>,
    Host(hostname): Host,
    Path(short_code): Path<String>,
) -> impl IntoResponse {
    let redirect_service = InternalRedirectService::new(
        state.db_reader_client.clone(),
        state.internal_redis_client.clone(),
    );
    match redirect_service.redirect_url(&short_code, &hostname).await {
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
    Path(short_code): Path<String>,
    Host(host): Host,
) -> impl IntoResponse {
    // Convert the host to lowercase and remove the "www." prefix
    let lowcase_host = host.to_lowercase();
    let host = lowcase_host.strip_prefix("www.").unwrap_or(&lowcase_host);

    let redirect_service = ExternalRedirectService::new(
        state.external_redis_client.clone(),
        state.default_domain_for_public_store.clone(),
    );

    match redirect_service.redirect_url(&short_code, host).await {
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
            match error {
                RedirectError::LinkNotFound => (StatusCode::NOT_FOUND).into_response(),
                _ => {
                    tracing::error!("Unexpected error: {error}");
                    (StatusCode::INTERNAL_SERVER_ERROR).into_response()
                }
            }
        }
    }
}

#[derive(serde::Deserialize)]
pub struct ExternalStoreUrlRequest {
    redirect_url: String,
}

#[derive(serde::Serialize)]
struct ExternalStoreUrlResponse {
    #[serde(rename = "shortUrl")]
    short_url: String,
    #[serde(rename = "longUrl")]
    long_url: String,
    #[serde(rename = "createdAt")]
    created_at: i64,
}

pub async fn external_store_url(
    state: State<AppState>,
    Json(payload): Json<ExternalStoreUrlRequest>,
) -> impl IntoResponse {
    let short_string = generate_base62_string();
    let redirect_service = ExternalRedirectService::new(
        state.external_redis_client.clone(),
        state.default_domain_for_public_store.clone(),
    );

    match redirect_service
        .store_url(&payload.redirect_url, &short_string)
        .await
    {
        Ok(_) => {
            let short_url = format!(
                "https://{}/ph/{}",
                state.default_domain_for_public_store, short_string
            );
            let response = ExternalStoreUrlResponse {
                long_url: payload.redirect_url,
                short_url,
                created_at: chrono::Utc::now().timestamp(),
            };
            (StatusCode::OK, Json(response)).into_response()
        }
        Err(error) => {
            tracing::error!("Error: {error}");
            (StatusCode::INTERNAL_SERVER_ERROR, "Error storing link").into_response()
        }
    }
}
