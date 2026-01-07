mod exception_list;
use std::sync::Arc;

use axum::routing::{get, post};
use axum::Router;
pub use exception_list::*;

use crate::app_context::AppContext;

async fn index() -> &'static str {
    "error tracking service"
}

pub fn processing_router() -> Router<Arc<AppContext>> {
    Router::<Arc<AppContext>>::new()
        .route("/", get(index))
        .route(
            "/:team_id/exception_list/process",
            post(process_exception_list),
        )
}
