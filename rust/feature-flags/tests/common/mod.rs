use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use common_database::get_pool;
use common_redis::MockRedisClient;
use feature_flags::team::team_models::{Team, TEAM_TOKEN_CACHE_PREFIX};
use limiters::redis::QUOTA_LIMITER_CACHE_KEY;
use reqwest::header::CONTENT_TYPE;
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

    pub async fn for_config_with_mock_redis(
        config: Config,
        limited_tokens: Vec<String>,
        valid_tokens: Vec<(String, i32)>, // (token, team_id) pairs
    ) -> ServerHandle {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let notify = Arc::new(Notify::new());
        let shutdown = notify.clone();

        // Create a mock client that handles both quota limit checks and token verification
        let mut mock_client = MockRedisClient::new().zrangebyscore_ret(
            "@posthog/quota-limits/feature_flag_requests",
            limited_tokens.clone(),
        );

        // Add handling for token verification
        for (token, team_id) in valid_tokens {
            println!(
                "Setting up mock for token: {token} with key: {TEAM_TOKEN_CACHE_PREFIX}{token}"
            );

            // Create a minimal valid Team object
            let team = Team {
                id: team_id,
                project_id: team_id as i64,
                name: "Test Team".to_string(),
                api_token: token.clone(),
                cookieless_server_hash_mode: 0,
                timezone: "UTC".to_string(),
                ..Default::default()
            };

            // Serialize to JSON
            let team_json = serde_json::to_string(&team).unwrap();
            println!("Team JSON for mock: {team_json}");

            mock_client =
                mock_client.get_ret(&format!("{TEAM_TOKEN_CACHE_PREFIX}{token}"), Ok(team_json));
        }

        tokio::spawn(async move {
            let redis_reader_client = Arc::new(mock_client);
            let redis_writer_client = redis_reader_client.clone();
            let reader = match get_pool(&config.read_database_url, config.max_pg_connections).await
            {
                Ok(client) => Arc::new(client),
                Err(e) => {
                    tracing::error!("Failed to create read Postgres client: {}", e);
                    return;
                }
            };
            let writer = match get_pool(&config.write_database_url, config.max_pg_connections).await
            {
                Ok(client) => Arc::new(client),
                Err(e) => {
                    tracing::error!("Failed to create write Postgres client: {}", e);
                    return;
                }
            };
            let geoip_service = match common_geoip::GeoIpClient::new(config.get_maxmind_db_path()) {
                Ok(service) => Arc::new(service),
                Err(e) => {
                    tracing::error!("Failed to create GeoIP service: {}", e);
                    return;
                }
            };
            let cohort_cache = Arc::new(
                feature_flags::cohorts::cohort_cache_manager::CohortCacheManager::new(
                    reader.clone(),
                    Some(config.cache_max_cohort_entries),
                    Some(config.cache_ttl_seconds),
                ),
            );

            let health = health::HealthRegistry::new("liveness");
            let simple_loop = health
                .register("simple_loop".to_string(), Duration::from_secs(30))
                .await;
            tokio::spawn(liveness_loop(simple_loop));

            let feature_flags_billing_limiter =
                feature_flags::billing_limiters::FeatureFlagsLimiter::new(
                    Duration::from_secs(5),
                    redis_reader_client.clone(),
                    QUOTA_LIMITER_CACHE_KEY.to_string(),
                    None,
                )
                .unwrap();

            let session_replay_billing_limiter =
                feature_flags::billing_limiters::SessionReplayLimiter::new(
                    Duration::from_secs(5),
                    redis_reader_client.clone(),
                    QUOTA_LIMITER_CACHE_KEY.to_string(),
                    None,
                )
                .unwrap();

            let cookieless_manager = Arc::new(common_cookieless::CookielessManager::new(
                config.get_cookieless_config(),
                redis_reader_client.clone(),
            ));

            // Create DatabasePools for tests
            let database_pools = Arc::new(feature_flags::database_pools::DatabasePools {
                non_persons_reader: reader.clone(),
                non_persons_writer: writer.clone(),
                persons_reader: reader.clone(),
                persons_writer: writer.clone(),
            });

            let app = feature_flags::router::router(
                redis_reader_client,
                redis_writer_client,
                database_pools,
                cohort_cache,
                geoip_service,
                health,
                feature_flags_billing_limiter,
                session_replay_billing_limiter,
                cookieless_manager,
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

    pub async fn send_flags_request<T: Into<reqwest::Body>>(
        &self,
        body: T,
        version: Option<&str>,
        config: Option<&str>,
    ) -> reqwest::Response {
        let client = reqwest::Client::new();
        let mut url = format!("http://{}/flags", self.addr);
        let mut params = vec![];
        if let Some(v) = version {
            params.push(format!("v={v}"));
        }
        if let Some(c) = config {
            params.push(format!("config={c}"));
        }
        if !params.is_empty() {
            url.push('?');
            url.push_str(&params.join("&"));
        }
        client
            .post(url)
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
