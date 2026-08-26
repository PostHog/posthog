//! Postgres-backed identity storage. This module is dispatch-only: each
//! trait method's logic lives in its own submodule (`resolve`,
//! `stub_create`, `attach`), keyed by the metrics operation label.

mod attach;
mod distinct_ids;
mod resolve;
mod stub_create;

use std::collections::HashMap;

use async_trait::async_trait;
use sqlx::postgres::{PgPool, PgRow};
use sqlx::Row;

use personhog_common::grpc::{current_client_name, current_method_name};

use crate::config::IdentityTables;
use crate::storage::error::StorageResult;
use crate::storage::types::{AttachOutcome, DistinctIdMapping, Person, PersonStub, StubOutcome};
use crate::storage::{IdentityStorage, DB_QUERY_DURATION};

const POOL_LABEL: &str = "primary";

/// Decode a person from a row whose SELECT list uses the canonical aliases
/// (`team_id::bigint AS team_id`, `properties::text AS properties`, the
/// `is_user_id` boolean CASE, …). Shared by every submodule that selects
/// person rows — the table name is interpolated at runtime, so the queries
/// cannot use the compile-time sqlx macros and their generated row types.
pub(super) fn person_from_row(row: &PgRow) -> Result<Person, sqlx::Error> {
    Ok(Person {
        id: row.try_get("id")?,
        uuid: row.try_get("uuid")?,
        team_id: row.try_get("team_id")?,
        properties: row.try_get("properties")?,
        properties_last_updated_at: row.try_get("properties_last_updated_at")?,
        properties_last_operation: row.try_get("properties_last_operation")?,
        created_at: row.try_get("created_at")?,
        version: row.try_get("version")?,
        is_identified: row.try_get("is_identified")?,
        is_user_id: row.try_get("is_user_id")?,
        last_seen_at: row.try_get("last_seen_at")?,
    })
}

/// The person-column SELECT list matching [`person_from_row`], with `{p}` as
/// the table alias.
pub(super) fn person_columns(p: &str) -> String {
    format!(
        "{p}.id, {p}.uuid, {p}.team_id::bigint AS team_id, \
         {p}.properties::text AS properties, \
         {p}.properties_last_updated_at::text AS properties_last_updated_at, \
         {p}.properties_last_operation::text AS properties_last_operation, \
         {p}.created_at, {p}.version, {p}.is_identified, \
         CASE WHEN {p}.is_user_id IS NULL THEN NULL ELSE ({p}.is_user_id != 0) END AS is_user_id, \
         {p}.last_seen_at"
    )
}

pub struct PostgresIdentityStorage {
    pub primary_pool: PgPool,
    tables: IdentityTables,
}

impl PostgresIdentityStorage {
    pub fn new(primary_pool: PgPool, tables: IdentityTables) -> Self {
        tables.validate().expect("invalid identity table set");
        Self {
            primary_pool,
            tables,
        }
    }

    fn query_labels(operation: &str) -> [(String, String); 4] {
        [
            ("operation".to_string(), operation.to_string()),
            ("pool".to_string(), POOL_LABEL.to_string()),
            ("client".to_string(), current_client_name().to_string()),
            ("method".to_string(), current_method_name().to_string()),
        ]
    }
}

#[async_trait]
impl IdentityStorage for PostgresIdentityStorage {
    async fn resolve_distinct_ids(
        &self,
        keys: &[(i64, String)],
    ) -> StorageResult<HashMap<(i64, String), Person>> {
        let labels = Self::query_labels("resolve_distinct_ids");
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);
        resolve::resolve_distinct_ids(&self.primary_pool, &self.tables, keys).await
    }

    async fn get_distinct_ids_for_persons(
        &self,
        team_id: i64,
        person_ids: &[i64],
        limit_per_person: Option<i64>,
    ) -> StorageResult<Vec<DistinctIdMapping>> {
        let labels = Self::query_labels("get_distinct_ids_for_persons");
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);
        distinct_ids::get_distinct_ids_for_persons(
            &self.primary_pool,
            &self.tables.person_distinct_id,
            team_id,
            person_ids,
            limit_per_person,
        )
        .await
    }

    async fn create_person_stubs(&self, stubs: &[PersonStub]) -> StorageResult<Vec<StubOutcome>> {
        let labels = Self::query_labels("create_person_stubs");
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);
        stub_create::create_person_stubs(&self.primary_pool, &self.tables, stubs).await
    }

    async fn attach_distinct_ids(
        &self,
        team_id: i64,
        person_id: i64,
        distinct_ids: &[String],
    ) -> StorageResult<HashMap<String, AttachOutcome>> {
        let labels = Self::query_labels("attach_distinct_ids");
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);
        attach::attach_distinct_ids(
            &self.primary_pool,
            &self.tables,
            team_id,
            person_id,
            distinct_ids,
        )
        .await
    }
}
