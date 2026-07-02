use std::{
    fmt::{Debug, Display},
    sync::Arc,
};

use async_trait::async_trait;
use bytes::Bytes;
use metrics::counter;
use sha2::{Digest, Sha512};
use sqlx::PgPool;
use tracing::error;

use crate::{
    error::{FrameError, UnhandledError},
    metric_consts::{CHUNK_ID_FAILURE_FETCHED, CHUNK_ID_NOT_FOUND},
    symbolication::symbol_store::BlobClient,
};

use super::{saving::SymbolSetRecord, Fetcher, Parser};

pub struct ChunkIdFetcher<Parser> {
    pub inner: Parser,
    pub client: Arc<dyn BlobClient>,
    pub pool: PgPool,
    pub bucket: String,
}

impl<P> ChunkIdFetcher<P> {
    pub fn new(inner: P, client: Arc<dyn BlobClient>, pool: PgPool, bucket: String) -> Self {
        Self {
            inner,
            client,
            pool,
            bucket,
        }
    }
}

pub enum OrChunkId<R> {
    Inner(R),
    ChunkId(String),
    Both { inner: R, id: String },
}

pub enum SymbolSetLoadResult {
    Data(Bytes),
    Missing,
    Failed(String),
    MissingStoragePtr(String),
    MissingBlob(SymbolSetRecord),
}

pub async fn load_symbol_set_data(
    pool: &PgPool,
    client: &dyn BlobClient,
    bucket: &str,
    team_id: i32,
    set_ref: &str,
) -> Result<SymbolSetLoadResult, UnhandledError> {
    let Some(mut record) = SymbolSetRecord::load(pool, team_id, set_ref).await? else {
        return Ok(SymbolSetLoadResult::Missing);
    };

    if let Some(failure_reason) = record.failure_reason {
        return Ok(SymbolSetLoadResult::Failed(failure_reason));
    }

    let Some(storage_ptr) = record.storage_ptr.clone() else {
        return Ok(SymbolSetLoadResult::MissingStoragePtr(record.set_ref));
    };

    record.set_last_used(pool).await?;

    // Otherwise, if we just failed to talk to s3 for some reason, treat it as an unhandled error and die
    match client.get(bucket, &storage_ptr).await? {
        Some(data) => Ok(SymbolSetLoadResult::Data(data)),
        None => Ok(SymbolSetLoadResult::MissingBlob(record)),
    }
}

// This is more-or-less a read-only version of the saving layer - it never writes symbol sets, although
// it will modify records to indicate an error if the underlying parser fails. For symbol sets we dynamically
// fetch (like js sourcemaps), it's main function is to strip the `OrChunkId` from the ref and pass the
// underlying identifier to the inner fetcher. In those cases, it should be wrapped in a saving layer, so
// that the data the inner fetcher returns will be saved to s3 and re-used - and due to this, it's own loading
// of saved symbol sets will never run, because the saving layer takes care of thet.
//
// For symbol sets we never fetch dynamically (hermes, node, java etc), it's used stand-alone, and the underlying
// fetcher unconditionally returns an error indicating the chunk ID was not found. Often, these inner fetchers
// use a 0 variant enum to indicate their data is only available in the presence of a chunk ID, and the underlying
// fetcher simply asserts `unreachable!()`.
//
// Layers above this one use dedicated ref-derivation traits:
//   - Caching and concurrency use `SymbolSetCacheKey`, which keeps the `Inner`, `ChunkId`,
//     and `Both` namespaces distinct so attacker-controlled refs cannot poison each other.
//   - The `Saving` persistence layer uses `SymbolSetKey`, which separates
//     the lookup keys (chunk id first, then URL) from the save key (URL when present).
//     See the trait's docs for why those are kept distinct.
#[async_trait]
impl<P> Fetcher for ChunkIdFetcher<P>
where
    P: Fetcher<Fetched = Bytes>,
    P::Ref: Send,
    P::Err: From<UnhandledError> + From<FrameError>,
{
    type Ref = OrChunkId<P::Ref>;
    type Fetched = P::Fetched;
    type Err = P::Err;

    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Self::Fetched, Self::Err> {
        let (id, inner) = match r {
            OrChunkId::Inner(inner) => {
                // We have no chunk id, just strip off the wrapper and return the inner result
                return self.inner.fetch(team_id, inner).await;
            }
            OrChunkId::ChunkId(id) => (id, None),
            OrChunkId::Both { inner, id } => (id, Some(inner)),
        };

        match load_symbol_set_data(&self.pool, self.client.as_ref(), &self.bucket, team_id, &id)
            .await?
        {
            SymbolSetLoadResult::Data(data) => Ok(data),
            SymbolSetLoadResult::Missing => {
                counter!(CHUNK_ID_NOT_FOUND).increment(1);
                let Some(inner) = inner else {
                    return Err(FrameError::MissingChunkIdData(id).into());
                };
                // We have a chunk id, but it's not saved - fetch with the inner, knowing the OrChunkId's
                // `Display` implementation will use the chunk id as the set reference everywhere else
                self.inner.fetch(team_id, inner).await
            }
            SymbolSetLoadResult::Failed(failure_reason) => {
                // If we failed to parse this chunk's data in the past, we should not try again.
                // Note that in situations where we're running beneath a `Saving` layer, we'll
                // never reach this point, but we still handle the case for correctness sake
                counter!(CHUNK_ID_FAILURE_FETCHED).increment(1);
                let error: FrameError =
                    serde_json::from_str(&failure_reason).map_err(UnhandledError::from)?;
                Err(error.into())
            }
            SymbolSetLoadResult::MissingStoragePtr(set_ref) => {
                // It's never valid to have no failure reason and no storage pointer - if we hit this case, just panic
                error!("No storage pointer found for chunk id {}", set_ref);
                panic!("No storage pointer found for chunk id {set_ref}");
            }
            SymbolSetLoadResult::MissingBlob(mut record) => {
                // If the chunk ID points to a record that doesn't exist, delete the record and treat it as a frame error
                record.delete(&self.pool).await?;
                Err(FrameError::MissingChunkIdData(record.set_ref).into())
            }
        }
    }
}

// Let the underlying parser handle decoding the data, not caring whether it was uploaded
// or fetched from the internet
#[async_trait]
impl<P> Parser for ChunkIdFetcher<P>
where
    P: Parser<Source = Bytes>,
    P::Set: Send,
{
    type Source = P::Source;
    type Set = P::Set;
    type Err = P::Err;

    async fn parse(&self, data: Self::Source) -> Result<Self::Set, Self::Err> {
        self.inner.parse(data).await
    }
}

impl<Ref> Debug for OrChunkId<Ref>
where
    Ref: Debug,
{
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OrChunkId::Inner(inner) => write!(f, "Inner({inner:?})"),
            OrChunkId::ChunkId(id) => write!(f, "ChunkId({id})"),
            OrChunkId::Both { inner, id } => write!(f, "Both {{ inner: {inner:?}, id: {id} }}"),
        }
    }
}

impl<Ref> Clone for OrChunkId<Ref>
where
    Ref: Clone,
{
    fn clone(&self) -> Self {
        match self {
            OrChunkId::Inner(inner) => OrChunkId::Inner(inner.clone()),
            OrChunkId::ChunkId(id) => OrChunkId::ChunkId(id.clone()),
            OrChunkId::Both { inner, id } => OrChunkId::Both {
                inner: inner.clone(),
                id: id.clone(),
            },
        }
    }
}

// `Display` is the human-readable identity of a ref, used by log lines and resolved frame
// metadata. For Both, we surface the chunk id because it's the more meaningful identifier
// across frames carrying both a URL and a chunk id.
//
// The persistence and caching layers do NOT use this — see `SymbolSetKey` and
// `SymbolSetCacheKey` below for why.
impl<R> Display for OrChunkId<R>
where
    R: Display,
{
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OrChunkId::Inner(inner) => inner.fmt(f),
            OrChunkId::ChunkId(id) => write!(f, "{id}"),
            OrChunkId::Both { inner: _, id } => write!(f, "{id}"),
        }
    }
}

// `SymbolSetCacheKey` is the in-memory cache / concurrency identity. Unlike `Display`, it
// must keep `Both(id, inner)` distinct from bare `ChunkId(id)`: a `Both` lookup may fall back
// to fetching attacker-controlled URL data when the chunk id is missing, and caching that under
// the bare chunk-id key would transiently poison future chunk-id-only lookups.
pub trait SymbolSetCacheKey {
    fn symbol_set_cache_key(&self) -> String;
}

fn hashed_symbol_set_cache_key(prefix: &str, parts: &[&str]) -> String {
    let mut hasher = Sha512::new();
    for part in parts {
        hasher.update(part.len().to_be_bytes());
        hasher.update(part.as_bytes());
    }
    format!("{}:{:x}", prefix, hasher.finalize())
}

impl<R> SymbolSetCacheKey for OrChunkId<R>
where
    R: Display,
{
    fn symbol_set_cache_key(&self) -> String {
        match self {
            OrChunkId::Inner(inner) => hashed_symbol_set_cache_key("inner", &[&inner.to_string()]),
            OrChunkId::ChunkId(id) => hashed_symbol_set_cache_key("chunk-id", &[id]),
            OrChunkId::Both { inner, id } => {
                hashed_symbol_set_cache_key("both", &[id, &inner.to_string()])
            }
        }
    }
}

impl SymbolSetCacheKey for reqwest::Url {
    fn symbol_set_cache_key(&self) -> String {
        hashed_symbol_set_cache_key("inner", &[self.as_str()])
    }
}

// `SymbolSetKey` separates the DB lookup keys from the DB save key.
//
// The capture pipeline can receive a frame carrying both an attacker-controlled URL and an
// arbitrary chunk id. Persisting that fetch under the chunk id namespace would let the
// capture path squat rows that the authenticated upload API (which always keys by chunk id)
// would later want to write — letting unauthenticated capture traffic pre-empt or be
// confused with authenticated uploads.
//
// To prevent that, capture-driven writes are keyed by the URL the bytes were fetched from,
// while upload-driven writes stay keyed by chunk id. The two writers can no longer target
// the same row. Lookups still try the chunk id first (so an upload-API row keyed by chunk
// id is preferred over a capture-cached row keyed by URL), then fall back to the URL.
//
// `save_ref` is `None` for a bare `ChunkId` ref — there is no URL to fetch from, so there's
// nothing meaningful to persist, and we refuse to write a row keyed by a chunk id we never
// fetched data for.
pub trait SymbolSetKey {
    fn lookup_refs(&self) -> Vec<String>;
    fn save_ref(&self) -> Option<String>;
}

impl<R> SymbolSetKey for OrChunkId<R>
where
    R: Display,
{
    fn lookup_refs(&self) -> Vec<String> {
        match self {
            OrChunkId::Inner(inner) => vec![inner.to_string()],
            OrChunkId::ChunkId(id) => vec![id.clone()],
            OrChunkId::Both { inner, id } => vec![id.clone(), inner.to_string()],
        }
    }

    fn save_ref(&self) -> Option<String> {
        match self {
            OrChunkId::Inner(inner) => Some(inner.to_string()),
            OrChunkId::Both { inner, .. } => Some(inner.to_string()),
            OrChunkId::ChunkId(_) => None,
        }
    }
}

// `Url` standalone behaves exactly like `OrChunkId::Inner(url)` — a single self-keyed ref
// with no chunk-id alternative. Used directly by unit tests that wrap `SourcemapProvider`
// in `Saving` without an intervening `ChunkIdFetcher`.
impl SymbolSetKey for reqwest::Url {
    fn lookup_refs(&self) -> Vec<String> {
        vec![self.to_string()]
    }

    fn save_ref(&self) -> Option<String> {
        Some(self.to_string())
    }
}

impl<R> OrChunkId<R> {
    pub fn inner(inner: R) -> Self {
        Self::Inner(inner)
    }

    pub fn chunk_id(chunk_id: String) -> Self {
        Self::ChunkId(chunk_id)
    }

    pub fn both(inner: R, chunk_id: String) -> Self {
        Self::Both {
            inner,
            id: chunk_id,
        }
    }
}

#[cfg(test)]
mod test {
    use std::sync::Arc;

    use async_trait::async_trait;
    use bytes::Bytes;
    use chrono::Utc;
    use common_types::ClickHouseEvent;
    use mockall::predicate;
    use posthog_symbol_data::write_symbol_data;
    use reqwest::Url;
    use sqlx::PgPool;
    use uuid::Uuid;

    use crate::{
        core::config::ResolverConfig,
        core::types::Stacktrace,
        error::ResolveError,
        frames::RawFrame,
        langs::js::RawJSFrame,
        symbolication::symbol_store::{
            apple::AppleProvider,
            chunk_id::{ChunkIdFetcher, OrChunkId, SymbolSetCacheKey},
            hermesmap::HermesMapProvider,
            native::NativeProvider,
            proguard::ProguardProvider,
            saving::SymbolSetRecord,
            sourcemap::{OwnedSourceMapCache, SourcemapProvider},
            Catalog, MockS3Client, Provider,
        },
        types::RawErrProps,
    };

    const EXAMPLE_EXCEPTION: &str =
        include_str!("../../../../tests/static/raw_ch_exception_list.json");
    const MINIFIED: &[u8] = include_bytes!("../../../../tests/static/chunk-PGUQKT6S.js");
    const MAP: &[u8] = include_bytes!("../../../../tests/static/chunk-PGUQKT6S.js.map");

    // Used to construct a Catalog with only the chunk id based provider implemented
    #[allow(dead_code)]
    struct UnimplementedProvider;
    #[async_trait]
    impl Provider for UnimplementedProvider {
        type Ref = Url;
        type Set = OwnedSourceMapCache;
        type Err = ResolveError;

        async fn lookup(&self, _team_id: i32, _r: Self::Ref) -> Result<Arc<Self::Set>, Self::Err> {
            unimplemented!()
        }
    }

    fn get_symbol_data_bytes() -> Vec<u8> {
        write_symbol_data(posthog_symbol_data::SourceAndMap {
            minified_source: String::from_utf8(MINIFIED.to_vec()).unwrap(),
            sourcemap: String::from_utf8(MAP.to_vec()).unwrap(),
        })
        .unwrap()
    }

    #[test]
    fn symbol_set_cache_key_keeps_ref_namespaces_distinct() {
        let chunk_id = Uuid::now_v7().to_string();
        let url = Url::parse("https://example.com/static/chunk.js").unwrap();

        let both = OrChunkId::both(url.clone(), chunk_id.clone()).symbol_set_cache_key();
        let chunk_only = OrChunkId::<Url>::chunk_id(chunk_id).symbol_set_cache_key();
        let inner_only = OrChunkId::inner(url).symbol_set_cache_key();

        assert_ne!(both, chunk_only);
        assert_ne!(both, inner_only);
        assert_ne!(chunk_only, inner_only);
    }

    fn get_example_frame() -> RawJSFrame {
        let event: ClickHouseEvent = serde_json::from_str(EXAMPLE_EXCEPTION).unwrap();
        let mut props: RawErrProps = serde_json::from_str(&event.properties.unwrap()).unwrap();
        let stack = props.exception_list.swap_remove(0).stack.unwrap();
        let Stacktrace::Raw { frames } = stack else {
            panic!("Expected a raw stacktrace");
        };

        let frame = frames.into_iter().next().unwrap();
        match frame {
            RawFrame::JavaScriptWeb(f) => f,
            RawFrame::LegacyJS(f) => f,
            _ => panic!("Expected a JS frame"),
        }
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_successful_chunk_idlookup(db: PgPool) {
        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();

        let chunk_id = Uuid::now_v7().to_string();

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id: 1,
            set_ref: chunk_id.clone(),
            storage_ptr: Some(chunk_id.clone()),
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
                predicate::eq(chunk_id.clone()), // We set the chunk id as the storage ptr above, in production it will be a different value with a prefix
            )
            .returning(|_, _| Ok(Some(Bytes::from(get_symbol_data_bytes()))));

        let client = Arc::new(client);

        let smp = SourcemapProvider::new(&config);
        let chunk_id_fetcher =
            ChunkIdFetcher::new(smp, client, db.clone(), config.object_storage_bucket);

        let r = OrChunkId::chunk_id(chunk_id);

        chunk_id_fetcher.lookup(1, r).await.unwrap();
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_frame_uses_right_resolver(db: PgPool) {
        let mut config = ResolverConfig::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();

        let chunk_id = Uuid::now_v7().to_string();

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id: 1,
            set_ref: chunk_id.clone(),
            storage_ptr: Some(chunk_id.clone()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: None,
            last_used: Some(Utc::now()),
        };

        record.save(&db).await.unwrap();

        let mut client = MockS3Client::default();

        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::eq(chunk_id.clone()), // We set the chunk id as the storage ptr above, in production it will be a different value with a prefix
            )
            .returning(|_, _| Ok(Some(Bytes::from(get_symbol_data_bytes()))));

        let client = Arc::new(client);

        let smp = SourcemapProvider::new(&config);
        let chunk_id_fetcher = ChunkIdFetcher::new(
            smp,
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let hermes_map_fetcher = ChunkIdFetcher::new(
            HermesMapProvider {},
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let pgp = ChunkIdFetcher::new(
            ProguardProvider {},
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let apple = ChunkIdFetcher::new(
            AppleProvider {},
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let native = ChunkIdFetcher::new(
            NativeProvider {},
            client.clone(),
            db.clone(),
            config.object_storage_bucket.clone(),
        );

        let catalog = Catalog::new(chunk_id_fetcher, hermes_map_fetcher, pgp, apple, native);

        let mut frame = get_example_frame();
        frame.chunk_id = Some(chunk_id.clone());

        let res = frame.resolve_frame(1, &catalog, 15).await.unwrap();
        assert!(res.resolved)
    }
}
