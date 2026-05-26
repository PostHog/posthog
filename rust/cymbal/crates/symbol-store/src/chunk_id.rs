use std::sync::Arc;

pub use crate::{OrChunkId, SymbolSetCacheKey, SymbolSetKey};
use async_trait::async_trait;
use bytes::Bytes;
use metrics::counter;
use sqlx::PgPool;
use tracing::error;

use crate::{
    error::{FrameError, UnhandledError},
    metric_consts::{CHUNK_ID_FAILURE_FETCHED, CHUNK_ID_NOT_FOUND},
    BlobClient,
};

use crate::{saving::SymbolSetRecord, Fetcher, Parser};

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
