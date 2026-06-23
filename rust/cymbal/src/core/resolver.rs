use std::sync::Arc;

use sqlx::{postgres::PgPoolOptions, PgPool};
use tokio::sync::Mutex;

use crate::core::config::{get_aws_config, ResolverConfig};
use crate::core::error::UnhandledError;
use crate::core::symbolication::symbol::{local::LocalSymbolResolver, SymbolResolver};
use crate::core::symbolication::symbol_store::{
    apple::AppleProvider,
    caching::{Caching, SymbolSetCache},
    chunk_id::ChunkIdFetcher,
    concurrency,
    hermesmap::HermesMapProvider,
    native::NativeProvider,
    proguard::ProguardProvider,
    saving::Saving,
    sourcemap::SourcemapProvider,
    BlobClient, Catalog, S3Client,
};

/// Build just the symbol-resolution stack from config: connects to Postgres,
/// builds the S3 client, and returns a fully-wired
/// `SymbolResolver`. **Does not** start Kafka producers, Redis clients,
/// signals, the issue cache, or the remote-resolution pool — those belong to
/// the processing pipeline (`crate::app_context::AppContext`).
///
/// Used by resolution mode (`crate::modes::resolution`), which only needs
/// symbol resolution; keeping this in `core` stops resolution-mode pods from
/// depending on the processing app context.
pub async fn build_symbol_resolver(
    config: &ResolverConfig,
) -> Result<Arc<dyn SymbolResolver>, UnhandledError> {
    let options = PgPoolOptions::new().max_connections(config.max_pg_connections);
    let posthog_pool = options.connect(&config.database_url).await?;
    let s3 = aws_sdk_s3::Client::from_conf(get_aws_config(config).await);
    let s3_client: Arc<dyn BlobClient> = Arc::new(S3Client::new(s3));
    s3_client.ping_bucket(&config.object_storage_bucket).await?;
    let catalog = build_catalog(config, s3_client, posthog_pool.clone());
    Ok(Arc::new(LocalSymbolResolver::new(
        config,
        catalog,
        posthog_pool,
    )))
}

/// Build the symbol-store [`Catalog`] from already-constructed S3 and PG
/// handles. Shared by [`crate::app_context::AppContext::new`] and
/// [`build_symbol_resolver`] so the provider wiring doesn't drift.
pub fn build_catalog(
    config: &ResolverConfig,
    s3_client: Arc<dyn BlobClient>,
    posthog_pool: PgPool,
) -> Arc<Catalog> {
    let ss_cache = Arc::new(Mutex::new(SymbolSetCache::new(
        config.symbol_store_cache_max_bytes,
    )));

    let smp = SourcemapProvider::new(config).with_chunk_id_rescue(
        posthog_pool.clone(),
        s3_client.clone(),
        config.object_storage_bucket.clone(),
    );
    let smp_chunk = ChunkIdFetcher::new(
        smp,
        s3_client.clone(),
        posthog_pool.clone(),
        config.object_storage_bucket.clone(),
    );
    let smp_saving = Saving::new(
        smp_chunk,
        posthog_pool.clone(),
        s3_client.clone(),
        config.object_storage_bucket.clone(),
        config.ss_prefix.clone(),
    );
    let smp_caching = Caching::new(smp_saving, ss_cache.clone());
    // We want to fetch each sourcemap from the outside world exactly once,
    // and if it isn't in the cache, load/parse it from s3 exactly once too.
    // Limiting the per symbol set reference concurrency to 1 ensures this.
    let smp_atmostonce = concurrency::AtMostOne::new(smp_caching);

    let hmp_chunk = ChunkIdFetcher::new(
        HermesMapProvider {},
        s3_client.clone(),
        posthog_pool.clone(),
        config.object_storage_bucket.clone(),
    );
    // Skip the saving layer for HermesMapProvider, since it'll never fetch
    // something from the outside world.
    let hmp_caching = Caching::new(hmp_chunk, ss_cache.clone());
    let hmp_atmostonce = concurrency::AtMostOne::new(hmp_caching);

    let pgp_chunk = ChunkIdFetcher::new(
        ProguardProvider {},
        s3_client.clone(),
        posthog_pool.clone(),
        config.object_storage_bucket.clone(),
    );
    let pgp_caching = Caching::new(pgp_chunk, ss_cache.clone());
    let pgp_atmostonce = concurrency::AtMostOne::new(pgp_caching);

    let apple_chunk = ChunkIdFetcher::new(
        AppleProvider {},
        s3_client.clone(),
        posthog_pool.clone(),
        config.object_storage_bucket.clone(),
    );
    let apple_caching = Caching::new(apple_chunk, ss_cache.clone());
    let apple_atmostonce = concurrency::AtMostOne::new(apple_caching);

    let native_chunk = ChunkIdFetcher::new(
        NativeProvider {},
        s3_client.clone(),
        posthog_pool.clone(),
        config.object_storage_bucket.clone(),
    );
    let native_caching = Caching::new(native_chunk, ss_cache);
    let native_atmostonce = concurrency::AtMostOne::new(native_caching);

    Arc::new(Catalog::new(
        smp_atmostonce,
        hmp_atmostonce,
        pgp_atmostonce,
        apple_atmostonce,
        native_atmostonce,
    ))
}
