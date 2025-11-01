use common_cache::CacheSource;
use common_metrics::inc;

/// Generic cache metrics tracker that works with any cache type
///
/// Tracks cache hits, misses, database reads, and cache errors based on the CacheSource
/// returned by ReadThroughCache operations.
pub fn track_cache_metrics(
    source: CacheSource,
    cache_hit_counter: &'static str,
    db_reads_counter: &'static str,
    cache_errors_counter: &'static str,
) {
    match source {
        CacheSource::PositiveCache => {
            inc(
                cache_hit_counter,
                &[
                    ("cache_hit".to_string(), "true".to_string()),
                    ("result_type".to_string(), "positive".to_string()),
                ],
                1,
            );
        }
        CacheSource::NegativeCache => {
            inc(
                cache_hit_counter,
                &[
                    ("cache_hit".to_string(), "true".to_string()),
                    ("result_type".to_string(), "negative".to_string()),
                ],
                1,
            );
        }
        CacheSource::LoaderCacheMiss
        | CacheSource::LoaderCacheCorrupted
        | CacheSource::LoaderRedisUnavailable
        | CacheSource::LoaderNotFoundCacheMiss
        | CacheSource::LoaderNotFoundCacheCorrupted
        | CacheSource::LoaderNotFoundRedisUnavailable => {
            // Cache miss
            inc(
                cache_hit_counter,
                &[("cache_hit".to_string(), "false".to_string())],
                1,
            );

            // Track database reads
            inc(db_reads_counter, &[], 1);

            // Track cache errors if there was a problem
            if matches!(
                source,
                CacheSource::LoaderCacheCorrupted
                    | CacheSource::LoaderRedisUnavailable
                    | CacheSource::LoaderNotFoundCacheCorrupted
                    | CacheSource::LoaderNotFoundRedisUnavailable
            ) {
                inc(cache_errors_counter, &[], 1);
            }
        }
    }
}
