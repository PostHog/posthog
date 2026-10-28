use std::{
    any::Any,
    collections::HashMap,
    sync::Arc,
    time::{Duration, Instant},
};

use async_trait::async_trait;
use bytes::Bytes;
use moka::future::{Cache, CacheBuilder};
use tokio::sync::{Mutex, Semaphore};
use tracing::{info, warn};

use crate::{
    error::{FrameError, ResolveError, UnhandledError},
    metric_consts::{
        STORE_CACHED_BYTES, STORE_CACHE_EVICTIONS, STORE_CACHE_EVICTION_RUNS, STORE_CACHE_HITS,
        STORE_CACHE_MISSES, SYMBOL_SET_LARGE_PARSE_WAIT_MS, SYMBOL_SET_PARSE_INPUT_BYTES,
        SYMBOL_SET_PARSE_REFUSED,
    },
};

use super::{chunk_id::SymbolSetCacheKey, Fetcher, ParsePermit, Parser, Provider};

// Parsing can transiently need many times the fetched size (e.g. ProguardCache::write), and
// none of that is held against the cache budget. We log large parses before they start, so
// the last log line of an OOM-killed pod names the symbol set that was being parsed.
const LARGE_FETCHED_BYTES: usize = 10_000_000;
const LARGE_PARSED_BYTES: usize = 50_000_000;

// This is a type-specific symbol provider layer, designed to
// wrap some inner provider and provide a type-safe caching layer
pub struct Caching<P> {
    inner: P,
    cache: Arc<Mutex<SymbolSetCache>>, // This inner cache is shared across providers
    parse_limiter: Option<ParseLimiter>,
}

// The parse memory budget is counted in MiB, because a tokio semaphore can acquire at most
// `u32::MAX` permits in one call.
const PARSE_BUDGET_UNIT_BYTES: usize = 1 << 20;

// Total byte budget for the cache of refused parses. Its keys contain event-controlled refs, so
// the cache is weighed by key size and not by entry count.
const REFUSED_PARSE_CACHE_MAX_WEIGHT: u64 = 16 * 1024 * 1024;

// Bounds the transient memory of large symbol set parses. A parse can need many times its
// decompressed size, and the cache budget does not count it. Each large parse reserves its
// estimated peak memory from a shared budget. It also reserves at least an equal share of the
// budget, so no more than `max_concurrent_large_parses` run at once. Clones share one budget,
// so a single limiter covers every provider it is given to.
//
// A parse of a known input size with an estimate above the whole budget is refused, because
// it can use more memory than the pod has free. The limiter remembers the refusal for
// `refusal_ttl`, so frames that use the same symbol set do not fetch it again. A parse of an
// unknown input size is never refused, because its estimate comes from the fetched size only.
// Such a parse reserves at most the whole budget and runs alone.
#[derive(Clone)]
pub struct ParseLimiter {
    large_parse_bytes: usize,
    memory_multiplier: usize,
    budget_bytes: usize,
    budget_units: u32,
    min_units: u32,
    permits: Arc<Semaphore>,
    // Maps a refused symbol set to the estimate that caused the refusal.
    refused: Cache<String, usize>,
}

impl ParseLimiter {
    pub fn new(
        large_parse_bytes: usize,
        max_concurrent_large_parses: usize,
        memory_budget_bytes: usize,
        memory_multiplier: usize,
        refusal_ttl: Duration,
    ) -> Self {
        assert!(
            large_parse_bytes > 0,
            "SYMBOL_SET_LARGE_PARSE_BYTES must be positive"
        );
        assert!(
            max_concurrent_large_parses > 0,
            "SYMBOL_SET_MAX_CONCURRENT_LARGE_PARSES must be positive"
        );
        assert!(
            memory_budget_bytes > 0,
            "SYMBOL_SET_PARSE_MEMORY_BUDGET_BYTES must be positive"
        );
        assert!(
            memory_multiplier > 0,
            "SYMBOL_SET_PARSE_MEMORY_MULTIPLIER must be positive"
        );
        let budget_units = units_for_bytes(memory_budget_bytes);
        let max_concurrent = u32::try_from(max_concurrent_large_parses).unwrap_or(u32::MAX);
        let refused = CacheBuilder::new(REFUSED_PARSE_CACHE_MAX_WEIGHT)
            .weigher(|key: &String, _: &usize| key.len().try_into().unwrap_or(u32::MAX))
            .time_to_live(refusal_ttl)
            .build();
        Self {
            large_parse_bytes,
            memory_multiplier,
            budget_bytes: memory_budget_bytes,
            budget_units,
            min_units: budget_units.div_ceil(max_concurrent),
            permits: Arc::new(Semaphore::new(budget_units as usize)),
            refused,
        }
    }

    // Returns None when the parse is small enough to skip the limiter. When the decompressed
    // size is unknown, the parse counts as large and at least as big as its fetched size.
    fn estimate_parse_bytes(
        &self,
        input_bytes: Option<usize>,
        fetched_bytes: usize,
    ) -> Option<usize> {
        let input_bytes = match input_bytes {
            Some(bytes) if bytes < self.large_parse_bytes => return None,
            Some(bytes) => bytes,
            None => fetched_bytes.max(self.large_parse_bytes),
        };
        Some(input_bytes.saturating_mul(self.memory_multiplier))
    }

    // Returns the estimate when the parse must be refused. Only a known input size can cause
    // a refusal.
    fn refused_estimate(
        &self,
        input_bytes: Option<usize>,
        estimated_bytes: Option<usize>,
    ) -> Option<usize> {
        input_bytes
            .and(estimated_bytes)
            .filter(|bytes| *bytes > self.budget_bytes)
    }

    fn refusal_error(&self, estimated_bytes: usize) -> ResolveError {
        FrameError::SymbolSetTooLarge {
            estimated_bytes,
            limit_bytes: self.budget_bytes,
        }
        .into()
    }

    async fn acquire(&self, estimated_bytes: Option<usize>) -> ParsePermit {
        let Some(estimated_bytes) = estimated_bytes else {
            return ParsePermit::none();
        };
        let units = units_for_bytes(estimated_bytes).clamp(self.min_units, self.budget_units);
        // UNWRAP - we never close the semaphore
        ParsePermit::limited(
            self.permits
                .clone()
                .acquire_many_owned(units)
                .await
                .unwrap(),
        )
    }
}

fn units_for_bytes(bytes: usize) -> u32 {
    u32::try_from(bytes.div_ceil(PARSE_BUDGET_UNIT_BYTES)).unwrap_or(u32::MAX)
}

impl<P> Caching<P>
// This where clause exists exclusively to give more obvious compiler errors in cases where
// the passed P doesn't cause Provider to be implemented for this Caching<P> - for example,
// if the P's P::Ref doesn't implement SymbolSetCacheKey
where
    P: Fetcher + Parser<Source = P::Fetched, Err = <P as Fetcher>::Err>,
    P::Ref: SymbolSetCacheKey + Send,
    P::Fetched: Countable + Send + 'static,
    P::Set: Countable + Any + Send + Sync,
    <P as Fetcher>::Err: From<ResolveError>,
{
    pub fn new(inner: P, cache: Arc<Mutex<SymbolSetCache>>) -> Self {
        Self {
            inner,
            cache,
            parse_limiter: None,
        }
    }

    pub fn with_parse_limiter(mut self, parse_limiter: ParseLimiter) -> Self {
        self.parse_limiter = Some(parse_limiter);
        self
    }
}

#[async_trait]
impl<P> Provider for Caching<P>
where
    P: Fetcher + Parser<Source = P::Fetched, Err = <P as Fetcher>::Err>,
    P::Ref: SymbolSetCacheKey + Send,
    P::Fetched: Countable + Send + 'static,
    P::Set: Countable + Any + Send + Sync,
    <P as Fetcher>::Err: From<ResolveError>,
{
    type Ref = P::Ref;
    type Set = P::Set;
    type Err = <P as Fetcher>::Err;

    async fn lookup(&self, team_id: i32, r: Self::Ref) -> Result<Arc<Self::Set>, Self::Err> {
        let mut cache = self.cache.lock().await;
        let cache_key = format!("{}:{}", team_id, r.symbol_set_cache_key());
        if let Some(set) = cache.get(&cache_key) {
            metrics::counter!(STORE_CACHE_HITS).increment(1);
            return Ok(set);
        }
        metrics::counter!(STORE_CACHE_MISSES).increment(1);
        drop(cache);

        let set_type = set_type_name::<P::Set>();
        let refused_key = format!("{set_type}:{cache_key}");
        if let Some(limiter) = &self.parse_limiter {
            if let Some(estimated_bytes) = limiter.refused.get(&refused_key).await {
                metrics::counter!(SYMBOL_SET_PARSE_REFUSED, "kind" => set_type, "cached" => "true")
                    .increment(1);
                return Err(limiter.refusal_error(estimated_bytes).into());
            }
        }

        // Do the fetch, not holding the lock across it to allow
        // concurrent fetches to occur. De-duping fetches is handled by the
        // `AtMostOne` provider wrapper in the production catalog.
        let found = self.inner.fetch(team_id, r).await?;
        let fetched_bytes = found.byte_count();

        let known_input_bytes = found.parse_input_bytes();
        let (found, parse_input_bytes) =
            if known_input_bytes.is_none() && self.parse_limiter.is_some() {
                measure_parse_input_bytes(found)
                    .await
                    .map_err(ResolveError::from)?
            } else {
                (found, known_input_bytes)
            };
        if let Some(bytes) = parse_input_bytes {
            metrics::histogram!(SYMBOL_SET_PARSE_INPUT_BYTES, "kind" => set_type)
                .record(bytes as f64);
        }
        let estimated_parse_bytes = self
            .parse_limiter
            .as_ref()
            .and_then(|limiter| limiter.estimate_parse_bytes(parse_input_bytes, fetched_bytes));

        if let Some(limiter) = &self.parse_limiter {
            if let Some(estimated_bytes) =
                limiter.refused_estimate(parse_input_bytes, estimated_parse_bytes)
            {
                limiter.refused.insert(refused_key, estimated_bytes).await;
                metrics::counter!(SYMBOL_SET_PARSE_REFUSED, "kind" => set_type, "cached" => "false")
                    .increment(1);
                warn!(
                    team_id,
                    cache_key,
                    set_type,
                    fetched_bytes,
                    parse_input_bytes,
                    estimated_parse_bytes = estimated_bytes,
                    budget_bytes = limiter.budget_bytes,
                    "Refusing symbol set parse above the parse memory budget"
                );
                return Err(limiter.refusal_error(estimated_bytes).into());
            }
        }

        let wait_start = Instant::now();
        let permit = match &self.parse_limiter {
            Some(limiter) => limiter.acquire(estimated_parse_bytes).await,
            None => ParsePermit::none(),
        };
        let wait_ms = wait_start.elapsed().as_millis() as u64;
        if permit.is_limited() {
            metrics::histogram!(SYMBOL_SET_LARGE_PARSE_WAIT_MS).record(wait_ms as f64);
        }

        let log_large_parse = fetched_bytes >= LARGE_FETCHED_BYTES
            || parse_input_bytes.is_some_and(|bytes| bytes >= LARGE_PARSED_BYTES);
        if log_large_parse {
            info!(
                team_id,
                cache_key,
                set_type,
                fetched_bytes,
                parse_input_bytes,
                estimated_parse_bytes,
                wait_ms,
                "Parsing large symbol set"
            );
        }
        let parse_start = Instant::now();
        let parsed = self.inner.parse(found, permit).await?;
        let bytes = parsed.byte_count();
        if log_large_parse || bytes >= LARGE_PARSED_BYTES {
            info!(
                team_id,
                cache_key,
                set_type,
                fetched_bytes,
                parse_input_bytes,
                estimated_parse_bytes,
                cached_bytes = bytes,
                parse_ms = parse_start.elapsed().as_millis() as u64,
                "Parsed large symbol set"
            );
        }

        let mut cache = self.cache.lock().await; // Re-acquire the cache-wide lock to insert, dropping the ref_lock

        let parsed = Arc::new(parsed);
        cache.insert(cache_key, parsed.clone(), bytes);
        Ok(parsed)
    }
}

// This is a cache shared across multiple symbol set providers, through the `Caching` above,
// such that two totally different "layers" can share an underlying "pool" of cache space. This
// is injected into the `Caching` layer at construct time, to allow this sharing across multiple
// provider layer "stacks" within the catalog.
pub struct SymbolSetCache {
    // We expect this cache to consist of few, but large, items.
    // TODO - handle cases where two CachedSymbolSets have identical keys but different types
    cached: HashMap<String, CachedSymbolSet>,
    held_bytes: usize,
    max_bytes: usize,
}

impl SymbolSetCache {
    pub fn new(max_bytes: usize) -> Self {
        Self {
            cached: HashMap::new(),
            held_bytes: 0,
            max_bytes,
        }
    }

    pub fn insert<T>(&mut self, key: String, value: Arc<T>, bytes: usize)
    where
        T: Any + Send + Sync,
    {
        if let Some(old) = self.cached.remove(&key) {
            self.held_bytes = self.held_bytes.saturating_sub(old.bytes);
        }
        self.held_bytes += bytes;
        self.cached.insert(
            key,
            CachedSymbolSet {
                data: value,
                bytes,
                last_used: Instant::now(),
            },
        );

        self.evict();
    }

    pub fn get<T>(&mut self, key: &str) -> Option<Arc<T>>
    where
        T: Any + Send + Sync,
    {
        let held = self.cached.get_mut(key)?;
        held.last_used = Instant::now();
        held.data.clone().downcast().ok()
    }

    fn evict(&mut self) {
        if self.held_bytes <= self.max_bytes {
            metrics::gauge!(STORE_CACHED_BYTES).set(self.held_bytes as f64);
            return;
        }

        metrics::counter!(STORE_CACHE_EVICTION_RUNS).increment(1);

        let mut vals: Vec<_> = self.cached.iter().collect();

        // Sort to oldest-last, then pop until we're below the water line
        vals.sort_unstable_by_key(|(_, v)| v.last_used);
        vals.reverse();

        // We're borrowing all these refs from the hashmap, so we collect here to
        // remove them in a separate pass.
        let mut to_remove = vec![];
        while self.held_bytes > self.max_bytes && !vals.is_empty() {
            // We can unwrap here because we know we're not empty from the line above (and
            // really, even the !empty check could be skipped - if held_bytes is non-zero, we
            // must have at least one element in vals)
            let (to_remove_key, to_remove_val) = vals.pop().unwrap();
            self.held_bytes -= to_remove_val.bytes;
            to_remove.push(to_remove_key.clone());
        }

        for key in to_remove {
            metrics::counter!(STORE_CACHE_EVICTIONS).increment(1);
            self.cached.remove(&key);
        }

        metrics::gauge!(STORE_CACHED_BYTES).set(self.held_bytes as f64);
    }
}

struct CachedSymbolSet {
    pub data: Arc<dyn Any + Send + Sync>,
    pub bytes: usize,
    pub last_used: Instant,
}

pub trait Countable {
    fn byte_count(&self) -> usize;

    // The size of the data the parser works on, after any decompression. None means unknown.
    fn parse_input_bytes(&self) -> Option<usize> {
        Some(self.byte_count())
    }

    // Like `parse_input_bytes`, but it can decode the data to find a size that is not stored.
    // It can be slow, so call it from a blocking thread.
    fn measure_parse_input_bytes(&self) -> Option<usize> {
        self.parse_input_bytes()
    }
}

impl Countable for Vec<u8> {
    fn byte_count(&self) -> usize {
        self.len()
    }
}

impl Countable for Bytes {
    fn byte_count(&self) -> usize {
        self.len()
    }

    fn parse_input_bytes(&self) -> Option<usize> {
        match posthog_symbol_data::symbol_data_known_decompressed_size(self) {
            Ok(Some(size)) => Some(size.max(self.len())),
            Ok(None) | Err(_) => None,
        }
    }

    fn measure_parse_input_bytes(&self) -> Option<usize> {
        posthog_symbol_data::symbol_data_decompressed_size(self)
            .ok()
            .map(|size| size.max(self.len()))
    }
}

// Measuring can decode the whole payload, so it runs on a blocking thread and not on a tokio
// worker.
async fn measure_parse_input_bytes<F>(found: F) -> Result<(F, Option<usize>), UnhandledError>
where
    F: Countable + Send + 'static,
{
    tokio::task::spawn_blocking(move || {
        let bytes = found.measure_parse_input_bytes();
        (found, bytes)
    })
    .await
    .map_err(|e| UnhandledError::Other(format!("symbol set measure task failed: {e}")))
}

fn set_type_name<T>() -> &'static str {
    let name = std::any::type_name::<T>();
    name.rsplit("::").next().unwrap_or(name)
}

#[cfg(test)]
mod tests {
    use std::{
        io::{Cursor, Write},
        sync::atomic::{AtomicUsize, Ordering},
        sync::{Arc, Condvar, Mutex as StdMutex},
    };

    use super::*;
    use crate::symbolication::symbol_store::chunk_id::OrChunkId;
    use async_trait::async_trait;
    use posthog_symbol_data::{write_symbol_data, SourceAndMap};
    use reqwest::Url;

    struct FakeProvider {
        fetches: Arc<AtomicUsize>,
    }

    #[async_trait]
    impl Fetcher for FakeProvider {
        type Ref = OrChunkId<Url>;
        type Fetched = Vec<u8>;
        type Err = ResolveError;

        async fn fetch(&self, _team_id: i32, r: Self::Ref) -> Result<Self::Fetched, Self::Err> {
            self.fetches.fetch_add(1, Ordering::SeqCst);
            let data = match r {
                OrChunkId::Inner(_) => b"inner".to_vec(),
                OrChunkId::ChunkId(_) => b"chunk-id".to_vec(),
                OrChunkId::Both { .. } => b"both".to_vec(),
            };
            Ok(data)
        }
    }

    #[async_trait]
    impl Parser for FakeProvider {
        type Source = Vec<u8>;
        type Set = Vec<u8>;
        type Err = ResolveError;

        async fn parse(
            &self,
            data: Self::Source,
            _permit: ParsePermit,
        ) -> Result<Self::Set, Self::Err> {
            Ok(data)
        }
    }

    #[tokio::test]
    async fn caching_does_not_share_both_and_chunk_id_keys() {
        let fetches = Arc::new(AtomicUsize::new(0));
        let provider = FakeProvider {
            fetches: fetches.clone(),
        };
        let cache = Arc::new(Mutex::new(SymbolSetCache::new(1024)));
        let caching = Caching::new(provider, cache);

        let chunk_id = "chunk-id-1".to_string();
        let url = Url::parse("https://example.com/static/chunk.js").unwrap();

        let both = caching
            .lookup(1, OrChunkId::both(url, chunk_id.clone()))
            .await
            .unwrap();
        let chunk_only = caching
            .lookup(1, OrChunkId::<Url>::chunk_id(chunk_id))
            .await
            .unwrap();

        assert_eq!(both.as_ref(), b"both");
        assert_eq!(chunk_only.as_ref(), b"chunk-id");
        assert_eq!(fetches.load(Ordering::SeqCst), 2);
    }

    struct SizedProvider {
        fetched_bytes: usize,
        in_flight: Arc<AtomicUsize>,
        max_in_flight: Arc<AtomicUsize>,
    }

    #[async_trait]
    impl Fetcher for SizedProvider {
        type Ref = OrChunkId<Url>;
        type Fetched = Vec<u8>;
        type Err = ResolveError;

        async fn fetch(&self, _team_id: i32, _r: Self::Ref) -> Result<Self::Fetched, Self::Err> {
            Ok(vec![0; self.fetched_bytes])
        }
    }

    #[async_trait]
    impl Parser for SizedProvider {
        type Source = Vec<u8>;
        type Set = Vec<u8>;
        type Err = ResolveError;

        async fn parse(
            &self,
            data: Self::Source,
            permit: ParsePermit,
        ) -> Result<Self::Set, Self::Err> {
            let _permit = permit;
            let now = self.in_flight.fetch_add(1, Ordering::SeqCst) + 1;
            self.max_in_flight.fetch_max(now, Ordering::SeqCst);
            for _ in 0..5 {
                tokio::task::yield_now().await;
            }
            self.in_flight.fetch_sub(1, Ordering::SeqCst);
            Ok(data)
        }
    }

    struct BlockingProvider {
        active: Arc<AtomicUsize>,
        started: tokio::sync::mpsc::UnboundedSender<()>,
        release: Arc<(StdMutex<bool>, Condvar)>,
    }

    #[async_trait]
    impl Fetcher for BlockingProvider {
        type Ref = OrChunkId<Url>;
        type Fetched = Vec<u8>;
        type Err = ResolveError;

        async fn fetch(&self, _team_id: i32, _r: Self::Ref) -> Result<Self::Fetched, Self::Err> {
            Ok(vec![0])
        }
    }

    #[async_trait]
    impl Parser for BlockingProvider {
        type Source = Vec<u8>;
        type Set = Vec<u8>;
        type Err = ResolveError;

        async fn parse(
            &self,
            data: Self::Source,
            permit: ParsePermit,
        ) -> Result<Self::Set, Self::Err> {
            let active = self.active.clone();
            let started = self.started.clone();
            let release = self.release.clone();

            Ok(tokio::task::spawn_blocking(move || {
                let _permit = permit;
                active.fetch_add(1, Ordering::SeqCst);
                started.send(()).unwrap();

                let (lock, condvar) = &*release;
                let mut released = lock.lock().unwrap();
                while !*released {
                    released = condvar.wait(released).unwrap();
                }

                active.fetch_sub(1, Ordering::SeqCst);
                data
            })
            .await
            .unwrap())
        }
    }

    #[tokio::test(flavor = "current_thread")]
    async fn parse_limiter_bounds_large_parses_by_count_and_memory() {
        // (fetched_bytes, max_concurrent, memory_multiplier, expected_max). The budget is
        // 3 MiB, so a 100 byte input times 20_000 estimates 2 MiB and runs alone.
        for (fetched_bytes, max_concurrent, memory_multiplier, expected_max) in [
            (100, 1, 1, 1),
            (99, 1, 1, 3),
            (100, 2, 1, 1),
            (100, 3, 1, 3),
            (100, 3, 20_000, 1),
        ] {
            let max_in_flight = Arc::new(AtomicUsize::new(0));
            let provider = SizedProvider {
                fetched_bytes,
                in_flight: Arc::new(AtomicUsize::new(0)),
                max_in_flight: max_in_flight.clone(),
            };
            let cache = Arc::new(Mutex::new(SymbolSetCache::new(1 << 20)));
            let caching = Caching::new(provider, cache).with_parse_limiter(ParseLimiter::new(
                100,
                max_concurrent,
                3 << 20,
                memory_multiplier,
                Duration::from_secs(60),
            ));

            futures::future::join_all(
                (0..3).map(|i| caching.lookup(1, OrChunkId::<Url>::chunk_id(format!("set-{i}")))),
            )
            .await;

            assert_eq!(
                max_in_flight.load(Ordering::SeqCst),
                expected_max,
                "fetched_bytes = {fetched_bytes}, max_concurrent = {max_concurrent}, \
                 memory_multiplier = {memory_multiplier}"
            );
        }

        let compressed = Bytes::from(
            write_symbol_data(SourceAndMap {
                minified_source: "a".repeat(100),
                sourcemap: "b".repeat(100),
            })
            .unwrap(),
        );
        assert!(compressed.len() < 100);
        assert!(compressed.parse_input_bytes().unwrap() >= 200);

        let mut raw_zip = Cursor::new(Vec::new());
        {
            let mut writer = zip::ZipWriter::new(&mut raw_zip);
            writer
                .start_file("symbols", zip::write::SimpleFileOptions::default())
                .unwrap();
            writer.write_all(b"symbols").unwrap();
            writer.finish().unwrap();
        }
        let raw_zip = Bytes::from(raw_zip.into_inner());
        assert_eq!(raw_zip.parse_input_bytes(), None);
    }

    struct PayloadProvider {
        payload: Bytes,
        fetches: Arc<AtomicUsize>,
    }

    #[async_trait]
    impl Fetcher for PayloadProvider {
        type Ref = OrChunkId<Url>;
        type Fetched = Bytes;
        type Err = ResolveError;

        async fn fetch(&self, _team_id: i32, _r: Self::Ref) -> Result<Self::Fetched, Self::Err> {
            self.fetches.fetch_add(1, Ordering::SeqCst);
            Ok(self.payload.clone())
        }
    }

    #[async_trait]
    impl Parser for PayloadProvider {
        type Source = Bytes;
        type Set = Bytes;
        type Err = ResolveError;

        async fn parse(
            &self,
            data: Self::Source,
            _permit: ParsePermit,
        ) -> Result<Self::Set, Self::Err> {
            Ok(data)
        }
    }

    #[tokio::test]
    async fn parse_limiter_refuses_known_parses_above_budget() {
        let source_and_map = SourceAndMap {
            minified_source: "a".repeat(1000),
            sourcemap: "b".repeat(1000),
        };
        let with_size = Bytes::from(write_symbol_data(source_and_map.clone()).unwrap());

        // Older writers made zstd frames with no content size in the header. The container
        // header is the magic, the version, the type and the compression byte.
        let header_len = b"posthog_error_tracking".len() + 4 + 4 + 1;
        let raw = posthog_symbol_data::write_symbol_data_uncompressed(source_and_map).unwrap();
        let mut encoder = zstd::Encoder::new(Vec::new(), 3).unwrap();
        encoder.write_all(&raw[header_len..]).unwrap();
        let mut without_size = with_size[..header_len].to_vec();
        without_size.extend(encoder.finish().unwrap());
        let without_size = Bytes::from(without_size);
        assert_eq!(without_size.parse_input_bytes(), None);

        let mut raw_zip = Cursor::new(Vec::new());
        {
            let mut writer = zip::ZipWriter::new(&mut raw_zip);
            writer
                .start_file("symbols", zip::write::SimpleFileOptions::default())
                .unwrap();
            writer.write_all(&[0; 1000]).unwrap();
            writer.finish().unwrap();
        }
        let raw_zip = Bytes::from(raw_zip.into_inner());

        // The budget is 1 MiB. A 2000 byte input times 1000 estimates about 2 MB.
        for (name, payload, memory_multiplier, refused) in [
            ("known size", with_size.clone(), 1000, true),
            ("measured size", without_size, 1000, true),
            ("known size within budget", with_size, 100, false),
            ("unknown size", raw_zip, 10_000, false),
        ] {
            let fetches = Arc::new(AtomicUsize::new(0));
            let provider = PayloadProvider {
                payload,
                fetches: fetches.clone(),
            };
            let caching =
                Caching::new(provider, Arc::new(Mutex::new(SymbolSetCache::new(1 << 20))))
                    .with_parse_limiter(ParseLimiter::new(
                        1,
                        1,
                        1 << 20,
                        memory_multiplier,
                        Duration::from_secs(60),
                    ));

            for _ in 0..2 {
                let result = caching
                    .lookup(1, OrChunkId::<Url>::chunk_id("set".to_string()))
                    .await;
                assert_eq!(
                    matches!(
                        result,
                        Err(ResolveError::ResolutionError(
                            FrameError::SymbolSetTooLarge { .. }
                        ))
                    ),
                    refused,
                    "{name}: {result:?}"
                );
            }
            assert_eq!(fetches.load(Ordering::SeqCst), 1, "{name}");
        }
    }

    #[tokio::test]
    async fn cancelled_lookup_keeps_permit_until_blocking_parse_finishes() {
        let active = Arc::new(AtomicUsize::new(0));
        let (started_tx, mut started_rx) = tokio::sync::mpsc::unbounded_channel();
        let release = Arc::new((StdMutex::new(false), Condvar::new()));
        let provider = BlockingProvider {
            active: active.clone(),
            started: started_tx,
            release: release.clone(),
        };
        let limiter = ParseLimiter::new(1, 1, 1 << 20, 1, Duration::from_secs(60));
        let caching = Arc::new(
            Caching::new(provider, Arc::new(Mutex::new(SymbolSetCache::new(1024))))
                .with_parse_limiter(limiter.clone()),
        );

        let lookup = tokio::spawn({
            let caching = caching.clone();
            async move {
                caching
                    .lookup(1, OrChunkId::<Url>::chunk_id("set".to_string()))
                    .await
            }
        });
        started_rx.recv().await.unwrap();
        lookup.abort();
        assert!(lookup.await.unwrap_err().is_cancelled());

        assert_eq!(active.load(Ordering::SeqCst), 1);
        assert_eq!(limiter.permits.available_permits(), 0);

        let (lock, condvar) = &*release;
        *lock.lock().unwrap() = true;
        condvar.notify_one();
        let released_permit = limiter.permits.clone().acquire_owned().await.unwrap();

        assert_eq!(active.load(Ordering::SeqCst), 0);
        drop(released_permit);
        assert_eq!(limiter.permits.available_permits(), 1);
    }

    #[test]
    fn replacing_cache_entry_keeps_held_bytes_accurate() {
        let mut cache = SymbolSetCache::new(10);

        cache.insert("key".to_string(), Arc::new(vec![0; 6]), 6);
        cache.insert("key".to_string(), Arc::new(vec![0; 6]), 6);

        assert_eq!(cache.held_bytes, 6);
        assert_eq!(cache.cached.len(), 1);
    }
}
