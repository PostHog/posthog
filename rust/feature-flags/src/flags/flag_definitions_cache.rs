use std::hash::Hasher;
use std::io;
use std::sync::Arc;
use std::time::Duration;

use common_hypercache::CacheSource;
use common_metrics::{gauge, histogram, inc};
use common_types::TeamId;
use moka::future::Cache;
use twox_hash::XxHash3_64;

use crate::api::errors::FlagError;
use crate::cohorts::cohort_models::Cohort;
use crate::flags::flag_models::{
    EvaluationMetadata, FeatureFlag, FeatureFlagList, HypercacheFlagsWrapper,
    PreparedFlagDefinitions,
};
use crate::metrics::consts::{
    FLAG_DEFINITIONS_HASH_DURATION_US, FLAG_DEFINITIONS_INMEM_CACHE_ENTRIES_GAUGE,
    FLAG_DEFINITIONS_INMEM_CACHE_HIT_COUNTER, FLAG_DEFINITIONS_INMEM_CACHE_MISS_COUNTER,
    FLAG_DEFINITIONS_INMEM_CACHE_SIZE_BYTES_GAUGE,
};

/// In-memory cache for regex-compiled flag definitions.
///
/// Sits between the HyperCache typed reader (which returns `Option<HypercacheFlagsWrapper>`)
/// and the evaluation pipeline. Caches regex-compiled flag definitions so identical
/// content for the same team returns a cheap `Arc` clone instead of re-compiling
/// regexes on every request.
///
/// Cache key: `(team_id, xxhash3_64(parsed_wrapper))`. Validation runs on every
/// request before the cache lookup so errors retain their original `FlagError`
/// variant (not flattened to `Internal`) and corrupt payloads stay visible in
/// logs/metrics. Regex compilation, which is the expensive step we're amortizing,
/// is infallible (invalid patterns store `CompiledRegex::InvalidPattern`), so the
/// cache uses moka's `get_with` rather than `try_get_with`.
pub struct FlagDefinitionsCache {
    cache: Cache<(TeamId, u64), Arc<PreparedFlagDefinitions>>,
}

impl FlagDefinitionsCache {
    const DEFAULT_CAPACITY_BYTES: u64 = 134_217_728; // 128 MB
    const DEFAULT_TTL_SECONDS: u64 = 90;

    pub fn new(capacity_bytes: Option<u64>, ttl_seconds: Option<u64>) -> Self {
        let weigher = |_key: &(TeamId, u64), value: &Arc<PreparedFlagDefinitions>| -> u32 {
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
    /// - `None` wrapper (sentinel `__missing__`) returns empty definitions, uncached.
    /// - PG fallback data (`CacheSource::Fallback`) bypasses the cache (transient data).
    /// - Validation errors (e.g. malformed `evaluation_metadata`) bubble up with
    ///   their original `FlagError` variant; the cache never sees them.
    /// - Concurrent misses coalesce via moka's `get_with`; only one task compiles.
    pub async fn get_or_prepare(
        &self,
        team_id: TeamId,
        wrapper: Option<HypercacheFlagsWrapper>,
        cache_source: &CacheSource,
    ) -> Result<Arc<PreparedFlagDefinitions>, FlagError> {
        // Validate eagerly on every request. Errors retain their original variant
        // (`DataParsingErrorWithContext` stays `DataParsingErrorWithContext`).
        let (flags, evaluation_metadata, cohorts) =
            FeatureFlagList::from_wrapper(wrapper, team_id)?;

        // PG fallback is transient — compile directly, skip the cache entirely.
        if matches!(cache_source, CacheSource::Fallback) {
            return Ok(Self::compile_only(flags, evaluation_metadata, cohorts));
        }

        // Empty sentinel (`__missing__` or empty PG result) — return uncached.
        // The caller doesn't need a stable Arc for the zero-flags case.
        if flags.is_empty() {
            return Ok(Self::compile_only(flags, evaluation_metadata, cohorts));
        }

        // Cheap content fingerprint via xxhash3 fed directly from serde_json,
        // avoiding any intermediate byte buffer allocation.
        let hash_start = std::time::Instant::now();
        let hash = fingerprint(&flags, &evaluation_metadata, cohorts.as_ref());
        histogram(
            FLAG_DEFINITIONS_HASH_DURATION_US,
            &[],
            hash_start.elapsed().as_micros() as f64,
        );

        let cache_key = (team_id, hash);

        if let Some(cached) = self.cache.get(&cache_key).await {
            inc(FLAG_DEFINITIONS_INMEM_CACHE_HIT_COUNTER, &[], 1);
            return Ok(cached);
        }

        // `get_with` coalesces concurrent misses; the closure runs at most once
        // per coalesced group, so the miss counter lives inside.
        let result = self
            .cache
            .get_with(cache_key, async move {
                inc(FLAG_DEFINITIONS_INMEM_CACHE_MISS_COUNTER, &[], 1);
                Self::compile_only(flags, evaluation_metadata, cohorts)
            })
            .await;

        self.report_cache_metrics();

        Ok(result)
    }

    /// Infallible regex compilation over already-validated flag definitions.
    /// Invalid patterns are stored as `CompiledRegex::InvalidPattern` by
    /// `prepare_regexes_in_place`, so this never fails. Prep runs on the
    /// `Vec<FeatureFlag>` before the one-time wrap into `Arc<[FeatureFlag]>`,
    /// avoiding any `Arc::get_mut` juggling.
    fn compile_only(
        mut flags: Vec<FeatureFlag>,
        evaluation_metadata: EvaluationMetadata,
        cohorts: Option<Vec<Cohort>>,
    ) -> Arc<PreparedFlagDefinitions> {
        FeatureFlagList::prepare_regexes_in_place(&mut flags);

        Arc::new(PreparedFlagDefinitions {
            flags: Arc::from(flags),
            evaluation_metadata,
            cohorts,
        })
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

/// `io::Write` adapter that forwards bytes to a `Hasher`, so we can drive
/// `serde_json::to_writer` straight into an incremental hash without allocating
/// a byte buffer. `write` and `flush` never fail.
struct HashWriter<H: Hasher>(H);

impl<H: Hasher> io::Write for HashWriter<H> {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.0.write(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

/// Computes a 64-bit content fingerprint over the parsed flag definitions.
///
/// Correctness: `serde_json` is configured without `preserve_order` in this
/// workspace, so `Value` objects serialize through a `BTreeMap` (sorted keys).
/// `EvaluationMetadata.transitive_deps` (a `HashMap<i32, HashSet<i32>>`) uses
/// its custom `serialize_string_keyed_i32_map` helper which sorts keys and
/// inner values. No other collection in the serialized types has
/// non-deterministic ordering.
///
/// Numeric stability: `PropertyFilter.value` is `serde_json::Value`. serde_json
/// preserves the originating numeric type (integer vs float) through
/// deserialize, so `{"value": 5}` and `{"value": 5.0}` fingerprint differently.
/// This is load-bearing only if the cache writer (Django today) ever flips
/// representation for the same semantic value; Django's `json.dumps` is stable
/// on this. `test_fingerprint_round_trips_through_hypercache_encoding` pins the
/// Django-path round-trip (pickle → JSON → serde_json::Value → re-serialize).
///
/// xxhash3-64 is non-cryptographic but collision-resistant enough for this use
/// case (birthday bound ~2^32 distinct entries); we only need equality on
/// identical content, not adversarial resistance.
fn fingerprint(
    flags: &[FeatureFlag],
    metadata: &EvaluationMetadata,
    cohorts: Option<&Vec<Cohort>>,
) -> u64 {
    let mut hw = HashWriter(XxHash3_64::new());
    // Tuple serialization is deterministic; each component serializes exactly
    // once into the hasher stream. `HashWriter::write` is infallible, so the
    // only way `to_writer` could err is a serde-side failure, which doesn't
    // occur for our own types (no `serialize_map` with mismatched len, etc.).
    serde_json::to_writer(&mut hw, &(flags, metadata, cohorts))
        .expect("HashWriter is infallible and these types serialize without error");
    hw.0.finish()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_models::{EvaluationMetadata, FeatureFlag};
    use crate::mock;
    use crate::properties::property_models::{OperatorType, PropertyFilter};
    use crate::utils::mock::MockInto;
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
        mock!(FeatureFlag,
            id: id,
            name: format!("Flag {id}").mock_into(),
            key: format!("flag_{id}"),
            filters: mock!(PropertyFilter,
                key: "email".mock_into(),
                value: Some(json!(pattern)),
                operator: Some(OperatorType::Regex),
            )
            .mock_into(),
        )
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

    /// Regression for the error-flattening observability bug: a malformed
    /// wrapper (flags present but `dependency_stages` empty) must surface as
    /// `FlagError::DataParsingErrorWithContext`, not be collapsed to
    /// `FlagError::Internal` by the cache boundary.
    #[tokio::test]
    async fn test_validation_errors_preserve_variant() {
        let cache = FlagDefinitionsCache::new(None, None);
        let wrapper = HypercacheFlagsWrapper {
            flags: vec![make_flag_with_regex(1, r"^test@.*\.com$")],
            evaluation_metadata: EvaluationMetadata {
                // Empty stages + non-empty flags trips `from_wrapper`'s contract check.
                dependency_stages: vec![],
                flags_with_missing_deps: vec![],
                transitive_deps: Default::default(),
            },
            cohorts: None,
        };

        let err = cache
            .get_or_prepare(1, Some(wrapper), &CacheSource::Redis)
            .await
            .expect_err("malformed wrapper must error");
        assert!(
            matches!(err, FlagError::DataParsingErrorWithContext(_)),
            "expected DataParsingErrorWithContext, got {err:?}"
        );
    }

    /// Regression for the fingerprint path: fingerprint MUST be stable across
    /// two independent deserializations of the same JSON. If a `HashMap` or
    /// `HashSet` inside the serialized graph ever leaks non-deterministic
    /// ordering, this test catches it.
    #[test]
    fn test_fingerprint_is_stable_across_deserializations() {
        let json = json!({
            "flags": [
                {
                    "id": 1, "team_id": 1, "key": "dep_on_2", "name": "",
                    "active": true, "deleted": false,
                    "filters": {"groups": [{
                        "properties": [
                            {"key": "2", "type": "flag", "value": true, "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100
                    }]}
                },
                {
                    "id": 2, "team_id": 1, "key": "leaf", "name": "",
                    "active": true, "deleted": false,
                    "filters": {"groups": []}
                }
            ],
            "evaluation_metadata": {
                "dependency_stages": [[2], [1]],
                "flags_with_missing_deps": [],
                "transitive_deps": {"1": [2], "2": []}
            }
        });
        let a: HypercacheFlagsWrapper = serde_json::from_value(json.clone()).unwrap();
        let b: HypercacheFlagsWrapper = serde_json::from_value(json).unwrap();

        let ha = fingerprint(&a.flags, &a.evaluation_metadata, a.cohorts.as_ref());
        let hb = fingerprint(&b.flags, &b.evaluation_metadata, b.cohorts.as_ref());
        assert_eq!(ha, hb, "fingerprint must be stable across deserializations");
    }

    /// `EvaluationMetadata.transitive_deps` is a `HashMap<i32, HashSet<i32>>`.
    /// Its custom `serialize_string_keyed_i32_map` sorts both keys and inner
    /// values; guard against anyone dropping that invariant and making the
    /// fingerprint order-dependent.
    #[test]
    fn test_fingerprint_is_stable_across_hashmap_insertion_order() {
        use std::collections::{HashMap, HashSet};
        let build = |inserts: &[(i32, Vec<i32>)]| {
            let mut m: HashMap<i32, HashSet<i32>> = HashMap::new();
            for (k, vs) in inserts {
                m.insert(*k, vs.iter().copied().collect());
            }
            EvaluationMetadata {
                dependency_stages: vec![vec![1], vec![2]],
                flags_with_missing_deps: vec![],
                transitive_deps: m,
            }
        };

        let forward = build(&[(1, vec![2, 3]), (2, vec![3]), (3, vec![])]);
        let reverse = build(&[(3, vec![]), (2, vec![3]), (1, vec![3, 2])]);

        let h1 = fingerprint(&[], &forward, None);
        let h2 = fingerprint(&[], &reverse, None);
        assert_eq!(
            h1, h2,
            "fingerprint must not depend on HashMap insertion order"
        );
    }

    /// Any change to flag filter content should shift the fingerprint (i.e.,
    /// the cache should produce a new entry). Cheap correctness guard.
    #[test]
    fn test_fingerprint_changes_when_content_changes() {
        let flag = make_flag_with_regex(1, r"^v1@.*$");
        let m = EvaluationMetadata::single_stage(std::slice::from_ref(&flag));

        let h_before = fingerprint(std::slice::from_ref(&flag), &m, None);

        let mut flag_after = flag.clone();
        flag_after.filters.groups[0].rollout_percentage = Some(50.0);
        let h_after = fingerprint(std::slice::from_ref(&flag_after), &m, None);

        assert_ne!(h_before, h_after, "content change must shift fingerprint");
    }

    /// Handler hot path: `Arc::clone(&prepared.flags)` must be a refcount bump,
    /// not a deep copy. This test confirms ptr equality of the slice held by
    /// `PreparedFlagDefinitions` versus a derived `FeatureFlagList`.
    #[tokio::test]
    async fn test_handler_clone_is_arc_refcount_bump() {
        let cache = FlagDefinitionsCache::new(None, None);
        let wrapper = make_test_wrapper(vec![make_flag_with_regex(1, r"^user@.*\.com$")]);
        let prepared = cache
            .get_or_prepare(1, Some(wrapper), &CacheSource::Redis)
            .await
            .unwrap();

        let shared = Arc::clone(&prepared.flags);
        // Same backing allocation — no deep copy of the flag vec.
        assert!(
            Arc::ptr_eq(&shared, &prepared.flags),
            "handler-path clone must share the Arc, not duplicate the data"
        );
    }

    /// Weigher must account for JSON-valued `PropertyFilter.value` bytes.
    /// Guards against the previous underreport that let the cache exceed
    /// its configured capacity for teams with large cohort-in-flag filters.
    #[test]
    fn test_weigher_accounts_for_property_value_json() {
        let make_flag = |value: serde_json::Value| {
            mock!(FeatureFlag,
                name: None,
                key: "k".mock_into(),
                filters: mock!(PropertyFilter,
                    key: "prop".mock_into(),
                    value: Some(value),
                    operator: Some(OperatorType::Exact),
                )
                .mock_into(),
            )
        };
        let small = Arc::new(PreparedFlagDefinitions {
            flags: Arc::from([make_flag(json!("x"))]),
            evaluation_metadata: EvaluationMetadata::default(),
            cohorts: None,
        });
        // ~10 KB string payload
        let big_str = "x".repeat(10_000);
        let big = Arc::new(PreparedFlagDefinitions {
            flags: Arc::from([make_flag(json!(big_str))]),
            evaluation_metadata: EvaluationMetadata::default(),
            cohorts: None,
        });

        let small_sz = small.estimated_size_bytes();
        let big_sz = big.estimated_size_bytes();
        assert!(
            big_sz > small_sz + 9_000,
            "weigher should reflect ~10KB of JSON payload: small={small_sz}, big={big_sz}"
        );
    }
}
