use std::sync::Arc;
use std::time::{Duration, Instant};

use common_hypercache::CacheSource;
use common_metrics::{gauge, histogram, inc};
use common_types::TeamId;
use lifecycle::Handle;
use moka::future::Cache;

use crate::api::errors::FlagError;
use crate::flags::feature_flag_list::PreparedFlags;
use crate::flags::flag_models::{FeatureFlagList, HypercacheFlagsWrapper, PreparedFlagDefinitions};
use crate::metrics::consts::{
    FLAG_DEFINITIONS_INMEM_CACHE_ENTRIES_GAUGE, FLAG_DEFINITIONS_INMEM_CACHE_HIT_COUNTER,
    FLAG_DEFINITIONS_INMEM_CACHE_MISS_COUNTER, FLAG_DEFINITIONS_INMEM_CACHE_NO_VERSION_COUNTER,
    FLAG_DEFINITIONS_INMEM_CACHE_SIZE_BYTES_GAUGE, FLAG_DEFINITIONS_INMEM_LOAD_MS,
};

/// Outcome of a single `get_or_load` call. Used as the `outcome` label on
/// `flags_definitions_inmem_load_ms`. The set is closed and small (5
/// values) so cardinality stays bounded.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum LoadOutcome {
    /// In-memory cache returned a value without invoking the loader.
    Hit,
    /// Loader ran successfully (HyperCache → Redis/S3 → PG); a cacheable
    /// (non-`Fallback`) result was produced.
    MissLoadOk,
    /// Loader returned `Err`. Includes both HyperCache infrastructure
    /// failures and `compile_from_wrapper` data-parsing errors.
    MissLoadErr,
    /// `etag` parameter was `Some` empty / missing in Redis but the
    /// loader returned a non-empty wrapper — true version-key drift.
    EtagMissing,
    /// `etag` was `None` and the loader returned the `__missing__`
    /// sentinel (Django's empty-team marker). Treated separately so
    /// dashboards can exclude steady-state empty teams from alerts.
    Sentinel,
}

impl LoadOutcome {
    /// Stable label value, kept in sync with the dashboard contract.
    const fn label(self) -> &'static str {
        match self {
            LoadOutcome::Hit => "hit",
            LoadOutcome::MissLoadOk => "miss_load_ok",
            LoadOutcome::MissLoadErr => "miss_load_err",
            LoadOutcome::EtagMissing => "etag_missing",
            LoadOutcome::Sentinel => "sentinel",
        }
    }
}

/// In-memory cache for regex-compiled flag definitions, keyed on
/// `(team_id, etag)` where `etag` is the version tag Django writes alongside
/// the hypercache payload (`HyperCache(enable_etag=True)`).
///
/// PG-source data (`CacheSource::Fallback`) is never inserted: when the etag
/// GET succeeds but the payload load falls through to PG, caching would seed
/// the entry with single-stage `EvaluationMetadata` for the rest of the TTL
/// window even though Django's full transitive-dep payload is still indexed
/// under the same etag.
///
/// Concurrent first-misses don't coalesce: `try_get_with` requires `E: Clone`
/// and `FlagError` carries non-`Clone` payloads. Each task compiles its own
/// value; last `insert` wins, post-storm reads hit.
pub struct FlagDefinitionsCache {
    cache: Cache<(TeamId, String), Arc<PreparedFlagDefinitions>>,
}

impl FlagDefinitionsCache {
    const DEFAULT_CAPACITY_BYTES: u64 = 134_217_728; // 128 MB
    const DEFAULT_TTL_SECONDS: u64 = 90;

    pub fn new(capacity_bytes: Option<u64>, ttl_seconds: Option<u64>) -> Self {
        let weigher = |_key: &(TeamId, String), value: &Arc<PreparedFlagDefinitions>| -> u32 {
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

    /// Returns a regex-compiled flag definitions bundle for the team. On a
    /// hit the cached `Arc` is shared across requests; on a miss the loader
    /// runs, the result is compiled, and only `Redis`/`S3`-source values are
    /// inserted. The returned `CacheSource` is `Redis` for in-memory hits
    /// and whatever the loader reports otherwise.
    ///
    /// Total wall-clock duration of this call is recorded into
    /// [`FLAG_DEFINITIONS_INMEM_LOAD_MS`] with an `outcome` label. Hits
    /// resolve in microseconds; misses dominate the p99 because the loader
    /// chain (HyperCache → Pickle/JSON decode → regex compile) is sync-
    /// heavy. A spike in `outcome="miss_load_ok"` p99 is the dashboard
    /// signature of an etag-rollover thunder herd (see struct doc).
    pub async fn get_or_load<F, Fut>(
        &self,
        team_id: TeamId,
        etag: Option<String>,
        load_payload: F,
    ) -> Result<(Arc<PreparedFlagDefinitions>, CacheSource), FlagError>
    where
        F: FnOnce() -> Fut,
        Fut: std::future::Future<
            Output = Result<(Option<HypercacheFlagsWrapper>, CacheSource), FlagError>,
        >,
    {
        let start = Instant::now();
        let result = self
            .get_or_load_classified(team_id, etag, load_payload)
            .await;
        let outcome = match &result {
            Ok((_, _, oc)) => *oc,
            Err(_) => LoadOutcome::MissLoadErr,
        };
        // Sub-ms-precision recording paired with the sub-ms-floor bucket
        // override registered in `metrics::buckets`. Hits would otherwise
        // collapse into the lowest integer-ms bucket and hide tail behavior.
        histogram(
            FLAG_DEFINITIONS_INMEM_LOAD_MS,
            &[("outcome".to_string(), outcome.label().to_string())],
            start.elapsed().as_secs_f64() * 1000.0,
        );
        result.map(|(prepared, src, _)| (prepared, src))
    }

    /// Inner worker for [`Self::get_or_load`]. Returns the success outcome
    /// alongside the value so the wrapper can pick the histogram label
    /// without re-deriving control flow. `Err` is treated as
    /// [`LoadOutcome::MissLoadErr`] uniformly at the wrapper level —
    /// including `compile_from_wrapper` parse failures, which are
    /// indistinguishable from infrastructure errors at the metric level.
    async fn get_or_load_classified<F, Fut>(
        &self,
        team_id: TeamId,
        etag: Option<String>,
        load_payload: F,
    ) -> Result<(Arc<PreparedFlagDefinitions>, CacheSource, LoadOutcome), FlagError>
    where
        F: FnOnce() -> Fut,
        Fut: std::future::Future<
            Output = Result<(Option<HypercacheFlagsWrapper>, CacheSource), FlagError>,
        >,
    {
        let Some(etag) = etag else {
            // `wrapper.is_none()` is the `__missing__` sentinel (Django
            // deletes the etag for empty teams); anything else with a
            // missing etag is real version-key drift. Splitting the labels
            // lets dashboards exclude steady-state empty teams from alerts.
            let (wrapper, src) = load_payload().await?;
            let outcome = if wrapper.is_none() {
                LoadOutcome::Sentinel
            } else {
                LoadOutcome::EtagMissing
            };
            inc(
                FLAG_DEFINITIONS_INMEM_CACHE_NO_VERSION_COUNTER,
                &[("reason".to_string(), outcome.label().to_string())],
                1,
            );
            let prepared = compile_from_wrapper(team_id, wrapper)?;
            return Ok((prepared, src, outcome));
        };

        let cache_key = (team_id, etag);

        if let Some(prepared) = self.cache.get(&cache_key).await {
            inc(FLAG_DEFINITIONS_INMEM_CACHE_HIT_COUNTER, &[], 1);
            return Ok((prepared, CacheSource::Redis, LoadOutcome::Hit));
        }

        let (wrapper, src) = load_payload().await?;
        let prepared = compile_from_wrapper(team_id, wrapper)?;
        inc(FLAG_DEFINITIONS_INMEM_CACHE_MISS_COUNTER, &[], 1);
        self.report_cache_metrics();

        // Source is checked after the loader returns so a fall-through to PG
        // never persists under the etag (see struct doc).
        if !matches!(src, CacheSource::Fallback) {
            self.cache.insert(cache_key, Arc::clone(&prepared)).await;
        }

        Ok((prepared, src, LoadOutcome::MissLoadOk))
    }

    /// Starts periodic monitoring of cache metrics. Honors the lifecycle
    /// `shutdown` handle so the manager can drain this monitor cleanly during
    /// graceful shutdown (mirrors `CohortCacheManager::start_monitoring`).
    pub async fn start_monitoring(&self, interval_secs: u64, shutdown: Handle) {
        let _scope = shutdown.process_scope();
        let mut ticker = tokio::time::interval(Duration::from_secs(interval_secs));

        tracing::info!(
            "Starting flag definitions cache monitoring (interval: {}s)",
            interval_secs
        );

        loop {
            tokio::select! {
                _ = shutdown.shutdown_recv() => {
                    tracing::info!("Flag definitions cache monitor shutting down");
                    break;
                }
                _ = ticker.tick() => {
                    self.report_cache_metrics();
                }
            }
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

/// Validates a `HypercacheFlagsWrapper` and compiles its regexes. Validation
/// runs here, not on the cache-lookup path, so hits never re-validate.
/// Malformed wrappers fail fast with `DataParsingErrorWithContext`.
pub(crate) fn compile_from_wrapper(
    team_id: TeamId,
    wrapper: Option<HypercacheFlagsWrapper>,
) -> Result<Arc<PreparedFlagDefinitions>, FlagError> {
    let (flags, evaluation_metadata, cohorts) = FeatureFlagList::from_wrapper(wrapper, team_id)?;
    let flags = PreparedFlags::seal(flags);
    Ok(Arc::new(PreparedFlagDefinitions {
        flags,
        evaluation_metadata: Arc::new(evaluation_metadata),
        cohorts: cohorts.map(Arc::from),
    }))
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

    /// Boxed-future shape expected by `get_or_load`'s `load_payload` argument,
    /// aliased to keep test helpers below from tripping `type_complexity`.
    type LoaderFuture = std::pin::Pin<
        Box<
            dyn std::future::Future<
                    Output = Result<(Option<HypercacheFlagsWrapper>, CacheSource), FlagError>,
                > + Send,
        >,
    >;

    /// Returns a `Redis`-source loader for `wrapper`.
    fn loader_for(wrapper: HypercacheFlagsWrapper) -> impl FnOnce() -> LoaderFuture {
        || Box::pin(async move { Ok::<_, FlagError>((Some(wrapper), CacheSource::Redis)) })
    }

    /// Like `loader_for`, but bumps `counter` every time it runs.
    fn counting_loader(
        wrapper: HypercacheFlagsWrapper,
        counter: Arc<AtomicUsize>,
    ) -> impl FnOnce() -> LoaderFuture {
        move || {
            counter.fetch_add(1, Ordering::SeqCst);
            Box::pin(async move { Ok::<_, FlagError>((Some(wrapper), CacheSource::Redis)) })
        }
    }

    /// Same etag → same cached `Arc`.
    #[tokio::test]
    async fn test_etag_hit_returns_same_arc() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w = make_test_wrapper(vec![make_flag_with_regex(1, r"^test@.*\.com$")]);
        let etag = Some("v1-etag".to_string());

        let (first, _) = cache
            .get_or_load(1, etag.clone(), loader_for(w.clone()))
            .await
            .unwrap();
        let (second, _) = cache.get_or_load(1, etag, loader_for(w)).await.unwrap();

        assert!(
            Arc::ptr_eq(&first, &second),
            "same etag must reuse the cached Arc"
        );
        assert!(first.flags[0].filters.groups[0]
            .properties
            .as_ref()
            .unwrap()[0]
            .compiled_regex
            .is_some());
    }

    /// On a hit, `load_payload` must not be polled — otherwise the
    /// version-key fast path would still pay the payload fetch + decode cost.
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
                counting_loader(w.clone(), Arc::clone(&counter)),
            )
            .await
            .unwrap();
        assert_eq!(
            counter.load(Ordering::SeqCst),
            1,
            "first call must populate"
        );

        // Hit — closure must not be invoked.
        cache
            .get_or_load(1, etag, counting_loader(w, Arc::clone(&counter)))
            .await
            .unwrap();
        assert_eq!(
            counter.load(Ordering::SeqCst),
            1,
            "cache hit must NOT poll load_payload"
        );
    }

    /// Different etag → fresh compile and a distinct cached Arc.
    #[tokio::test]
    async fn test_etag_change_invalidates_cache() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w1 = make_test_wrapper(vec![make_flag_with_regex(1, r"^v1@.*$")]);
        let w2 = make_test_wrapper(vec![make_flag_with_regex(1, r"^v2@.*$")]);

        let (a, _) = cache
            .get_or_load(1, Some("v1".into()), loader_for(w1))
            .await
            .unwrap();
        let (b, _) = cache
            .get_or_load(1, Some("v2".into()), loader_for(w2))
            .await
            .unwrap();

        assert!(
            !Arc::ptr_eq(&a, &b),
            "different etag must produce a fresh Arc"
        );
    }

    /// `etag = None` invokes the loader on every call and never inserts.
    #[tokio::test]
    async fn test_etag_none_bypasses_cache() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w = make_test_wrapper(vec![make_flag_with_regex(1, r"^t@.*$")]);
        let counter = Arc::new(AtomicUsize::new(0));

        cache
            .get_or_load(1, None, counting_loader(w.clone(), Arc::clone(&counter)))
            .await
            .unwrap();
        cache
            .get_or_load(1, None, counting_loader(w, Arc::clone(&counter)))
            .await
            .unwrap();

        assert_eq!(
            counter.load(Ordering::SeqCst),
            2,
            "etag=None must invoke loader on every call"
        );
    }

    /// When the etag GET succeeds but the loader returns `Fallback` (e.g.
    /// payload evicted before the etag key), the value must not land in
    /// the cache under the still-fresh etag — otherwise single-stage PG
    /// data would be served for the rest of the TTL window.
    #[tokio::test]
    async fn test_pg_fallback_with_etag_present_does_not_cache() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w = make_test_wrapper(vec![make_flag_with_regex(1, r"^t@.*$")]);
        let etag = Some("present".to_string());

        let counter = Arc::new(AtomicUsize::new(0));
        let fallback_loader = |c: Arc<AtomicUsize>, w: HypercacheFlagsWrapper| {
            move || -> LoaderFuture {
                c.fetch_add(1, Ordering::SeqCst);
                Box::pin(async move { Ok::<_, FlagError>((Some(w), CacheSource::Fallback)) })
            }
        };

        let (first, src1) = cache
            .get_or_load(
                1,
                etag.clone(),
                fallback_loader(Arc::clone(&counter), w.clone()),
            )
            .await
            .unwrap();
        let (second, src2) = cache
            .get_or_load(1, etag, fallback_loader(Arc::clone(&counter), w))
            .await
            .unwrap();

        assert!(matches!(src1, CacheSource::Fallback));
        assert!(matches!(src2, CacheSource::Fallback));
        assert!(
            !Arc::ptr_eq(&first, &second),
            "Fallback data must not be cached under the etag — second call must reload",
        );
        assert_eq!(
            counter.load(Ordering::SeqCst),
            2,
            "loader must run on every call when source is Fallback",
        );
    }

    /// `disabled()` always misses — no Arc reuse across calls.
    #[tokio::test]
    async fn test_disabled_cache_always_misses() {
        let cache = FlagDefinitionsCache::disabled();
        let w = make_test_wrapper(vec![make_flag_with_regex(1, r"^t@.*$")]);
        let etag = Some("doesnt-matter".to_string());

        let (a, _) = cache
            .get_or_load(1, etag.clone(), loader_for(w.clone()))
            .await
            .unwrap();
        let (b, _) = cache.get_or_load(1, etag, loader_for(w)).await.unwrap();

        assert!(!Arc::ptr_eq(&a, &b));
    }

    /// Cached values carry the right `CompiledRegex` variant for both valid
    /// and invalid patterns.
    #[tokio::test]
    async fn test_regexes_are_precompiled_in_cached_value() {
        let cache = FlagDefinitionsCache::new(None, None);
        let w = make_test_wrapper(vec![
            make_flag_with_regex(1, r"^user@.*\.com$"),
            make_flag_with_regex(2, r"[invalid"),
        ]);

        let (result, _) = cache
            .get_or_load(1, Some("rgx".into()), loader_for(w))
            .await
            .unwrap();

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

    /// A malformed wrapper (flags present but `dependency_stages` empty) must
    /// surface as `FlagError::DataParsingErrorWithContext`, not be collapsed
    /// into `Internal` at the cache boundary.
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
            .get_or_load(1, Some("bad".into()), loader_for(bad_wrapper))
            .await
            .expect_err("malformed wrapper must error");
        assert!(
            matches!(err, FlagError::DataParsingErrorWithContext(_)),
            "expected DataParsingErrorWithContext, got {err:?}"
        );
    }

    /// Non-parse loader errors (e.g. `DatabaseUnavailable`) must round-trip
    /// through `get_or_load` without being collapsed into `Internal`.
    #[tokio::test]
    async fn test_loader_error_variants_propagate_unchanged() {
        let cache = FlagDefinitionsCache::new(None, None);
        let loader = || -> LoaderFuture {
            Box::pin(async {
                Err::<(Option<HypercacheFlagsWrapper>, CacheSource), _>(
                    FlagError::DatabaseUnavailable,
                )
            })
        };
        let err = cache
            .get_or_load(1, Some("e".into()), loader)
            .await
            .expect_err("loader error must surface");
        assert!(
            matches!(err, FlagError::DatabaseUnavailable),
            "non-parse variants must propagate verbatim, got {err:?}"
        );
    }

    /// Storm tasks may each compile their own Arc (no coalescing).
    /// Post-storm reads must hit and ptr_eq, and every storm Arc must
    /// carry a compiled regex regardless of identity.
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn test_concurrent_first_misses_settle_to_canonical_arc() {
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
                    .get_or_load(42, etag, counting_loader(w, counter))
                    .await
                    .unwrap()
            }));
        }

        let mut results = Vec::with_capacity(n);
        for h in handles {
            results.push(h.await.unwrap());
        }

        // counting_loader on the post-storm reads pins "loader did not run".
        let post_counter = Arc::new(AtomicUsize::new(0));
        let (canonical_a, _) = cache
            .get_or_load(
                42,
                etag.clone(),
                counting_loader(w.clone(), Arc::clone(&post_counter)),
            )
            .await
            .unwrap();
        let (canonical_b, _) = cache
            .get_or_load(42, etag, counting_loader(w, Arc::clone(&post_counter)))
            .await
            .unwrap();
        assert_eq!(
            post_counter.load(Ordering::SeqCst),
            0,
            "post-storm reads must hit, not invoke the loader",
        );
        assert!(
            Arc::ptr_eq(&canonical_a, &canonical_b),
            "cache must settle to a single canonical Arc",
        );

        for (i, (arc, _)) in results.iter().enumerate() {
            let compiled =
                &arc.flags[0].filters.groups[0].properties.as_ref().unwrap()[0].compiled_regex;
            assert!(
                matches!(
                    compiled,
                    Some(crate::properties::property_models::CompiledRegex::Compiled(
                        _
                    ))
                ),
                "storm result {i} must carry a compiled regex",
            );
        }

        assert!(
            counter.load(Ordering::SeqCst) >= 1,
            "at least one cold load must happen",
        );
    }

    /// The weigher must walk `super_groups` as well as `groups` so cache
    /// capacity isn't silently overshot for teams whose super_groups carry
    /// non-trivial property payloads.
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
            flags: PreparedFlags::seal(vec![make_flag(None)]),
            evaluation_metadata: Arc::new(EvaluationMetadata::default()),
            cohorts: None,
        });
        let with = Arc::new(PreparedFlagDefinitions {
            flags: PreparedFlags::seal(vec![make_flag(Some(vec![big_group]))]),
            evaluation_metadata: Arc::new(EvaluationMetadata::default()),
            cohorts: None,
        });

        let without_sz = without.estimated_size_bytes();
        let with_sz = with.estimated_size_bytes();
        assert!(
            with_sz > without_sz + 9_000,
            "weigher must count super_groups property bytes: without={without_sz}, with={with_sz}"
        );
    }

    /// The weigher must include JSON-valued `PropertyFilter.value` bytes so
    /// large cohort-in-flag filters don't push the cache over its capacity.
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
            flags: PreparedFlags::seal(vec![make_flag(json!("x"))]),
            evaluation_metadata: Arc::new(EvaluationMetadata::default()),
            cohorts: None,
        });
        let big_str = "x".repeat(10_000);
        let big = Arc::new(PreparedFlagDefinitions {
            flags: PreparedFlags::seal(vec![make_flag(json!(big_str))]),
            evaluation_metadata: Arc::new(EvaluationMetadata::default()),
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
