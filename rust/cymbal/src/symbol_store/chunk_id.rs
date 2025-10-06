use std::{
    fmt::{Debug, Display},
    sync::Arc,
};

use axum::async_trait;
use metrics::counter;
use sqlx::PgPool;
use tracing::error;

use crate::{
    error::{FrameError, UnhandledError},
    metric_consts::{CHUNK_ID_FAILURE_FETCHED, CHUNK_ID_NOT_FOUND},
};

use super::{saving::SymbolSetRecord, Fetcher, Parser, S3Client};

pub struct ChunkIdFetcher<Parser> {
    pub inner: Parser,
    pub client: Arc<S3Client>,
    pub pool: PgPool,
    pub bucket: String,
}

impl<P> ChunkIdFetcher<P> {
    pub fn new(inner: P, client: Arc<S3Client>, pool: PgPool, bucket: String) -> Self {
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

// The chunk id handling layer is a little odd. In cases where users have uploaded the symbol set
// with a chunk it, it'll never be hit, because the "saving" layer will fetch the data first, and in
// cases where the user has injected the chunk ID but not uploaded the symbol set, it'll never resolve
// the chunk, instead just fetching the data from the inner layer. This means, in normal practice, all
// it does is strip off the chunk id and pass the inner request to the inner layer. We only make it able
// to hit PG/S3 at all for testing cases.
//
// Most of the "cleverness" of this layer is actually that the `Display` implementation of `OrChunkId`
// which returns the chunk ID if it's set, rather than the inner T's display implementation, which means
// that the saving and caching layers, or any other layers above this one that rely on Fetcher::Ref: ToString
// will use the chunk ID as the symbol set key, rather than the inner T's reference - which makes things like
// deleting all saved frame resolution results for any frame with a chunk ID that were seen before the chunk id
// symbol data was uploaded, possible using the chunk id directly.
#[async_trait]
impl<P> Fetcher for ChunkIdFetcher<P>
where
    P: Fetcher<Fetched = Vec<u8>>,
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

        let Some(record) = SymbolSetRecord::load(&self.pool, team_id, &id).await? else {
            counter!(CHUNK_ID_NOT_FOUND).increment(1);
            let Some(inner) = inner else {
                return Err(FrameError::MissingChunkIdData(id).into());
            };
            // We have a chunk id, but it's not saved - fetch with the inner, knowing the OrChunkId's
            // `Display` implementation will use the chunk id as the set reference everywhere else
            return self.inner.fetch(team_id, inner).await;
        };

        // If we failed to parse this chunk's data in the past, we should not try again.
        // Note that in situations where we're running beneath a `Saving` layer, we'll
        // never reach this point, but we still handle the case for correctness sake
        if let Some(failure_reason) = &record.failure_reason {
            counter!(CHUNK_ID_FAILURE_FETCHED).increment(1);
            let error: FrameError =
                serde_json::from_str(failure_reason).map_err(UnhandledError::from)?;
            return Err(error.into());
        }

        let Some(storage_ptr) = &record.storage_ptr else {
            // It's never valid to have no failure reason and no storage pointer - if we hit this case, just panic
            error!("No storage pointer found for chunk id {}", id);
            panic!("No storage pointer found for chunk id {id}");
        };

        let Ok(data) = self.client.get(&self.bucket, storage_ptr).await else {
            let mut record = record;
            record.delete(&self.pool).await?;
            // This is kind-of false - the actual problem is missing data in s3, with a record that exists, rather than no record being found for
            // a given chunk id - but it's close enough that it's fine for a temporary fix.
            return Err(FrameError::MissingChunkIdData(record.set_ref).into());
        };
        Ok(data)
    }
}

// Let the underlying parser handle decoding the data, not caring whether it was uploaded
// or fetched from the internet
#[async_trait]
impl<P> Parser for ChunkIdFetcher<P>
where
    P: Parser<Source = Vec<u8>>,
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

// The "cleverness" mentioned above - any time an OrChunkId is used as a symbol set reference,
// and the chunk id is set, it will be used as the key when calling ToString, rather than the
// inner T's display impl
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

    use axum::async_trait;
    use chrono::Utc;
    use common_types::ClickHouseEvent;
    use mockall::predicate;
    use posthog_symbol_data::write_symbol_data;
    use reqwest::Url;
    use sqlx::PgPool;
    use uuid::Uuid;

    use crate::{
        config::Config,
        error::ResolveError,
        frames::RawFrame,
        langs::js::RawJSFrame,
        symbol_store::{
            chunk_id::{ChunkIdFetcher, OrChunkId},
            hermesmap::HermesMapProvider,
            saving::SymbolSetRecord,
            sourcemap::{OwnedSourceMapCache, SourcemapProvider},
            Catalog, Provider, S3Client,
        },
        types::{RawErrProps, Stacktrace},
    };

    const EXAMPLE_EXCEPTION: &str = include_str!("../../tests/static/raw_ch_exception_list.json");
    const MINIFIED: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js");
    const MAP: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js.map");

    // Used to construct a Catalog with only the chunk id based provider implemented
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
        let mut config = Config::init_with_defaults().unwrap();
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

        let mut client = S3Client::default();

        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::eq(chunk_id.clone()), // We set the chunk id as the storage ptr above, in production it will be a different value with a prefix
            )
            .returning(|_, _| Ok(get_symbol_data_bytes()));

        let client = Arc::new(client);

        let smp = SourcemapProvider::new(&config);
        let chunk_id_fetcher =
            ChunkIdFetcher::new(smp, client, db.clone(), config.object_storage_bucket);

        let r = OrChunkId::chunk_id(chunk_id);

        chunk_id_fetcher.lookup(1, r).await.unwrap();
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_frame_uses_right_resolver(db: PgPool) {
        let mut config = Config::init_with_defaults().unwrap();
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

        let mut client = S3Client::default();

        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::eq(chunk_id.clone()), // We set the chunk id as the storage ptr above, in production it will be a different value with a prefix
            )
            .returning(|_, _| Ok(get_symbol_data_bytes()));

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
            config.object_storage_bucket,
        );

        let catalog = Catalog::new(chunk_id_fetcher, hermes_map_fetcher);

        let mut frame = get_example_frame();
        frame.chunk_id = Some(chunk_id.clone());

        let res = frame.resolve(1, &catalog).await.unwrap();
        assert!(res.resolved)
    }
}
