use std::net::SocketAddr;
use std::sync::Arc;

use common_redis::MockRedisClient;
use limiters::redis::{QuotaResource, RedisLimiter, QUOTA_LIMITER_CACHE_KEY};
use reqwest::header::CONTENT_TYPE;
use time::Duration;
use tokio::net::TcpListener;
use tokio::sync::Notify;

use feature_flags::config::Config;
use feature_flags::server::serve;

pub struct ServerHandle {
    pub addr: SocketAddr,
    shutdown: Arc<Notify>,
}

impl ServerHandle {
    pub async fn for_config(config: Config) -> ServerHandle {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let notify = Arc::new(Notify::new());
        let shutdown = notify.clone();

        tokio::spawn(async move {
            serve(config, listener, async move { notify.notified().await }).await
        });
        ServerHandle { addr, shutdown }
    }

    pub async fn for_config_with_limited_tokens(
        config: Config,
        limited_tokens: Vec<String>,
    ) -> ServerHandle {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let notify = Arc::new(Notify::new());
        let shutdown = notify.clone();

        let mock_client = MockRedisClient::new().zrangebyscore_ret(
            "@posthog/quota-limits/feature_flag_requests",
            limited_tokens.clone(),
        );

        tokio::spawn(async move {
            let redis_client = Arc::new(mock_client);
            let reader = match feature_flags::client::database::get_pool(
                &config.read_database_url,
                config.max_pg_connections,
            )
            .await
            {
                Ok(client) => Arc::new(client),
                Err(e) => {
                    tracing::error!("Failed to create read Postgres client: {}", e);
                    return;
                }
            };
            let writer = match feature_flags::client::database::get_pool(
                &config.write_database_url,
                config.max_pg_connections,
            )
            .await
            {
                Ok(client) => Arc::new(client),
                Err(e) => {
                    tracing::error!("Failed to create write Postgres client: {}", e);
                    return;
                }
            };
            let geoip_service = match feature_flags::client::geoip::GeoIpClient::new(&config) {
                Ok(service) => Arc::new(service),
                Err(e) => {
                    tracing::error!("Failed to create GeoIP service: {}", e);
                    return;
                }
            };
            let cohort_cache = Arc::new(
                feature_flags::cohort::cohort_cache_manager::CohortCacheManager::new(
                    reader.clone(),
                    Some(config.cache_max_cohort_entries),
                    Some(config.cache_ttl_seconds),
                ),
            );

            let health = health::HealthRegistry::new("liveness");
            let simple_loop = health
                .register("simple_loop".to_string(), Duration::seconds(30))
                .await;
            tokio::spawn(liveness_loop(simple_loop));

            let billing_limiter = RedisLimiter::new(
                Duration::seconds(5),
                redis_client.clone(),
                QUOTA_LIMITER_CACHE_KEY.to_string(),
                None,
                QuotaResource::FeatureFlags,
            )
            .unwrap();

            let app = feature_flags::router::router(
                redis_client,
                reader,
                writer,
                cohort_cache,
                geoip_service,
                health,
                billing_limiter,
                config,
            );

            axum::serve(
                listener,
                app.into_make_service_with_connect_info::<SocketAddr>(),
            )
            .with_graceful_shutdown(async move { notify.notified().await })
            .await
            .unwrap()
        });

        tokio::time::sleep(std::time::Duration::from_millis(100)).await;

        ServerHandle { addr, shutdown }
    }

    pub async fn send_flags_request<T: Into<reqwest::Body>>(&self, body: T) -> reqwest::Response {
        let client = reqwest::Client::new();
        client
            .post(format!("http://{:?}/flags", self.addr))
            .body(body)
            .header(CONTENT_TYPE, "application/json")
            .send()
            .await
            .expect("failed to send request")
    }

    pub async fn send_invalid_header_for_flags_request<T: Into<reqwest::Body>>(
        &self,
        body: T,
    ) -> reqwest::Response {
        let client = reqwest::Client::new();
        client
            .post(format!("http://{:?}/flags", self.addr))
            .body(body)
            .header(CONTENT_TYPE, "xyz")
            .send()
            .await
            .expect("failed to send request")
    }
}

impl Drop for ServerHandle {
    fn drop(&mut self) {
        self.shutdown.notify_one()
    }
}

async fn liveness_loop(handle: health::HealthHandle) {
    loop {
        handle.report_healthy().await;
        tokio::time::sleep(std::time::Duration::from_secs(10)).await;
    }
}
