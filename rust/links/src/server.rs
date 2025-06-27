use std::{future::Future, net::SocketAddr, sync::Arc, time::Duration};

use common_database::get_pool;
use common_redis::RedisClient;
use health::{HealthHandle, HealthRegistry};
use tokio::net::TcpListener;

use crate::{config::Config, router::router};

pub async fn serve<F>(config: Config, listener: TcpListener, shutdown: F)
where
    F: Future<Output = ()> + Send + 'static,
{
    let external_redis_client = match RedisClient::new(config.external_link_redis_url.clone()).await
    {
        Ok(client) => Arc::new(client),
        Err(e) => {
            tracing::error!("Failed to create Redis client: {}", e);
            return;
        }
    };

    let internal_redis_client = match RedisClient::new(config.internal_link_redis_url.clone()).await
    {
        Ok(client) => Arc::new(client),
        Err(e) => {
            tracing::error!("Failed to create Redis client: {}", e);
            return;
        }
    };

    let reader = match get_pool(&config.read_database_url, config.max_pg_connections).await {
        Ok(client) => {
            tracing::info!("Successfully created read Postgres client");
            Arc::new(client)
        }
        Err(e) => {
            tracing::error!(
                error = %e,
                url = %config.read_database_url,
                max_connections = config.max_pg_connections,
                "Failed to create read Postgres client"
            );
            return;
        }
    };

    let health = HealthRegistry::new("liveness");

    let simple_loop = health
        .register("simple_loop".to_string(), Duration::from_secs(30))
        .await;
    tokio::spawn(liveness_loop(simple_loop));

    tracing::info!("listening on {:?}", listener.local_addr().unwrap());
    let app = router(
        reader,
        external_redis_client,
        internal_redis_client,
        config.default_domain_for_public_store,
        health,
        config.enable_metrics,
    );
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
