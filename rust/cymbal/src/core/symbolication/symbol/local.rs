use std::{
    sync::Arc,
    time::{Duration, Instant},
};

use async_trait::async_trait;

use common_types::error_tracking::RawFrameId;
use moka::{
    future::{Cache, CacheBuilder},
    Expiry,
};

use sqlx::PgPool;

use crate::{
    core::config::ResolverConfig,
    error::{JsResolveErr, ProguardError, ResolveError, UnhandledError},
    frames::{releases::ReleaseRecord, Frame, RawFrame},
    langs::native::DebugImage,
    metric_consts::{
        FRAME_CACHE_HITS, FRAME_CACHE_MISSES, FRAME_DB_HITS, FRAME_DB_MISSES,
        RELEASE_ID_CACHE_HITS, RELEASE_ID_CACHE_MISSES, SUSPICIOUS_FRAMES_DETECTED,
    },
    symbolication::resolve::Resolve,
    symbolication::symbol::records::{ErrorTrackingStackFrame, FrameResultTtlPolicy},
    symbolication::symbol::SymbolResolver,
    symbolication::symbol_store::{
        chunk_id::OrChunkId,
        dart_minified_names::lookup_minified_type,
        proguard::{FetchedMapping, ProguardRef},
        saving::{truncate_ref, SymbolSetRecord},
        Catalog,
    },
    types::operator::TeamId,
};
use uuid::Uuid;

const FRAME_EXPIRY_FALLBACK_SECONDS: u64 = 300;

#[derive(Clone)]
pub struct LocalSymbolResolver {
    catalog: Arc<Catalog>,
    cache: Cache<RawFrameId, Vec<ErrorTrackingStackFrame>>,
    // (team_id, sorted truncated refs) -> latest release id, including None results. Without
    // this, every exception with symbol-set refs costs one Postgres query per resolve, even
    // when frame resolution itself is fully served from the frame cache above. Refs are
    // event-controlled, so the cache is byte-weighted rather than entry-counted, like the
    // negative cache in the Saving layer.
    release_id_cache: Cache<(TeamId, Vec<String>), Option<Uuid>>,
    pool: PgPool,
    ttl_policy: FrameResultTtlPolicy,
    // Lines of pre/post source context to attach per resolved frame.
    context_lines: usize,
}

impl Expiry<RawFrameId, Vec<ErrorTrackingStackFrame>> for FrameResultTtlPolicy {
    fn expire_after_create(
        &self,
        key: &RawFrameId,
        value: &Vec<ErrorTrackingStackFrame>,
        _created_at: Instant,
    ) -> Option<Duration> {
        Some(expiration_duration(self, key, value))
    }

    fn expire_after_update(
        &self,
        key: &RawFrameId,
        value: &Vec<ErrorTrackingStackFrame>,
        _updated_at: Instant,
        _duration_until_expiry: Option<Duration>,
    ) -> Option<Duration> {
        Some(expiration_duration(self, key, value))
    }
}

fn expiration_duration(
    policy: &FrameResultTtlPolicy,
    key: &RawFrameId,
    value: &[ErrorTrackingStackFrame],
) -> Duration {
    policy
        .ttl_for_records(key, value)
        .to_std()
        .unwrap_or_else(|err| {
            tracing::warn!(error = %err, "invalid frame cache ttl, using fallback");
            Duration::from_secs(FRAME_EXPIRY_FALLBACK_SECONDS)
        })
}

impl LocalSymbolResolver {
    pub fn new(config: &ResolverConfig, catalog: Arc<Catalog>, pool: PgPool) -> Self {
        let ttl_policy = FrameResultTtlPolicy::new(
            chrono::Duration::seconds(config.frame_resolved_ttl_seconds as i64),
            chrono::Duration::seconds(config.frame_unresolved_ttl_seconds as i64),
        );
        let cache = CacheBuilder::new(config.frame_cache_size)
            .expire_after(ttl_policy)
            .build();

        let release_id_cache = CacheBuilder::new(config.release_id_cache_max_bytes)
            .weigher(|(_, refs): &(TeamId, Vec<String>), _: &Option<Uuid>| {
                // Bound by the bytes actually held; saturate rather than wrap for huge keys.
                refs.iter()
                    .map(String::len)
                    .sum::<usize>()
                    .try_into()
                    .unwrap_or(u32::MAX)
            })
            .time_to_live(Duration::from_secs(config.release_id_cache_ttl_seconds))
            .build();

        Self {
            catalog,
            pool,
            cache,
            release_id_cache,
            ttl_policy,
            context_lines: config.context_line_count,
        }
    }

    pub async fn resolve(
        &self,
        team_id: i32,
        frame: &RawFrame,
        debug_images: &[DebugImage],
    ) -> Result<Vec<Frame>, UnhandledError> {
        if frame.is_suspicious() {
            metrics::counter!(SUSPICIOUS_FRAMES_DETECTED, "frame_type" => "raw").increment(1);
        }
        let raw_id = frame.raw_id(team_id, debug_images);
        let mut cache_miss = false;
        let frames = self
            .cache
            .try_get_with(raw_id.clone(), async {
                cache_miss = true;
                self.resolve_impl(frame, raw_id.clone(), debug_images).await
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
        debug_images: &[DebugImage],
    ) -> Result<Vec<ErrorTrackingStackFrame>, UnhandledError> {
        let loaded =
            ErrorTrackingStackFrame::load_all(&self.pool, &raw_id, self.ttl_policy).await?;
        if !loaded.is_empty() {
            metrics::counter!(FRAME_DB_HITS).increment(1);
            return Ok(loaded);
        }

        metrics::counter!(FRAME_DB_MISSES).increment(1);

        let resolved = frame
            .resolve(
                raw_id.team_id,
                &self.catalog,
                debug_images,
                self.context_lines,
            )
            .await?;

        assert!(!resolved.is_empty()); // If this ever happens, we've got a data-dropping bug, and want to crash

        let set = if let Some(set_ref) = frame.symbol_set_ref(debug_images) {
            let mut set = SymbolSetRecord::load(&self.pool, raw_id.team_id, &set_ref).await?;
            if let Some(s) = &mut set {
                s.set_last_used(&self.pool).await?;
            }
            set
        } else {
            None
        };

        let mut records = Vec::new();
        for r_frame in &resolved {
            // Save back to the DB
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
        debug_images: &[DebugImage],
    ) -> Result<Vec<Frame>, UnhandledError> {
        self.resolve(team_id, frame, debug_images).await
    }

    async fn resolve_java_class(
        &self,
        team_id: TeamId,
        symbolset_ref: OrChunkId<ProguardRef>,
        class: String,
    ) -> Result<String, ResolveError> {
        let map: Arc<FetchedMapping> = self.catalog.pg.lookup(team_id, symbolset_ref).await?;
        let result = map
            .remap_class(class.as_str())?
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

    async fn latest_release_id(
        &self,
        team_id: TeamId,
        symbol_set_refs: &[String],
    ) -> Result<Option<Uuid>, UnhandledError> {
        if symbol_set_refs.is_empty() {
            return Ok(None);
        }

        // Truncated to the ref size the DB matches on, which caps what an event-controlled
        // ref can pin in the cache key. Sorted so frame-order variations of the same stack
        // share a cache entry, and deduped because truncation can collapse distinct refs.
        let mut refs: Vec<String> = symbol_set_refs
            .iter()
            .map(|r| truncate_ref(r).to_string())
            .collect();
        refs.sort_unstable();
        refs.dedup();

        let mut cache_miss = false;
        let release_id = self
            .release_id_cache
            .try_get_with((team_id, refs.clone()), async {
                cache_miss = true;
                ReleaseRecord::latest_id_for_symbol_set_refs(&self.pool, &refs, team_id).await
            })
            .await
            .map_err(|e| UnhandledError::Other(e.to_string()))?;

        if cache_miss {
            metrics::counter!(RELEASE_ID_CACHE_MISSES).increment(1);
        } else {
            metrics::counter!(RELEASE_ID_CACHE_HITS).increment(1);
        }

        Ok(release_id)
    }
}

#[cfg(test)]
mod test {

    use std::sync::Arc;

    use bytes::Bytes;
    use common_types::ClickHouseEvent;
    use httpmock::MockServer;
    use mockall::predicate;
    use sqlx::PgPool;
    use symbolic::sourcemapcache::SourceMapCacheWriter;
    use uuid::Uuid;

    use crate::{
        core::config::ResolverConfig,
        core::types::Stacktrace,
        frames::RawFrame,
        symbolication::symbol::records::ErrorTrackingStackFrame,
        symbolication::symbol::{local::LocalSymbolResolver, SymbolResolver},
        symbolication::symbol_store::{
            apple::AppleProvider,
            chunk_id::ChunkIdFetcher,
            hermesmap::HermesMapProvider,
            native::NativeProvider,
            proguard::ProguardProvider,
            saving::{truncate_ref, Saving, SymbolSetRecord, MAX_REF_BYTES},
            sourcemap::SourcemapProvider,
            Catalog, MockS3Client,
        },
        types::RawExceptionProperties,
    };

    const CHUNK_PATH: &str = "/static/chunk-PGUQKT6S.js";
    const MINIFIED: &[u8] = include_bytes!("../../../../tests/static/chunk-PGUQKT6S.js");
    const MAP: &[u8] = include_bytes!("../../../../tests/static/chunk-PGUQKT6S.js.map");
    const EXAMPLE_EXCEPTION: &str =
        include_str!("../../../../tests/static/raw_ch_exception_list.json");

    async fn setup_test_context<S>(
        pool: PgPool,
        s3_init: S,
    ) -> (ResolverConfig, Catalog, MockServer)
    where
        S: FnOnce(&ResolverConfig, MockS3Client) -> MockS3Client,
    {
        let mut config = ResolverConfig::init_with_defaults().unwrap();
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
            std::time::Duration::from_secs(config.symbol_set_negative_cache_ttl_seconds),
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

        let apple = ChunkIdFetcher::new(
            AppleProvider {},
            client.clone(),
            pool.clone(),
            config.object_storage_bucket.clone(),
        );

        let native = ChunkIdFetcher::new(
            NativeProvider {},
            client.clone(),
            pool.clone(),
            config.object_storage_bucket.clone(),
        );

        let catalog = Catalog::new(saving_smp, hmp, pgp, apple, native);

        (config, catalog, server)
    }

    fn get_test_frame(server: &MockServer) -> RawFrame {
        let exception: ClickHouseEvent = serde_json::from_str(EXAMPLE_EXCEPTION).unwrap();
        let mut props: RawExceptionProperties =
            serde_json::from_str(&exception.properties.unwrap()).unwrap();
        let Stacktrace::Raw {
            frames: mut test_stack,
        } = props.exception_list.swap_remove(0).stack.unwrap()
        else {
            panic!("Expected a Raw stacktrace")
        };

        // We're going to pretend our stack consists exclusively of JS frames whose source
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
        config: &ResolverConfig,
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
            .returning(|_, _| Ok(Some(Bytes::from(get_sourcemapcache_bytes()))))
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
        let resolved_1 = resolver.resolve_raw_frame(0, &frame, &[]).await.unwrap();

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

        // get the symbol set (JS frame: debug images are irrelevant)
        let set_ref = frame.symbol_set_ref(&[]);
        let set = SymbolSetRecord::load(&pool, 0, &set_ref.unwrap())
            .await
            .unwrap()
            .unwrap();

        // get the frame
        let frame_id = frame.raw_id(0, &[]);
        let frame = ErrorTrackingStackFrame::load_all(&pool, &frame_id, resolver.ttl_policy)
            .await
            .unwrap()
            .pop()
            .unwrap();

        assert_eq!(frame.symbol_set_id.unwrap(), set.id);

        // Re-do the resolution, which will then hit the in-memory frame cache
        let frame = get_test_frame(&server);
        let resolved_2 = resolver.resolve_raw_frame(0, &frame, &[]).await.unwrap();

        resolver.cache.invalidate_all();
        resolver.cache.run_pending_tasks().await;
        assert_eq!(resolver.cache.entry_count(), 0);

        // Now we should hit PG for the frame
        let frame = get_test_frame(&server);
        let resolved_3 = resolver.resolve_raw_frame(0, &frame, &[]).await.unwrap();

        assert_eq!(resolved_1, resolved_2);
        assert_eq!(resolved_2, resolved_3);
    }

    async fn insert_release(pool: &PgPool, team_id: i32, days_ago: i32) -> Uuid {
        let id = Uuid::new_v4();
        sqlx::query(
            "INSERT INTO posthog_errortrackingrelease (id, team_id, hash_id, created_at, version, project)
             VALUES ($1, $2, $3, NOW() - make_interval(days => $4), '1.0', 'test-project')",
        )
        .bind(id)
        .bind(team_id)
        .bind(id.to_string())
        .bind(days_ago)
        .execute(pool)
        .await
        .unwrap();
        id
    }

    async fn bind_symbol_set(pool: &PgPool, team_id: i32, set_ref: &str, release_id: Uuid) {
        sqlx::query(
            "INSERT INTO posthog_errortrackingsymbolset (id, ref, team_id, release_id)
             VALUES ($1, $2, $3, $4)",
        )
        .bind(Uuid::new_v4())
        .bind(set_ref)
        .bind(team_id)
        .bind(release_id)
        .execute(pool)
        .await
        .unwrap();
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    pub async fn latest_release_id_is_cached_and_ref_order_insensitive(pool: PgPool) {
        let (config, catalog, _server) = setup_test_context(pool.clone(), |_, client| client).await;
        let resolver = LocalSymbolResolver::new(&config, Arc::new(catalog), pool.clone());

        let team_id = 0;
        let old_release = insert_release(&pool, team_id, 1).await;
        bind_symbol_set(&pool, team_id, "ref_a", old_release).await;

        let first = resolver
            .latest_release_id(team_id, &["ref_b".to_string(), "ref_a".to_string()])
            .await
            .unwrap();
        assert_eq!(first, Some(old_release));

        // A fresh query would now return the newer release, so getting the old id back for the
        // reordered refs proves the lookup was served from the cache under a normalized key.
        let new_release = insert_release(&pool, team_id, 0).await;
        bind_symbol_set(&pool, team_id, "ref_b", new_release).await;

        let second = resolver
            .latest_release_id(team_id, &["ref_a".to_string(), "ref_b".to_string()])
            .await
            .unwrap();
        assert_eq!(second, Some(old_release));
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    pub async fn latest_release_id_cache_key_uses_truncated_refs(pool: PgPool) {
        let (config, catalog, _server) = setup_test_context(pool.clone(), |_, client| client).await;
        let resolver = LocalSymbolResolver::new(&config, Arc::new(catalog), pool.clone());

        let team_id = 0;
        // Two refs the DB treats as the same symbol set: identical up to the stored ref
        // size, differing only past it.
        let prefix = "a".repeat(MAX_REF_BYTES);
        let ref_one = format!("{prefix}_tail_one");
        let ref_two = format!("{prefix}_tail_two");

        let old_release = insert_release(&pool, team_id, 1).await;
        bind_symbol_set(&pool, team_id, truncate_ref(&ref_one), old_release).await;

        let first = resolver
            .latest_release_id(team_id, &[ref_one])
            .await
            .unwrap();
        assert_eq!(first, Some(old_release));

        // Rebind the set so a fresh query would return the newer release; getting the old id
        // back for a ref with a different over-length tail proves both refs normalize to the
        // same truncated cache key.
        let new_release = insert_release(&pool, team_id, 0).await;
        sqlx::query("UPDATE posthog_errortrackingsymbolset SET release_id = $1 WHERE team_id = $2")
            .bind(new_release)
            .bind(team_id)
            .execute(&pool)
            .await
            .unwrap();

        let second = resolver
            .latest_release_id(team_id, &[ref_two])
            .await
            .unwrap();
        assert_eq!(second, Some(old_release));
    }
}
