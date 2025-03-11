use std::{
    fmt::{Debug, Display},
    sync::Arc,
};

use axum::async_trait;
use metrics::counter;
use sqlx::PgPool;
use tracing::{error, warn};

use crate::{
    error::{ChunkIdError, Error, UnhandledError},
    metric_consts::{
        CHUNK_ID_FAILURE_FETCHED, CHUNK_ID_FAILURE_SAVED, CHUNK_ID_MISSING_STORAGE_PTR,
        CHUNK_ID_NOT_FOUND,
    },
};

use super::{
    saving::{Saveable, SymbolSetRecord},
    Fetcher, Parser, S3Client,
};

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

pub struct WithChunkId<R> {
    pub inner: R,
    pub chunk_id: ChunkId,
}

#[derive(Debug, Clone)]
pub struct ChunkId(pub String);

#[async_trait]
impl<P> Fetcher for ChunkIdFetcher<P>
where
    P: Send + Sync + 'static,
{
    type Ref = ChunkId;
    type Fetched = Saveable;
    type Err = ChunkIdError;

    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Self::Fetched, Self::Err> {
        let id = r.0;

        let Some(record) = SymbolSetRecord::load(&self.pool, team_id, &id).await? else {
            counter!(CHUNK_ID_NOT_FOUND).increment(1);
            return Err(ChunkIdError::NotFound(id.clone()).into());
        };

        // If we failed to parse this chunk's data in the past, we should not try again.
        if let Some(failure_reason) = record.failure_reason {
            counter!(CHUNK_ID_FAILURE_FETCHED).increment(1);
            // TODO - see comment in `saving.rs` about whether we should simply delete records where
            // we fail to parse the failure reason, but for now requiring manual intervention is fine
            let error = serde_json::from_str(&failure_reason).map_err(UnhandledError::from)?;
            return Err(Error::ResolutionError(error).into());
        }

        let Some(storage_ptr) = record.storage_ptr else {
            // TODO: I think we should just panic on this, actually - it's never valid for us to
            // have a symbol record for a chunk id with no storage pointer and no failure reason.
            error!("No storage pointer found for chunk id {}", id);
            counter!(CHUNK_ID_MISSING_STORAGE_PTR).increment(1);
            return Err(ChunkIdError::MissingStoragePtr(id.clone()).into());
        };

        let data = self.client.get(&self.bucket, &storage_ptr).await?;

        Ok(Saveable {
            data,
            storage_ptr: Some(storage_ptr),
            team_id,
            set_ref: id,
        })
    }
}

#[async_trait]
impl<P> Parser for ChunkIdFetcher<P>
where
    P: Parser<Source = Vec<u8>, Err = Error>,
    P::Set: Send,
{
    type Source = Saveable;
    type Set = P::Set;
    type Err = ChunkIdError;

    async fn parse(&self, data: Self::Source) -> Result<Self::Set, Self::Err> {
        let (team_id, chunk_id, data) = (data.team_id, data.set_ref, data.data);
        let res = self.inner.parse(data).await;

        match res {
            Ok(s) => Ok(s),
            Err(Error::ResolutionError(e)) => {
                if let Some(mut record) =
                    SymbolSetRecord::load(&self.pool, team_id, &chunk_id).await?
                {
                    // If someone else has already deleted the chunk id record, that's fine, just return an error
                    warn!("Saving a parse error for chunk id: {}", chunk_id);
                    counter!(CHUNK_ID_FAILURE_SAVED).increment(1);
                    record.storage_ptr = None;
                    record.content_hash = None;
                    record.failure_reason =
                        Some(serde_json::to_string(&e).map_err(UnhandledError::from)?);
                    record.save(&self.pool).await?;
                };

                Err(e.into())
            }
            Err(e) => Err(e.into()),
        }
    }
}

impl<Ref> Debug for WithChunkId<Ref>
where
    Ref: Debug,
{
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("WithChunkId")
            .field("inner", &self.inner)
            .field("chunk_id", &self.chunk_id)
            .finish()
    }
}

impl<Ref> Clone for WithChunkId<Ref>
where
    Ref: Clone,
{
    fn clone(&self) -> Self {
        Self {
            inner: self.inner.clone(),
            chunk_id: self.chunk_id.clone(),
        }
    }
}

impl Display for ChunkId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

#[cfg(test)]
mod test {
    use std::sync::Arc;

    use axum::async_trait;
    use chrono::Utc;
    use common_symbol_data::write_symbol_data;
    use common_types::ClickHouseEvent;
    use mockall::predicate;
    use reqwest::Url;
    use sqlx::PgPool;
    use uuid::Uuid;

    use crate::{
        config::Config,
        error::Error,
        frames::RawFrame,
        langs::js::RawJSFrame,
        symbol_store::{
            chunk_id::{ChunkId, ChunkIdFetcher},
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
        type Err = Error;

        async fn lookup(&self, _team_id: i32, _r: Self::Ref) -> Result<Arc<Self::Set>, Self::Err> {
            unimplemented!()
        }
    }

    fn get_symbol_data_bytes() -> Vec<u8> {
        write_symbol_data(common_symbol_data::SourceAndMap {
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
            content_hash: None,
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

        chunk_id_fetcher
            .lookup(1, ChunkId(chunk_id.clone()))
            .await
            .unwrap();
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

        let catalog = Catalog::new(UnimplementedProvider, chunk_id_fetcher);

        let mut frame = get_example_frame();
        frame.chunk_id = Some(chunk_id.clone());

        let res = frame.resolve(1, &catalog).await.unwrap();
        assert!(res.resolved)
    }
}
