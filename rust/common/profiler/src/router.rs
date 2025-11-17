use crate::pprof::{
    handle_allocation_flamegraph, handle_allocation_report, handle_profile_flamegraph,
    handle_profile_report,
};
use axum::{routing::get, Router};

// Call this method when building your axum::Router in your Rust service
pub fn apply_pprof_routes(router: Router) -> Router {
    router
        .route("/pprof/profile/report", get(handle_profile_report))
        .route("/pprof/profile/flamegraph", get(handle_profile_flamegraph))
        .route("/pprof/heap/report", get(handle_allocation_report))
        .route("/pprof/heap/flamegraph", get(handle_allocation_flamegraph))
}
