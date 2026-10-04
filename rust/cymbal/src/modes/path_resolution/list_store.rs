//! Django writes one list object per team, repo and commit, and never changes it afterwards
//! (`products/error_tracking/backend/logic/repo_paths/storage.py`), so cached lists need no TTL.

use std::io::Read;
use std::sync::Arc;
use std::time::{Duration, Instant};

use moka::future::Cache;
use tracing::warn;

use crate::core::metric_consts::{
    PATH_RESOLUTION_CACHE_BYTES, PATH_RESOLUTION_LIST_CACHE, PATH_RESOLUTION_LIST_LOAD_SECONDS,
};
use crate::core::symbolication::symbol_store::BlobClient;

use super::file_index::FileIndex;

// Bounds the memory of the negative cache when many requests name commits that have no list.
const MAX_NEGATIVE_ENTRIES: u64 = 100_000;

#[derive(Clone, Debug, Hash, PartialEq, Eq)]
pub struct ListKey {
    pub team_id: i64,
    pub repo: String,
    pub commit: String,
}

impl ListKey {
    pub fn object_key(&self, folder: &str) -> String {
        format!(
            "{folder}/v1/{}/{}/{}.zst",
            self.team_id, self.repo, self.commit
        )
    }
}

pub enum ListLookup {
    Loaded(Arc<FileIndex>),
    Missing,
    Error,
}

#[derive(Debug, thiserror::Error)]
pub enum LoadError {
    #[error("no file list is stored for this key")]
    NotFound,
    #[error("object storage failed: {0}")]
    Storage(String),
    #[error("object storage did not answer in time")]
    Timeout,
    #[error("the file list is larger than the decompression limit")]
    TooLarge,
    #[error("the file list cannot be read: {0}")]
    Corrupt(String),
}

#[derive(Clone, Copy)]
enum Negative {
    Missing,
    Unreadable,
}

#[derive(Clone)]
pub struct ListStoreConfig {
    pub bucket: String,
    pub folder: String,
    pub cache_bytes: u64,
    pub negative_ttl: Duration,
    pub max_decompressed_bytes: usize,
    pub load_timeout: Duration,
}

pub struct ListStore {
    blob: Arc<dyn BlobClient>,
    config: ListStoreConfig,
    lists: Cache<ListKey, Arc<FileIndex>>,
    // Keys with no object, or with an object that cannot be read. Both answers can change only
    // when Django writes the object, so they are remembered for a short time only.
    negative: Cache<ListKey, Negative>,
}

impl ListStore {
    pub fn new(blob: Arc<dyn BlobClient>, config: ListStoreConfig) -> Arc<Self> {
        let lists = Cache::builder()
            .max_capacity(config.cache_bytes)
            .weigher(|_key: &ListKey, index: &Arc<FileIndex>| {
                u32::try_from(index.weight_bytes()).unwrap_or(u32::MAX)
            })
            .build();
        let negative = Cache::builder()
            .max_capacity(MAX_NEGATIVE_ENTRIES)
            .time_to_live(config.negative_ttl)
            .build();
        Arc::new(Self {
            blob,
            config,
            lists,
            negative,
        })
    }

    pub async fn get(self: &Arc<Self>, key: &ListKey) -> ListLookup {
        if let Some(index) = self.lists.get(key).await {
            metrics::counter!(PATH_RESOLUTION_LIST_CACHE, "result" => "hit").increment(1);
            return ListLookup::Loaded(index);
        }
        if let Some(negative) = self.negative.get(key).await {
            metrics::counter!(PATH_RESOLUTION_LIST_CACHE, "result" => "negative").increment(1);
            return match negative {
                Negative::Missing => ListLookup::Missing,
                Negative::Unreadable => ListLookup::Error,
            };
        }
        metrics::counter!(PATH_RESOLUTION_LIST_CACHE, "result" => "miss").increment(1);

        // The load runs in its own task, so it fills the cache even when the request that started
        // it passes its deadline. Concurrent misses for one key share a single load.
        let store = self.clone();
        let key = key.clone();
        let load = tokio::spawn(async move {
            let result = store
                .lists
                .try_get_with(key.clone(), store.load(&key))
                .await;
            match &result {
                Ok(_) => {
                    // moka applies an insert to its size counters lazily, so settle it first.
                    store.lists.run_pending_tasks().await;
                    metrics::gauge!(PATH_RESOLUTION_CACHE_BYTES)
                        .set(store.lists.weighted_size() as f64);
                }
                Err(error) => store.remember_failure(&key, error).await,
            }
            result
        });
        match load.await {
            Ok(Ok(index)) => ListLookup::Loaded(index),
            Ok(Err(error)) if matches!(*error, LoadError::NotFound) => ListLookup::Missing,
            _ => ListLookup::Error,
        }
    }

    async fn load(&self, key: &ListKey) -> Result<Arc<FileIndex>, LoadError> {
        let started = Instant::now();
        let result = self.fetch_and_index(key).await;
        let outcome = match &result {
            Ok(_) => "loaded",
            Err(LoadError::NotFound) => "not_found",
            Err(LoadError::Storage(_)) => "storage_error",
            Err(LoadError::Timeout) => "timeout",
            Err(LoadError::TooLarge) => "too_large",
            Err(LoadError::Corrupt(_)) => "corrupt",
        };
        metrics::histogram!(PATH_RESOLUTION_LIST_LOAD_SECONDS, "outcome" => outcome)
            .record(started.elapsed().as_secs_f64());
        result
    }

    async fn fetch_and_index(&self, key: &ListKey) -> Result<Arc<FileIndex>, LoadError> {
        let object_key = key.object_key(&self.config.folder);
        let fetched = tokio::time::timeout(
            self.config.load_timeout,
            self.blob.get(&self.config.bucket, &object_key),
        )
        .await
        .map_err(|_| LoadError::Timeout)?
        .map_err(|error| LoadError::Storage(error.to_string()))?
        .ok_or(LoadError::NotFound)?;

        let max_bytes = self.config.max_decompressed_bytes;
        // Decompressing and indexing a large list takes tens of milliseconds of CPU.
        let index = tokio::task::spawn_blocking(move || decode_index(&fetched, max_bytes))
            .await
            .map_err(|error| LoadError::Corrupt(error.to_string()))??;
        Ok(Arc::new(index))
    }

    async fn remember_failure(&self, key: &ListKey, error: &LoadError) {
        let negative = match error {
            LoadError::NotFound => Negative::Missing,
            LoadError::TooLarge | LoadError::Corrupt(_) => {
                warn!(team_id = key.team_id, repo = %key.repo, commit = %key.commit, error = %error, "unreadable file list");
                Negative::Unreadable
            }
            // A transient failure must not hide a list that the next request could load.
            LoadError::Storage(_) | LoadError::Timeout => return,
        };
        self.negative.insert(key.clone(), negative).await;
    }
}

/// Decompress a stored list and index it. Rejects a list that decompresses past `max_bytes`, so a
/// small object cannot expand into gigabytes of memory.
pub fn decode_index(compressed: &[u8], max_bytes: usize) -> Result<FileIndex, LoadError> {
    let decoder = zstd::stream::read::Decoder::new(compressed)
        .map_err(|error| LoadError::Corrupt(error.to_string()))?;
    let mut text = Vec::new();
    decoder
        .take(max_bytes as u64 + 1)
        .read_to_end(&mut text)
        .map_err(|error| LoadError::Corrupt(error.to_string()))?;
    if text.len() > max_bytes {
        return Err(LoadError::TooLarge);
    }
    let text = String::from_utf8(text).map_err(|error| LoadError::Corrupt(error.to_string()))?;
    Ok(FileIndex::from_text(text))
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use async_trait::async_trait;
    use bytes::Bytes;
    use tokio::sync::Notify;

    use super::*;
    use crate::core::error::UnhandledError;

    const TEAM: i64 = 7;
    const COMMIT: &str = "0123456789abcdef0123456789abcdef01234567";

    struct FakeBlobs {
        objects: std::collections::HashMap<String, Bytes>,
        gets: AtomicUsize,
        gate: Option<Arc<Notify>>,
    }

    #[async_trait]
    impl BlobClient for FakeBlobs {
        async fn get(&self, _bucket: &str, key: &str) -> Result<Option<Bytes>, UnhandledError> {
            self.gets.fetch_add(1, Ordering::SeqCst);
            if let Some(gate) = &self.gate {
                gate.notified().await;
            }
            Ok(self.objects.get(key).cloned())
        }

        async fn put(&self, _bucket: &str, _key: &str, _data: Bytes) -> Result<(), UnhandledError> {
            unimplemented!()
        }

        async fn delete(&self, _bucket: &str, _key: &str) -> Result<(), UnhandledError> {
            unimplemented!()
        }

        async fn ping_bucket(&self, _bucket: &str) -> Result<(), UnhandledError> {
            Ok(())
        }
    }

    fn key(repo: &str) -> ListKey {
        ListKey {
            team_id: TEAM,
            repo: repo.to_string(),
            commit: COMMIT.to_string(),
        }
    }

    fn store_with(
        objects: Vec<(ListKey, &[u8])>,
        gate: Option<Arc<Notify>>,
    ) -> (Arc<ListStore>, Arc<FakeBlobs>) {
        let config = ListStoreConfig {
            bucket: "posthog".to_string(),
            folder: "repo_paths".to_string(),
            cache_bytes: 1 << 20,
            negative_ttl: Duration::from_secs(60),
            max_decompressed_bytes: 1024,
            load_timeout: Duration::from_secs(5),
        };
        let blobs = Arc::new(FakeBlobs {
            objects: objects
                .into_iter()
                .map(|(key, text)| {
                    let compressed = zstd::encode_all(text, 3).unwrap();
                    (key.object_key(&config.folder), Bytes::from(compressed))
                })
                .collect(),
            gets: AtomicUsize::new(0),
            gate,
        });
        (ListStore::new(blobs.clone(), config), blobs)
    }

    #[tokio::test]
    async fn remembers_a_missing_list_and_loads_a_stored_one_once() {
        let (store, blobs) = store_with(vec![(key("github.com/acme/shop"), b"a/b.py\nc.py")], None);

        assert!(matches!(
            store.get(&key("github.com/acme/other")).await,
            ListLookup::Missing
        ));
        assert!(matches!(
            store.get(&key("github.com/acme/other")).await,
            ListLookup::Missing
        ));
        let ListLookup::Loaded(index) = store.get(&key("github.com/acme/shop")).await else {
            panic!("expected a loaded list");
        };
        assert_eq!(index.len(), 2);
        assert!(matches!(
            store.get(&key("github.com/acme/shop")).await,
            ListLookup::Loaded(_)
        ));

        assert_eq!(blobs.gets.load(Ordering::SeqCst), 2);
    }

    #[tokio::test]
    async fn rejects_a_list_that_decompresses_past_the_limit() {
        let large = "x/y.py\n".repeat(1000);
        let (store, _) = store_with(vec![(key("github.com/acme/shop"), large.as_bytes())], None);

        assert!(matches!(
            store.get(&key("github.com/acme/shop")).await,
            ListLookup::Error
        ));
    }

    #[tokio::test]
    async fn concurrent_misses_share_one_load_that_outlives_its_callers() {
        let gate = Arc::new(Notify::new());
        let (store, blobs) = store_with(
            vec![(key("github.com/acme/shop"), b"a/b.py")],
            Some(gate.clone()),
        );

        let waiting: Vec<_> = (0..10)
            .map(|_| {
                let store = store.clone();
                tokio::spawn(async move { store.get(&key("github.com/acme/shop")).await })
            })
            .collect();
        // Every caller gives up before the object arrives, like a request that passes its deadline.
        while blobs.gets.load(Ordering::SeqCst) == 0 {
            tokio::task::yield_now().await;
        }
        for caller in &waiting {
            caller.abort();
        }
        gate.notify_one();

        for _ in 0..100 {
            if store
                .lists
                .get(&key("github.com/acme/shop"))
                .await
                .is_some()
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        assert!(matches!(
            store.get(&key("github.com/acme/shop")).await,
            ListLookup::Loaded(_)
        ));
        assert_eq!(blobs.gets.load(Ordering::SeqCst), 1);
    }
}
