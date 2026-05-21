use std::sync::Arc;
use std::time::Instant;

use futures::stream::{FuturesUnordered, StreamExt};
use posthog_symbol_data::{sniff_data_type, SymbolDataType};
use sqlx::PgPool;
use tokio::sync::{Mutex, Semaphore};
use tokio::time::Duration;
use tracing::{info, warn};

use crate::{
    config::Config,
    error::UnhandledError,
    metric_consts::{
        CACHE_WARMING_BYTES_LOADED, CACHE_WARMING_DURATION, CACHE_WARMING_ENTRIES_FAILED,
        CACHE_WARMING_ENTRIES_LOADED,
    },
    symbol_store::{
        apple::{AppleProvider, ParsedAppleSymbols},
        caching::{Countable, SymbolSetCache},
        hermesmap::{HermesMapProvider, ParsedHermesMap},
        proguard::{FetchedMapping, ProguardProvider},
        saving::SymbolSetRecord,
        sourcemap::{OwnedSourceMapCache, SourcemapProvider},
        BlobClient, Parser,
    },
};

// Leave headroom in the shared cache for traffic that arrives right after the pod is ready.
const WARMING_FILL_FRACTION: f64 = 0.85;

struct WarmingParsers {
    sourcemap: SourcemapProvider,
    hermes: HermesMapProvider,
    proguard: ProguardProvider,
    apple: AppleProvider,
}

#[derive(Debug)]
struct WarmingBudget {
    max_bytes: usize,
    loaded_bytes: usize,
    reserved_bytes: usize,
}

impl WarmingBudget {
    fn new(max_bytes: usize, loaded_bytes: usize) -> Self {
        Self {
            max_bytes,
            loaded_bytes,
            reserved_bytes: 0,
        }
    }

    fn remaining_bytes(&self) -> usize {
        self.max_bytes
            .saturating_sub(self.loaded_bytes)
            .saturating_sub(self.reserved_bytes)
    }

    fn reserve(&mut self, bytes: usize) -> bool {
        if bytes > self.remaining_bytes() {
            return false;
        }

        self.reserved_bytes += bytes;
        true
    }

    fn release(&mut self, bytes: usize) {
        self.reserved_bytes = self.reserved_bytes.saturating_sub(bytes);
    }

    fn commit(&mut self, reserved_bytes: usize, loaded_bytes: usize) -> bool {
        self.release(reserved_bytes);
        if loaded_bytes > self.remaining_bytes() {
            return false;
        }

        self.loaded_bytes += loaded_bytes;
        true
    }
}

/// Pre-populates the symbol set cache from DB + S3 on startup.
///
/// We warm recently used symbol sets across all teams. Each pod warms the same global top-N set:
/// this is intentionally simple until Cymbal has stable sharding/routing assignments.
pub async fn warm_cache(
    pool: &PgPool,
    s3_client: &Arc<dyn BlobClient>,
    bucket: &str,
    ss_cache: &Arc<Mutex<SymbolSetCache>>,
    config: &Config,
) -> Result<(), UnhandledError> {
    let start = Instant::now();
    let byte_budget = (config.symbol_store_cache_max_bytes as f64 * WARMING_FILL_FRACTION) as usize;

    let records = load_warming_candidates(pool, config).await?;
    let total = records.len();
    info!(total, byte_budget, "Fetched cache warming candidates");

    if total == 0 {
        metrics::histogram!(CACHE_WARMING_DURATION).record(start.elapsed().as_secs_f64());
        return Ok(());
    }

    let initial_loaded_bytes = ss_cache.lock().await.held_bytes();
    let budget = Arc::new(Mutex::new(WarmingBudget::new(
        byte_budget,
        initial_loaded_bytes,
    )));
    let semaphore = Arc::new(Semaphore::new(config.cache_warming_concurrency.max(1)));
    let parsers = Arc::new(WarmingParsers {
        sourcemap: SourcemapProvider::new(config),
        hermes: HermesMapProvider {},
        proguard: ProguardProvider {},
        apple: AppleProvider {},
    });

    let mut abort_handles = Vec::with_capacity(total);
    let mut tasks = FuturesUnordered::new();

    for record in records {
        let semaphore = semaphore.clone();
        let s3_client = s3_client.clone();
        let bucket = bucket.to_string();
        let ss_cache = ss_cache.clone();
        let parsers = parsers.clone();
        let budget = budget.clone();

        let handle = tokio::spawn(async move {
            let _permit = semaphore
                .acquire_owned()
                .await
                .expect("warming semaphore open");
            let result =
                warm_single_entry(&s3_client, &bucket, &ss_cache, &parsers, &record, &budget).await;
            (record.set_ref, result)
        });
        abort_handles.push(handle.abort_handle());
        tasks.push(handle);
    }

    let mut loaded = 0_u64;
    let mut failed = 0_u64;
    let mut skipped = 0_u64;
    let mut bytes_loaded = 0_u64;
    let mut timed_out = false;
    let timeout = tokio::time::sleep(Duration::from_secs(config.cache_warming_timeout_seconds));
    tokio::pin!(timeout);

    loop {
        tokio::select! {
            maybe_result = tasks.next() => {
                match maybe_result {
                    Some(Ok((_, Ok(Some(bytes))))) => {
                        loaded += 1;
                        bytes_loaded += bytes as u64;
                    }
                    Some(Ok((_, Ok(None)))) => {
                        skipped += 1;
                    }
                    Some(Ok((set_ref, Err(error)))) => {
                        warn!(%set_ref, %error, "Failed to warm symbol set");
                        failed += 1;
                    }
                    Some(Err(error)) => {
                        warn!(%error, "Cache warming task failed");
                        failed += 1;
                    }
                    None => break,
                }
            }
            _ = &mut timeout => {
                timed_out = true;
                break;
            }
        }
    }

    if timed_out {
        let aborted = tasks.len() as u64;
        for abort_handle in abort_handles {
            abort_handle.abort();
        }
        warn!(
            timeout_seconds = config.cache_warming_timeout_seconds,
            loaded, failed, skipped, aborted, "Cache warming timed out, aborting remaining tasks"
        );
    }

    let elapsed = start.elapsed();
    info!(
        loaded,
        failed,
        skipped,
        total,
        bytes_loaded,
        byte_budget,
        elapsed_ms = elapsed.as_millis() as u64,
        "Cache warming complete"
    );

    metrics::counter!(CACHE_WARMING_ENTRIES_LOADED).increment(loaded);
    metrics::counter!(CACHE_WARMING_ENTRIES_FAILED).increment(failed);
    metrics::counter!(CACHE_WARMING_BYTES_LOADED).increment(bytes_loaded);
    metrics::histogram!(CACHE_WARMING_DURATION).record(elapsed.as_secs_f64());

    Ok(())
}

async fn load_warming_candidates(
    pool: &PgPool,
    config: &Config,
) -> Result<Vec<SymbolSetRecord>, UnhandledError> {
    let records = sqlx::query_as::<_, SymbolSetRecord>(
        r#"
        SELECT id, team_id, ref AS set_ref, storage_ptr, failure_reason, created_at, content_hash, last_used
        FROM posthog_errortrackingsymbolset
        WHERE content_hash IS NOT NULL
          AND storage_ptr IS NOT NULL
          AND last_used > NOW() - ($1::double precision * INTERVAL '1 hour')
        ORDER BY last_used DESC
        LIMIT $2
        "#,
    )
    .bind(config.cache_warming_lookback_hours as f64)
    .bind(config.cache_warming_max_entries as i64)
    .fetch_all(pool)
    .await?;

    Ok(records)
}

async fn warm_single_entry(
    s3_client: &Arc<dyn BlobClient>,
    bucket: &str,
    cache: &Arc<Mutex<SymbolSetCache>>,
    parsers: &WarmingParsers,
    record: &SymbolSetRecord,
    budget: &Arc<Mutex<WarmingBudget>>,
) -> Result<Option<usize>, UnhandledError> {
    let storage_ptr = record
        .storage_ptr
        .as_ref()
        .ok_or_else(|| UnhandledError::Other("missing storage_ptr".to_string()))?;

    if budget.lock().await.remaining_bytes() == 0 {
        return Ok(None);
    }

    let object_size = s3_client
        .get_size(bucket, storage_ptr)
        .await?
        .ok_or_else(|| UnhandledError::Other("S3 object not found".to_string()))?;

    if !budget.lock().await.reserve(object_size) {
        return Ok(None);
    }

    let data = match s3_client.get(bucket, storage_ptr).await? {
        Some(data) => data,
        None => {
            budget.lock().await.release(object_size);
            return Err(UnhandledError::Other("S3 object not found".to_string()));
        }
    };

    let data_type = match sniff_data_type(&data) {
        Ok(data_type) => data_type,
        Err(error) => {
            budget.lock().await.release(object_size);
            return Err(UnhandledError::Other(format!(
                "failed to sniff symbol data type: {error}"
            )));
        }
    };
    let cache_key = format!("{}:{}", record.team_id, record.set_ref);

    match data_type {
        SymbolDataType::SourceAndMap => {
            let parsed = match parsers.sourcemap.parse(data).await {
                Ok(parsed) => parsed,
                Err(error) => {
                    budget.lock().await.release(object_size);
                    return Err(UnhandledError::Other(format!(
                        "sourcemap parse failed: {error}"
                    )));
                }
            };
            insert_warmed_entry::<OwnedSourceMapCache>(
                cache,
                budget,
                object_size,
                cache_key,
                parsed,
            )
            .await
        }
        SymbolDataType::HermesMap => {
            let parsed = match parsers.hermes.parse(data).await {
                Ok(parsed) => parsed,
                Err(error) => {
                    budget.lock().await.release(object_size);
                    return Err(UnhandledError::Other(format!(
                        "hermes map parse failed: {error}"
                    )));
                }
            };
            insert_warmed_entry::<ParsedHermesMap>(cache, budget, object_size, cache_key, parsed)
                .await
        }
        SymbolDataType::ProguardMapping => {
            let parsed = match parsers.proguard.parse(data).await {
                Ok(parsed) => parsed,
                Err(error) => {
                    budget.lock().await.release(object_size);
                    return Err(UnhandledError::Other(format!(
                        "proguard mapping parse failed: {error}"
                    )));
                }
            };
            insert_warmed_entry::<FetchedMapping>(cache, budget, object_size, cache_key, parsed)
                .await
        }
        SymbolDataType::AppleDsym => {
            let parsed = match parsers.apple.parse(data).await {
                Ok(parsed) => parsed,
                Err(error) => {
                    budget.lock().await.release(object_size);
                    return Err(UnhandledError::Other(format!(
                        "apple symbols parse failed: {error}"
                    )));
                }
            };
            insert_warmed_entry::<ParsedAppleSymbols>(cache, budget, object_size, cache_key, parsed)
                .await
        }
    }
}

async fn insert_warmed_entry<T>(
    cache: &Arc<Mutex<SymbolSetCache>>,
    budget: &Arc<Mutex<WarmingBudget>>,
    reserved_bytes: usize,
    cache_key: String,
    parsed: T,
) -> Result<Option<usize>, UnhandledError>
where
    T: Countable + Send + Sync + 'static,
{
    let bytes = parsed.byte_count();
    if !budget.lock().await.commit(reserved_bytes, bytes) {
        return Ok(None);
    }

    cache
        .lock()
        .await
        .insert::<T>(cache_key, Arc::new(parsed), bytes);
    Ok(Some(bytes))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use posthog_symbol_data::write_symbol_data;
    use uuid::Uuid;

    use crate::symbol_store::MockS3Client;

    const MINIFIED: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js");
    const MAP: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js.map");

    fn test_symbol_data() -> bytes::Bytes {
        write_symbol_data(posthog_symbol_data::SourceAndMap {
            minified_source: String::from_utf8(MINIFIED.to_vec()).unwrap(),
            sourcemap: String::from_utf8(MAP.to_vec()).unwrap(),
        })
        .unwrap()
        .into()
    }

    fn make_record(key: &str) -> SymbolSetRecord {
        SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id: 1,
            set_ref: format!("http://example.com/{key}"),
            storage_ptr: Some(key.to_string()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("abc123".to_string()),
            last_used: Some(Utc::now()),
        }
    }

    fn make_parsers() -> WarmingParsers {
        let config = Config::init_with_defaults().unwrap();
        WarmingParsers {
            sourcemap: SourcemapProvider::new(&config),
            hermes: HermesMapProvider {},
            proguard: ProguardProvider {},
            apple: AppleProvider {},
        }
    }

    #[tokio::test]
    async fn skips_entry_when_over_byte_budget() {
        let parsers = make_parsers();
        let cache = Arc::new(Mutex::new(SymbolSetCache::new(1000)));
        cache
            .lock()
            .await
            .insert("prefill".to_string(), Arc::new(vec![0_u8; 500]), 500);

        let s3_client: Arc<dyn BlobClient> = Arc::new(MockS3Client::new());
        let record = make_record("test-key");

        let budget = Arc::new(Mutex::new(WarmingBudget::new(100, 500)));

        let result =
            warm_single_entry(&s3_client, "bucket", &cache, &parsers, &record, &budget).await;

        assert!(result.unwrap().is_none());
        assert_eq!(cache.lock().await.held_bytes(), 500);
    }

    #[tokio::test]
    async fn skips_entry_when_object_size_exceeds_remaining_budget() {
        let parsers = make_parsers();
        let cache = Arc::new(Mutex::new(SymbolSetCache::new(1000)));

        let mut s3_client = MockS3Client::new();
        s3_client.expect_get_size().returning(|_, _| Ok(Some(500)));

        let s3_client: Arc<dyn BlobClient> = Arc::new(s3_client);
        let record = make_record("test-key");
        let budget = Arc::new(Mutex::new(WarmingBudget::new(100, 0)));

        let result =
            warm_single_entry(&s3_client, "bucket", &cache, &parsers, &record, &budget).await;

        assert!(result.unwrap().is_none());
        assert_eq!(cache.lock().await.held_bytes(), 0);
    }

    #[tokio::test]
    async fn loads_entry_when_under_byte_budget() {
        let parsers = make_parsers();
        let cache = Arc::new(Mutex::new(SymbolSetCache::new(100_000_000)));

        let data = test_symbol_data();
        let data_size = data.len();
        let mut s3_client = MockS3Client::new();
        s3_client
            .expect_get_size()
            .returning(move |_, _| Ok(Some(data_size)));
        s3_client
            .expect_get()
            .returning(move |_, _| Ok(Some(data.clone())));

        let s3_client: Arc<dyn BlobClient> = Arc::new(s3_client);
        let record = make_record("test-key");
        let budget = Arc::new(Mutex::new(WarmingBudget::new(100_000_000, 0)));

        let result =
            warm_single_entry(&s3_client, "bucket", &cache, &parsers, &record, &budget).await;

        let bytes = result.unwrap().unwrap();
        assert!(bytes > 0);
        assert_eq!(cache.lock().await.held_bytes(), bytes);
    }
}
