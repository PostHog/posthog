use std::future::Future;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use health::{HealthHandle, HealthRegistry};
use tokio::net::TcpListener;

use crate::config::Config;
use crate::database::get_pool;
use crate::geoip::GeoIpClient;
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

    let read_postgres_client =
        match get_pool(&config.read_database_url, config.max_pg_connections).await {
            Ok(client) => Arc::new(client),
            Err(e) => {
                tracing::error!("Failed to create read Postgres client: {}", e);
                return;
            }
        };

    let geoip_service = match GeoIpClient::new(&config) {
        Ok(service) => Arc::new(service),
        Err(e) => {
            tracing::error!("Failed to create GeoIP service: {}", e);
            return;
        }
    };

    let health = HealthRegistry::new("liveness");

    // TODO - we don't have a more complex health check yet, but we should add e.g. some around DB operations
    let simple_loop = health
        .register("simple_loop".to_string(), Duration::from_secs(30))
        .await;
    tokio::spawn(liveness_loop(simple_loop));

    // You can decide which client to pass to the router, or pass both if needed
    let app = router::router(
        redis_client,
        read_postgres_client,
        geoip_service,
        health,
        config.enable_metrics,
    );

    tracing::info!("listening on {:?}", listener.local_addr().unwrap());
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown)
    .await
    .unwrap()
}

async fn liveness_loop(handle: HealthHandle) {
    loop {
        handle.report_healthy().await;
        tokio::time::sleep(std::time::Duration::from_secs(10)).await;
    }
}
