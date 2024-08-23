use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;

use tokio::net::TcpListener;

use crate::config::Config;
use crate::database::PgClient;
use crate::geoip::GeoIpService;
use crate::redis::RedisClient;
use crate::router;

pub async fn serve<F>(config: Config, listener: TcpListener, shutdown: F)
where
    F: Future<Output = ()> + Send + 'static,
{
    let redis_client = match RedisClient::new(config.redis_url.clone()) {
        Ok(client) => Arc::new(client),
        Err(e) => {
            tracing::error!("Failed to create Redis client: {}", e);
            return;
        }
    };

    let read_postgres_client = match PgClient::new_read_client(&config).await {
        Ok(client) => Arc::new(client),
        Err(e) => {
            tracing::error!("Failed to create read Postgres client: {}", e);
            return;
        }
    };

    let geoip_service = match GeoIpService::new(&config) {
        Ok(service) => Arc::new(service),
        Err(e) => {
            tracing::error!("Failed to create GeoIP service: {}", e);
            return;
        }
    };

    // You can decide which client to pass to the router, or pass both if needed
    let app = router::router(redis_client, read_postgres_client, geoip_service);

    tracing::info!("listening on {:?}", listener.local_addr().unwrap());
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown)
    .await
    .unwrap()
}
