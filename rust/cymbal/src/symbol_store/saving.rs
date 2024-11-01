use axum::async_trait;
use chrono::{DateTime, Utc};

use sqlx::PgPool;
use uuid::Uuid;

use crate::error::Error;

use super::{Fetcher, Parser, S3Client};

// A wrapping layer around a fetcher and parser, that provides transparent storing of the
// source bytes into s3, and the storage pointer into a postgres database.
pub struct Saving<F> {
    inner: F,
    s3_client: S3Client,
    pool: PgPool,
    bucket: String,
    prefix: String,
}

// A record of an attempt to fetch a symbol set. If it succeeded, it will have a storage pointer
pub struct SymbolSetRecord {
    id: Uuid,
    team_id: i32,
    // "ref" is a reserved keyword in Rust, whoops
    set_ref: String,
    storage_ptr: Option<String>,
    created_at: DateTime<Utc>,
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
        s3_client: S3Client,
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
    ) -> Result<String, Error> {
        // Generate a new opaque key, appending our prefix.
        let key = self.add_prefix(Uuid::now_v7().to_string());

        let record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id,
            set_ref,
            storage_ptr: Some(key.clone()),
            created_at: Utc::now(),
        };

        self.s3_client.put(&self.bucket, &key, data).await?;
        record.save(&self.pool).await?;
        Ok(key)
    }

    pub async fn save_no_data(&self, team_id: i32, set_ref: String) -> Result<(), Error> {
        SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id,
            set_ref,
            storage_ptr: None,
            created_at: Utc::now(),
        }
        .save(&self.pool)
        .await
    }

    fn add_prefix(&self, key: String) -> String {
        format!("{}/{}", self.prefix, key)
    }
}

#[async_trait]
impl<F> Fetcher for Saving<F>
where
    F: Fetcher<Fetched = Vec<u8>>,
    F::Ref: ToString + Send,
{
    type Ref = F::Ref;
    type Fetched = Saveable;

    async fn fetch(&self, team_id: i32, r: Self::Ref) -> Result<Self::Fetched, Error> {
        let set_ref = r.to_string();
        if let Some(record) = SymbolSetRecord::load(&self.pool, team_id, &set_ref).await? {
            if let Some(storage_ptr) = record.storage_ptr {
                let data = self.s3_client.get(&self.bucket, &storage_ptr).await?;
                return Ok(Saveable {
                    data,
                    storage_ptr: Some(storage_ptr),
                    team_id,
                    set_ref,
                });
            } else if Utc::now() - record.created_at < chrono::Duration::days(1) {
                // We tried less than a day ago to get the set data, and failed, so bail out
                return todo!("I need to return a language-specific error here, but don't have language context");
            }
            // We last tried to get the symbol set more than a day ago, so we should try again
        }

        match self.inner.fetch(team_id, r).await {
            // NOTE: We don't save the data here, because we want to save it only after parsing
            Ok(data) => Ok(Saveable {
                data,
                storage_ptr: None,
                team_id,
                set_ref,
            }),
            Err(e) => {
                // But if we failed to get any data, we save that fact
                self.save_no_data(team_id, set_ref).await?;
                return Err(e);
            }
        }
    }
}

#[async_trait]
impl<F> Parser for Saving<F>
where
    F: Parser<Source = Vec<u8>>,
    F::Set: Send,
{
    type Source = Saveable;
    type Set = F::Set;
    async fn parse(&self, data: Saveable) -> Result<Self::Set, Error> {
        match self.inner.parse(data.data.clone()).await {
            Ok(s) => {
                if data.storage_ptr.is_none() {
                    // We only save the data if we fetched it from the underlying fetcher
                    self.save_data(data.team_id, data.set_ref, data.data)
                        .await?;
                }
                return Ok(s);
            }
            Err(e) => {
                // We save the no-data case here, to prevent us from fetching again for day
                self.save_no_data(data.team_id, data.set_ref).await?;
                return Err(e);
            }
        }
    }
}

impl SymbolSetRecord {
    pub async fn load<'c, E>(e: E, team_id: i32, set_ref: &str) -> Result<Option<Self>, Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        let record = sqlx::query_as!(
            SymbolSetRecord,
            r#"SELECT id, team_id, ref as set_ref, storage_ptr, created_at
            FROM posthog_errortrackingsymbolset
            WHERE team_id = $1 AND ref = $2"#,
            team_id,
            set_ref
        )
        .fetch_optional(e)
        .await?;

        Ok(record)
    }

    pub async fn save<'c, E>(&self, e: E) -> Result<(), Error>
    where
        E: sqlx::Executor<'c, Database = sqlx::Postgres>,
    {
        sqlx::query!(
            r#"INSERT INTO posthog_errortrackingsymbolset (id, team_id, ref, storage_ptr, created_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (team_id, ref) DO UPDATE SET storage_ptr = $4"#,
            self.id,
            self.team_id,
            self.set_ref,
            self.storage_ptr,
            self.created_at
        )
        .execute(e)
        .await?;

        Ok(())
    }
}

#[cfg(test)]
mod test {
    use httpmock::MockServer;
    use mockall::predicate;
    use reqwest::Url;
    use sqlx::PgPool;

    use crate::{
        config::Config,
        symbol_store::{saving::Saving, sourcemap::SourcemapProvider, Provider, S3Client},
    };

    const CHUNK_PATH: &str = "/static/chunk-PGUQKT6S.js";
    const MINIFIED: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js");
    const MAP: &[u8] = include_bytes!("../../tests/static/chunk-PGUQKT6S.js.map");

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_successful_lookup(db: PgPool) {
        let server = MockServer::start();

        let mut config = Config::init_with_defaults().unwrap();
        config.ss_bucket = "test-bucket".to_string();
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
                predicate::eq(config.ss_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
                predicate::eq(Vec::from(MAP)),
            )
            .returning(|_, _, _| Ok(()))
            .once();

        client
            .expect_get()
            .with(
                predicate::eq(config.ss_bucket.clone()),
                predicate::str::starts_with(config.ss_prefix.clone()),
            )
            .returning(|_, _| Ok(Vec::from(MAP)));

        let smp = SourcemapProvider::new(&config).unwrap();
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            client,
            config.ss_bucket.clone(),
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
        config.ss_bucket = "test-bucket".to_string();
        config.ss_prefix = "test-prefix".to_string();
        config.allow_internal_ips = true;

        let source_mock = server.mock(|when, then| {
            when.method("GET").path(CHUNK_PATH);
            then.status(404);
        });

        // We don't expect any S3 operations since we won't get any valid data
        let client = S3Client::default();

        let smp = SourcemapProvider::new(&config).unwrap();
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            client,
            config.ss_bucket.clone(),
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
        let record = sqlx::query!(
            r#"SELECT storage_ptr FROM posthog_errortrackingsymbolset
                WHERE team_id = $1 AND ref = $2"#,
            0,
            test_url.to_string()
        )
        .fetch_one(&db)
        .await
        .unwrap();

        assert!(record.storage_ptr.is_none());
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_invalid_sourcemap_handling(db: PgPool) {
        let server = MockServer::start();

        let mut config = Config::init_with_defaults().unwrap();
        config.ss_bucket = "test-bucket".to_string();
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

        let smp = SourcemapProvider::new(&config).unwrap();
        let saving_smp = Saving::new(
            smp,
            db.clone(),
            client,
            config.ss_bucket.clone(),
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
        let record = sqlx::query!(
            r#"SELECT storage_ptr FROM posthog_errortrackingsymbolset
                WHERE team_id = $1 AND ref = $2"#,
            0,
            test_url.to_string()
        )
        .fetch_one(&db)
        .await
        .unwrap();

        assert!(record.storage_ptr.is_none());
    }
}
