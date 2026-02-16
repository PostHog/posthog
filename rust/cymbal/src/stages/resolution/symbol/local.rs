use std::{sync::Arc, time::Duration};

use axum::async_trait;

use common_types::error_tracking::RawFrameId;
use moka::future::{Cache, CacheBuilder};

use sqlx::PgPool;

use crate::{
    config::Config,
    error::{JsResolveErr, ProguardError, ResolveError, UnhandledError},
    frames::{records::ErrorTrackingStackFrame, releases::ReleaseRecord, Frame, RawFrame},
    metric_consts::{
        FRAME_CACHE_HITS, FRAME_CACHE_MISSES, FRAME_DB_HITS, FRAME_DB_MISSES,
        SUSPICIOUS_FRAMES_DETECTED,
    },
    stages::resolution::symbol::SymbolResolver,
    symbol_store::{
        chunk_id::OrChunkId,
        dart_minified_names::lookup_minified_type,
        proguard::{FetchedMapping, ProguardRef},
        saving::SymbolSetRecord,
        Catalog,
    },
    types::operator::TeamId,
};

#[derive(Clone)]
pub struct LocalSymbolResolver {
    catalog: Arc<Catalog>,
    cache: Cache<RawFrameId, Vec<ErrorTrackingStackFrame>>,
    pool: PgPool,
    result_ttl: chrono::Duration,
}

impl LocalSymbolResolver {
    pub fn new(config: &Config, catalog: Arc<Catalog>, pool: PgPool) -> Self {
        let cache = CacheBuilder::new(config.frame_cache_size)
            .time_to_live(Duration::from_secs(config.frame_cache_ttl_seconds))
            .build();

        let result_ttl = chrono::Duration::minutes(config.frame_result_ttl_minutes as i64);

        Self {
            catalog,
            pool,
            cache,
            result_ttl,
        }
    }

    pub async fn resolve(
        &self,
        team_id: i32,
        frame: &RawFrame,
    ) -> Result<Vec<Frame>, UnhandledError> {
        if frame.is_suspicious() {
            metrics::counter!(SUSPICIOUS_FRAMES_DETECTED, "frame_type" => "raw").increment(1);
        }
        let raw_id = frame.raw_id(team_id);
        let mut cache_miss = false;
        let frames = self
            .cache
            .try_get_with(raw_id.clone(), async {
                cache_miss = true;
                self.resolve_impl(frame, raw_id.clone()).await
            })
            .await
            .map_err(|e| UnhandledError::Other(e.to_string()))?;

        if cache_miss {
            metrics::counter!(FRAME_CACHE_MISSES).increment(1);
        } else {
            metrics::counter!(FRAME_CACHE_HITS).increment(1);
        }

        Ok(frames.into_iter().map(|f| f.contents).collect())
    }

    async fn resolve_impl(
        &self,
        frame: &RawFrame,
        raw_id: RawFrameId,
    ) -> Result<Vec<ErrorTrackingStackFrame>, UnhandledError> {
        let loaded =
            ErrorTrackingStackFrame::load_all(&self.pool, &raw_id, self.result_ttl).await?;
        if !loaded.is_empty() {
            metrics::counter!(FRAME_DB_HITS).increment(1);
            return Ok(loaded);
        }

        metrics::counter!(FRAME_DB_MISSES).increment(1);

        let resolved = frame.resolve(raw_id.team_id, &self.catalog).await?;

        assert!(!resolved.is_empty()); // If this ever happens, we've got a data-dropping bug, and want to crash

        let (set, release) = if let Some(set_ref) = frame.symbol_set_ref() {
            // TODO - should be a join
            (
                SymbolSetRecord::load(&self.pool, raw_id.team_id, &set_ref).await?,
                ReleaseRecord::for_symbol_set_ref(&self.pool, &set_ref, raw_id.team_id).await?,
            )
        } else {
            (None, None)
        };

        let mut records = Vec::new();
        let mut resolved = resolved.clone();
        for r_frame in resolved.iter_mut() {
            r_frame.release = release.clone(); // Enrich with release information

            // And save back to the DB
            let record = ErrorTrackingStackFrame::new(
                r_frame.frame_id.clone(),
                set.as_ref().map(|s| s.id),
                r_frame.clone(),
                r_frame.resolved,
                r_frame.context.clone(),
            );
            record.save(&self.pool).await?;
            if r_frame.suspicious {
                metrics::counter!(SUSPICIOUS_FRAMES_DETECTED, "frame_type" => "resolved")
                    .increment(1);
            }

            // And gather up for the cache
            records.push(record);
        }
        Ok(records)
    }
}

#[async_trait]
impl SymbolResolver for LocalSymbolResolver {
    async fn resolve_raw_frame(
        &self,
        team_id: TeamId,
        frame: &RawFrame,
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve(team_id, frame).await
    }

    async fn resolve_java_class(
        &self,
        team_id: TeamId,
        symbolset_ref: OrChunkId<ProguardRef>,
        class: String,
    ) -> Result<String, ResolveError> {
        let map: Arc<FetchedMapping> = self.catalog.pg.lookup(team_id, symbolset_ref).await?;
        let mapper = map.get_mapper();
        let result = mapper
            .remap_class(class.as_str())
            .map(|s| s.to_string())
            .ok_or(ProguardError::MissingClass)?;
        Ok(result)
    }

    async fn resolve_dart_minified_name(
        &self,
        team_id: TeamId,
        chunk_id: String,
        minified_name: &str,
    ) -> Result<String, ResolveError> {
        // TODO - implement this properly once we have a real Dart minification resolver
        let sourcemap = self
            .catalog
            .smp
            .lookup(team_id, OrChunkId::ChunkId(chunk_id))
            .await?;

        let minified_names = sourcemap
            .get_dart_minified_names()
            .ok_or(ResolveError::from(JsResolveErr::InvalidSourceAndMap))?;

        lookup_minified_type(minified_names, minified_name)
            .ok_or(ResolveError::from(JsResolveErr::InvalidSourceAndMap))
    }
}

#[cfg(test)]
mod test {

    use std::sync::Arc;

    use common_types::ClickHouseEvent;
    use httpmock::MockServer;
    use mockall::predicate;
    use sqlx::PgPool;
    use symbolic::sourcemapcache::SourceMapCacheWriter;

    use crate::{
        config::Config,
        frames::{records::ErrorTrackingStackFrame, RawFrame},
        stages::resolution::symbol::{local::LocalSymbolResolver, SymbolResolver},
        symbol_store::{
            chunk_id::ChunkIdFetcher,
            hermesmap::HermesMapProvider,
            proguard::ProguardProvider,
            saving::{Saving, SymbolSetRecord},
            sourcemap::SourcemapProvider,
            Catalog, MockS3Client,
        },
        types::{RawErrProps, Stacktrace},
    };

    const CHUNK_PATH: &str = "/static/chunk-PGUQKT6S.js";
    const MINIFIED: &[u8] = include_bytes!("../../../../tests/static/chunk-PGUQKT6S.js");
    const MAP: &[u8] = include_bytes!("../../../../tests/static/chunk-PGUQKT6S.js.map");
    const EXAMPLE_EXCEPTION: &str =
        include_str!("../../../../tests/static/raw_ch_exception_list.json");

    async fn setup_test_context<S>(pool: PgPool, s3_init: S) -> (Config, Catalog, MockServer)
    where
        S: FnOnce(&Config, MockS3Client) -> MockS3Client,
    {
        let mut config = Config::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();
        config.allow_internal_ips = true; // Gonna be hitting the sourcemap mocks

        let server = MockServer::start();
        server.mock(|when, then| {
            when.method("GET").path(CHUNK_PATH);
            then.status(200).body(MINIFIED);
        });

        server.mock(|when, then| {
            // Our minified example source uses a relative URL, formatted like this
            when.method("GET").path(format!("{CHUNK_PATH}.map"));
            then.status(200).body(MAP);
        });

        let client = MockS3Client::default();

        let client = s3_init(&config, client);

        let client = Arc::new(client);

        let chunk_id_smp = ChunkIdFetcher::new(
            SourcemapProvider::new(&config),
            client.clone(),
            pool.clone(),
            config.object_storage_bucket.clone(),
        );

        let saving_smp = Saving::new(
            chunk_id_smp,
            pool.clone(),
            client.clone(),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
        );

        let hmp = ChunkIdFetcher::new(
            HermesMapProvider {},
            client.clone(),
            pool.clone(),
            config.object_storage_bucket.clone(),
        );

        let pgp = ChunkIdFetcher::new(
            ProguardProvider {},
            client.clone(),
            pool.clone(),
            config.object_storage_bucket.clone(),
        );

        let catalog = Catalog::new(saving_smp, hmp, pgp);

        (config, catalog, server)
    }

    fn get_test_frame(server: &MockServer) -> RawFrame {
        let exception: ClickHouseEvent = serde_json::from_str(EXAMPLE_EXCEPTION).unwrap();
        let mut props: RawErrProps = serde_json::from_str(&exception.properties.unwrap()).unwrap();
        let Stacktrace::Raw {
            frames: mut test_stack,
        } = props.exception_list.swap_remove(0).stack.unwrap()
        else {
            panic!("Expected a Raw stacktrace")
        };

        // We're going to pretend out stack consists exclusively of JS frames whose source
        // we have locally
        test_stack.retain(|s| {
            let RawFrame::JavaScriptWeb(s) = s else {
                return false;
            };
            s.source_url.as_ref().unwrap().contains(CHUNK_PATH)
        });

        for frame in test_stack.iter_mut() {
            let RawFrame::JavaScriptWeb(frame) = frame else {
                panic!("Expected a JavaScript frame")
            };
            // Our test data contains our /actual/ source urls - we need to swap that to localhost
            // When I first wrote this test, I forgot to do this, and it took me a while to figure out
            // why the test was passing before I'd even set up the mockserver - which was pretty cool, tbh
            frame.source_url = Some(server.url(CHUNK_PATH).to_string());
        }

        test_stack.pop().unwrap()
    }

    fn get_sourcemapcache_bytes() -> Vec<u8> {
        let mut result = Vec::new();
        let writer = SourceMapCacheWriter::new(
            core::str::from_utf8(MINIFIED).unwrap(),
            core::str::from_utf8(MAP).unwrap(),
        )
        .unwrap();

        writer.serialize(&mut result).unwrap();
        result
    }

    fn expect_puts_and_gets(
        config: &Config,
        mut client: MockS3Client,
        puts: usize,
        gets: usize,
    ) -> MockS3Client {
        client
            .expect_put()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
                predicate::always(), // We don't assert on what we store, because who cares
            )
            .returning(|_, _, _| Ok(()))
            .times(puts);

        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
            )
            .returning(|_, _| Ok(Some(get_sourcemapcache_bytes())))
            .times(gets);

        client
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    pub async fn happy_path_test(pool: PgPool) {
        // We assert here that s3 receives 1 put and no gets, because we're only resolving
        // one frame, twice. Note that we're not using a caching symbol set provider, so if
        // the frame is resolved twice, unless the resolver is doing the right thing and fetching the stored
        // result from PG, it would have to fetch the sourcemap twice to resolve the frame
        let (config, catalog, server) =
            setup_test_context(pool.clone(), |c, cl| expect_puts_and_gets(c, cl, 1, 0)).await;
        let resolver = LocalSymbolResolver::new(&config, Arc::new(catalog), pool.clone());
        let frame = get_test_frame(&server);
        let resolved_1 = resolver.resolve_raw_frame(0, &frame).await.unwrap();

        // Check there's only 1 symbol set row, and only one frame row
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM posthog_errortrackingsymbolset")
            .fetch_one(&pool)
            .await
            .unwrap();
        assert_eq!(count, 1);

        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM posthog_errortrackingstackframe")
            .fetch_one(&pool)
            .await
            .unwrap();
        assert_eq!(count, 1);

        // get the symbol set
        let set_ref = frame.symbol_set_ref();
        let set = SymbolSetRecord::load(&pool, 0, &set_ref.unwrap())
            .await
            .unwrap()
            .unwrap();

        // get the frame
        let frame_id = frame.raw_id(0);
        let frame =
            ErrorTrackingStackFrame::load_all(&pool, &frame_id, chrono::Duration::minutes(30))
                .await
                .unwrap()
                .pop()
                .unwrap();

        assert_eq!(frame.symbol_set_id.unwrap(), set.id);

        // Re-do the resolution, which will then hit the in-memory frame cache
        let frame = get_test_frame(&server);
        let resolved_2 = resolver.resolve_raw_frame(0, &frame).await.unwrap();

        resolver.cache.invalidate_all();
        resolver.cache.run_pending_tasks().await;
        assert_eq!(resolver.cache.entry_count(), 0);

        // Now we should hit PG for the frame
        let frame = get_test_frame(&server);
        let resolved_3 = resolver.resolve_raw_frame(0, &frame).await.unwrap();

        assert_eq!(resolved_1, resolved_2);
        assert_eq!(resolved_2, resolved_3);
    }
}
