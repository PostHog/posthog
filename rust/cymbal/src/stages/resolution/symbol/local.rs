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

        let resolved = frame.resolve(raw_id.team_id, &self.catalog, &[]).await?;

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
