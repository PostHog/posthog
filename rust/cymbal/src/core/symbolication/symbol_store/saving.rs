use std::sync::Arc;

use async_trait::async_trait;
use bytes::Bytes;
use chrono::{DateTime, Duration, Utc};

use moka::future::{Cache, CacheBuilder};
use sha2::{Digest, Sha512};
use sqlx::PgPool;
use tracing::{error, info, warn};
use uuid::Uuid;

use crate::{
    core::analytics::{capture_symbol_set_deleted, capture_symbol_set_saved},
    error::{FrameError, ResolveError, UnhandledError},
    metric_consts::{
        FRAME_RESOLUTION_RESULTS_DELETED, SAVED_SYMBOL_SET_ERROR_RETURNED, SAVED_SYMBOL_SET_LOADED,
        SAVE_SYMBOL_SET, SYMBOL_SET_DB_FETCHES, SYMBOL_SET_DB_HITS, SYMBOL_SET_DB_MISSES,
        SYMBOL_SET_FETCH_RETRY, SYMBOL_SET_NEGATIVE_CACHE_HIT, SYMBOL_SET_SAVED,
    },
    symbolication::symbol_store::{chunk_id::SymbolSetKey, BlobClient},
};

use super::{Fetcher, Parser};

const MAX_REF_BYTES: usize = 2048;

// Total byte budget for the in-memory negative cache. Refs and failure reasons are
// event-controlled (a JS frame's ref is its source URL, and a `NoSourcemap` failure embeds that
// URL), so the cache is weighed by the byte size of each key+value and bounded by total weight
// rather than entry count — a flood of unique, long URLs can't grow it without bound. 64 MiB is
// ample for the working set of recently-failed symbol sets. TTL is the primary staleness bound.
const NEGATIVE_CACHE_MAX_WEIGHT: u64 = 64 * 1024 * 1024;

// We truncate the reference to resolve an issue with the maximum size in a BTRee index on Postgres
// TODO: update model to use a hash of the reference instead
fn truncate_ref(s: &str) -> &str {
    if s.len() <= MAX_REF_BYTES {
        return s;
    }
    // Find a valid UTF-8 boundary at or before MAX_REF_BYTES
    let mut end = MAX_REF_BYTES;
    while end > 0 && !s.is_char_boundary(end) {
        end -= 1;
    }
    &s[..end]
}

// A wrapping layer around a fetcher and parser, that provides transparent storing of the
// source bytes into s3, and the storage pointer into a postgres database.
pub struct Saving<F> {
    inner: F,
    s3_client: Arc<dyn BlobClient>,
    pool: PgPool,
    bucket: String,
    prefix: String,
    // In-memory negative cache of recently-failed lookups, keyed per (team_id, truncated
    // lookup_ref). It holds only the serialized `failure_reason` of a *stored* failure record
    // (never transient DB/S3/network errors), so a hit can rebuild the exact stored error
    // without re-reading Postgres. The DB stays the source of truth; this only short-circuits
    // the repeated negative reads for sets we already know failed recently. Keyed per
    // individual ref (not the whole `OrChunkId`) so the chunk-id-wins priority in `fetch` is
    // preserved, and by the *truncated* ref so the key-space matches the DB (which truncates
    // before writing) and stays bounded against long, event-controlled URLs. The cache TTL
    // bounds staleness after a user uploads the missing symbols.
    negative_cache: Cache<(i32, String), String>,
}

// A record of an attempt to fetch a symbol set. If it succeeded, it will have a storage pointer
#[derive(Debug, sqlx::FromRow)]
pub struct SymbolSetRecord {
    pub id: Uuid,
    pub team_id: i32,
    // "ref" is a reserved keyword in Rust, whoops
    pub set_ref: String,
    pub storage_ptr: Option<String>,
    pub failure_reason: Option<String>,
    pub created_at: DateTime<Utc>,
    pub content_hash: Option<String>,
    pub last_used: Option<DateTime<Utc>>,
}

// This is the "intermediate" symbol set data. Rather than a simple `Bytes`, the saving layer
// has to return this from calls to `fetch`, and accept it in calls to `parse`, so that it can
// pass the information necessary to store the underlying data between the fetch and parse stages,
// (to avoid saving data we can't parse). The payload is held as `Bytes` so it can be cheaply
// cloned (refcount bump) when the parse and save paths both need a reference.
//
// `save_ref` is the DB key to insert under when persisting a fresh fetch. It is `None` when
// the original ref had no save target (a bare `OrChunkId::ChunkId`, which has no URL to
// fetch from). When `storage_ptr` is `Some`, `save_ref` is irrelevant — parse won't persist.
pub struct Saveable {
    pub data: Bytes,
    pub storage_ptr: Option<String>, // This is None if we still need to save this data
    pub team_id: i32,
    pub save_ref: Option<String>,
}

impl<F> Saving<F> {
    pub fn new(
        inner: F,
        pool: sqlx::PgPool,
        s3_client: Arc<dyn BlobClient>,
        bucket: String,
        prefix: String,
        negative_cache_ttl: std::time::Duration,
    ) -> Self {
        let negative_cache = CacheBuilder::new(NEGATIVE_CACHE_MAX_WEIGHT)
            .weigher(|(_, ref_key): &(i32, String), reason: &String| {
                // Bound by the bytes actually held; saturate rather than wrap for huge values.
                (ref_key.len() + reason.len())
                    .try_into()
                    .unwrap_or(u32::MAX)
            })
            .time_to_live(negative_cache_ttl)
            .build();
        Self {
            inner,
            pool,
            s3_client,
            bucket,
            prefix,
            negative_cache,
        }
    }

    pub async fn save_data(
        &self,
        team_id: i32,
        set_ref: String,
        data: Bytes,
    ) -> Result<String, UnhandledError> {
        info!("Saving symbol set data for {}", set_ref);
        let start = common_metrics::timing_guard(SAVE_SYMBOL_SET, &[]).label("data", "true");
        // Generate a new opaque key, prepending our prefix.
        let key = self.add_prefix(Uuid::now_v7().to_string());
        let mut content_hasher = Sha512::new();
        content_hasher.update(&data);

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id,
            set_ref,
            storage_ptr: Some(key.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some(format!("{:x}", content_hasher.finalize())),
            last_used: Some(Utc::now()),
        };

        self.s3_client.put(&self.bucket, &key, data).await?;
        let wrote_new_data = record.save_data_if_missing(&self.pool).await?;
        // Reaching here means real data is now present for this ref (we just wrote it, or an
        // existing row already had it), so any negative-cache entry for it is stale — drop it
        // so lookups stop returning the old failure before the TTL would expire it. This also
        // clears entries a concurrent failing lookup for the same URL save key may have added
        // while we were fetching/parsing.
        self.negative_cache
            .invalidate(&Self::negative_cache_key(team_id, &record.set_ref))
            .await;
        if !wrote_new_data {
            warn!(
                "Not overwriting existing symbol set data for {} after dynamic fetch",
                record.set_ref
            );
            if let Err(err) = self.s3_client.delete(&self.bucket, &key).await {
                warn!(
                    "Failed to clean up unused symbol set data at {} after skipped DB update: {:?}",
                    key, err
                );
            }
            start.label("outcome", "skipped_existing_data").fin();
            return Ok(key);
        }
        // We just saved new data for this symbol set, which invalidates all our previous stack frame resolution results,
        // so delete them
        let deleted: u64 = sqlx::query_scalar!(
            r#"WITH deleted AS (DELETE FROM posthog_errortrackingstackframe WHERE symbol_set_id = $1 RETURNING *) SELECT count(*) from deleted"#,
            record.id // The call to save() above ensures that this id is correct
        )
        .fetch_one(&self.pool)
        .await.expect("Got at least one row back").map_or(0, |v| {
            v.max(0) as u64
        });

        info!(
            "Deleted {} stack frames for symbol set {}",
            deleted, record.id
        );
        metrics::counter!(FRAME_RESOLUTION_RESULTS_DELETED).increment(deleted);

        capture_symbol_set_saved(team_id, &record.set_ref, &key, deleted > 0);

        start.label("outcome", "success").fin();
        Ok(key)
    }

    pub async fn save_no_data(
        &self,
        team_id: i32,
        set_ref: String,
        reason: &FrameError,
    ) -> Result<(), UnhandledError> {
        info!("Saving symbol set error for {}", set_ref);
        let start = common_metrics::timing_guard(SAVE_SYMBOL_SET, &[]).label("data", "false");
        let failure_reason = serde_json::to_string(&reason)?;
        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id,
            set_ref: set_ref.clone(),
            storage_ptr: None,
            failure_reason: Some(failure_reason.clone()),
            created_at: Utc::now(),
            content_hash: None,
            last_used: Some(Utc::now()),
        };
        // Only prime the negative cache if the failure was actually persisted. When
        // `save_failure` is a no-op — a row with real symbol data already exists for this ref
        // (e.g. an upload raced ahead of us) — caching the failure would shadow that data until
        // TTL, so we must not.
        if record.save_failure(&self.pool).await? {
            self.negative_cache
                .insert(Self::negative_cache_key(team_id, &set_ref), failure_reason)
                .await;
        }
        start.label("outcome", "success").fin();
        Ok(())
    }

    fn add_prefix(&self, key: String) -> String {
        format!("{}/{}", self.prefix, key)
    }

    // Negative-cache key for a ref. Truncated to match the DB key-space (the DB truncates before
    // writing/looking up) and to keep keys bounded against long, event-controlled URLs.
    fn negative_cache_key(team_id: i32, set_ref: &str) -> (i32, String) {
        (team_id, truncate_ref(set_ref).to_string())
    }

    // Probe the negative cache for a single lookup ref, rebuilding the stored error on a hit
    // exactly as the DB recent-failure path does (deserialize the stored `failure_reason` into
    // a `FrameError`). Called per ref, interleaved with the DB lookup in `fetch`, so a
    // higher-priority ref's real data is always found before a lower-priority ref's cached
    // failure — preserving the chunk-id-wins order.
    async fn negative_cache_lookup(
        &self,
        team_id: i32,
        lookup_ref: &str,
    ) -> Result<Option<ResolveError>, UnhandledError> {
        let Some(failure_reason) = self
            .negative_cache
            .get(&Self::negative_cache_key(team_id, lookup_ref))
            .await
        else {
            return Ok(None);
        };
        metrics::counter!(SYMBOL_SET_NEGATIVE_CACHE_HIT).increment(1);
        let error: FrameError =
            serde_json::from_str(&failure_reason).map_err(UnhandledError::from)?;
        Ok(Some(ResolveError::ResolutionError(error)))
    }
}

#[async_trait]
impl<F> Fetcher for Saving<F>
where
    F: Fetcher<Fetched = Bytes, Err = ResolveError>,
    F::Ref: SymbolSetKey + Send,
{
    type Ref = F::Ref;
    type Fetched = Saveable;
    type Err = F::Err;

    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Self::Fetched, Self::Err> {
        let lookup_refs = r.lookup_refs();
        let save_ref = r.save_ref();

        metrics::counter!(SYMBOL_SET_DB_FETCHES).increment(1);

        // Try lookup keys in priority order — for an `OrChunkId::Both`, this means the chunk
        // id (authoritative, upload-API namespace) wins over the URL (capture-cached). A stale
        // failure under one key falls through to the next; a fresh failure or data short-circuits.
        // `DB_HITS` is bumped at most once per fetch (on the first row found) regardless of
        // how many lookup refs we probe — multi-ref lookups must not inflate the counter.
        let mut hit_counted = false;
        for lookup_ref in &lookup_refs {
            // Consult the in-memory negative cache for this ref before the DB read. It only ever
            // holds stored failures (never transient errors), so a hit reproduces the same error
            // the DB recent-failure path would, without the SELECT + deserialize + log. Checked
            // per ref inside the priority loop so a higher-priority ref's real data is always
            // found first — a cached failure can only short-circuit once every earlier ref has
            // missed both the cache and the DB.
            if let Some(error) = self.negative_cache_lookup(team_id, lookup_ref).await? {
                return Err(error);
            }

            info!("Fetching symbol set data for {}", lookup_ref);
            let Some(mut record) = SymbolSetRecord::load(&self.pool, team_id, lookup_ref).await?
            else {
                continue;
            };
            if !hit_counted {
                metrics::counter!(SYMBOL_SET_DB_HITS).increment(1);
                hit_counted = true;
            }

            if let Some(storage_ptr) = record.storage_ptr.clone() {
                info!("Found s3 saved symbol set data for {}", lookup_ref);
                record.set_last_used(&self.pool).await?;
                let data = match self.s3_client.get(&self.bucket, &storage_ptr).await {
                    Ok(Some(data)) => data,
                    Ok(None) => {
                        warn!("Storage pointer points to a record that doesn't exist");
                        record.delete(&self.pool).await?;
                        return Err(FrameError::MissingChunkIdData(lookup_ref.clone()).into());
                    }
                    // Otherwise, if we just failed to talk to s3 for some reason, treat it as an unhandled error, and die
                    Err(err) => return Err(err.into()),
                };
                metrics::counter!(SAVED_SYMBOL_SET_LOADED).increment(1);
                return Ok(Saveable {
                    data,
                    storage_ptr: Some(storage_ptr),
                    team_id,
                    save_ref: save_ref.clone(),
                });
            }

            if record
                .last_used
                .is_some_and(|l| Utc::now() - l < chrono::Duration::days(1))
            {
                info!("Found recent symbol set error for {}", lookup_ref);
                // We tried less than a day ago to get the set data, and failed, so bail out
                // with the stored error. We unwrap here because we should never store a "no set"
                // row without also storing the error, and if we do, we want to panic, but we
                // also want to log an error
                metrics::counter!(SAVED_SYMBOL_SET_ERROR_RETURNED).increment(1);
                let Some(failure_reason) = record.failure_reason.clone() else {
                    error!("Found a record with no data and no error: {:?}", record);
                    panic!("Found a record with no data and no error");
                };
                // Cache this known-recent failure so subsequent lookups for the same ref skip
                // the DB read. Keyed by the individual ref we hit, preserving lookup priority.
                self.negative_cache
                    .insert(
                        Self::negative_cache_key(team_id, lookup_ref),
                        failure_reason.clone(),
                    )
                    .await;
                // TODO - this can fail due to changes in how we serialise, or changes in
                // the error type - and we should handle that by deleting the symbol record
                // and re-fetching, I think (we don't need to cleanup s3 since it's a failure
                // case, there is no saved data).
                let error = serde_json::from_str(&failure_reason).map_err(UnhandledError::from)?;
                return Err(ResolveError::ResolutionError(error));
            }

            info!("Found stale symbol set error for {}", lookup_ref);
            // We last tried to get the symbol set more than a day ago, so we should try again
            metrics::counter!(SYMBOL_SET_FETCH_RETRY).increment(1);
        }

        metrics::counter!(SYMBOL_SET_DB_MISSES).increment(1);

        match self.inner.fetch(team_id, r).await {
            // NOTE: We don't save the data here, because we want to save it only after parsing
            Ok(data) => {
                info!("Inner fetched symbol set data");
                Ok(Saveable {
                    data,
                    storage_ptr: None,
                    team_id,
                    save_ref,
                })
            }
            Err(ResolveError::ResolutionError(e)) => {
                // Only record a failure when we actually have a save key — bare chunk-id refs
                // never write to the DB (otherwise capture traffic could squat the upload-API
                // namespace with failure rows).
                if let Some(save_ref) = save_ref {
                    self.save_no_data(team_id, save_ref, &e).await?;
                }
                Err(ResolveError::ResolutionError(e))
            }
            Err(e) => Err(e), // If some non-resolution error occurred, we just bail out
        }
    }
}

#[async_trait]
impl<F> Parser for Saving<F>
where
    F: Parser<Source = Bytes, Err = ResolveError>,
    F::Set: Send,
{
    type Source = Saveable;
    type Set = F::Set;
    type Err = F::Err;

    async fn parse(&self, data: Saveable) -> Result<Self::Set, Self::Err> {
        let Saveable {
            data: bytes,
            storage_ptr,
            team_id,
            save_ref,
        } = data;

        // On the loaded-from-S3 path we never need to save the bytes back, so we hand them
        // straight to the parser by move. On the fresh-fetch path we keep a refcounted handle
        // so we can save after a successful parse — cloning `Bytes` is just a refcount bump.
        let bytes_to_save = if storage_ptr.is_none() {
            Some(bytes.clone())
        } else {
            None
        };

        match self.inner.parse(bytes).await {
            Ok(s) => {
                info!("Parsed symbol set data");
                if let (Some(bytes_to_save), Some(save_ref)) = (bytes_to_save, &save_ref) {
                    self.save_data(team_id, save_ref.clone(), bytes_to_save)
                        .await?;
                }
                Ok(s)
            }
            Err(ResolveError::ResolutionError(e)) => {
                info!("Failed to parse symbol set data");
                if storage_ptr.is_none() {
                    if let Some(save_ref) = save_ref {
                        // Save fresh parse failures to prevent refetching for a day, but never
                        // replace an existing uploaded blob with a parser error, and never
                        // write to a namespace we don't own (bare chunk-id refs have no save key).
                        self.save_no_data(team_id, save_ref, &e).await?;
                    }
                }
                Err(ResolveError::ResolutionError(e))
            }
            Err(e) => Err(e),
        }
    }
}

impl SymbolSetRecord {
    pub async fn load(
        pool: &sqlx::PgPool,
        team_id: i32,
        set_ref: &str,
    ) -> Result<Option<Self>, UnhandledError> {
        // Query looks a bit odd. Symbol sets are usable by cymbal if they have no storage ptr (indicating an
        // unfound symbol set) or if they have a content hash (indicating a full saved symbol set). The in-between
        // states (storage_ptr is not null AND content_hash is null) indicate an ongoing upload.
        let truncated_ref = truncate_ref(set_ref);
        let record = sqlx::query_as!(
            SymbolSetRecord,
            r#"SELECT id, team_id, ref as set_ref, storage_ptr, created_at, failure_reason, content_hash, last_used
            FROM posthog_errortrackingsymbolset
            WHERE (content_hash is not null OR storage_ptr is null) AND team_id = $1 AND ref = $2"#,
            team_id,
            truncated_ref
        )
        .fetch_optional(pool)
        .await?;

        Ok(record)
    }

    // Set the last used timestamp. Called on successful symbol set lookups, and also
    // used by retention cleanup jobs to determine which symbol sets are still in use.
    pub(crate) async fn set_last_used<'c, E>(&mut self, e: E) -> Result<(), UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        // If the elapsed time is less than 12 hours, do nothing
        if self
            .last_used
            .map(|l| Utc::now() - l < Duration::hours(12))
            .unwrap_or_default()
        {
            return Ok(());
        }

        let now = Utc::now();

        sqlx::query!(
            r#"UPDATE posthog_errortrackingsymbolset SET last_used = $2 WHERE id = $1"#,
            self.id,
            now
        )
        .execute(e)
        .await?;

        self.last_used = Some(now);

        Ok(())
    }

    // Save the current record to the database. If the record already exists, it will be updated
    // with the new storage pointer, content hash and failure reason. If it doesn't exist, a new
    // record will be created. Takes a mutable reference to self because it will update the found
    // id if a conflict occurs.
    pub async fn save<'c, E>(&mut self, e: E) -> Result<(), UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let truncated_ref = truncate_ref(&self.set_ref);
        self.id = sqlx::query_scalar!(
            r#"
            INSERT INTO posthog_errortrackingsymbolset (id, team_id, ref, storage_ptr, failure_reason, created_at, content_hash, last_used)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (team_id, ref) DO UPDATE SET storage_ptr = $4, content_hash = $7, failure_reason = $5, last_used = $8
            RETURNING id
            "#,
            self.id,
            self.team_id,
            truncated_ref,
            self.storage_ptr,
            self.failure_reason,
            self.created_at,
            self.content_hash,
            self.last_used
        )
        .fetch_one(e)
        .await.expect("Got at least one row back");

        metrics::counter!(SYMBOL_SET_SAVED).increment(1);

        Ok(())
    }

    pub async fn save_data_if_missing<'c, E>(&mut self, e: E) -> Result<bool, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let truncated_ref = truncate_ref(&self.set_ref);
        let id = sqlx::query_scalar::<_, Uuid>(
            r#"
            INSERT INTO posthog_errortrackingsymbolset (id, team_id, ref, storage_ptr, failure_reason, created_at, content_hash, last_used)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (team_id, ref) DO UPDATE
            SET storage_ptr = $4, content_hash = $7, failure_reason = $5, last_used = $8
            WHERE posthog_errortrackingsymbolset.storage_ptr IS NULL
            RETURNING id
            "#,
        )
        .bind(self.id)
        .bind(self.team_id)
        .bind(truncated_ref)
        .bind(&self.storage_ptr)
        .bind(&self.failure_reason)
        .bind(self.created_at)
        .bind(&self.content_hash)
        .bind(self.last_used)
        .fetch_optional(e)
        .await?;

        if let Some(id) = id {
            self.id = id;
            metrics::counter!(SYMBOL_SET_SAVED).increment(1);
            return Ok(true);
        }

        Ok(false)
    }

    // Returns whether a failure row was actually written. The upsert is a no-op (returns
    // `false`) when a row already exists with a `storage_ptr` — i.e. real symbol data is present
    // — because the `WHERE storage_ptr IS NULL` guard refuses to clobber it. Callers must not
    // treat a no-op as a stored failure (e.g. must not cache it), since the DB source of truth
    // still holds usable data for that ref.
    pub async fn save_failure<'c, E>(&mut self, e: E) -> Result<bool, UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let truncated_ref = truncate_ref(&self.set_ref);
        if let Some(id) = sqlx::query_scalar::<_, Uuid>(
            r#"
            INSERT INTO posthog_errortrackingsymbolset (id, team_id, ref, storage_ptr, failure_reason, created_at, content_hash, last_used)
            VALUES ($1, $2, $3, NULL, $4, $5, NULL, $6)
            ON CONFLICT (team_id, ref) DO UPDATE
            SET failure_reason = $4, last_used = $6
            WHERE posthog_errortrackingsymbolset.storage_ptr IS NULL
            RETURNING id
            "#,
        )
        .bind(self.id)
        .bind(self.team_id)
        .bind(truncated_ref)
        .bind(&self.failure_reason)
        .bind(self.created_at)
        .bind(self.last_used)
        .fetch_optional(e)
        .await?
        {
            self.id = id;
            metrics::counter!(SYMBOL_SET_SAVED).increment(1);
            return Ok(true);
        }

        Ok(false)
    }

    pub async fn delete<'c, E>(&mut self, e: E) -> Result<(), UnhandledError>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let _ignored = sqlx::query!(
            r#"
            DELETE FROM posthog_errortrackingsymbolset WHERE id = $1
            "#,
            self.id
        )
        .execute(e)
        .await; // We don't really care if this fails, since it's a robustness thing anyway

        capture_symbol_set_deleted(self.team_id, &self.set_ref, self.storage_ptr.as_deref());

        Ok(())
    }
}

#[cfg(test)]
mod test {
    use std::sync::Arc;

    use bytes::Bytes;
    use chrono::Utc;
    use httpmock::MockServer;
    use mockall::predicate;
    use posthog_symbol_data::write_symbol_data;
    use reqwest::Url;
    use sqlx::PgPool;
    use uuid::Uuid;

    use crate::{
        core::config::ResolverConfig,
        symbolication::symbol_store::{
            saving::{truncate_ref, Saving, SymbolSetRecord, MAX_REF_BYTES},
            sourcemap::SourcemapProvider,
            MockS3Client, Provider,
        },
    };

    const CHUNK_PATH: &str = "/static/chunk-PGUQKT6S.js";
    const MINIFIED: &[u8] = include_bytes!("../../../../tests/static/chunk-PGUQKT6S.js");
    const MAP: &[u8] = include_bytes!("../../../../tests/static/chunk-PGUQKT6S.js.map");

    #[test]
    fn test_truncate_ref_short_string() {
        let short = "hello";
        assert_eq!(truncate_ref(short), short);
    }

    #[test]
    fn test_truncate_ref_exact_length() {
        let exact: String = "a".repeat(MAX_REF_BYTES);
        assert_eq!(truncate_ref(&exact), exact.as_str());
    }

    #[test]
    fn test_truncate_ref_long_string() {
        let long: String = "a".repeat(MAX_REF_BYTES + 100);
        let truncated = truncate_ref(&long);
        assert_eq!(truncated.len(), MAX_REF_BYTES);
    }

    #[test]
    fn test_truncate_ref_multibyte_char_boundary() {
        // Create a string with multibyte characters (emoji is 4 bytes)
        let prefix: String = "a".repeat(MAX_REF_BYTES - 2);
        let with_emoji = format!("{}🎉extra", prefix); // emoji at position 1022, would split at 1024
        let truncated = truncate_ref(&with_emoji);
        // Should truncate before the emoji to stay at a valid char boundary
        assert!(truncated.len() <= MAX_REF_BYTES);
        assert!(truncated.is_char_boundary(truncated.len()));
    }

    fn get_symbol_data_bytes() -> Vec<u8> {
        write_symbol_data(posthog_symbol_data::SourceAndMap {
            minified_source: String::from_utf8(MINIFIED.to_vec()).unwrap(),
            sourcemap: String::from_utf8(MAP.to_vec()).unwrap(),
        })
        .unwrap()
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_successful_lookup(db: PgPool) {
        let server = MockServer::start();

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();
        config.allow_internal_ips = true; // Gonna be hitting the sourcemap mocks

        let source_mock = server.mock(|when, then| {
            when.method("GET").path(CHUNK_PATH);
            then.status(200).body(MINIFIED);
        });

        let map_mock = server.mock(|when, then| {
            // Our minified example source uses a relative URL, formatted like this
            when.method("GET").path(format!("{CHUNK_PATH}.map"));
            then.status(200).body(MAP);
        });

        let mut client = MockS3Client::default();
        // Expected: we'll hit the backend and store the data in s3.
        client
            .expect_put()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
                predicate::eq(Bytes::from(get_symbol_data_bytes())), // We won't assert on the contents written
            )
            .returning(|_, _, _| Ok(()))
            .once();

        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
            )
            .returning(|_, _| Ok(Some(Bytes::from(get_symbol_data_bytes()))));

        let smp = SourcemapProvider::new(&config);
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            Arc::new(client),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
            std::time::Duration::from_secs(config.symbol_set_negative_cache_ttl_seconds),
        );

        let test_url = Url::parse(&server.url(CHUNK_PATH.to_string())).unwrap();

        // First hit - we should fetch the data
        saving_smp.lookup(0, test_url.clone()).await.unwrap();
        source_mock.assert_hits(1);
        map_mock.assert_hits(1);

        // On the second lookup, we don't hit the "backend" at all
        saving_smp.lookup(0, test_url.clone()).await.unwrap();
        source_mock.assert_hits(1);
        map_mock.assert_hits(1);
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_dynamic_fetch_cleanup_when_existing_blob_wins_race(db: PgPool) {
        let server = MockServer::start();

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();

        let test_url = Url::parse(&server.url(CHUNK_PATH.to_string())).unwrap();
        let storage_ptr = "symbolsets/existing".to_string();

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id: 0,
            set_ref: test_url.to_string(),
            storage_ptr: Some(storage_ptr.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        };
        record.save(&db).await.unwrap();

        let mut client = MockS3Client::default();
        client
            .expect_put()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
                predicate::eq(Bytes::from(get_symbol_data_bytes())),
            )
            .returning(|_, _, _| Ok(()))
            .once();
        client
            .expect_delete()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
            )
            .returning(|_, _| Ok(()))
            .once();

        let smp = SourcemapProvider::new(&config);
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            Arc::new(client),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
            std::time::Duration::from_secs(config.symbol_set_negative_cache_ttl_seconds),
        );

        saving_smp
            .save_data(
                0,
                test_url.to_string(),
                Bytes::from(get_symbol_data_bytes()),
            )
            .await
            .unwrap();

        let record = SymbolSetRecord::load(&db, 0, test_url.as_ref())
            .await
            .unwrap()
            .unwrap();

        assert_eq!(record.storage_ptr.as_deref(), Some(storage_ptr.as_str()));
        assert!(record.failure_reason.is_none());
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_symbol_set_404_handling(db: PgPool) {
        let server = MockServer::start();

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();
        config.allow_internal_ips = true;

        let source_mock = server.mock(|when, then| {
            when.method("GET").path(CHUNK_PATH);
            then.status(404);
        });

        // We don't expect any S3 operations since we won't get any valid data
        let client = MockS3Client::default();

        let smp = SourcemapProvider::new(&config);
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            Arc::new(client),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
            std::time::Duration::from_secs(config.symbol_set_negative_cache_ttl_seconds),
        );

        let test_url = Url::parse(&server.url(CHUNK_PATH.to_string())).unwrap();

        // First attempt should fail
        saving_smp.lookup(0, test_url.clone()).await.unwrap_err();
        source_mock.assert_hits(1);

        // Second attempt should fail immediately without hitting the server
        saving_smp.lookup(0, test_url.clone()).await.unwrap_err();
        source_mock.assert_hits(1); // Still only 1 hit

        // Verify the failure was recorded in postgres
        let record = SymbolSetRecord::load(&db, 0, test_url.as_ref())
            .await
            .unwrap()
            .unwrap();

        assert!(record.storage_ptr.is_none());
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_invalid_sourcemap_handling(db: PgPool) {
        let server = MockServer::start();

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();
        config.allow_internal_ips = true;

        let source_mock = server.mock(|when, then| {
            when.method("GET").path(CHUNK_PATH);
            then.status(200).body(MINIFIED);
        });

        let map_mock = server.mock(|when, then| {
            when.method("GET").path(format!("{CHUNK_PATH}.map"));
            then.status(200).body(Vec::new()); // Empty/invalid sourcemap
        });

        // We don't expect any S3 operations since we won't get any valid data
        let client = MockS3Client::default();

        let smp = SourcemapProvider::new(&config);
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            Arc::new(client),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
            std::time::Duration::from_secs(config.symbol_set_negative_cache_ttl_seconds),
        );

        let test_url = Url::parse(&server.url(CHUNK_PATH.to_string())).unwrap();

        // First attempt should fail
        saving_smp.lookup(0, test_url.clone()).await.unwrap_err();
        source_mock.assert_hits(1);
        map_mock.assert_hits(1);

        // Second attempt should fail immediately without hitting the server
        saving_smp.lookup(0, test_url.clone()).await.unwrap_err();
        source_mock.assert_hits(1); // Still only 1 hit
        map_mock.assert_hits(1); // Still only 1 hit

        // Verify the failure was recorded in postgres
        let record = SymbolSetRecord::load(&db, 0, test_url.as_ref())
            .await
            .unwrap()
            .unwrap();

        assert!(record.storage_ptr.is_none());
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_parse_failure_does_not_overwrite_existing_blob(db: PgPool) {
        let server = MockServer::start();

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();
        config.allow_internal_ips = true;

        let test_url = Url::parse(&server.url(CHUNK_PATH.to_string())).unwrap();
        let storage_ptr = "symbolsets/existing".to_string();

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id: 0,
            set_ref: test_url.to_string(),
            storage_ptr: Some(storage_ptr.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        };
        record.save(&db).await.unwrap();

        let mut client = MockS3Client::default();
        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::eq(storage_ptr.clone()),
            )
            .returning(|_, _| Ok(Some(Bytes::from_static(b"not a sourcemap"))));

        let smp = SourcemapProvider::new(&config);
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            Arc::new(client),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
            std::time::Duration::from_secs(config.symbol_set_negative_cache_ttl_seconds),
        );

        saving_smp.lookup(0, test_url.clone()).await.unwrap_err();

        let record = SymbolSetRecord::load(&db, 0, test_url.as_ref())
            .await
            .unwrap()
            .unwrap();

        assert_eq!(record.storage_ptr.as_deref(), Some(storage_ptr.as_str()));
        assert!(record.failure_reason.is_none());
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_negative_cache_short_circuits_db(db: PgPool) {
        let server = MockServer::start();

        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();
        config.allow_internal_ips = true;

        let source_mock = server.mock(|when, then| {
            when.method("GET").path(CHUNK_PATH);
            then.status(404);
        });

        let client = MockS3Client::default();
        let smp = SourcemapProvider::new(&config);
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            Arc::new(client),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
            std::time::Duration::from_secs(config.symbol_set_negative_cache_ttl_seconds),
        );

        let test_url = Url::parse(&server.url(CHUNK_PATH.to_string())).unwrap();

        // First attempt fails, persists the failure to Postgres, and primes the negative cache.
        saving_smp.lookup(0, test_url.clone()).await.unwrap_err();
        source_mock.assert_hits(1);

        // Delete the stored failure row out from under the resolver. If the second lookup still
        // returns the failure, it can only have come from the in-memory negative cache — proof
        // the DB read was skipped entirely.
        let mut record = SymbolSetRecord::load(&db, 0, test_url.as_ref())
            .await
            .unwrap()
            .unwrap();
        record.delete(&db).await.unwrap();
        assert!(SymbolSetRecord::load(&db, 0, test_url.as_ref())
            .await
            .unwrap()
            .is_none());

        saving_smp.lookup(0, test_url.clone()).await.unwrap_err();
        // Still no second upstream hit, and the DB no longer holds the row.
        source_mock.assert_hits(1);
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_transient_errors_are_not_cached(db: PgPool) {
        use std::sync::atomic::{AtomicUsize, Ordering};

        use async_trait::async_trait;

        use crate::{error::UnhandledError, symbolication::symbol_store::Fetcher};

        // Inner fetcher that always fails with a *transient* (non-resolution) error and counts
        // how many times it was called.
        struct FlakyFetcher {
            fetches: Arc<std::sync::atomic::AtomicUsize>,
        }

        #[async_trait]
        impl Fetcher for FlakyFetcher {
            type Ref = Url;
            type Fetched = Bytes;
            type Err = crate::error::ResolveError;

            async fn fetch(
                &self,
                _team_id: i32,
                _r: Self::Ref,
            ) -> Result<Self::Fetched, Self::Err> {
                self.fetches.fetch_add(1, Ordering::SeqCst);
                Err(UnhandledError::Other("transient boom".to_string()).into())
            }
        }

        let fetches = Arc::new(AtomicUsize::new(0));
        let saving = Saving::new(
            FlakyFetcher {
                fetches: fetches.clone(),
            },
            db.clone(),
            Arc::new(MockS3Client::default()),
            "test-bucket".to_string(),
            "test-prefix".to_string(),
            std::time::Duration::from_secs(300),
        );

        let url = Url::parse("https://example.com/static/app.js").unwrap();

        // Two fetches: a transient error must never be cached, so the inner fetcher is reached
        // both times (the second isn't short-circuited by the negative cache). `Saveable` (the
        // Ok type) isn't `Debug`, so match rather than `unwrap_err`.
        assert!(saving.fetch(0, url.clone()).await.is_err());
        assert!(saving.fetch(0, url.clone()).await.is_err());
        assert_eq!(fetches.load(Ordering::SeqCst), 2);
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_uploaded_chunk_id_data_wins_over_cached_url_failure(db: PgPool) {
        use crate::symbolication::symbol_store::{
            chunk_id::{ChunkIdFetcher, OrChunkId},
            Fetcher,
        };

        // Regression: for an `OrChunkId::Both`, a cached failure under the (lower-priority) URL
        // must never short-circuit ahead of real data uploaded under the (higher-priority)
        // chunk id. The cache is probed per ref inside the priority loop, so the chunk-id row is
        // found before the URL cache entry is ever consulted.
        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();

        let chunk_id = Uuid::now_v7().to_string();
        let url = Url::parse("https://example.com/static/app.js").unwrap();
        let storage_ptr = "symbolsets/uploaded".to_string();

        // Uploaded symbol data, keyed by chunk id.
        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id: 0,
            set_ref: chunk_id.clone(),
            storage_ptr: Some(storage_ptr.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        };
        record.save(&db).await.unwrap();

        // `Saving::fetch` handles saved lookup refs itself: it loads the chunk-id row and reads
        // the blob via its OWN s3 client, without delegating to the inner ChunkIdFetcher. So the
        // S3 expectation must live on the Saving-layer client; the ChunkIdFetcher's client is
        // never exercised on this path.
        let mut saving_client = MockS3Client::default();
        saving_client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::eq(storage_ptr.clone()),
            )
            .returning(|_, _| Ok(Some(Bytes::from(get_symbol_data_bytes()))));

        let chunk_id_smp = ChunkIdFetcher::new(
            SourcemapProvider::new(&config),
            Arc::new(MockS3Client::default()),
            db.clone(),
            config.object_storage_bucket.clone(),
        );
        let saving = Saving::new(
            chunk_id_smp,
            db.clone(),
            Arc::new(saving_client),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
            std::time::Duration::from_secs(config.symbol_set_negative_cache_ttl_seconds),
        );

        // Poison the URL key with a stored failure, as a prior capture-time miss would have.
        let stored = crate::error::FrameError::JavaScript(crate::error::JsResolveErr::NoSourcemap(
            url.to_string(),
        ));
        saving
            .negative_cache
            .insert(
                (0, url.to_string()),
                serde_json::to_string(&stored).unwrap(),
            )
            .await;

        // The Both lookup must return the uploaded chunk-id data, not the cached URL failure.
        let both = OrChunkId::both(url, chunk_id);
        saving
            .fetch(0, both)
            .await
            .map(|_| ())
            .expect("chunk-id data must win over the cached URL failure");
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_saving_data_invalidates_cached_failure(db: PgPool) {
        use crate::symbolication::symbol_store::Fetcher;

        // Regression: once real data is saved for a ref, a previously-cached failure for that
        // same ref must not keep shadowing it until the TTL. `save_data` invalidates the entry.
        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();

        let url = Url::parse("https://example.com/static/app.js").unwrap();

        let mut client = MockS3Client::default();
        client
            .expect_put()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
                predicate::always(),
            )
            .returning(|_, _, _| Ok(()))
            .once();
        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
            )
            .returning(|_, _| Ok(Some(Bytes::from(get_symbol_data_bytes()))));

        // The inner provider is irrelevant here: after invalidation the lookup is served from the
        // DB data row + S3, and if it were ever reached it would just error.
        let smp = SourcemapProvider::new(&config);
        let saving = Saving::new(
            smp,
            db.clone(),
            Arc::new(client),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
            std::time::Duration::from_secs(config.symbol_set_negative_cache_ttl_seconds),
        );

        // Prime a stored failure for the URL, as an earlier failed lookup would have.
        let stored = crate::error::FrameError::JavaScript(crate::error::JsResolveErr::NoSourcemap(
            url.to_string(),
        ));
        saving
            .negative_cache
            .insert(
                (0, url.to_string()),
                serde_json::to_string(&stored).unwrap(),
            )
            .await;

        // Persist real data for the same URL. This must invalidate the negative-cache entry.
        saving
            .save_data(0, url.to_string(), Bytes::from(get_symbol_data_bytes()))
            .await
            .unwrap();

        // The next fetch must return the freshly-saved data, not the stale cached failure.
        saving
            .fetch(0, url)
            .await
            .map(|_| ())
            .expect("saved data must win over the previously-cached failure");
    }

    // Negative-cache tests. These construct `Saving` over a *lazy* Postgres pool that never
    // connects: on a negative-cache hit `fetch` returns before any DB query, so the pool is
    // never touched, and the assertions are DB-free. The `transient_errors_are_not_cached`
    // and populate-from-DB behaviours require a live DB and live in the sqlx tests above.
    mod negative_cache {
        use std::{
            sync::{
                atomic::{AtomicUsize, Ordering},
                Arc,
            },
            time::Duration,
        };

        use async_trait::async_trait;
        use bytes::Bytes;
        use reqwest::Url;
        use sqlx::PgPool;

        use crate::{
            error::{FrameError, JsResolveErr, ResolveError},
            symbolication::symbol_store::{
                saving::{truncate_ref, Saving, MAX_REF_BYTES},
                Fetcher, MockS3Client,
            },
        };

        // A `Fetcher` that counts how many times its `fetch` runs, so a test can assert the
        // negative cache short-circuited before reaching the inner layer.
        struct CountingFetcher {
            fetches: Arc<AtomicUsize>,
        }

        #[async_trait]
        impl Fetcher for CountingFetcher {
            type Ref = Url;
            type Fetched = Bytes;
            type Err = ResolveError;

            async fn fetch(
                &self,
                _team_id: i32,
                _r: Self::Ref,
            ) -> Result<Self::Fetched, Self::Err> {
                self.fetches.fetch_add(1, Ordering::SeqCst);
                Ok(Bytes::from_static(b"unexpected"))
            }
        }

        fn build_saving(fetches: Arc<AtomicUsize>) -> Saving<CountingFetcher> {
            // Lazy pool: constructing it never connects, and these tests never trigger a query.
            let pool = PgPool::connect_lazy("postgres://localhost/does-not-connect").unwrap();
            Saving::new(
                CountingFetcher { fetches },
                pool,
                Arc::new(MockS3Client::default()),
                "test-bucket".to_string(),
                "test-prefix".to_string(),
                Duration::from_secs(300),
            )
        }

        #[tokio::test]
        async fn hit_returns_stored_error_without_touching_inner_or_db() {
            let fetches = Arc::new(AtomicUsize::new(0));
            let saving = build_saving(fetches.clone());

            let team_id = 7;
            let url = Url::parse("https://example.com/static/app.js").unwrap();
            // Store the same serialized shape the DB path persists: a JSON `FrameError`.
            let stored = FrameError::JavaScript(JsResolveErr::NoSourcemap(url.to_string()));
            saving
                .negative_cache
                .insert(
                    (team_id, url.to_string()),
                    serde_json::to_string(&stored).unwrap(),
                )
                .await;

            // `Saveable` (the Ok type) isn't `Debug`, so destructure rather than `unwrap_err`.
            let Err(err) = saving.fetch(team_id, url.clone()).await else {
                panic!("expected the cached failure to be returned");
            };

            // The stored failure is rebuilt exactly, not swallowed into an UnhandledError, and
            // the inner fetcher (and thus the DB, since the pool can't connect) is never reached.
            match err {
                ResolveError::ResolutionError(frame_err) => assert_eq!(frame_err, stored),
                other => panic!("expected rebuilt ResolutionError, got {other:?}"),
            }
            assert_eq!(fetches.load(Ordering::SeqCst), 0);
        }

        #[tokio::test]
        async fn miss_for_a_different_team_does_not_collide() {
            let fetches = Arc::new(AtomicUsize::new(0));
            let saving = build_saving(fetches.clone());

            let url = Url::parse("https://example.com/static/app.js").unwrap();
            let stored = FrameError::JavaScript(JsResolveErr::NoSourcemap(url.to_string()));
            // Seed team 1 only.
            saving
                .negative_cache
                .insert(
                    (1, url.to_string()),
                    serde_json::to_string(&stored).unwrap(),
                )
                .await;

            // A lookup for team 2 with the same ref must not hit team 1's entry — the probe
            // misses, falls through to the (lazy, unconnected) DB, and errors trying to connect.
            // `Saveable` (the Ok type) isn't `Debug`, so destructure rather than `unwrap_err`.
            let Err(err) = saving.fetch(2, url).await else {
                panic!("expected a DB connection failure on cache miss");
            };
            match err {
                ResolveError::UnhandledError(_) => {} // DB connect failure — expected on a miss
                other => panic!("expected a DB connection failure on cache miss, got {other:?}"),
            }
        }

        #[tokio::test]
        async fn probe_truncates_the_ref_to_match_the_db_key_space() {
            let fetches = Arc::new(AtomicUsize::new(0));
            let saving = build_saving(fetches.clone());

            // A ref longer than the DB truncation bound. The DB writes/looks up under the
            // truncated form, so the cache must key by the truncated form too — otherwise a
            // populate-under-truncated / probe-under-full mismatch would silently never hit.
            let long_url = Url::parse(&format!(
                "https://example.com/{}",
                "a".repeat(MAX_REF_BYTES)
            ))
            .unwrap();
            let long_ref = long_url.to_string();
            assert!(long_ref.len() > MAX_REF_BYTES);
            let stored = FrameError::JavaScript(JsResolveErr::NoSourcemap("x".to_string()));
            // Seed exactly as the code does: under the truncated key.
            saving
                .negative_cache
                .insert(
                    (3, truncate_ref(&long_ref).to_string()),
                    serde_json::to_string(&stored).unwrap(),
                )
                .await;

            // Probing with the full (untruncated) ref must still hit, proving the probe truncates.
            let Err(err) = saving.fetch(3, long_url).await else {
                panic!("expected the cached failure for the truncated ref to be returned");
            };
            match err {
                ResolveError::ResolutionError(frame_err) => assert_eq!(frame_err, stored),
                other => panic!("expected rebuilt ResolutionError, got {other:?}"),
            }
            assert_eq!(fetches.load(Ordering::SeqCst), 0);
        }
    }
}
