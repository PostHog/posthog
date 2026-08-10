//! Postgres-backed identity storage. This module is dispatch-only: each
//! trait method's logic lives in its own submodule (`resolve`,
//! `stub_create`), keyed by the metrics operation label.

mod resolve;
mod stub_create;

use std::collections::HashMap;

use async_trait::async_trait;
use sqlx::postgres::PgPool;

use personhog_common::grpc::{current_client_name, current_method_name};

use crate::storage::error::StorageResult;
use crate::storage::types::{Person, PersonStub, StubOutcome};
use crate::storage::{IdentityStorage, DB_QUERY_DURATION};

const POOL_LABEL: &str = "primary";

pub struct PostgresIdentityStorage {
    pub primary_pool: PgPool,
}

impl PostgresIdentityStorage {
    pub fn new(primary_pool: PgPool) -> Self {
        Self { primary_pool }
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
        resolve::resolve_distinct_ids(&self.primary_pool, keys).await
    }

    async fn create_person_stubs(&self, stubs: &[PersonStub]) -> StorageResult<Vec<StubOutcome>> {
        let labels = Self::query_labels("create_person_stubs");
        let _timer = common_metrics::timing_guard(DB_QUERY_DURATION, &labels);
        stub_create::create_person_stubs(&self.primary_pool, stubs).await
    }
}
