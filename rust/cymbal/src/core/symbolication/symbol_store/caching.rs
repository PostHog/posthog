use std::{any::Any, collections::HashMap, sync::Arc, time::Instant};

use async_trait::async_trait;
use bytes::Bytes;
use tokio::sync::{Mutex, Semaphore};
use tracing::info;

use crate::metric_consts::{
    STORE_CACHED_BYTES, STORE_CACHE_EVICTIONS, STORE_CACHE_EVICTION_RUNS, STORE_CACHE_HITS,
    STORE_CACHE_MISSES, SYMBOL_SET_LARGE_PARSE_WAIT_MS,
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

// Bounds how many large symbol sets are parsed at once. A parse can need many times the
// fetched size in transient memory, and the cache budget does not count it. Clones share
// one set of permits, so a single limiter covers every provider it is given to.
#[derive(Clone)]
pub struct ParseLimiter {
    large_parse_bytes: usize,
    permits: Arc<Semaphore>,
}

impl ParseLimiter {
    pub fn new(large_parse_bytes: usize, max_concurrent_large_parses: usize) -> Self {
        Self {
            large_parse_bytes,
            permits: Arc::new(Semaphore::new(max_concurrent_large_parses.max(1))),
        }
    }

    async fn acquire(&self, required: bool) -> ParsePermit {
        if !required {
            return ParsePermit::none();
        }
        // UNWRAP - we never close the semaphore
        ParsePermit::limited(self.permits.clone().acquire_owned().await.unwrap())
    }
}

impl<P> Caching<P>
// This where clause exists exclusively to give more obvious compiler errors in cases where
// the passed P doesn't cause Provider to be implemented for this Caching<P> - for example,
// if the P's P::Ref doesn't implement SymbolSetCacheKey
where
    P: Fetcher + Parser<Source = P::Fetched, Err = <P as Fetcher>::Err>,
    P::Ref: SymbolSetCacheKey + Send,
    P::Fetched: Countable + Send,
    P::Set: Countable + Any + Send + Sync,
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
    P::Fetched: Countable + Send,
    P::Set: Countable + Any + Send + Sync,
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

        // Do the fetch, not holding the lock across it to allow
        // concurrent fetches to occur. De-duping fetches is handled by the
        // `AtMostOne` provider wrapper in the production catalog.
        let found = self.inner.fetch(team_id, r).await?;
        let fetched_bytes = found.byte_count();
        let set_type = set_type_name::<P::Set>();

        let wait_start = Instant::now();
        let permit = match &self.parse_limiter {
            Some(limiter) => {
                let required = found.requires_parse_permit(limiter.large_parse_bytes);
                limiter.acquire(required).await
            }
            None => ParsePermit::none(),
        };
        let wait_ms = wait_start.elapsed().as_millis() as u64;
        if permit.is_limited() {
            metrics::histogram!(SYMBOL_SET_LARGE_PARSE_WAIT_MS).record(wait_ms as f64);
        }

        if fetched_bytes >= LARGE_FETCHED_BYTES {
            info!(
                team_id,
                cache_key, set_type, fetched_bytes, wait_ms, "Parsing large symbol set"
            );
        }
        let parse_start = Instant::now();
        let parsed = self.inner.parse(found, permit).await?;
        let bytes = parsed.byte_count();
        if fetched_bytes >= LARGE_FETCHED_BYTES || bytes >= LARGE_PARSED_BYTES {
            info!(
                team_id,
                cache_key,
                set_type,
                fetched_bytes,
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

    fn requires_parse_permit(&self, threshold: usize) -> bool {
        self.byte_count() >= threshold
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

    fn requires_parse_permit(&self, threshold: usize) -> bool {
        match posthog_symbol_data::symbol_data_known_decompressed_size(self) {
            Ok(Some(size)) => size.max(self.len()) >= threshold,
            Ok(None) | Err(_) => true,
        }
    }
}

fn set_type_name<T>() -> &'static str {
    let name = std::any::type_name::<T>();
    name.rsplit("::").next().unwrap_or(name)
}

#[cfg(test)]
mod tests {
    use std::{
        convert::Infallible,
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
        type Err = Infallible;

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
        type Err = Infallible;

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
        type Err = Infallible;

        async fn fetch(&self, _team_id: i32, _r: Self::Ref) -> Result<Self::Fetched, Self::Err> {
            Ok(vec![0; self.fetched_bytes])
        }
    }

    #[async_trait]
    impl Parser for SizedProvider {
        type Source = Vec<u8>;
        type Set = Vec<u8>;
        type Err = Infallible;

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
        type Err = Infallible;

        async fn fetch(&self, _team_id: i32, _r: Self::Ref) -> Result<Self::Fetched, Self::Err> {
            Ok(vec![0])
        }
    }

    #[async_trait]
    impl Parser for BlockingProvider {
        type Source = Vec<u8>;
        type Set = Vec<u8>;
        type Err = Infallible;

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
    async fn parse_limiter_bounds_only_large_parses() {
        for (fetched_bytes, expected_max) in [(100, 1), (99, 3)] {
            let max_in_flight = Arc::new(AtomicUsize::new(0));
            let provider = SizedProvider {
                fetched_bytes,
                in_flight: Arc::new(AtomicUsize::new(0)),
                max_in_flight: max_in_flight.clone(),
            };
            let cache = Arc::new(Mutex::new(SymbolSetCache::new(1 << 20)));
            let caching =
                Caching::new(provider, cache).with_parse_limiter(ParseLimiter::new(100, 1));

            futures::future::join_all(
                (0..3).map(|i| caching.lookup(1, OrChunkId::<Url>::chunk_id(format!("set-{i}")))),
            )
            .await;

            assert_eq!(
                max_in_flight.load(Ordering::SeqCst),
                expected_max,
                "fetched_bytes = {fetched_bytes}"
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
        assert!(compressed.requires_parse_permit(100));

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
        assert!(raw_zip.requires_parse_permit(raw_zip.len() + 1));
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
        let limiter = ParseLimiter::new(1, 1);
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
