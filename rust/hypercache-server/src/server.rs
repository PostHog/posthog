use std::{future::Future, net::SocketAddr, sync::Arc};

use common_cache::NegativeCache;
use common_hypercache::{HyperCacheConfig, HyperCacheReader};
use common_redis::{Client, CompressionConfig, ReadWriteClient, ReadWriteClientConfig};
use tokio::net::TcpListener;

use crate::config::Config;

pub async fn serve<F>(config: Config, listener: TcpListener, shutdown: F)
where
    F: Future<Output = ()> + Send + 'static,
{
    let writer_url = config.redis_url.clone();
    let reader_url = if config.redis_reader_url.is_empty() {
        writer_url.clone()
    } else {
        config.redis_reader_url.clone()
    };

    let rw_config = ReadWriteClientConfig::new(
        writer_url,
        reader_url,
        CompressionConfig::disabled(),
        common_redis::RedisValueFormat::default(),
        if config.redis_timeout_ms == 0 {
            None
        } else {
            Some(std::time::Duration::from_millis(config.redis_timeout_ms))
        },
        None, // No connection timeout
    );

    let redis_client: Arc<dyn Client + Send + Sync> =
        match ReadWriteClient::with_config(rw_config).await {
            Ok(client) => {
                tracing::info!("Created Redis client");
                Arc::new(client)
            }
            Err(e) => {
                tracing::error!("Failed to create Redis client: {:?}", e);
                return;
            }
        };

    // Surveys HyperCache: namespace "surveys", value "surveys.json", token-based
    let surveys_hypercache_reader =
        match create_hypercache_reader(redis_client.clone(), "surveys", "surveys.json", &config)
            .await
        {
            Some(reader) => reader,
            None => return,
        };

    // Remote config HyperCache: namespace "array", value "config.json", token-based
    let config_hypercache_reader =
        match create_hypercache_reader(redis_client.clone(), "array", "config.json", &config).await
        {
            Some(reader) => reader,
            None => return,
        };

    // Build one negative cache per namespace when enabled. Keeping them separate
    // avoids false positives: a token missing from surveys can legitimately exist
    // in remote config.
    let (surveys_negative_cache, config_negative_cache) = if *config.negative_cache_enabled {
        tracing::info!(
            max_entries = config.negative_cache_max_entries,
            ttl_seconds = config.negative_cache_ttl_seconds,
            "Negative cache enabled"
        );
        (
            Some(NegativeCache::new(
                config.negative_cache_max_entries,
                config.negative_cache_ttl_seconds,
            )),
            Some(NegativeCache::new(
                config.negative_cache_max_entries,
                config.negative_cache_ttl_seconds,
            )),
        )
    } else {
        (None, None)
    };

    let app = crate::router::router(
        surveys_hypercache_reader,
        config_hypercache_reader,
        surveys_negative_cache,
        config_negative_cache,
        config,
    );

    tracing::info!(
        "listening on {:?}",
        listener.local_addr().expect("could not get local addr")
    );

    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown)
    .await
    .expect("failed to start server");
}

async fn create_hypercache_reader(
    redis_client: Arc<dyn Client + Send + Sync>,
    namespace: &str,
    value: &str,
    config: &Config,
) -> Option<Arc<HyperCacheReader>> {
    let mut hc_config = HyperCacheConfig::new(
        namespace.to_string(),
        value.to_string(),
        config.object_storage_region.clone(),
        config.object_storage_bucket.clone(),
    );
    hc_config.token_based = true;

    if !config.object_storage_endpoint.is_empty() {
        hc_config.s3_endpoint = Some(config.object_storage_endpoint.clone());
    }

    match HyperCacheReader::new(redis_client, hc_config).await {
        Ok(reader) => {
            tracing::info!("Created HyperCacheReader for {namespace}/{value}");
            Some(Arc::new(reader))
        }
        Err(e) => {
            tracing::error!(
                "Failed to create HyperCacheReader for {namespace}/{value}: {:?}",
                e
            );
            None
        }
    }
}
