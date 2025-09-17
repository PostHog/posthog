use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};

use serde::Serialize;
use thiserror::Error;

#[derive(Clone, Error, Debug, PartialEq, Eq)]
pub enum ApiError {
    #[error("invalid request parameter: {0}")]
    InvalidRequestParam(String),
    #[error("query error: {0}")]
    QueryError(String),
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        match &self {
            irp @ ApiError::InvalidRequestParam(_) => {
                (StatusCode::BAD_REQUEST, Json(Message::new(irp.to_string())))
            }
            qe @ ApiError::QueryError(_) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(Message::new(qe.to_string())),
            ),
        }
        .into_response()
    }
}

#[derive(Clone, Debug, Serialize)]
struct Message {
    cause: String,
}

impl Message {
    fn new(msg: String) -> Self {
        Self { cause: msg }
    }
}
