use std::sync::Arc;

use axum::async_trait;
use chrono::Duration;
use common_types::error_tracking::RawFrameId;
use moka::future::Cache;
use reqwest::Url;
use sqlx::PgPool;

use crate::{
    error::{ProguardError, ResolveError, UnhandledError},
    frames::{records::ErrorTrackingStackFrame, releases::ReleaseRecord, Frame, RawFrame},
    metric_consts::{
        FRAME_CACHE_HITS, FRAME_CACHE_MISSES, FRAME_DB_HITS, FRAME_DB_MISSES,
        JAVA_EXCEPTION_REMAP_FAILED, SUSPICIOUS_FRAMES_DETECTED,
    },
    stages::resolution::{exception::ResolveExceptionError, symbol::SymbolResolver},
    symbol_store::{
        chunk_id::OrChunkId, dart_minified_names::lookup_minified_type, proguard::FetchedMapping,
        saving::SymbolSetRecord, Catalog, SymbolCatalog,
    },
    types::{operator::TeamId, Exception},
};

#[derive(Clone)]
pub struct LocalSymbolResolver {
    catalog: Arc<Catalog>,
    cache: Cache<RawFrameId, Vec<ErrorTrackingStackFrame>>,
    pool: PgPool,
    result_ttl: Duration,
}

impl LocalSymbolResolver {
    pub fn new(
        catalog: Arc<Catalog>,
        pool: PgPool,
        cache: Cache<RawFrameId, Vec<ErrorTrackingStackFrame>>,
        result_ttl: Duration,
    ) -> Self {
        Self {
            catalog,
            pool,
            cache,
            result_ttl,
        }
    }
}

impl LocalSymbolResolver {
    pub async fn resolve(
        &self,
        team_id: i32,
        frame: &RawFrame,
    ) -> Result<Vec<Frame>, Arc<UnhandledError>> {
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
            .await?;

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
    ) -> Result<Vec<Frame>, ResolveError> {
        self.resolve(team_id, frame)
            .await
            .map_err(|e| UnhandledError::Other(e.to_string()).into())
    }

    async fn resolve_java_exception(
        &self,
        team_id: TeamId,
        mut exception: Exception,
    ) -> Result<Exception, ResolveError> {
        let module = exception.module.clone().ok_or_else(|| {
            metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => "module_not_found")
                .increment(1);
            ProguardError::NoModuleProvided
        })?;

        let exception_type = exception.exception_type.clone();
        let symbol_ref = exception.first_ref();
        let class = format!("{module}.{exception_type}");
        let catalog = self.catalog.clone();
        let map: Arc<FetchedMapping> = catalog
            .lookup(team_id, symbol_ref.clone())
            .await
            .inspect_err(|e| {
                metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => "lookup_error")
                    .increment(1)
            })
            .map_err(|e| UnhandledError::Other(e.to_string()))?;

        let mapper = map.get_mapper();
        if let Some(remapped_class) = mapper.remap_class(class.as_str()) {
            match split_last_dot(&remapped_class) {
                Ok((remapped_module, remapped_type)) => {
                    exception.module = Some(remapped_module.to_string());
                    exception.exception_type = remapped_type.to_string();
                }
                Err(_) => {
                    metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => "invalid_format")
                        .increment(1);
                }
            }
        } else {
            metrics::counter!(JAVA_EXCEPTION_REMAP_FAILED, "reason" => "class_not_found")
                .increment(1)
        }
        Ok(exception)
    }

    async fn resolve_dart_exception(
        &self,
        team_id: TeamId,
        mut exception: Exception,
    ) -> Result<Exception, ResolveError> {
        let symbol_ref = exception.first_ref();
        if let Some(sourcemap) = self.catalog.smp.lookup(team_id, symbol_ref).await.ok() {
            if let Some(minified_names) = sourcemap.get_dart_minified_names() {
                if let Some(resolved_type) =
                    lookup_minified_type(minified_names, exception.exception_type.as_str())
                {
                    exception.exception_type = resolved_type;
                }
            }
        }
        Ok(exception)
    }
}

fn split_last_dot(s: &str) -> Result<(String, String), ResolveExceptionError> {
    let mut parts = s.rsplitn(2, '.');
    let last = parts.next().unwrap();
    let before = parts.next().ok_or(ResolveExceptionError::InvalidFormat(
        "Could not split remapped module and type".to_string(),
    ))?;
    Ok((before.to_string(), last.to_string()))
}
