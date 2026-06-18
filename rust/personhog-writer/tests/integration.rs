mod common;

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common::{
    cleanup_team, create_local_kafka_producer, create_mock_kafka, create_test_pool, make_person,
    KAFKA_BOOTSTRAP, TARGET_TABLE, TOPIC,
};
use personhog_proto::personhog::types::v1::Person;
use personhog_writer::buffer::PersonBuffer;
use personhog_writer::consumer::{ConsumerTask, FlushBatch};
use personhog_writer::kafka::PersonConsumer;
use personhog_writer::pg::PgStore;
use personhog_writer::store::{
    BatchOutcome, PersonDb, PersonWriteStore, RowResult, WriteError, WriteErrorKind,
};
use personhog_writer::writer::WriterTask;
use prost::Message;
use rdkafka::producer::FutureRecord;
use rdkafka::ClientConfig;
use tokio::sync::mpsc;

// ============================================================
// PG Writer: upsert correctness
// ============================================================

#[tokio::test]
async fn writer_upserts_person_to_pg() {
    let pool = create_test_pool().await;
    let team_id: i32 = 99_001;
    cleanup_team(&pool, team_id).await;

    let writer = PersonWriteStore::new(
        PgStore::new(pool.clone(), TARGET_TABLE.to_string()),
        common::test_store_config(),
    );
    let person = make_person(team_id as i64, 1, 1);

    assert!(matches!(
        writer.upsert_batch(vec![person]).await,
        BatchOutcome::Success
    ));

    let row: (i64, i64, bool) = sqlx::query_as(
        "SELECT id, version, is_identified FROM personhog_person_tmp WHERE team_id = $1 AND id = $2",
    )
    .bind(team_id)
    .bind(1_i64)
    .fetch_one(&pool)
    .await
    .unwrap();

    assert_eq!(row.0, 1); // id
    assert_eq!(row.1, 1); // version
    assert!(!row.2); // is_identified

    cleanup_team(&pool, team_id).await;
}

#[tokio::test]
async fn writer_version_guard_skips_stale_updates() {
    let pool = create_test_pool().await;
    let team_id: i32 = 99_002;
    cleanup_team(&pool, team_id).await;

    let writer = PersonWriteStore::new(
        PgStore::new(pool.clone(), TARGET_TABLE.to_string()),
        common::test_store_config(),
    );

    // Write version 5
    let person_v5 = make_person(team_id as i64, 1, 5);
    assert!(matches!(
        writer.upsert_batch(vec![person_v5]).await,
        BatchOutcome::Success
    ));

    // Attempt to write version 3 (stale) -- should be a no-op
    let mut person_v3 = make_person(team_id as i64, 1, 3);
    person_v3.properties =
        serde_json::to_vec(&serde_json::json!({"email": "stale@example.com"})).unwrap();
    assert!(matches!(
        writer.upsert_batch(vec![person_v3]).await,
        BatchOutcome::Success
    ));

    let row: (i64,) =
        sqlx::query_as("SELECT version FROM personhog_person_tmp WHERE team_id = $1 AND id = $2")
            .bind(team_id)
            .bind(1_i64)
            .fetch_one(&pool)
            .await
            .unwrap();

    assert_eq!(row.0, 5); // version unchanged

    cleanup_team(&pool, team_id).await;
}

#[tokio::test]
async fn writer_upsert_batch_multiple_persons() {
    let pool = create_test_pool().await;
    let team_id: i32 = 99_003;
    cleanup_team(&pool, team_id).await;

    let writer = PersonWriteStore::new(
        PgStore::new(pool.clone(), TARGET_TABLE.to_string()),
        common::test_store_config(),
    );
    let persons: Vec<Person> = (1..=10)
        .map(|i| make_person(team_id as i64, i, 1))
        .collect();

    assert!(matches!(
        writer.upsert_batch(persons).await,
        BatchOutcome::Success
    ));

    let count: (i64,) =
        sqlx::query_as("SELECT COUNT(*) FROM personhog_person_tmp WHERE team_id = $1")
            .bind(team_id)
            .fetch_one(&pool)
            .await
            .unwrap();

    assert_eq!(count.0, 10);

    cleanup_team(&pool, team_id).await;
}

#[tokio::test]
async fn writer_skips_invalid_uuids_without_failing_batch() {
    let pool = create_test_pool().await;
    let team_id: i32 = 99_004;
    cleanup_team(&pool, team_id).await;

    let writer = PersonWriteStore::new(
        PgStore::new(pool.clone(), TARGET_TABLE.to_string()),
        common::test_store_config(),
    );

    let valid_person = make_person(team_id as i64, 1, 1);
    let mut bad_person = make_person(team_id as i64, 2, 1);
    bad_person.uuid = "not-a-valid-uuid".to_string();
    let another_valid = make_person(team_id as i64, 3, 1);

    // Batch contains one invalid UUID -- it should be skipped,
    // and the valid persons should still be written.
    assert!(matches!(
        writer
            .upsert_batch(vec![valid_person, bad_person, another_valid])
            .await,
        BatchOutcome::Success
    ));

    let count: (i64,) =
        sqlx::query_as("SELECT COUNT(*) FROM personhog_person_tmp WHERE team_id = $1")
            .bind(team_id)
            .fetch_one(&pool)
            .await
            .unwrap();

    assert_eq!(count.0, 2);

    cleanup_team(&pool, team_id).await;
}

// ============================================================
// Consumer + Writer: channel flow with mock Kafka
// ============================================================

#[tokio::test]
async fn consumer_flushes_on_buffer_size_threshold() {
    let (mock_cluster, _producer) = create_mock_kafka().await;
    let pool = create_test_pool().await;
    let team_id: i32 = 99_010;
    cleanup_team(&pool, team_id).await;

    let (flush_tx, flush_rx) = mpsc::channel::<FlushBatch>(2);

    let client_config = ClientConfig::new()
        .set("bootstrap.servers", mock_cluster.bootstrap_servers())
        .set("group.id", "test-flush-threshold")
        .set("auto.offset.reset", "earliest")
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .clone();
    let kafka_consumer = Arc::new(PersonConsumer::new(&client_config, TOPIC.to_string()).unwrap());

    let mut manager = lifecycle::Manager::builder("test")
        .with_trap_signals(false)
        .build();
    let consumer_handle = manager.register(
        "consumer",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let writer_handle = manager.register(
        "writer",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let _monitor = manager.monitor_background();

    // Start writer task
    let writer = PersonWriteStore::new(
        PgStore::new(pool.clone(), TARGET_TABLE.to_string()),
        common::test_store_config(),
    );
    let writer_task = WriterTask::new(
        Arc::clone(&kafka_consumer),
        writer,
        flush_rx,
        writer_handle,
        None,
    );
    tokio::spawn(async move { writer_task.run().await });

    // Produce 6 messages to mock Kafka (two full batches of 3)
    let producer = &_producer;
    for i in 1..=6 {
        let person = make_person(team_id as i64, i, 1);
        let payload = person.encode_to_vec();
        let key = format!("{}:{}", team_id, i);
        let record = FutureRecord::to(TOPIC).key(&key).payload(&payload);
        producer
            .send_result(record)
            .unwrap()
            .await
            .unwrap()
            .unwrap();
    }

    // Start consumer with flush_buffer_size=3 (flushes at exactly 3 and 6)
    let consumer_task = ConsumerTask::new(
        kafka_consumer,
        PersonBuffer::new(100),
        flush_tx,
        Duration::from_secs(60), // long timer so only size triggers flush
        3,                       // flush at 3 messages
        consumer_handle,
    );
    tokio::spawn(async move { consumer_task.run().await });

    // Wait for all 6 rows to appear in PG (two flush cycles)
    let mut retries = 0;
    loop {
        let count: (i64,) =
            sqlx::query_as("SELECT COUNT(*) FROM personhog_person_tmp WHERE team_id = $1")
                .bind(team_id)
                .fetch_one(&pool)
                .await
                .unwrap();

        if count.0 >= 6 {
            break;
        }

        retries += 1;
        if retries > 50 {
            panic!(
                "Expected 6 rows in personhog_person_tmp for team {}, got {}",
                team_id, count.0
            );
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }

    cleanup_team(&pool, team_id).await;
}

// ============================================================
// Consumer + Writer: timer-based flush
// ============================================================

#[tokio::test]
async fn consumer_flushes_on_timer() {
    let (mock_cluster, _producer) = create_mock_kafka().await;
    let pool = create_test_pool().await;
    let team_id: i32 = 99_011;
    cleanup_team(&pool, team_id).await;

    let (flush_tx, flush_rx) = mpsc::channel::<FlushBatch>(2);

    let client_config = ClientConfig::new()
        .set("bootstrap.servers", mock_cluster.bootstrap_servers())
        .set("group.id", "test-flush-timer")
        .set("auto.offset.reset", "earliest")
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .clone();
    let kafka_consumer = Arc::new(PersonConsumer::new(&client_config, TOPIC.to_string()).unwrap());

    let mut manager = lifecycle::Manager::builder("test")
        .with_trap_signals(false)
        .build();
    let consumer_handle = manager.register(
        "consumer",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let writer_handle = manager.register(
        "writer",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let _monitor = manager.monitor_background();

    let writer = PersonWriteStore::new(
        PgStore::new(pool.clone(), TARGET_TABLE.to_string()),
        common::test_store_config(),
    );
    let writer_task = WriterTask::new(
        Arc::clone(&kafka_consumer),
        writer,
        flush_rx,
        writer_handle,
        None,
    );
    tokio::spawn(async move { writer_task.run().await });

    // Produce 2 messages -- below the size threshold of 1000
    let producer = &_producer;
    for i in 1..=2 {
        let person = make_person(team_id as i64, i, 1);
        let payload = person.encode_to_vec();
        let key = format!("{}:{}", team_id, i);
        let record = FutureRecord::to(TOPIC).key(&key).payload(&payload);
        producer
            .send_result(record)
            .unwrap()
            .await
            .unwrap()
            .unwrap();
    }

    // Start consumer with high size threshold but short timer (500ms)
    let consumer_task = ConsumerTask::new(
        kafka_consumer,
        PersonBuffer::new(100),
        flush_tx,
        Duration::from_millis(500), // short timer triggers flush
        1000,                       // high threshold so only timer triggers
        consumer_handle,
    );
    tokio::spawn(async move { consumer_task.run().await });

    // Wait for rows -- should appear within ~1s (timer flush)
    let mut retries = 0;
    loop {
        let count: (i64,) =
            sqlx::query_as("SELECT COUNT(*) FROM personhog_person_tmp WHERE team_id = $1")
                .bind(team_id)
                .fetch_one(&pool)
                .await
                .unwrap();

        if count.0 >= 2 {
            break;
        }

        retries += 1;
        if retries > 30 {
            panic!(
                "Expected 2 rows from timer flush for team {}, got {}",
                team_id, count.0
            );
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    cleanup_team(&pool, team_id).await;
}

// ============================================================
// Consumer + Writer: dedup under load
// ============================================================

#[tokio::test]
async fn consumer_deduplicates_multiple_updates_for_same_person() {
    let (mock_cluster, _producer) = create_mock_kafka().await;
    let pool = create_test_pool().await;
    let team_id: i32 = 99_012;
    cleanup_team(&pool, team_id).await;

    let (flush_tx, flush_rx) = mpsc::channel::<FlushBatch>(2);

    let client_config = ClientConfig::new()
        .set("bootstrap.servers", mock_cluster.bootstrap_servers())
        .set("group.id", "test-dedup")
        .set("auto.offset.reset", "earliest")
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .clone();
    let kafka_consumer = Arc::new(PersonConsumer::new(&client_config, TOPIC.to_string()).unwrap());

    let mut manager = lifecycle::Manager::builder("test")
        .with_trap_signals(false)
        .build();
    let consumer_handle = manager.register(
        "consumer",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let writer_handle = manager.register(
        "writer",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let _monitor = manager.monitor_background();

    let writer = PersonWriteStore::new(
        PgStore::new(pool.clone(), TARGET_TABLE.to_string()),
        common::test_store_config(),
    );
    let writer_task = WriterTask::new(
        Arc::clone(&kafka_consumer),
        writer,
        flush_rx,
        writer_handle,
        None,
    );
    tokio::spawn(async move { writer_task.run().await });

    // Produce 5 updates for the same person (id=1) with increasing versions
    let producer = &_producer;
    for v in 1..=5 {
        let mut person = make_person(team_id as i64, 1, v);
        person.properties = serde_json::to_vec(&serde_json::json!({"version_seen": v})).unwrap();
        let payload = person.encode_to_vec();
        let key = format!("{}:1", team_id);
        let record = FutureRecord::to(TOPIC).key(&key).payload(&payload);
        producer
            .send_result(record)
            .unwrap()
            .await
            .unwrap()
            .unwrap();
    }

    // Start consumer with high size threshold, short timer
    let consumer_task = ConsumerTask::new(
        kafka_consumer,
        PersonBuffer::new(100),
        flush_tx,
        Duration::from_millis(500),
        1000,
        consumer_handle,
    );
    tokio::spawn(async move { consumer_task.run().await });

    // Wait for the row to appear
    let mut retries = 0;
    loop {
        let result: Option<(i64, i64)> = sqlx::query_as(
            "SELECT version, id FROM personhog_person_tmp WHERE team_id = $1 AND id = $2",
        )
        .bind(team_id)
        .bind(1_i64)
        .fetch_optional(&pool)
        .await
        .unwrap();

        if let Some((version, _)) = result {
            // Should have the latest version, not an intermediate one
            assert_eq!(version, 5, "expected latest version 5 after dedup");
            break;
        }

        retries += 1;
        if retries > 30 {
            panic!("Row never appeared for deduped person");
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    // Should be exactly 1 row, not 5
    let count: (i64,) =
        sqlx::query_as("SELECT COUNT(*) FROM personhog_person_tmp WHERE team_id = $1")
            .bind(team_id)
            .fetch_one(&pool)
            .await
            .unwrap();
    assert_eq!(count.0, 1, "expected 1 row after dedup, not 5");

    cleanup_team(&pool, team_id).await;
}

// ============================================================
// Writer task: signals completion through channel
// ============================================================

#[tokio::test]
async fn writer_processes_batch_from_channel() {
    let pool = create_test_pool().await;
    let team_id: i32 = 99_020;
    cleanup_team(&pool, team_id).await;

    let (flush_tx, flush_rx) = mpsc::channel::<FlushBatch>(2);

    let (mock_cluster, _) = create_mock_kafka().await;
    let mut client_config = ClientConfig::new();
    client_config
        .set("bootstrap.servers", mock_cluster.bootstrap_servers())
        .set("group.id", "test-writer-channel")
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false");
    let kafka_consumer = Arc::new(PersonConsumer::new(&client_config, TOPIC.to_string()).unwrap());

    let mut manager = lifecycle::Manager::builder("test")
        .with_trap_signals(false)
        .build();
    let writer_handle = manager.register("writer", lifecycle::ComponentOptions::new());
    let _monitor = manager.monitor_background();

    let writer = PersonWriteStore::new(
        PgStore::new(pool.clone(), TARGET_TABLE.to_string()),
        common::test_store_config(),
    );
    let writer_task = WriterTask::new(
        Arc::clone(&kafka_consumer),
        writer,
        flush_rx,
        writer_handle,
        None,
    );
    tokio::spawn(async move { writer_task.run().await });

    // Send a batch directly through the channel
    let person = make_person(team_id as i64, 1, 1);
    let batch = FlushBatch {
        persons: vec![person],
        offsets: HashMap::new(),
        oldest_message_ts_ms: None,
    };
    flush_tx.send(batch).await.unwrap();

    // Wait for the row to appear
    let mut retries = 0;
    loop {
        let count: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM personhog_person_tmp WHERE team_id = $1 AND id = $2",
        )
        .bind(team_id)
        .bind(1_i64)
        .fetch_one(&pool)
        .await
        .unwrap();

        if count.0 == 1 {
            break;
        }

        retries += 1;
        if retries > 50 {
            panic!("Row never appeared in personhog_person_tmp");
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }

    cleanup_team(&pool, team_id).await;
}

// ============================================================
// Writer task: failure and recovery (mock-based)
// ============================================================

/// Mock DB that fails chunks a configurable number of times, then succeeds.
/// Rows always succeed. Exercises the full orchestration layer above it.
struct MockDb {
    chunk_remaining_failures: std::sync::atomic::AtomicU32,
    chunk_error_kind: WriteErrorKind,
}

#[async_trait::async_trait]
impl PersonDb for MockDb {
    async fn execute_chunk(&self, _chunk: &[Person]) -> Result<(), WriteError> {
        let remaining = self.chunk_remaining_failures.fetch_update(
            std::sync::atomic::Ordering::SeqCst,
            std::sync::atomic::Ordering::SeqCst,
            |v| if v > 0 { Some(v - 1) } else { None },
        );
        if remaining.is_ok() {
            Err(WriteError {
                message: "mock failure".to_string(),
                kind: self.chunk_error_kind,
            })
        } else {
            Ok(())
        }
    }

    async fn execute_row(
        &self,
        _person: &Person,
        _override: Option<&str>,
    ) -> Result<(), WriteError> {
        Ok(())
    }
}

#[tokio::test]
async fn writer_crashes_after_exhausting_transient_retries() {
    let (flush_tx, flush_rx) = mpsc::channel::<FlushBatch>(4);

    let (mock_cluster, _) = create_mock_kafka().await;
    let mut client_config = ClientConfig::new();
    client_config
        .set("bootstrap.servers", mock_cluster.bootstrap_servers())
        .set("group.id", "test-writer-crash")
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false");
    let kafka_consumer = Arc::new(PersonConsumer::new(&client_config, TOPIC.to_string()).unwrap());

    let mut manager = lifecycle::Manager::builder("test")
        .with_trap_signals(false)
        .build();
    let writer_handle = manager.register("writer", lifecycle::ComponentOptions::new());
    let monitor = manager.monitor_background();

    // Always fail with transient errors
    let mock_db = MockDb {
        chunk_remaining_failures: std::sync::atomic::AtomicU32::new(100),
        chunk_error_kind: WriteErrorKind::Transient,
    };
    let store = PersonWriteStore::new(
        mock_db,
        personhog_writer::store::StoreConfig {
            chunk_size: 10,
            row_fallback_concurrency: 4,
            ..common::test_store_config()
        },
    );

    let writer_task = WriterTask::new(
        Arc::clone(&kafka_consumer),
        store,
        flush_rx,
        writer_handle,
        None,
    );
    tokio::spawn(async move { writer_task.run().await });

    let batch = FlushBatch {
        persons: vec![make_person(99_040, 1, 1)],
        offsets: HashMap::new(),
        oldest_message_ts_ms: None,
    };
    flush_tx.send(batch).await.unwrap();

    // Should crash within backoff time (1s + 2s + 4s = 7s + overhead)
    let result = tokio::time::timeout(Duration::from_secs(15), monitor.wait()).await;
    assert!(result.is_ok(), "lifecycle should shut down within timeout");
    assert!(
        result.unwrap().is_err(),
        "lifecycle should report component failure"
    );
}

#[tokio::test]
async fn writer_recovers_on_transient_retry() {
    let (flush_tx, flush_rx) = mpsc::channel::<FlushBatch>(4);

    let (mock_cluster, _) = create_mock_kafka().await;
    let mut client_config = ClientConfig::new();
    client_config
        .set("bootstrap.servers", mock_cluster.bootstrap_servers())
        .set("group.id", "test-writer-recover")
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false");
    let kafka_consumer = Arc::new(PersonConsumer::new(&client_config, TOPIC.to_string()).unwrap());

    let mut manager = lifecycle::Manager::builder("test")
        .with_trap_signals(false)
        .build();
    let writer_handle = manager.register("writer", lifecycle::ComponentOptions::new());
    let _monitor = manager.monitor_background();

    // Fail once, then succeed
    let mock_db = MockDb {
        chunk_remaining_failures: std::sync::atomic::AtomicU32::new(1),
        chunk_error_kind: WriteErrorKind::Transient,
    };
    let store = PersonWriteStore::new(
        mock_db,
        personhog_writer::store::StoreConfig {
            chunk_size: 10,
            row_fallback_concurrency: 4,
            ..common::test_store_config()
        },
    );

    let writer_task = WriterTask::new(
        Arc::clone(&kafka_consumer),
        store,
        flush_rx,
        writer_handle,
        None,
    );
    tokio::spawn(async move { writer_task.run().await });

    let batch = FlushBatch {
        persons: vec![make_person(99_041, 1, 1)],
        offsets: HashMap::new(),
        oldest_message_ts_ms: None,
    };
    flush_tx.send(batch).await.unwrap();

    // Send a second batch to verify the writer is still alive after recovery
    tokio::time::sleep(Duration::from_secs(3)).await;
    let batch2 = FlushBatch {
        persons: vec![make_person(99_041, 2, 1)],
        offsets: HashMap::new(),
        oldest_message_ts_ms: None,
    };
    assert!(
        flush_tx.send(batch2).await.is_ok(),
        "writer should still be alive after transient recovery"
    );
}

#[tokio::test]
async fn writer_falls_back_to_per_row_on_data_error() {
    let (flush_tx, flush_rx) = mpsc::channel::<FlushBatch>(4);

    let (mock_cluster, _) = create_mock_kafka().await;
    let mut client_config = ClientConfig::new();
    client_config
        .set("bootstrap.servers", mock_cluster.bootstrap_servers())
        .set("group.id", "test-writer-fallback")
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false");
    let kafka_consumer = Arc::new(PersonConsumer::new(&client_config, TOPIC.to_string()).unwrap());

    let mut manager = lifecycle::Manager::builder("test")
        .with_trap_signals(false)
        .build();
    let writer_handle = manager.register("writer", lifecycle::ComponentOptions::new());
    let _monitor = manager.monitor_background();

    // Batch always fails with data error, per-row always succeeds
    let mock_db = MockDb {
        chunk_remaining_failures: std::sync::atomic::AtomicU32::new(100),
        chunk_error_kind: WriteErrorKind::Data,
    };
    let store = PersonWriteStore::new(
        mock_db,
        personhog_writer::store::StoreConfig {
            chunk_size: 10,
            row_fallback_concurrency: 4,
            ..common::test_store_config()
        },
    );

    let writer_task = WriterTask::new(
        Arc::clone(&kafka_consumer),
        store,
        flush_rx,
        writer_handle,
        None,
    );
    tokio::spawn(async move { writer_task.run().await });

    let batch = FlushBatch {
        persons: vec![make_person(99_042, 1, 1), make_person(99_042, 2, 1)],
        offsets: HashMap::new(),
        oldest_message_ts_ms: None,
    };
    flush_tx.send(batch).await.unwrap();

    // Writer should handle the data error via fallback and stay alive
    tokio::time::sleep(Duration::from_secs(1)).await;
    let batch2 = FlushBatch {
        persons: vec![make_person(99_042, 3, 1)],
        offsets: HashMap::new(),
        oldest_message_ts_ms: None,
    };
    assert!(
        flush_tx.send(batch2).await.is_ok(),
        "writer should still be alive after data error fallback"
    );
}

// ============================================================
// Properties size violation: trim → successful write
// ============================================================

#[tokio::test]
async fn properties_size_violation_trim_succeeds() {
    let pool = create_test_pool().await;
    let team_id: i32 = 99_050;
    cleanup_team(&pool, team_id).await;

    let store = PersonWriteStore::new(
        PgStore::new(pool.clone(), TARGET_TABLE.to_string()),
        common::test_store_config(),
    );

    // Build properties that exceed 640KB total but fit once custom keys are
    // trimmed. Protected "email" is small; two large custom properties push
    // the serialized JSON well past the DB constraint.
    let mut props = serde_json::Map::new();
    props.insert(
        "email".to_string(),
        serde_json::json!("protected@example.com"),
    );
    let big_value = "x".repeat(400_000);
    props.insert("custom_a".to_string(), serde_json::json!(big_value));
    props.insert("custom_b".to_string(), serde_json::json!(big_value));

    let mut person = make_person(team_id as i64, 1, 1);
    person.properties = serde_json::to_vec(&serde_json::Value::Object(props)).unwrap();

    let result = store.upsert_row(&person).await;
    let RowResult::Trimmed(warning) = result else {
        panic!("expected RowResult::Trimmed");
    };
    assert_eq!(warning.team_id, team_id as i64);
    assert_eq!(warning.person_id, 1);
    assert!(!warning.message.is_empty());

    // Verify the row landed in PG with trimmed properties
    let row: (i64, String) = sqlx::query_as(
        "SELECT id, properties::text FROM personhog_person_tmp WHERE team_id = $1 AND id = $2",
    )
    .bind(team_id)
    .bind(1_i64)
    .fetch_one(&pool)
    .await
    .unwrap();

    assert_eq!(row.0, 1);
    let stored_props: serde_json::Value = serde_json::from_str(&row.1).unwrap();
    let stored_map = stored_props.as_object().unwrap();
    assert!(
        stored_map.contains_key("email"),
        "protected property 'email' should be preserved"
    );
    // The trim algorithm removes custom properties in alphabetical order
    // until the result fits under the target. "custom_a" is removed first;
    // that alone brings the total below 512KB, so "custom_b" survives.
    assert!(
        !stored_map.contains_key("custom_a"),
        "custom property 'custom_a' should have been trimmed"
    );

    cleanup_team(&pool, team_id).await;
}

// ============================================================
// Properties size violation: untrimable (protected only) → skip
// ============================================================

#[tokio::test]
async fn properties_size_violation_untrimable_skips() {
    let pool = create_test_pool().await;
    let team_id: i32 = 99_051;
    cleanup_team(&pool, team_id).await;

    let store = PersonWriteStore::new(
        PgStore::new(pool.clone(), TARGET_TABLE.to_string()),
        common::test_store_config(),
    );

    // Only protected properties, and they exceed 640KB on their own.
    let mut props = serde_json::Map::new();
    let huge_email = "e".repeat(700_000);
    props.insert("email".to_string(), serde_json::json!(huge_email));

    let mut person = make_person(team_id as i64, 1, 1);
    person.properties = serde_json::to_vec(&serde_json::Value::Object(props)).unwrap();

    let result = store.upsert_row(&person).await;
    let RowResult::Skipped(warning) = result else {
        panic!("expected RowResult::Skipped");
    };
    assert_eq!(warning.team_id, team_id as i64);
    assert_eq!(warning.person_id, 1);
    assert!(!warning.message.is_empty());

    // Verify no row was written
    let count: (i64,) =
        sqlx::query_as("SELECT COUNT(*) FROM personhog_person_tmp WHERE team_id = $1 AND id = $2")
            .bind(team_id)
            .bind(1_i64)
            .fetch_one(&pool)
            .await
            .unwrap();

    assert_eq!(count.0, 0, "no row should exist for a skipped person");

    cleanup_team(&pool, team_id).await;
}

// ============================================================
// E2E: real Kafka + real PG
// ============================================================

#[tokio::test]
async fn e2e_produce_to_kafka_and_verify_pg_write() {
    let pool = create_test_pool().await;
    let team_id: i32 = 99_030;
    cleanup_team(&pool, team_id).await;

    // Produce a Person proto to local Kafka
    let producer = create_local_kafka_producer().await;
    let person = make_person(team_id as i64, 42, 1);
    let payload = person.encode_to_vec();
    let key = format!("{team_id}:42");
    let record = FutureRecord::to(TOPIC).key(&key).payload(&payload);
    producer
        .send_result(record)
        .unwrap()
        .await
        .unwrap()
        .unwrap();

    // Set up the full consumer + writer pipeline against local Kafka
    let (flush_tx, flush_rx) = mpsc::channel::<FlushBatch>(2);

    let client_config = ClientConfig::new()
        .set("bootstrap.servers", KAFKA_BOOTSTRAP)
        .set(
            "group.id",
            format!("e2e-pg-writer-{}", uuid::Uuid::new_v4()),
        )
        .set("auto.offset.reset", "earliest")
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        .clone();
    let kafka_consumer = Arc::new(PersonConsumer::new(&client_config, TOPIC.to_string()).unwrap());

    let mut manager = lifecycle::Manager::builder("test")
        .with_trap_signals(false)
        .build();
    let consumer_handle = manager.register(
        "consumer",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let writer_handle = manager.register(
        "writer",
        lifecycle::ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
    );
    let _monitor = manager.monitor_background();

    let writer = PersonWriteStore::new(
        PgStore::new(pool.clone(), TARGET_TABLE.to_string()),
        common::test_store_config(),
    );
    let writer_task = WriterTask::new(
        Arc::clone(&kafka_consumer),
        writer,
        flush_rx,
        writer_handle,
        None,
    );
    tokio::spawn(async move { writer_task.run().await });

    let consumer_task = ConsumerTask::new(
        kafka_consumer,
        PersonBuffer::new(50000),
        flush_tx,
        Duration::from_millis(500), // fast flush for test
        1,                          // flush after every message
        consumer_handle,
    );
    tokio::spawn(async move { consumer_task.run().await });

    // Wait for the row to appear in PG
    let mut retries = 0;
    loop {
        let result: Option<(i64, i64)> = sqlx::query_as(
            "SELECT id, version FROM personhog_person_tmp WHERE team_id = $1 AND id = $2",
        )
        .bind(team_id)
        .bind(42_i64)
        .fetch_optional(&pool)
        .await
        .unwrap();

        if let Some((id, version)) = result {
            assert_eq!(id, 42);
            assert_eq!(version, 1);
            break;
        }

        retries += 1;
        if retries > 100 {
            panic!("Row never appeared in personhog_person_tmp for team {team_id}, person 42");
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }

    cleanup_team(&pool, team_id).await;
}
