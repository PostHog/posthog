use axum::{routing::post, Router};
use std::net::SocketAddr;
use tower_http::trace::TraceLayer;

mod api;
mod capture;
mod event;
mod token;

pub fn router() -> Router {
    Router::new()
        .route("/capture", post(capture::event))
        .route("/batch", post(capture::batch))
        .layer(TraceLayer::new_for_http())
}

#[tokio::main]
async fn main() {
    // initialize tracing
    tracing_subscriber::fmt::init();

    let app = router();

    // run our app with hyper
    // `axum::Server` is a re-export of `hyper::Server`
    let addr = SocketAddr::from(([127, 0, 0, 1], 3000));

    tracing::debug!("listening on {}", addr);

    axum::Server::bind(&addr)
        .serve(app.into_make_service())
        .await
        .unwrap();
}
