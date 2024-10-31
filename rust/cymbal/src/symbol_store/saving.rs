use aws_sdk_s3::{primitives::ByteStream, Client as S3Client, Error as S3Error};
use axum::async_trait;
use chrono::{DateTime, Utc};
use sqlx::PgPool;
use uuid::Uuid;

use crate::error::Error;

use super::{Fetcher, Parser};

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

        self.store_in_s3(&key, data).await?;
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

    async fn fetch_from_s3(&self, key: &str) -> Result<Vec<u8>, Error> {
        let res = self
            .s3_client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await;

        if let Ok(res) = res {
            let data = res.body.collect().await?;
            return Ok(data.to_vec());
        }

        // Note that we're not handling the "object not found" case here, because if we
        // got a key from the DB, we should have the object in S3
        Err(S3Error::from(res.unwrap_err()).into())
    }

    async fn store_in_s3(&self, key: &str, data: Vec<u8>) -> Result<(), Error> {
        // TODO - lifecycle stuff I guess? Idk
        self.s3_client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(ByteStream::from(data))
            .send()
            .await
            .map_err(|e| S3Error::from(e).into())
            .map(|_| ()) // We don't care about the result as long as it's success
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
                let data = self.fetch_from_s3(&storage_ptr).await?;
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

impl<F> Saving<F> {
    fn add_prefix(&self, key: String) -> String {
        format!("{}/{}", self.prefix, key)
    }

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
}
