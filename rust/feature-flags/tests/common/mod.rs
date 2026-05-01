use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use common_cache::{CacheConfig, NegativeCache, ReadThroughCache, ReadThroughCacheWithMetrics};
use common_database::get_pool;
use common_hypercache::{HyperCacheConfig, HyperCacheReader};
use common_redis::MockRedisClient;
use feature_flags::team::team_models::Team;
use feature_flags::utils::test_utils::team_token_hypercache_key;
use lifecycle::Manager;
use limiters::redis::QUOTA_LIMITER_CACHE_KEY;
use reqwest::header::CONTENT_TYPE;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

use feature_flags::cohorts::membership::NoOpCohortMembershipProvider;
use feature_flags::config::Config;
use feature_flags::rayon_dispatcher::RayonDispatcher;
use feature_flags::server::{register_components, serve};

pub struct ServerHandle {
    pub addr: SocketAddr,
    shutdown: CancellationToken,
}

impl ServerHandle {
    /// Cancel the shutdown token. Drop also does this; use only for explicit
    /// early shutdown.
    #[allow(dead_code)]
    pub fn shutdown_now(&self) {
        self.shutdown.cancel();
    }
}

fn build_test_manager(token: CancellationToken) -> Manager {
    Manager::builder("feature-flags-test")
        .with_trap_signals(false)
        .with_prestop_check(false)
        .with_shutdown_token(token)
        .with_global_shutdown_timeout(Duration::from_secs(10))
        .build()
}

impl ServerHandle {
    pub async fn for_config(config: Config) -> ServerHandle {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let shutdown = CancellationToken::new();
        let mut manager = build_test_manager(shutdown.clone());
        let handles = register_components(&mut manager);
        let monitor_guard = manager.monitor_background();

        let rayon_dispatcher = RayonDispatcher::new(2, None);
        tokio::spawn(async move {
            serve(config, listener, rayon_dispatcher, handles).await;
            // Drain the lifecycle monitor after serve returns so the supervisor
            // thread exits cleanly. Any error is logged — a failing shutdown
            // shouldn't fail the test unless the test explicitly asserts on it.
            if let Err(e) = monitor_guard.wait().await {
                tracing::warn!("test lifecycle monitor reported: {e}");
            }
        });
        ServerHandle { addr, shutdown }
    }

    /// Poll the server's readiness endpoint until it responds successfully.
    /// Panics if the server doesn't become ready within 5 seconds.
    #[allow(dead_code)]
    pub async fn wait_until_ready(&self) {
        let client = reqwest::Client::new();
        let url = format!("http://{}/_readiness", self.addr);
        for _ in 0..100 {
            match client.get(&url).send().await {
                Ok(resp) if resp.status().is_success() => return,
                _ => tokio::time::sleep(std::time::Duration::from_millis(50)).await,
            }
        }
        panic!("Server failed to become ready within 5 seconds");
    }

    #[allow(dead_code)]
    pub async fn for_config_with_mock_redis(
        config: Config,
        limited_tokens: Vec<String>,
        valid_tokens: Vec<(String, i32)>, // (token, team_id) pairs
    ) -> ServerHandle {
        Self::for_config_with_mock_redis_and_recordings(
            config,
            limited_tokens,
            vec![], // no recordings-limited tokens
            valid_tokens,
        )
        .await
    }

    /// Create a server with mock Redis that supports both feature flag and recordings quota limits.
    #[allow(dead_code)]
    pub async fn for_config_with_mock_redis_and_recordings(
        config: Config,
        limited_tokens: Vec<String>,            // feature flags limited
        recordings_limited_tokens: Vec<String>, // session recordings limited
        valid_tokens: Vec<(String, i32)>,       // (token, team_id) pairs
    ) -> ServerHandle {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let shutdown = CancellationToken::new();
        let mut manager = build_test_manager(shutdown.clone());
        // `monitor_background()` is intentionally not called in this path:
        // ReadinessHandler reads the token directly and `trap_signals=false`
        // means no supervisor is required. `manager` is dropped at the end of
        // this function — before the spawned task runs — which closes the
        // receiver for the supervision channel. That's safe here because
        // shutdown is driven by the `CancellationToken` (via
        // `handles.http.shutdown_signal()`), not by the manager loop, and the
        // lifecycle crate intentionally ignores send errors from
        // `work_completed()` and handle drops. If that ever changes (e.g. a
        // channel-full panic, or handles relying on a manager ACK), this test
        // harness will need to keep `manager` alive for the spawn's lifetime.
        let handles = register_components(&mut manager);

        // Create a mock client that handles both quota limit checks and token verification
        let mut mock_client = MockRedisClient::new()
            .zrangebyscore_ret(
                "@posthog/quota-limits/feature_flag_requests",
                limited_tokens.clone(),
            )
            .zrangebyscore_ret(
                "@posthog/quota-limits/recordings",
                recordings_limited_tokens.clone(),
            );

        // Add handling for token verification using HyperCache format
        for (token, team_id) in valid_tokens {
            let cache_key = team_token_hypercache_key(&token);
            println!("Setting up mock for token: {token} with key: {cache_key}");

            // Create a minimal valid Team object
            let team = Team {
                id: team_id,
                name: "Test Team".to_string(),
                api_token: token.clone(),
                cookieless_server_hash_mode: Some(0),
                timezone: "UTC".to_string(),
                ..Default::default()
            };

            // Serialize to JSON, then Pickle-encode it (matching HyperCache format)
            let team_json = serde_json::to_string(&team).unwrap();
            println!("Team JSON for mock: {team_json}");
            let pickled_bytes = serde_pickle::ser::to_vec(&team_json, Default::default()).unwrap();

            mock_client = mock_client.get_raw_bytes_ret(&cache_key, Ok(pickled_bytes));
        }

        tokio::spawn(async move {
            let redis_reader_client: Arc<dyn common_redis::Client + Send + Sync> =
                Arc::new(mock_client);
            let redis_writer_client = redis_reader_client.clone();

            let (persons_reader, persons_writer, non_persons_reader, non_persons_writer) = if config
                .is_persons_db_routing_enabled()
            {
                // Separate persons and non-persons databases
                let persons_reader = match get_pool(
                    &config.get_persons_read_database_url(),
                    config.max_pg_connections,
                ) {
                    Ok(client) => Arc::new(client),
                    Err(e) => {
                        tracing::error!("Failed to create persons read Postgres client: {}", e);
                        return;
                    }
                };
                let persons_writer = match get_pool(
                    &config.get_persons_write_database_url(),
                    config.max_pg_connections,
                ) {
                    Ok(client) => Arc::new(client),
                    Err(e) => {
                        tracing::error!("Failed to create persons write Postgres client: {}", e);
                        return;
                    }
                };
                let non_persons_reader =
                    match get_pool(&config.read_database_url, config.max_pg_connections) {
                        Ok(client) => Arc::new(client),
                        Err(e) => {
                            tracing::error!(
                                "Failed to create non-persons read Postgres client: {}",
                                e
                            );
                            return;
                        }
                    };
                let non_persons_writer =
                    match get_pool(&config.write_database_url, config.max_pg_connections) {
                        Ok(client) => Arc::new(client),
                        Err(e) => {
                            tracing::error!(
                                "Failed to create non-persons write Postgres client: {}",
                                e
                            );
                            return;
                        }
                    };
                (
                    persons_reader,
                    persons_writer,
                    non_persons_reader,
                    non_persons_writer,
                )
            } else {
                // Same database for both persons and non-persons tables
                let reader = match get_pool(&config.read_database_url, config.max_pg_connections) {
                    Ok(client) => Arc::new(client),
                    Err(e) => {
                        tracing::error!("Failed to create read Postgres client: {}", e);
                        return;
                    }
                };
                let writer = match get_pool(&config.write_database_url, config.max_pg_connections) {
                    Ok(client) => Arc::new(client),
                    Err(e) => {
                        tracing::error!("Failed to create write Postgres client: {}", e);
                        return;
                    }
                };
                (
                    reader.clone(),
                    writer.clone(),
                    reader.clone(),
                    writer.clone(),
                )
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
                    non_persons_reader.clone(),
                    Some(config.cohort_cache_capacity_bytes),
                    Some(config.cache_ttl_seconds),
                ),
            );

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
                non_persons_reader: non_persons_reader.clone(),
                non_persons_writer: non_persons_writer.clone(),
                persons_reader: persons_reader.clone(),
                persons_writer: persons_writer.clone(),
                behavioral_cohorts_reader: None,
                test_before_acquire: *config.test_before_acquire,
            });

            // Create HyperCacheReader for flags
            let flags_hypercache_config = HyperCacheConfig::new(
                "feature_flags".to_string(),
                "flags.json".to_string(),
                config.object_storage_region.clone(),
                config.object_storage_bucket.clone(),
            );
            let flags_hypercache_reader =
                match HyperCacheReader::new(redis_reader_client.clone(), flags_hypercache_config)
                    .await
                {
                    Ok(reader) => Arc::new(reader),
                    Err(e) => {
                        tracing::error!("Failed to create flags HyperCacheReader: {:?}", e);
                        return;
                    }
                };

            // Create HyperCacheReader for flags with cohorts (used by /flags/definitions endpoint)
            let flags_with_cohorts_hypercache_config = HyperCacheConfig::new(
                "feature_flags".to_string(),
                "flags_with_cohorts.json".to_string(),
                config.object_storage_region.clone(),
                config.object_storage_bucket.clone(),
            );
            let flags_with_cohorts_hypercache_reader = match HyperCacheReader::new(
                redis_reader_client.clone(),
                flags_with_cohorts_hypercache_config,
            )
            .await
            {
                Ok(reader) => Arc::new(reader),
                Err(e) => {
                    tracing::error!(
                        "Failed to create flags_with_cohorts HyperCacheReader: {:?}",
                        e
                    );
                    return;
                }
            };

            // Create team metadata hypercache reader
            let mut team_hypercache_config = HyperCacheConfig::new(
                "team_metadata".to_string(),
                "full_metadata.json".to_string(),
                config.object_storage_region.clone(),
                config.object_storage_bucket.clone(),
            );
            team_hypercache_config.token_based = true;
            let team_hypercache_reader =
                match HyperCacheReader::new(redis_reader_client.clone(), team_hypercache_config)
                    .await
                {
                    Ok(reader) => Arc::new(reader),
                    Err(e) => {
                        tracing::error!("Failed to create team HyperCacheReader: {:?}", e);
                        return;
                    }
                };

            // Create config hypercache reader for remote config (array/config.json)
            let mut config_hypercache_config = HyperCacheConfig::new(
                "array".to_string(),
                "config.json".to_string(),
                config.object_storage_region.clone(),
                config.object_storage_bucket.clone(),
            );
            config_hypercache_config.token_based = true;
            let config_hypercache_reader =
                match HyperCacheReader::new(redis_reader_client.clone(), config_hypercache_config)
                    .await
                {
                    Ok(reader) => Arc::new(reader),
                    Err(e) => {
                        tracing::error!("Failed to create config HyperCacheReader: {:?}", e);
                        return;
                    }
                };

            let group_type_cache = Arc::new(
                feature_flags::flags::flag_group_type_mapping::GroupTypeCacheManager::new(
                    persons_reader.clone(),
                    Some(config.group_type_cache_max_entries),
                    Some(config.group_type_cache_ttl_seconds),
                ),
            );

            let flag_definitions_cache = Arc::new(
                feature_flags::flags::flag_definitions_cache::FlagDefinitionsCache::disabled(),
            );

            let app = feature_flags::router::router(
                redis_writer_client.clone(), // Use writer client for both reads and writes in tests
                None,                        // No dedicated flags Redis in tests
                database_pools,
                cohort_cache,
                group_type_cache,
                geoip_service,
                handles.readiness,
                handles.liveness,
                feature_flags_billing_limiter,
                session_replay_billing_limiter,
                cookieless_manager,
                flags_hypercache_reader,
                flag_definitions_cache,
                flags_with_cohorts_hypercache_reader,
                team_hypercache_reader,
                config_hypercache_reader,
                RayonDispatcher::new(2, None),
                NegativeCache::new(10_000, 300),
                Arc::new(ReadThroughCacheWithMetrics::new(
                    Arc::new(ReadThroughCache::new(
                        redis_writer_client.clone(),
                        redis_writer_client.clone(),
                        CacheConfig::with_ttl(
                            feature_flags::api::auth::TOKEN_CACHE_PREFIX,
                            config.auth_token_cache_ttl_seconds,
                        ),
                        None,
                    )),
                    "auth",
                    "token",
                    &[],
                )),
                Arc::new(NoOpCohortMembershipProvider),
                config,
            );

            axum::serve(
                listener,
                app.into_make_service_with_connect_info::<SocketAddr>(),
            )
            .with_graceful_shutdown(handles.http.shutdown_signal())
            .await
            .unwrap();
            handles.http.work_completed();
        });

        tokio::time::sleep(std::time::Duration::from_millis(100)).await;

        ServerHandle { addr, shutdown }
    }

    #[allow(dead_code)]
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

    #[allow(dead_code)]
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
        self.shutdown.cancel();
    }
}
