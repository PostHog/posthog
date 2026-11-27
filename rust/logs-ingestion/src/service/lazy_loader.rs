//! Loader retries are not ported, because the logs servers build their loaders without `loaderRetry`.

use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use futures::future::{BoxFuture, FutureExt, Shared};
use rand::Rng;

use crate::pipeline::DependencyUnavailableError;

pub type LoadResult<V> = anyhow::Result<HashMap<String, Option<V>>>;
pub type Loader<V> = Arc<dyn Fn(Vec<String>) -> BoxFuture<'static, LoadResult<V>> + Send + Sync>;
type SharedLoad = Shared<BoxFuture<'static, Result<(), Arc<anyhow::Error>>>>;

#[derive(Clone)]
pub struct LazyLoaderOptions {
    pub name: &'static str,
    pub refresh_age: Duration,
    pub refresh_null_age: Option<Duration>,
    pub background_age: Option<Duration>,
    pub jitter: Option<Duration>,
    pub buffer: Duration,
    pub max_size: usize,
}

impl LazyLoaderOptions {
    pub fn new(name: &'static str, refresh_age: Duration) -> Self {
        Self {
            name,
            refresh_age,
            refresh_null_age: None,
            background_age: None,
            jitter: None,
            buffer: Duration::from_millis(10),
            max_size: 100_000,
        }
    }
}

struct Entry<V> {
    value: Option<V>,
    last_used: Instant,
    /// `None` after `mark_for_refresh`.
    cache_until: Option<Instant>,
    background_after: Option<Instant>,
}

struct State<V> {
    cache: HashMap<String, Entry<V>>,
    pending: HashMap<String, SharedLoad>,
    buffer: Option<(HashSet<String>, SharedLoad)>,
}

struct Inner<V> {
    options: LazyLoaderOptions,
    loader: Loader<V>,
    state: Mutex<State<V>>,
}

pub struct LazyLoader<V> {
    inner: Arc<Inner<V>>,
}

impl<V> Clone for LazyLoader<V> {
    fn clone(&self) -> Self {
        Self {
            inner: self.inner.clone(),
        }
    }
}

/// Keeps `DependencyUnavailableError` recognisable after the error went through a shared load.
fn rebuild_error(error: &anyhow::Error) -> anyhow::Error {
    match error.downcast_ref::<DependencyUnavailableError>() {
        Some(e) => anyhow::Error::new(e.clone()),
        None => anyhow::anyhow!("{error:#}"),
    }
}

impl<V: Clone + Send + Sync + 'static> LazyLoader<V> {
    pub fn new(options: LazyLoaderOptions, loader: Loader<V>) -> Self {
        Self {
            inner: Arc::new(Inner {
                options,
                loader,
                state: Mutex::new(State {
                    cache: HashMap::new(),
                    pending: HashMap::new(),
                    buffer: None,
                }),
            }),
        }
    }

    pub async fn get(&self, key: &str) -> anyhow::Result<Option<V>> {
        let wait = {
            let mut state = self.inner.state.lock().unwrap();
            let now = Instant::now();
            if let Some(entry) = state.cache.get_mut(key) {
                entry.last_used = now;
                if entry.cache_until.is_some_and(|until| now <= until) {
                    let value = entry.value.clone();
                    if entry.background_after.is_none_or(|b| now <= b) {
                        return Ok(value);
                    }
                    let load = self.load_locked(&mut state, key);
                    let name = self.inner.options.name;
                    let key = key.to_string();
                    tokio::spawn(async move {
                        if let Err(error) = load.await {
                            tracing::warn!(loader = name, key, error = %error, "LazyLoader background refresh failed");
                        }
                    });
                    return Ok(value);
                }
            }
            self.load_locked(&mut state, key)
        };
        if let Err(error) = wait.await {
            return Err(rebuild_error(&error));
        }
        let state = self.inner.state.lock().unwrap();
        Ok(state.cache.get(key).and_then(|e| e.value.clone()))
    }

    /// The next lookup reloads before it returns.
    pub fn mark_for_refresh(&self, keys: &[String]) {
        let mut state = self.inner.state.lock().unwrap();
        for key in keys {
            if let Some(entry) = state.cache.get_mut(key) {
                entry.cache_until = None;
                entry.background_after = None;
            }
        }
    }

    fn load_locked(&self, state: &mut State<V>, key: &str) -> SharedLoad {
        if let Some(pending) = state.pending.get(key) {
            return pending.clone();
        }
        let load = match &mut state.buffer {
            Some((keys, load)) => {
                keys.insert(key.to_string());
                load.clone()
            }
            None => {
                let load = self.spawn_buffer();
                let mut keys = HashSet::new();
                keys.insert(key.to_string());
                state.buffer = Some((keys, load.clone()));
                load
            }
        };
        state.pending.insert(key.to_string(), load.clone());
        load
    }

    fn spawn_buffer(&self) -> SharedLoad {
        let inner = self.inner.clone();
        let task = tokio::spawn(async move {
            tokio::time::sleep(inner.options.buffer).await;
            let keys: Vec<String> = {
                let mut state = inner.state.lock().unwrap();
                state
                    .buffer
                    .take()
                    .map(|(k, _)| k.into_iter().collect())
                    .unwrap_or_default()
            };
            let result = (inner.loader)(keys.clone()).await;
            let mut state = inner.state.lock().unwrap();
            for key in &keys {
                state.pending.remove(key);
            }
            match result {
                Ok(mut loaded) => {
                    for key in keys {
                        loaded.entry(key).or_insert(None);
                    }
                    set_values(&inner.options, &mut state, loaded);
                    Ok(())
                }
                Err(e) => Err(Arc::new(e)),
            }
        });
        async move {
            match task.await {
                Ok(r) => r,
                Err(e) => Err(Arc::new(anyhow::anyhow!("lazy loader task failed: {e}"))),
            }
        }
        .boxed()
        .shared()
    }
}

fn set_values<V>(
    options: &LazyLoaderOptions,
    state: &mut State<V>,
    loaded: HashMap<String, Option<V>>,
) {
    let now = Instant::now();
    let jitter_max = options.jitter.unwrap_or(options.refresh_age / 5);
    let null_age = options.refresh_null_age.unwrap_or(options.refresh_age);
    let mut rng = rand::thread_rng();
    for (key, value) in loaded {
        let jitter = if jitter_max.is_zero() {
            Duration::ZERO
        } else {
            Duration::from_millis(rng.gen_range(0..jitter_max.as_millis().max(1) as u64))
        };
        let age = if value.is_none() {
            null_age
        } else {
            options.refresh_age
        };
        let background_after = options
            .background_age
            .map(|b| now + if value.is_none() { null_age } else { b } + jitter);
        state.cache.insert(
            key,
            Entry {
                value,
                last_used: now,
                cache_until: Some(now + age + jitter),
                background_after,
            },
        );
    }
    if state.cache.len() > options.max_size {
        let headroom = if options.max_size > 100 {
            options.max_size.div_ceil(10)
        } else {
            0
        };
        let evict = state.cache.len() - options.max_size + headroom;
        let mut keys: Vec<(Instant, String)> = state
            .cache
            .iter()
            .map(|(k, e)| (e.last_used, k.clone()))
            .collect();
        keys.sort();
        for (_, key) in keys.into_iter().take(evict) {
            state.cache.remove(&key);
        }
    }
    metrics::gauge!("lazy_loader_cache_size", "name" => options.name).set(state.cache.len() as f64);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    fn counting_loader(calls: Arc<Mutex<Vec<Vec<String>>>>) -> Loader<String> {
        Arc::new(move |mut keys: Vec<String>| {
            keys.sort();
            calls.lock().unwrap().push(keys.clone());
            async move {
                Ok(keys
                    .into_iter()
                    .map(|k| {
                        let v = (k != "missing").then(|| format!("v-{k}"));
                        (k, v)
                    })
                    .collect())
            }
            .boxed()
        })
    }

    #[tokio::test]
    async fn concurrent_misses_share_one_buffered_load_and_hits_skip_it() {
        let calls = Arc::new(Mutex::new(Vec::new()));
        let loader = LazyLoader::new(
            LazyLoaderOptions::new("t", Duration::from_secs(60)),
            counting_loader(calls.clone()),
        );
        let (a, b, c) = tokio::join!(loader.get("a"), loader.get("b"), loader.get("a"));
        assert_eq!(a.unwrap().as_deref(), Some("v-a"));
        assert_eq!(b.unwrap().as_deref(), Some("v-b"));
        assert_eq!(c.unwrap().as_deref(), Some("v-a"));
        assert_eq!(loader.get("missing").await.unwrap(), None);
        assert_eq!(loader.get("missing").await.unwrap(), None);
        assert_eq!(loader.get("a").await.unwrap().as_deref(), Some("v-a"));
        assert_eq!(
            *calls.lock().unwrap(),
            vec![
                vec!["a".to_string(), "b".to_string()],
                vec!["missing".to_string()]
            ]
        );
        loader.mark_for_refresh(&["a".to_string()]);
        loader.get("a").await.unwrap();
        assert_eq!(calls.lock().unwrap().len(), 3);
    }

    #[tokio::test]
    async fn a_failed_load_reaches_every_waiter_and_is_not_cached() {
        let attempts = Arc::new(AtomicUsize::new(0));
        let a = attempts.clone();
        let loader: LazyLoader<String> = LazyLoader::new(
            LazyLoaderOptions::new("t", Duration::from_secs(60)),
            Arc::new(move |_keys| {
                a.fetch_add(1, Ordering::SeqCst);
                async move {
                    Err(anyhow::Error::new(DependencyUnavailableError {
                        message: "down".into(),
                        dependency_name: "Postgres".into(),
                    }))
                }
                .boxed()
            }),
        );
        let (x, y) = tokio::join!(loader.get("a"), loader.get("a"));
        assert!(crate::pipeline::errors::is_dependency_unavailable(
            &x.unwrap_err()
        ));
        assert!(y.is_err());
        assert!(loader.get("a").await.is_err());
        assert_eq!(attempts.load(Ordering::SeqCst), 2);
    }
}
