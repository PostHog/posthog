use axum::{
    body::Body,
    extract::State,
    http::{header::AUTHORIZATION, Request, StatusCode},
    middleware::Next,
    response::Response,
};

use crate::app::AppState;

pub async fn auth_middleware(
    State(state): State<AppState>,
    mut request: Request<Body>,
    next: Next,
) -> Result<Response, StatusCode> {
    let auth_header = request
        .headers()
        .get(AUTHORIZATION)
        .and_then(|h| h.to_str().ok());

    let token = match auth_header {
        Some(header) if header.starts_with("Bearer ") => &header[7..],
        _ => return Err(StatusCode::UNAUTHORIZED),
    };

    let auth_context = state
        .auth
        .authenticate(token)
        .await
        .map_err(|_| StatusCode::UNAUTHORIZED)?;

    request.extensions_mut().insert(auth_context);

    Ok(next.run(request).await)
}
