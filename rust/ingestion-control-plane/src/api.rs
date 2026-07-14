use axum::routing::get;
use axum::Router;

use crate::state::AppState;
use crate::ui;

pub fn router(state: AppState) -> Router {
    Router::new().route("/", get(ui::index)).with_state(state)
}
