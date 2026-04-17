use std::sync::Arc;
use std::time::Duration;

use common_hypercache::CacheSource;
use common_metrics::{gauge, histogram, inc};
use common_types::TeamId;
use moka::future::Cache;
use sha2::{Digest, Sha256};

use crate::api::errors::FlagError;
use crate::flags::flag_models::{FeatureFlagList, HypercacheFlagsWrapper, PreparedFlagDefinitions};
use crate::metrics::consts::{
    FLAG_DEFINITIONS_HASH_DURATION_US, FLAG_DEFINITIONS_INMEM_CACHE_ENTRIES_GAUGE,
    FLAG_DEFINITIONS_INMEM_CACHE_HIT_COUNTER, FLAG_DEFINITIONS_INMEM_CACHE_MISS_COUNTER,
    FLAG_DEFINITIONS_INMEM_CACHE_SIZE_BYTES_GAUGE,
};

/// In-memory cache for regex-compiled flag definitions.
///
/// Sits between the HyperCache typed reader (which returns `Option<HypercacheFlagsWrapper>`)
/// and the evaluation pipeline. Caches the validated wrapper with pre-compiled regexes
/// so that identical data for the same team returns a cheap `Arc` clone instead of
/// re-validating and re-compiling regexes on every request.
///
/// Cache key: `(team_id, sha256_of_wrapper_json)` — the content hash ensures correctness
/// when flag definitions change between Django cache refreshes.
pub struct FlagDefinitionsCache {
    cache: Cache<(TeamId, [u8; 32]), Arc<PreparedFlagDefinitions>>,
}

impl FlagDefinitionsCache {
    const DEFAULT_CAPACITY_BYTES: u64 = 134_217_728; // 128 MB
    const DEFAULT_TTL_SECONDS: u64 = 90;

    pub fn new(capacity_bytes: Option<u64>, ttl_seconds: Option<u64>) -> Self {
        let weigher = |_key: &(TeamId, [u8; 32]), value: &Arc<PreparedFlagDefinitions>| -> u32 {
            u32::try_from(value.estimated_size_bytes()).unwrap_or(u32::MAX)
        };

        let cache = Cache::builder()
            .time_to_live(Duration::from_secs(
                ttl_seconds.unwrap_or(Self::DEFAULT_TTL_SECONDS),
            ))
            .weigher(weigher)
            .max_capacity(capacity_bytes.unwrap_or(Self::DEFAULT_CAPACITY_BYTES))
            .build();

        Self { cache }
    }

    /// Creates a cache that always misses. Useful for tests that don't exercise caching.
    pub fn disabled() -> Self {
        let cache = Cache::builder().max_capacity(0).build();
        Self { cache }
    }

    /// Returns cached `PreparedFlagDefinitions` or validates + compiles from the
    /// already-deserialized `HypercacheFlagsWrapper` on cache miss.
    ///
    /// - `None` wrapper (sentinel `__missing__`) returns empty definitions.
    /// - PG fallback data (`CacheSource::Fallback`) bypasses the cache (transient data).
    /// - Uses moka's `try_get_with` for per-key coalescing: concurrent requests for the
    ///   same `(team_id, hash)` block on the first one and share the result.
    pub async fn get_or_prepare(
        &self,
        team_id: TeamId,
        wrapper: Option<HypercacheFlagsWrapper>,
        cache_source: &CacheSource,
    ) -> Result<Arc<PreparedFlagDefinitions>, FlagError> {
        // None (sentinel __missing__) → empty definitions, no caching needed
        let wrapper = match wrapper {
            None => {
                return Ok(Arc::new(PreparedFlagDefinitions {
                    flags: vec![],
                    evaluation_metadata: Default::default(),
                    cohorts: None,
                }));
            }
            Some(w) => w,
        };

        // PG fallback data is transient — validate + compile directly without caching
        if matches!(cache_source, CacheSource::Fallback) {
            return Self::validate_and_prepare(team_id, wrapper);
        }

        // Compute content hash for cache key.
        // We serialize the wrapper to JSON bytes for hashing — this is much cheaper
        // than the regex compilation it amortizes across requests.
        let hash_start = std::time::Instant::now();
        let json_bytes = serde_json::to_vec(&wrapper).map_err(|e| {
            FlagError::Internal(format!("Failed to serialize wrapper for hashing: {e}"))
        })?;
        let hash: [u8; 32] = Sha256::digest(&json_bytes).into();
        histogram(
            FLAG_DEFINITIONS_HASH_DURATION_US,
            &[],
            hash_start.elapsed().as_micros() as f64,
        );

        let cache_key = (team_id, hash);

        // Fast path: check cache without coalescing overhead
        if let Some(cached) = self.cache.get(&cache_key).await {
            inc(FLAG_DEFINITIONS_INMEM_CACHE_HIT_COUNTER, &[], 1);
            return Ok(cached);
        }

        inc(FLAG_DEFINITIONS_INMEM_CACHE_MISS_COUNTER, &[], 1);

        // Slow path: validate + compile, with per-key coalescing.
        // We convert FlagError to String for moka's Arc<E> requirement since
        // FlagError doesn't implement Clone.
        let result = self
            .cache
            .try_get_with(cache_key, async move {
                Self::validate_and_prepare(team_id, wrapper).map_err(|e| e.to_string())
            })
            .await
            .map_err(|arc_err| FlagError::Internal((*arc_err).clone()))?;

        self.report_cache_metrics();

        Ok(result)
    }

    /// Validates the wrapper and pre-compiles all regex patterns.
    fn validate_and_prepare(
        team_id: TeamId,
        wrapper: HypercacheFlagsWrapper,
    ) -> Result<Arc<PreparedFlagDefinitions>, FlagError> {
        let (flags, evaluation_metadata, cohorts) =
            FeatureFlagList::from_wrapper(Some(wrapper), team_id)?;

        let mut flag_list = FeatureFlagList::new(flags);
        flag_list.prepare_regexes();

        Ok(Arc::new(PreparedFlagDefinitions {
            flags: flag_list.flags,
            evaluation_metadata,
            cohorts,
        }))
    }

    /// Starts periodic monitoring of cache metrics.
    pub async fn start_monitoring(&self, interval_secs: u64) {
        let mut ticker = tokio::time::interval(Duration::from_secs(interval_secs));

        tracing::info!(
            "Starting flag definitions cache monitoring (interval: {}s)",
            interval_secs
        );

        loop {
            ticker.tick().await;
            self.report_cache_metrics();
        }
    }

    fn report_cache_metrics(&self) {
        gauge(
            FLAG_DEFINITIONS_INMEM_CACHE_SIZE_BYTES_GAUGE,
            &[],
            self.cache.weighted_size() as f64,
        );
        gauge(
            FLAG_DEFINITIONS_INMEM_CACHE_ENTRIES_GAUGE,
            &[],
            self.cache.entry_count() as f64,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_models::{
        EvaluationMetadata, FeatureFlag, FlagFilters, FlagPropertyGroup,
    };
    use crate::properties::property_models::{OperatorType, PropertyFilter, PropertyType};
    use serde_json::json;

    fn make_test_wrapper(flags: Vec<FeatureFlag>) -> HypercacheFlagsWrapper {
        let metadata = EvaluationMetadata::single_stage(&flags);
        HypercacheFlagsWrapper {
            flags,
            evaluation_metadata: metadata,
            cohorts: None,
        }
    }

    fn make_flag_with_regex(id: i32, pattern: &str) -> FeatureFlag {
        FeatureFlag {
            id,
            team_id: 1,
            name: Some(format!("Flag {id}")),
            key: format!("flag_{id}"),
            filters: FlagFilters {
                groups: vec![FlagPropertyGroup {
                    properties: Some(vec![PropertyFilter {
                        key: "email".to_string(),
                        value: Some(json!(pattern)),
                        operator: Some(OperatorType::Regex),
                        prop_type: PropertyType::Person,
                        ..Default::default()
                    }]),
                    rollout_percentage: Some(100.0),
                    ..Default::default()
                }],
                ..Default::default()
            },
            active: true,
            ..Default::default()
        }
    }

    #[tokio::test]
    async fn test_cache_hit_returns_same_arc() {
        let cache = FlagDefinitionsCache::new(None, None);
        let wrapper = make_test_wrapper(vec![make_flag_with_regex(1, r"^test@.*\.com$")]);

        let first = cache
            .get_or_prepare(1, Some(wrapper.clone()), &CacheSource::Redis)
            .await
            .unwrap();
        let second = cache
            .get_or_prepare(1, Some(wrapper), &CacheSource::Redis)
            .await
            .unwrap();

        // Same Arc pointer — no re-compilation
        assert!(Arc::ptr_eq(&first, &second));
        assert_eq!(first.flags.len(), 1);
        // Regexes should be compiled
        assert!(first.flags[0].filters.groups[0]
            .properties
            .as_ref()
            .unwrap()[0]
            .compiled_regex
            .is_some());
    }

    #[tokio::test]
    async fn test_different_data_produces_different_entries() {
        let cache = FlagDefinitionsCache::new(None, None);

        let w1 = make_test_wrapper(vec![make_flag_with_regex(1, r"^v1@.*\.com$")]);
        let w2 = make_test_wrapper(vec![make_flag_with_regex(1, r"^v2@.*\.com$")]);

        let v1 = cache
            .get_or_prepare(1, Some(w1), &CacheSource::Redis)
            .await
            .unwrap();
        let v2 = cache
            .get_or_prepare(1, Some(w2), &CacheSource::Redis)
            .await
            .unwrap();

        assert!(!Arc::ptr_eq(&v1, &v2));
    }

    #[tokio::test]
    async fn test_pg_fallback_bypasses_cache() {
        let cache = FlagDefinitionsCache::new(None, None);
        let wrapper = make_test_wrapper(vec![make_flag_with_regex(1, r"^test@.*\.com$")]);

        let first = cache
            .get_or_prepare(1, Some(wrapper.clone()), &CacheSource::Fallback)
            .await
            .unwrap();
        let second = cache
            .get_or_prepare(1, Some(wrapper), &CacheSource::Fallback)
            .await
            .unwrap();

        // Different Arc pointers — not cached
        assert!(!Arc::ptr_eq(&first, &second));
    }

    #[tokio::test]
    async fn test_none_returns_empty() {
        let cache = FlagDefinitionsCache::new(None, None);
        let result = cache
            .get_or_prepare(1, None, &CacheSource::Redis)
            .await
            .unwrap();
        assert!(result.flags.is_empty());
    }

    #[tokio::test]
    async fn test_disabled_cache_always_misses() {
        let cache = FlagDefinitionsCache::disabled();
        let wrapper = make_test_wrapper(vec![make_flag_with_regex(1, r"^test@.*\.com$")]);

        let first = cache
            .get_or_prepare(1, Some(wrapper.clone()), &CacheSource::Redis)
            .await
            .unwrap();
        let second = cache
            .get_or_prepare(1, Some(wrapper), &CacheSource::Redis)
            .await
            .unwrap();

        // Disabled cache should not return the same Arc
        assert!(!Arc::ptr_eq(&first, &second));
    }

    #[tokio::test]
    async fn test_regexes_are_precompiled_in_cached_value() {
        let cache = FlagDefinitionsCache::new(None, None);
        let wrapper = make_test_wrapper(vec![
            make_flag_with_regex(1, r"^user@.*\.com$"),
            make_flag_with_regex(2, r"[invalid"),
        ]);

        let result = cache
            .get_or_prepare(1, Some(wrapper), &CacheSource::Redis)
            .await
            .unwrap();

        // Valid regex should be compiled
        let regex_1 = &result.flags[0].filters.groups[0]
            .properties
            .as_ref()
            .unwrap()[0]
            .compiled_regex;
        assert!(matches!(
            regex_1,
            Some(crate::properties::property_models::CompiledRegex::Compiled(
                _
            ))
        ));

        // Invalid regex should be marked as InvalidPattern
        let regex_2 = &result.flags[1].filters.groups[0]
            .properties
            .as_ref()
            .unwrap()[0]
            .compiled_regex;
        assert!(matches!(
            regex_2,
            Some(crate::properties::property_models::CompiledRegex::InvalidPattern)
        ));
    }

    #[tokio::test]
    async fn test_s3_source_is_cached() {
        let cache = FlagDefinitionsCache::new(None, None);
        let wrapper = make_test_wrapper(vec![make_flag_with_regex(1, r"^test@.*\.com$")]);

        let first = cache
            .get_or_prepare(1, Some(wrapper.clone()), &CacheSource::S3)
            .await
            .unwrap();
        let second = cache
            .get_or_prepare(1, Some(wrapper), &CacheSource::S3)
            .await
            .unwrap();

        assert!(Arc::ptr_eq(&first, &second));
    }
}
