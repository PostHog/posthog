use std::fs;

use axum::{body::Body, http::Request};

use chrono::Utc;
use cymbal::{
    error::UnhandledError,
    symbol_store::saving::SymbolSetRecord,
    types::{ExceptionList, RawErrProps},
};

use insta::assert_json_snapshot;
use mockall::predicate;
use posthog_symbol_data::{write_symbol_data, SourceAndMap};
use serde::Deserialize;
use serde_json::{from_str, json};
use sqlx::PgPool;
use std::sync::Arc;
use uuid::Uuid;

use crate::utils::MockS3Client;
mod utils;

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn process_invalid_list(db: PgPool) {
    #[derive(Deserialize)]
    pub struct ProcessExceptionListError {
        error: String,
    }
    let storage_bucket = "test-bucket".to_string();
    let mut s3_client = MockS3Client::new();
    s3_client
        .expect_ping_bucket()
        .with(predicate::eq(storage_bucket.clone()))
        .returning(|_| Ok(()));

    let (status, body) = utils::get_response::<ProcessExceptionListError>(
        db,
        storage_bucket,
        || {
            Request::builder()
                .method("POST")
                .header("content-type", "application/json")
                .uri("/2/exception_list/process")
                .body(Body::from(serde_json::to_vec(&json!({})).unwrap()))
                .unwrap()
        },
        Arc::new(s3_client),
    )
    .await;

    assert!(status.is_client_error());
    assert_eq!(body.error, "invalid type: map, expected a sequence");
}

#[sqlx::test(migrations = "./tests/test_migrations")]
async fn process_empty_list(db: PgPool) {
    let storage_bucket = "test-bucket".to_string();
    let mut s3_client = MockS3Client::new();
    s3_client
        .expect_ping_bucket()
        .with(predicate::eq(storage_bucket.clone()))
        .returning(|_| Ok(()));

    let (status, body) = utils::get_response::<ExceptionList>(
        db,
        storage_bucket,
        || {
            Request::builder()
                .method("POST")
                .header("content-type", "application/json")
                .uri("/2/exception_list/process")
                .body(Body::from(serde_json::to_vec(&json!([])).unwrap()))
                .unwrap()
        },
        Arc::new(s3_client),
    )
    .await;

    assert!(status.is_success());
    assert!(body.0.is_empty());
}

// embed static symbol sets store
fn get_sourcemap(chunk_id: &str) -> Result<Option<Vec<u8>>, UnhandledError> {
    let Ok(minified_source) = fs::read_to_string(format!("tests/static/sourcemaps/{chunk_id}.js"))
    else {
        return Ok(None);
    };

    let Ok(sourcemap) = fs::read_to_string(format!("tests/static/sourcemaps/{chunk_id}.js.map"))
    else {
        return Ok(None);
    };

    let symbol_data = write_symbol_data(SourceAndMap {
        minified_source,
        sourcemap,
    })
    .map_err(|e| UnhandledError::Other(e.to_string()))?;

    Ok(Some(symbol_data))
}

async fn database_records(db: PgPool, team_id: i32, chunk_id: &str) {
    let map_id = chunk_id.to_string();
    let mut record = SymbolSetRecord {
        id: Uuid::now_v7(),
        team_id,
        set_ref: map_id.clone(),
        storage_ptr: Some(map_id.clone()),
        failure_reason: None,
        created_at: Utc::now(),
        content_hash: Some("fake-hash".to_string()),
        last_used: Some(Utc::now()),
    };

    record.save(&db).await.expect("Failed to insert records");
}

macro_rules! test_exception_list_processing {
    ($name: ident, $event: expr, $setup: expr) => {
        #[sqlx::test(migrations = "./tests/test_migrations")]
        async fn $name(db: PgPool) {
            const RAW_EVENT: &str = include_str!(concat!("./static/events/", $event, ".json"));
            let event: RawErrProps = from_str(RAW_EVENT).unwrap();
            let team_id = 1;
            let mut s3_client = MockS3Client::new();
            let storage_bucket = "test-bucket".to_string();

            s3_client
                .expect_ping_bucket()
                .with(predicate::eq(storage_bucket.clone()))
                .returning(|_| Ok(()));

            $setup(db.clone(), storage_bucket.clone(), team_id, &mut s3_client).await;

            let (status, body) = utils::get_response::<ExceptionList>(
                db,
                storage_bucket,
                || {
                    Request::builder()
                        .method("POST")
                        .header("content-type", "application/json")
                        .uri(format!("/{team_id}/exception_list/process"))
                        .body(Body::from(
                            serde_json::to_vec(&event.exception_list).unwrap(),
                        ))
                        .unwrap()
                },
                Arc::new(s3_client),
            )
            .await;

            assert!(status.is_success());
            assert_json_snapshot!(body.0, {
                "[].id" => "REDACTED",
            });
        }
    };
}

test_exception_list_processing!(
    test_javascript_resolution_without_chunk_id,
    "javascript",
    async |_, _, _, _| -> () {}
);

test_exception_list_processing!(
    test_javascript_resolution_with_chunk_id,
    "javascript_chunk_id",
    async |db: PgPool, storage_bucket: String, team_id: i32, s3_client: &mut MockS3Client| -> () {
        database_records(db.clone(), team_id, "1234").await;

        s3_client
            .expect_get()
            .with(predicate::eq(storage_bucket), predicate::eq("1234"))
            .returning(|_, chunk_id| get_sourcemap(chunk_id));
    }
);

test_exception_list_processing!(
    test_javascript_resolution_failure,
    "javascript_chunk_id_2",
    async |_, _, _, _| -> () {}
);

test_exception_list_processing!(test_exception_list_python, "python", async |_,
                                                                             _,
                                                                             _,
                                                                             _|
       -> () {});
