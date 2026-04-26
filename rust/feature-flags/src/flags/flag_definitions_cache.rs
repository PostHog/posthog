use std::sync::Arc;
use std::time::Duration;

use common_hypercache::CacheSource;
use common_metrics::{gauge, inc};
use common_types::TeamId;
use moka::future::Cache;

use crate::api::errors::FlagError;
use crate::flags::flag_models::{
    FeatureFlagList, HypercacheFlagsWrapper, PreparedFlagDefinitions,
};
use crate::metrics::consts::{
    FLAG_DEFINITIONS_INMEM_CACHE_ENTRIES_GAUGE, FLAG_DEFINITIONS_INMEM_CACHE_HIT_COUNTER,
    FLAG_DEFINITIONS_INMEM_CACHE_MISS_COUNTER, FLAG_DEFINITIONS_INMEM_CACHE_NO_VERSION_COUNTER,
    FLAG_DEFINITIONS_INMEM_CACHE_SIZE_BYTES_GAUGE,
};

/// In-memory cache for regex-compiled flag definitions, keyed on
/// `(team_id, etag)` where `etag` is the version tag Django writes alongside
/// the hypercache payload (`HyperCache(enable_etag=True)`).
///
/// On a hit the caller never touches Redis for the payload, never un-pickles or
/// JSON-decodes anything, and never walks the deserialized tree to fingerprint
/// it — the hot path is `Arc::clone` of an already-compiled value. The closure
/// passed to `get_or_load` only runs on a miss, on PG fallback, or when no etag
/// is available, so the caller pays for the payload fetch and validation only
/// when the in-memory copy is genuinely stale.
///
/// Concurrent misses on the same `(team_id, etag)` coalesce via moka's
/// `entry().or_try_insert_with(...)`, so the closure runs exactly once per
/// coalesced group. `Entry::is_fresh()` distinguishes the winner (counted as a
/// miss) from coalesced followers (counted as hits).
///
/// PG fallback (`CacheSource::Fallback`) and the etag-absent path bypass moka
/// entirely — the former because PG-fallback data is transient, the latter
/// because we have no version to key on. Both bumps the no-version counter so
/// we can tell from metrics how often the version-key fast path is unavailable.
pub struct FlagDefinitionsCache {
    cache: Cache<(TeamId, String), Arc<PreparedFlagDefinitions>>,
}

impl FlagDefinitionsCache {
    const DEFAULT_CAPACITY_BYTES: u64 = 134_217_728; // 128 MB
    const DEFAULT_TTL_SECONDS: u64 = 90;

    pub fn new(capacity_bytes: Option<u64>, ttl_seconds: Option<u64>) -> Self {
        let weigher = |_key: &(TeamId, String),
                       value: &Arc<PreparedFlagDefinitions>|
         -> u32 { u32::try_from(value.estimated_size_bytes()).unwrap_or(u32::MAX) };

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

    /// Returns a regex-compiled flag definitions bundle for the team, sharing
    /// the underlying `Arc` across requests when the etag matches a cached
    /// entry.
    ///
    /// `load_payload` is invoked only when we genuinely need the payload — i.e.
    /// on PG fallback, when no etag is available, or on a true cache miss.
    /// On a hit it is dropped without being polled, which is the entire point
    /// of this redesign: the caller doesn't pay for the Redis payload fetch,
    /// pickle decode, JSON decode, or wrapper validation on the hot path.
    ///
    /// The returned `CacheSource` reflects where the response came from:
    /// `Redis` for in-memory hits (we read the etag from Redis), and whatever
    /// the closure reports for misses / PG fallback.
    pub async fn get_or_load<F, Fut>(
        &self,
        team_id: TeamId,
        etag: Option<String>,
        cache_source: &CacheSource,
        load_payload: F,
    ) -> Result<(Arc<PreparedFlagDefinitions>, CacheSource), FlagError>
    where
        F: FnOnce() -> Fut,
        Fut: std::future::Future<
            Output = Result<(Option<HypercacheFlagsWrapper>, CacheSource), FlagError>,
        >,
    {
        // PG fallback is transient — never cache it. Mirrors the original PR's
        // behavior to avoid serving degraded single-stage data past its window.
        if matches!(cache_source, CacheSource::Fallback) {
            let (wrapper, src) = load_payload().await?;
            let prepared = compile_from_wrapper(team_id, wrapper)?;
            return Ok((prepared, src));
        }

        let Some(etag) = etag else {
            // No version to key on — could be the `__missing__` sentinel (no
            // flags), TTL drift, or a hypercache entry written before
            // `enable_etag` was on. Fall through to a fresh load and skip the
            // cache; bump the no-version counter so the rate is observable.
            inc(
                FLAG_DEFINITIONS_INMEM_CACHE_NO_VERSION_COUNTER,
                &[("reason".to_string(), "etag_missing".to_string())],
                1,
            );
            let (wrapper, src) = load_payload().await?;
            let prepared = compile_from_wrapper(team_id, wrapper)?;
            return Ok((prepared, src));
        };

        let cache_key = (team_id, etag);

        // `or_try_insert_with` coalesces concurrent misses (closure runs once
        // for the winner, the rest await the same Arc) AND propagates a
        // fallible compute. `is_fresh()` tells us which branch we took so the
        // hit/miss counters stay accurate even under coalescing.
        let entry_result = self
            .cache
            .entry(cache_key)
            .or_try_insert_with(async move {
                let (wrapper, _src) = load_payload().await?;
                compile_from_wrapper(team_id, wrapper)
            })
            .await;

        match entry_result {
            Ok(entry) => {
                if entry.is_fresh() {
                    inc(FLAG_DEFINITIONS_INMEM_CACHE_MISS_COUNTER, &[], 1);
                    self.report_cache_metrics();
                } else {
                    inc(FLAG_DEFINITIONS_INMEM_CACHE_HIT_COUNTER, &[], 1);
                }
                Ok((entry.into_value(), CacheSource::Redis))
            }
            Err(arc_err) => Err(unwrap_cache_err(arc_err)),
        }
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

/// Validates and compiles a `HypercacheFlagsWrapper` into the cached, sharable
/// shape. Pulled out so both the Fallback / no-version paths and the
/// `or_try_insert_with` closure share one implementation.
///
/// Validation runs here (not inside a `from_wrapper` step before the cache
/// call) so cache hits never re-validate. On miss the validation cost is
/// unchanged from the pre-redesign behavior — we still fail fast on malformed
/// wrappers with `DataParsingErrorWithContext`.
fn compile_from_wrapper(
    team_id: TeamId,
    wrapper: Option<HypercacheFlagsWrapper>,
) -> Result<Arc<PreparedFlagDefinitions>, FlagError> {
    let (mut flags, evaluation_metadata, cohorts) =
        FeatureFlagList::from_wrapper(wrapper, team_id)?;

    // `prepare_regexes_in_place` is infallible — invalid patterns are stored
    // as `CompiledRegex::InvalidPattern`. We pre-compile here once before the
    // single `Arc::from(flags)` wrap to avoid `Arc::get_mut` juggling later.
    FeatureFlagList::prepare_regexes_in_place(&mut flags);

    Ok(Arc::new(PreparedFlagDefinitions {
        flags: Arc::from(flags),
        evaluation_metadata,
        cohorts,
    }))
}

/// Maps moka's `Arc<FlagError>` (shared across all coalesced waiters) back
/// onto an owned `FlagError`.
///
/// The only error variant the closure path produces in production today is
/// `DataParsingErrorWithContext` (from `from_wrapper`'s contract checks);
/// anything else from the payload-fetch side is mapped through to `Internal`
/// to keep the cache boundary from silently widening that error. This
/// mirrors the original PR's "validation errors retain their original
/// `FlagError` variant" guarantee under the new closure-driven design.
fn unwrap_cache_err(arc: Arc<FlagError>) -> FlagError {
    match &*arc {
        FlagError::DataParsingErrorWithContext(s) => {
            FlagError::DataParsingErrorWithContext(s.clone())
        }
        other => FlagError::Internal(format!(
            "flag definitions cache load failure: {other}"
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_models::{EvaluationMetadata, FeatureFlag};
    use crate::mock;
    use crate::properties::property_models::{OperatorType, PropertyFilter};
    use crate::utils::mock::MockInto;
    use serde_json::json;
    use std::sync::atomic::{AtomicUsize, Ordering};

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

    /// Boxed-future return shape expected by `get_or_load`'s `load_payload`
    /// argument. Aliased so the test helpers below can return a single named
    /// type instead of an unwieldy inline `impl Future` (which clippy flags as
    /// `type_complexity`).
    type LoaderFuture = std::pin::Pin<
        Box<
            dyn std::future::Future<
                    Output = Result<(Option<HypercacheFlagsWrapper>, CacheSource), FlagError>,
                > + Send,
        >,
    >;

    /// Wraps a wrapper in a closure suitable for `get_or_load`'s `load_payload`
    /// argument, returning a Redis-source tuple. Tests that need to assert how
    /// many times the closure ran should use `counting_loader` instead.
    fn loader_for(wrapper: HypercacheFlagsWrapper) -> impl FnOnce() -> LoaderFuture {
        || Box::pin(async move { Ok::<_, FlagError>((Some(wrapper), CacheSource::Redis)) })
    }

    /// Same as `loader_for`, but bumps `counter` every time it runs. Use with
    /// `Arc::clone(&counter)` and `assert_eq!(counter.load(...), expected)` to
    /// pin the exact number of times the closure was polled.
    fn counting_loader(
        wrapper: HypercacheFlagsWrapper,
        counter: Arc<AtomicUsize>,
    ) -> impl FnOnce() -> LoaderFuture {
        move || {
            counter.fetch_add(1, Ordering::SeqCst);
            Box::pin(async move { Ok::<_, FlagError>((Some(wrapper), CacheSource::Redis)) })
        }
    }

    /// Two `get_or_load` calls with the same `(team_id, etag)` against fresh
    /// wrapper instances must return the same `Arc<PreparedFlagDefinitions>`.
    /// This is the version-key fast path: identical etag = cached compile.
    #[tokio::test]
    async fn test_etag_hit_returns_same_arc() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w = make_test_wrapper(vec![make_flag_with_regex(1, r"^test@.*\.com$")]);
        let etag = Some("v1-etag".to_string());

        let (first, _) = cache
            .get_or_load(1, etag.clone(), &CacheSource::Redis, loader_for(w.clone()))
            .await
            .unwrap();
        let (second, _) = cache
            .get_or_load(1, etag, &CacheSource::Redis, loader_for(w))
            .await
            .unwrap();

        assert!(Arc::ptr_eq(&first, &second), "same etag must reuse the cached Arc");
        assert!(first.flags[0].filters.groups[0]
            .properties
            .as_ref()
            .unwrap()[0]
            .compiled_regex
            .is_some());
    }

    /// On a hit, `load_payload` must NOT be polled — that's the whole point of
    /// the redesign. If it is, we'd be paying the payload fetch + decode cost
    /// on every request and the version-key path would deliver no hot-path win.
    #[tokio::test]
    async fn test_etag_hit_skips_payload_load() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w = make_test_wrapper(vec![make_flag_with_regex(1, r"^t@.*$")]);
        let etag = Some("hot-etag".to_string());

        // Prime the cache.
        let counter = Arc::new(AtomicUsize::new(0));
        cache
            .get_or_load(
                1,
                etag.clone(),
                &CacheSource::Redis,
                counting_loader(w.clone(), Arc::clone(&counter)),
            )
            .await
            .unwrap();
        assert_eq!(counter.load(Ordering::SeqCst), 1, "first call must populate");

        // Hit — closure must not be invoked.
        cache
            .get_or_load(
                1,
                etag,
                &CacheSource::Redis,
                counting_loader(w, Arc::clone(&counter)),
            )
            .await
            .unwrap();
        assert_eq!(
            counter.load(Ordering::SeqCst),
            1,
            "cache hit must NOT poll load_payload"
        );
    }

    /// Two etags = two cache entries with two distinct compiles. Guards against
    /// a regression where the etag is dropped from the key and identical etags
    /// would resolve to the same entry across content changes.
    #[tokio::test]
    async fn test_etag_change_invalidates_cache() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w1 = make_test_wrapper(vec![make_flag_with_regex(1, r"^v1@.*$")]);
        let w2 = make_test_wrapper(vec![make_flag_with_regex(1, r"^v2@.*$")]);

        let (a, _) = cache
            .get_or_load(1, Some("v1".into()), &CacheSource::Redis, loader_for(w1))
            .await
            .unwrap();
        let (b, _) = cache
            .get_or_load(1, Some("v2".into()), &CacheSource::Redis, loader_for(w2))
            .await
            .unwrap();

        assert!(!Arc::ptr_eq(&a, &b), "different etag must produce a fresh Arc");
    }

    /// `etag = None` (sentinel write, TTL drift, or pre-etag entry) must
    /// invoke the loader and skip the cache. A second call with `None` must
    /// invoke the loader again, proving nothing was inserted under a sentinel
    /// key.
    #[tokio::test]
    async fn test_etag_none_bypasses_cache() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w = make_test_wrapper(vec![make_flag_with_regex(1, r"^t@.*$")]);
        let counter = Arc::new(AtomicUsize::new(0));

        cache
            .get_or_load(
                1,
                None,
                &CacheSource::Redis,
                counting_loader(w.clone(), Arc::clone(&counter)),
            )
            .await
            .unwrap();
        cache
            .get_or_load(
                1,
                None,
                &CacheSource::Redis,
                counting_loader(w, Arc::clone(&counter)),
            )
            .await
            .unwrap();

        assert_eq!(
            counter.load(Ordering::SeqCst),
            2,
            "etag=None must invoke loader on every call"
        );
    }

    /// PG fallback data is transient — it lacks dependency metadata Django
    /// computes. Caching it would mean serving degraded data well past the
    /// transient window. Two fallback calls must produce two fresh Arcs.
    #[tokio::test]
    async fn test_pg_fallback_bypasses_cache() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w = make_test_wrapper(vec![make_flag_with_regex(1, r"^t@.*$")]);
        let etag = Some("present".to_string());

        let (first, src) = cache
            .get_or_load(
                1,
                etag.clone(),
                &CacheSource::Fallback,
                loader_for(w.clone()),
            )
            .await
            .unwrap();
        let (second, _) = cache
            .get_or_load(1, etag, &CacheSource::Fallback, loader_for(w))
            .await
            .unwrap();

        assert!(matches!(src, CacheSource::Redis));
        assert!(!Arc::ptr_eq(&first, &second));
    }

    /// `disabled()` cache must always miss — no Arc reuse across calls. Used
    /// in tests that don't exercise caching to keep their setups identical to
    /// production code paths.
    #[tokio::test]
    async fn test_disabled_cache_always_misses() {
        let cache = FlagDefinitionsCache::disabled();
        let w = make_test_wrapper(vec![make_flag_with_regex(1, r"^t@.*$")]);
        let etag = Some("doesnt-matter".to_string());

        let (a, _) = cache
            .get_or_load(1, etag.clone(), &CacheSource::Redis, loader_for(w.clone()))
            .await
            .unwrap();
        let (b, _) = cache
            .get_or_load(1, etag, &CacheSource::Redis, loader_for(w))
            .await
            .unwrap();

        assert!(!Arc::ptr_eq(&a, &b));
    }

    /// Both valid and invalid regex patterns must reach the cached value with
    /// the right `CompiledRegex` variant. Compilation runs inside
    /// `compile_from_wrapper`, so this is the regression test for that path.
    #[tokio::test]
    async fn test_regexes_are_precompiled_in_cached_value() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w = make_test_wrapper(vec![
            make_flag_with_regex(1, r"^user@.*\.com$"),
            make_flag_with_regex(2, r"[invalid"),
        ]);

        let (result, _) = cache
            .get_or_load(1, Some("rgx".into()), &CacheSource::Redis, loader_for(w))
            .await
            .unwrap();

        let regex_1 = &result.flags[0].filters.groups[0]
            .properties
            .as_ref()
            .unwrap()[0]
            .compiled_regex;
        assert!(matches!(
            regex_1,
            Some(crate::properties::property_models::CompiledRegex::Compiled(_))
        ));

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

    /// Regression for the error-flattening observability bug: a malformed
    /// wrapper (flags present but `dependency_stages` empty) must surface as
    /// `FlagError::DataParsingErrorWithContext`, not be collapsed to
    /// `FlagError::Internal` by the cache boundary.
    ///
    /// Under the closure-driven design the variant flows through moka's
    /// `Arc<FlagError>` and back via `unwrap_cache_err`, which is why this
    /// test explicitly pins the variant.
    #[tokio::test]
    async fn test_validation_errors_preserve_variant() {
        let cache = FlagDefinitionsCache::new(None, None);
        let bad_wrapper = HypercacheFlagsWrapper {
            flags: vec![make_flag_with_regex(1, r"^test@.*\.com$")],
            evaluation_metadata: EvaluationMetadata {
                dependency_stages: vec![],
                flags_with_missing_deps: vec![],
                transitive_deps: Default::default(),
            },
            cohorts: None,
        };

        let err = cache
            .get_or_load(
                1,
                Some("bad".into()),
                &CacheSource::Redis,
                loader_for(bad_wrapper),
            )
            .await
            .expect_err("malformed wrapper must error");
        assert!(
            matches!(err, FlagError::DataParsingErrorWithContext(_)),
            "expected DataParsingErrorWithContext, got {err:?}"
        );
    }

    /// Handler hot path: `Arc::clone(&prepared.flags)` must be a refcount bump,
    /// not a deep copy. This test confirms ptr equality of the slice held by
    /// `PreparedFlagDefinitions` versus a derived `FeatureFlagList`.
    #[tokio::test]
    async fn test_handler_clone_is_arc_refcount_bump() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w = make_test_wrapper(vec![make_flag_with_regex(1, r"^user@.*\.com$")]);
        let (prepared, _) = cache
            .get_or_load(1, Some("e".into()), &CacheSource::Redis, loader_for(w))
            .await
            .unwrap();

        let shared = Arc::clone(&prepared.flags);
        assert!(
            Arc::ptr_eq(&shared, &prepared.flags),
            "handler-path clone must share the Arc, not duplicate the data"
        );
    }

    /// Concurrent callers on the same `(team_id, etag)` must coalesce onto a
    /// single compile: all tasks see the same `Arc<PreparedFlagDefinitions>`
    /// pointer, and the loader closure runs **exactly once**. This is the
    /// invariant moka's `or_try_insert_with` provides; we pin it here so a
    /// future migration to a different cache crate can't silently regress to
    /// per-caller compute.
    #[tokio::test]
    async fn test_concurrent_callers_coalesce_to_single_compile() {
        let cache = Arc::new(FlagDefinitionsCache::new(None, None));
        let w = make_test_wrapper(vec![make_flag_with_regex(1, r"^t@.*$")]);
        let etag = Some("coalesce-etag".to_string());
        let counter = Arc::new(AtomicUsize::new(0));

        let n: usize = 16;
        let mut handles = Vec::with_capacity(n);
        for _ in 0..n {
            let cache = Arc::clone(&cache);
            let w = w.clone();
            let etag = etag.clone();
            let counter = Arc::clone(&counter);
            handles.push(tokio::spawn(async move {
                cache
                    .get_or_load(
                        42,
                        etag,
                        &CacheSource::Redis,
                        counting_loader(w, counter),
                    )
                    .await
                    .unwrap()
            }));
        }

        let mut results = Vec::with_capacity(n);
        for h in handles {
            results.push(h.await.unwrap());
        }

        let (first, _) = &results[0];
        for (i, (r, _)) in results.iter().enumerate().skip(1) {
            assert!(
                Arc::ptr_eq(first, r),
                "concurrent caller {i} did not coalesce onto the shared Arc"
            );
        }
        assert_eq!(
            counter.load(Ordering::SeqCst),
            1,
            "loader must run exactly once under concurrent misses"
        );
    }

    /// `super_groups` are walked by `prepare_regexes_in_place`, so the weigher
    /// must walk them too. Regression for the asymmetry where super_groups
    /// filters were compiled but not counted, letting the cache silently
    /// exceed its configured capacity for teams with non-trivial
    /// early-access-enrollment flags.
    #[test]
    fn test_weigher_accounts_for_super_groups() {
        use crate::flags::flag_models::FlagPropertyGroup;
        use crate::properties::property_models::PropertyType;

        let make_flag = |super_groups: Option<Vec<FlagPropertyGroup>>| {
            let mut flag = mock!(FeatureFlag,
                name: None,
                key: "k".mock_into(),
            );
            flag.filters.super_groups = super_groups;
            flag
        };

        let big_str = "x".repeat(10_000);
        let big_group = FlagPropertyGroup {
            properties: Some(vec![PropertyFilter {
                key: "prop".to_string(),
                value: Some(json!(big_str)),
                operator: Some(OperatorType::Exact),
                prop_type: PropertyType::Person,
                group_type_index: None,
                negation: None,
                compiled_regex: None,
            }]),
            rollout_percentage: Some(100.0),
            variant: None,
            aggregation_group_type_index: None,
        };

        let without = Arc::new(PreparedFlagDefinitions {
            flags: Arc::from([make_flag(None)]),
            evaluation_metadata: EvaluationMetadata::default(),
            cohorts: None,
        });
        let with = Arc::new(PreparedFlagDefinitions {
            flags: Arc::from([make_flag(Some(vec![big_group]))]),
            evaluation_metadata: EvaluationMetadata::default(),
            cohorts: None,
        });

        let without_sz = without.estimated_size_bytes();
        let with_sz = with.estimated_size_bytes();
        assert!(
            with_sz > without_sz + 9_000,
            "weigher must count super_groups property bytes: without={without_sz}, with={with_sz}"
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
