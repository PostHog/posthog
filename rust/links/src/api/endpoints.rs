use axum::{
    extract::{ConnectInfo, Host, Path, State},
    http::StatusCode,
    response::IntoResponse,
    Json,
};

use crate::{
    redirect::redirect_service::{
        ExternalRedirectService, InternalRedirectService, RedirectError, RedirectServiceTrait,
    },
    state::State as AppState,
    types::ClickHouseEventProperties,
    utils::{
        event::{create_clickhouse_event, publish_event},
        generator::generate_base62_string,
    },
};

#[axum::debug_handler]
pub async fn internal_redirect_url(
    state: State<AppState>,
    Host(hostname): Host,
    Path(short_code): Path<String>,
    ConnectInfo(addr): ConnectInfo<std::net::SocketAddr>,
    headers: axum::http::HeaderMap,
) -> impl IntoResponse {
    // Log request information
    let user_agent = headers
        .get(axum::http::header::USER_AGENT)
        .and_then(|h| h.to_str().ok());

    tracing::info!(
        "Request from IP: {}, User-Agent: {:?}",
        addr.ip(),
        user_agent
    );

    let redirect_service = InternalRedirectService::new(
        state.db_reader_client.clone(),
        state.internal_redis_client.clone(),
    );
    match redirect_service.redirect_url(&short_code, &hostname).await {
        Ok(item) => {
            let url = item.url;
            let location = format!("https://{url}");

            if let Some(team_id) = item.team_id {
                let event = create_clickhouse_event(
                    team_id,
                    "$link_click".to_string(),
                    uuid::Uuid::new_v4().to_string(),
                    Some(ClickHouseEventProperties {
                        current_url: location.clone(),
                        ip: Some(addr.ip().to_string()),
                        user_agent: user_agent.map(|ua| ua.to_string()),
                    }),
                );

                // Do I really need to await here? Maybe should just put it in Tokio and let it run
                // in the background?
                publish_event(&state.internal_events_producer, &state.events_topic, event).await;
            }

            (
                StatusCode::FOUND,
                [(axum::http::header::LOCATION, location)],
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
        Ok(item) => {
            let url = item.url;
            let redirect_url = format!("https://{url}");
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
    let redirect_service = ExternalRedirectService::new(
        state.external_redis_client.clone(),
        state.default_domain_for_public_store.clone(),
    );
    let short_string = generate_base62_string();

    match redirect_service
        .store_url(&payload.redirect_url, &short_string)
        .await
    {
        Ok(redirect_url) => {
            let response = ExternalStoreUrlResponse {
                long_url: payload.redirect_url,
                short_url: redirect_url,
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
