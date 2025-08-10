use std::sync::Arc;

use axum::async_trait;
use chrono::{DateTime, Duration, Utc};

use sha2::{Digest, Sha512};
use sqlx::PgPool;
use tracing::{error, info};
use uuid::Uuid;

use crate::{
    error::{Error, FrameError, UnhandledError},
    metric_consts::{
        FRAME_RESOLUTION_RESULTS_DELETED, SAVED_SYMBOL_SET_ERROR_RETURNED, SAVED_SYMBOL_SET_LOADED,
        SAVE_SYMBOL_SET, SYMBOL_SET_DB_FETCHES, SYMBOL_SET_DB_HITS, SYMBOL_SET_DB_MISSES,
        SYMBOL_SET_FETCH_RETRY, SYMBOL_SET_SAVED,
    },
    posthog_utils::capture_symbol_set_saved,
};

use super::{Fetcher, Parser, S3Client};

// A wrapping layer around a fetcher and parser, that provides transparent storing of the
// source bytes into s3, and the storage pointer into a postgres database.
pub struct Saving<F> {
    inner: F,
    s3_client: Arc<S3Client>,
    pool: PgPool,
    bucket: String,
    prefix: String,
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

// This is the "intermediate" symbol set data. Rather than a simple `Vec<u8>`, the saving layer
// has to return this from calls to `fetch`, and accept it in calls to `parse`, so that it can
// pass the information necessary to store the underlying data between the fetch and parse stages,
// (to avoid saving data we can't parse)
pub struct Saveable {
    pub data: Vec<u8>,
    pub storage_ptr: Option<String>, // This is None if we still need to save this data
    pub team_id: i32,
    pub set_ref: String,
}

impl<F> Saving<F> {
    pub fn new(
        inner: F,
        pool: sqlx::PgPool,
        s3_client: Arc<S3Client>,
        bucket: String,
        prefix: String,
    ) -> Self {
        Self {
            inner,
            pool,
            s3_client,
            bucket,
            prefix,
        }
    }

    pub async fn save_data(
        &self,
        team_id: i32,
        set_ref: String,
        data: Vec<u8>,
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
        record.save(&self.pool).await?;
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
        SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id,
            set_ref,
            storage_ptr: None,
            failure_reason: Some(serde_json::to_string(&reason)?),
            created_at: Utc::now(),
            content_hash: None,
            last_used: Some(Utc::now()),
        }
        .save(&self.pool)
        .await?;
        start.label("outcome", "success").fin();
        Ok(())
    }

    fn add_prefix(&self, key: String) -> String {
        format!("{}/{}", self.prefix, key)
    }
}

#[async_trait]
impl<F> Fetcher for Saving<F>
where
    F: Fetcher<Fetched = Vec<u8>, Err = Error>,
    F::Ref: ToString + Send,
{
    type Ref = F::Ref;
    type Fetched = Saveable;
    type Err = F::Err;

    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Self::Fetched, Self::Err> {
        let set_ref = r.to_string();
        info!("Fetching symbol set data for {}", set_ref);
        metrics::counter!(SYMBOL_SET_DB_FETCHES).increment(1);

        if let Some(record) = SymbolSetRecord::load(&self.pool, team_id, &set_ref).await? {
            metrics::counter!(SYMBOL_SET_DB_HITS).increment(1);
            if let Some(storage_ptr) = record.storage_ptr {
                info!("Found s3 saved symbol set data for {}", set_ref);
                let data = self.s3_client.get(&self.bucket, &storage_ptr).await?;
                metrics::counter!(SAVED_SYMBOL_SET_LOADED).increment(1);
                return Ok(Saveable {
                    data,
                    storage_ptr: Some(storage_ptr),
                    team_id,
                    set_ref,
                });
            } else if Utc::now() - record.created_at < chrono::Duration::days(1) {
                info!("Found recent symbol set error for {}", set_ref);
                // We tried less than a day ago to get the set data, and failed, so bail out
                // with the stored error. We unwrap here because we should never store a "no set"
                // row without also storing the error, and if we do, we want to panic, but we
                // also want to log an error
                metrics::counter!(SAVED_SYMBOL_SET_ERROR_RETURNED).increment(1);
                if record.failure_reason.is_none() {
                    error!("Found a record with no data and no error: {:?}", record);
                    panic!("Found a record with no data and no error");
                }
                // TODO - this can fail due to changes in how we serialise, or changes in
                // the error type - and we should handle that by deleting the symbol record
                // and re-fetching, I think (we don't need to cleanup s3 since it's a failure
                // case, there is no saved data).
                let error = serde_json::from_str(&record.failure_reason.unwrap())
                    .map_err(UnhandledError::from)?;
                return Err(Error::ResolutionError(error));
            }
            info!("Found stale symbol set error for {}", set_ref);
            // We last tried to get the symbol set more than a day ago, so we should try again
            metrics::counter!(SYMBOL_SET_FETCH_RETRY).increment(1);
        }

        metrics::counter!(SYMBOL_SET_DB_MISSES).increment(1);

        match self.inner.fetch(team_id, r).await {
            // NOTE: We don't save the data here, because we want to save it only after parsing
            Ok(data) => {
                info!("Inner fetched symbol set data for {}", set_ref);
                Ok(Saveable {
                    data,
                    storage_ptr: None,
                    team_id,
                    set_ref,
                })
            }
            Err(Error::ResolutionError(e)) => {
                // But if we failed to get any data, we save that fact
                self.save_no_data(team_id, set_ref, &e).await?;
                return Err(Error::ResolutionError(e));
            }
            Err(e) => Err(e), // If some non-resolution error occurred, we just bail out
        }
    }
}

#[async_trait]
impl<F> Parser for Saving<F>
where
    F: Parser<Source = Vec<u8>, Err = Error>,
    F::Set: Send,
{
    type Source = Saveable;
    type Set = F::Set;
    type Err = F::Err;

    async fn parse(&self, data: Saveable) -> Result<Self::Set, Self::Err> {
        match self.inner.parse(data.data.clone()).await {
            Ok(s) => {
                info!("Parsed symbol set data for {}", data.set_ref);
                if data.storage_ptr.is_none() {
                    // We only save the data if we fetched it from the underlying fetcher
                    self.save_data(data.team_id, data.set_ref, data.data)
                        .await?;
                }
                return Ok(s);
            }
            Err(Error::ResolutionError(e)) => {
                info!("Failed to parse symbol set data for {}", data.set_ref);
                // We save the no-data case here, to prevent us from fetching again for day
                self.save_no_data(data.team_id, data.set_ref, &e).await?;
                return Err(Error::ResolutionError(e));
            }
            Err(e) => return Err(e),
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
        let mut record = sqlx::query_as!(
            SymbolSetRecord,
            r#"SELECT id, team_id, ref as set_ref, storage_ptr, created_at, failure_reason, content_hash, last_used
            FROM posthog_errortrackingsymbolset
            WHERE (content_hash is not null OR storage_ptr is null) AND team_id = $1 AND ref = $2"#,
            team_id,
            set_ref
        )
        .fetch_optional(pool)
        .await?;

        if let Some(r) = &mut record {
            r.set_last_used(pool).await?;
        }

        Ok(record)
    }

    // Set the last used timestamp. This isn't used anywhere in cymbal right now, but is
    // used by retention cleanup jobs to determine which symbol sets are still in use.
    async fn set_last_used<'c, E>(&mut self, e: E) -> Result<(), UnhandledError>
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
        self.id = sqlx::query_scalar!(
            r#"
            INSERT INTO posthog_errortrackingsymbolset (id, team_id, ref, storage_ptr, failure_reason, created_at, content_hash)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (team_id, ref) DO UPDATE SET storage_ptr = $4, content_hash = $7, failure_reason = $5
            RETURNING id
            "#,
            self.id,
            self.team_id,
            self.set_ref,
            self.storage_ptr,
            self.failure_reason,
            self.created_at,
            self.content_hash
        )
        .fetch_one(e)
        .await.expect("Got at least one row back");

        metrics::counter!(SYMBOL_SET_SAVED).increment(1);

        Ok(())
    }
}

#[cfg(test)]
mod test {
    use std::sync::Arc;

    use httpmock::MockServer;
    use mockall::predicate;
    use posthog_symbol_data::write_symbol_data;
    use reqwest::Url;
    use sqlx::PgPool;

    use crate::{
        config::Config,
        symbol_store::{
            saving::{Saving, SymbolSetRecord},
            sourcemap::SourcemapProvider,
            Provider, S3Client,
        },
    };

    const CHUNK_PATH: &str = "/static/chunk-PGUQKT6S.js";
    const MINIFIED: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js");
    const MAP: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js.map");

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

        let mut config = Config::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();
        config.allow_internal_ips = true; // Gonna be hitting the sourcemap mocks

        let source_mock = server.mock(|when, then| {
            when.method("GET").path(CHUNK_PATH);
            then.status(200).body(MINIFIED);
        });

        let map_mock = server.mock(|when, then| {
            // Our minified example source uses a relative URL, formatted like this
            when.method("GET").path(format!("{}.map", CHUNK_PATH));
            then.status(200).body(MAP);
        });

        let mut client = S3Client::default();
        // Expected: we'll hit the backend and store the data in s3.
        client
            .expect_put()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
                predicate::eq(get_symbol_data_bytes()), // We won't assert on the contents written
            )
            .returning(|_, _, _| Ok(()))
            .once();

        client
            .expect_get()
            .with(
                predicate::eq(config.object_storage_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
            )
            .returning(|_, _| Ok(get_symbol_data_bytes()));

        let smp = SourcemapProvider::new(&config);
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            Arc::new(client),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
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
    async fn test_symbol_set_404_handling(db: PgPool) {
        let server = MockServer::start();

        let mut config = Config::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();
        config.allow_internal_ips = true;

        let source_mock = server.mock(|when, then| {
            when.method("GET").path(CHUNK_PATH);
            then.status(404);
        });

        // We don't expect any S3 operations since we won't get any valid data
        let client = S3Client::default();

        let smp = SourcemapProvider::new(&config);
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            Arc::new(client),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
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

        let mut config = Config::init_with_defaults().unwrap();
        config.object_storage_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();
        config.allow_internal_ips = true;

        let source_mock = server.mock(|when, then| {
            when.method("GET").path(CHUNK_PATH);
            then.status(200).body(MINIFIED);
        });

        let map_mock = server.mock(|when, then| {
            when.method("GET").path(format!("{}.map", CHUNK_PATH));
            then.status(200).body(Vec::new()); // Empty/invalid sourcemap
        });

        // We don't expect any S3 operations since we won't get any valid data
        let client = S3Client::default();

        let smp = SourcemapProvider::new(&config);
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            Arc::new(client),
            config.object_storage_bucket.clone(),
            config.ss_prefix.clone(),
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
}
