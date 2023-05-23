use std::net::SocketAddr;

use crate::time::SystemTime;

mod api;
mod capture;
mod event;
mod router;
mod sink;
mod time;
mod token;

#[tokio::main]
async fn main() {
    // initialize tracing
    tracing_subscriber::fmt::init();

    let st = SystemTime {};
    let app = router::router(st);

    // run our app with hyper
    // `axum::Server` is a re-export of `hyper::Server`
    let addr = SocketAddr::from(([127, 0, 0, 1], 3000));

    tracing::debug!("listening on {}", addr);

    axum::Server::bind(&addr)
        .serve(app.into_make_service())
        .await
        .unwrap();
}
