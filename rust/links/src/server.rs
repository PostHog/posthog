use std::{future::Future, net::SocketAddr};

use tokio::net::TcpListener;

use crate::{router::router, state::State};

pub async fn serve<F>(state: State, listener: TcpListener, shutdown: F)
where
    F: Future<Output = ()> + Send + 'static,
{
    tracing::info!("listening on {:?}", listener.local_addr().unwrap());

    let app = router(state);
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown)
    .await
    .unwrap()
}
