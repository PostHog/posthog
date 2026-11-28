use std::sync::Arc;
use std::time::Duration;

use logs_ingestion::service::hog_functions::{EncryptedFields, PgHogFunctions};
use logs_ingestion::transformations::HogFunctionSource;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::mpsc;

const DATABASE_URL: &str = "postgres://posthog:posthog@localhost:5432/postgres";
const KEY: &str = "00beef0000beef0000beef0000beef00";
/// `new EncryptedFields(KEY).encrypt('{"apiKey":{"value":"test-key","order":0}}')` from fernet-nodejs.
const NODE_TOKEN: &str = "gAAAAABq7brKHRWvBDB4PkkAK5QfuvLhlNIXH2xPsrMUwpW2F5o_58MUyAlspxmFh0feDmwGx9lEqevRRedtiZ3p0zKxxLEqBvWzvJ0U4VOqgNHVgtCyB6kdby0naw8OM_7AF95Ir-8Z";
const TEAM_ID: i32 = 4242;

/// One connection, so the temporary table is visible to every query the loader makes.
async fn pool() -> Option<PgPool> {
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .acquire_timeout(Duration::from_secs(2))
        .connect(DATABASE_URL)
        .await
        .map_err(|e| eprintln!("skipping: no Postgres at {DATABASE_URL}: {e}"))
        .ok()?;
    sqlx::query(
        "CREATE TEMPORARY TABLE posthog_hogfunction (
            id uuid PRIMARY KEY,
            team_id integer NOT NULL,
            name varchar(400),
            created_at timestamptz NOT NULL,
            deleted boolean NOT NULL,
            enabled boolean NOT NULL,
            type varchar(24),
            hog text NOT NULL,
            bytecode jsonb,
            inputs jsonb,
            encrypted_inputs text,
            execution_order smallint CHECK (execution_order >= 0)
        )",
    )
    .execute(&pool)
    .await
    .unwrap();
    Some(pool)
}

async fn insert(
    pool: &PgPool,
    id: &str,
    name: &str,
    order: Option<i16>,
    extra: (&str, bool, bool),
) {
    let (function_type, enabled, deleted) = extra;
    sqlx::query(
        "INSERT INTO posthog_hogfunction
            (id, team_id, name, created_at, deleted, enabled, type, hog, bytecode, inputs, encrypted_inputs, execution_order)
         VALUES ($1::uuid, $2, $3, '2025-01-01T00:00:00Z', $4, $5, $6, 'return record',
                 '[\"_H\", 1, 32, \"record\", 1, 1, 38]', '{\"tag\": {\"value\": \"t\", \"order\": 0}}', $7, $8)",
    )
    .bind(id)
    .bind(TEAM_ID)
    .bind(name)
    .bind(deleted)
    .bind(enabled)
    .bind(function_type)
    .bind(NODE_TOKEN)
    .bind(order)
    .execute(pool)
    .await
    .unwrap();
}

#[tokio::test]
async fn loads_transformations_with_smallint_order_and_decrypted_inputs() {
    let Some(pool) = pool().await else {
        return;
    };
    let first = "00000000-0000-4000-a000-000000000001";
    let second = "00000000-0000-4000-a000-000000000002";
    insert(
        &pool,
        second,
        "second",
        Some(7),
        ("transformation_log", true, false),
    )
    .await;
    insert(
        &pool,
        first,
        "first",
        Some(2),
        ("transformation_log", true, false),
    )
    .await;
    insert(
        &pool,
        "00000000-0000-4000-a000-000000000003",
        "unordered",
        None,
        ("transformation_log", true, false),
    )
    .await;
    insert(
        &pool,
        "00000000-0000-4000-a000-000000000004",
        "disabled",
        Some(1),
        ("transformation_log", false, false),
    )
    .await;
    insert(
        &pool,
        "00000000-0000-4000-a000-000000000005",
        "deleted",
        Some(1),
        ("transformation_log", true, true),
    )
    .await;
    insert(
        &pool,
        "00000000-0000-4000-a000-000000000006",
        "destination",
        Some(1),
        ("destination", true, false),
    )
    .await;

    sqlx::query("UPDATE posthog_hogfunction SET name = NULL WHERE name = 'unordered'")
        .execute(&pool)
        .await
        .unwrap();

    let source = PgHogFunctions::new(pool.clone(), Arc::new(EncryptedFields::new(KEY).unwrap()));
    let functions = source.transformations(TEAM_ID as i64).await.unwrap();
    let names: Vec<&str> = functions.iter().map(|f| f.name.as_str()).collect();
    assert_eq!(names, vec!["first", "second", "null"]);
    assert_eq!(functions[0].execution_order, Some(2.0));
    assert_eq!(functions[0].id, first);
    assert!(functions[0].bytecode.is_ok());
    let keys: Vec<&str> = functions[0].inputs.iter().map(|i| i.key.as_str()).collect();
    assert_eq!(keys, vec!["tag", "apiKey"]);
    assert_eq!(functions[0].sensitive_values, vec!["test-key".to_string()]);

    sqlx::query("UPDATE posthog_hogfunction SET execution_order = 9 WHERE id = $1::uuid")
        .bind(first)
        .execute(&pool)
        .await
        .unwrap();
    source.reload(&TEAM_ID.to_string(), &[first.to_string()]);
    let reloaded = source.transformations(TEAM_ID as i64).await.unwrap();
    let names: Vec<&str> = reloaded.iter().map(|f| f.name.as_str()).collect();
    assert_eq!(names, vec!["second", "first", "null"]);
}

const REDIS_ADDR: &str = "127.0.0.1:6379";

/// Forwards to Redis and reports each accepted connection and each `subscribe` reply.
/// After `silent` is set, it holds every connection open and forwards nothing, as a half-open link does.
async fn redis_proxy(
    silent: Arc<std::sync::atomic::AtomicBool>,
    events: mpsc::UnboundedSender<&'static str>,
) -> std::net::SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    tokio::spawn(async move {
        loop {
            let (client, _) = listener.accept().await.unwrap();
            let _ = events.send("accepted");
            let Ok(server) = TcpStream::connect(REDIS_ADDR).await else {
                continue;
            };
            let (mut from_client, mut to_client) = client.into_split();
            let (mut from_server, mut to_server) = server.into_split();
            let (silent_up, silent_down) = (silent.clone(), silent.clone());
            let events = events.clone();
            tokio::spawn(async move {
                let mut buffer = [0u8; 4096];
                while let Ok(read) = from_client.read(&mut buffer).await {
                    if read == 0 || silent_up.load(std::sync::atomic::Ordering::SeqCst) {
                        break;
                    }
                    let _ = to_server.write_all(&buffer[..read]).await;
                }
                std::future::pending::<()>().await;
            });
            tokio::spawn(async move {
                let mut buffer = [0u8; 4096];
                while let Ok(read) = from_server.read(&mut buffer).await {
                    if read == 0 || silent_down.load(std::sync::atomic::Ordering::SeqCst) {
                        break;
                    }
                    let _ = to_client.write_all(&buffer[..read]).await;
                    if buffer[..read].windows(9).any(|w| w == b"subscribe") {
                        let _ = events.send("subscribed");
                    }
                }
                std::future::pending::<()>().await;
            });
        }
    });
    address
}

#[tokio::test]
async fn the_reload_listener_reconnects_when_the_connection_goes_silent() {
    // The listener never queries Postgres, so the pool does not connect.
    let pool = PgPoolOptions::new().connect_lazy(DATABASE_URL).unwrap();
    if TcpStream::connect(REDIS_ADDR).await.is_err() {
        eprintln!("skipping: no Redis at {REDIS_ADDR}");
        return;
    }
    let silent = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let (events, mut seen) = mpsc::unbounded_channel();
    let address = redis_proxy(silent.clone(), events).await;
    let functions = PgHogFunctions::new(pool, Arc::new(EncryptedFields::new(KEY).unwrap()));
    let listener = functions.spawn_reload_listener_with(
        redis::Client::open(format!("redis://{address}")).unwrap(),
        Duration::from_millis(50),
        Duration::from_millis(500),
    );

    assert_eq!(seen.recv().await, Some("accepted"));
    assert_eq!(seen.recv().await, Some("subscribed"));
    // Six ping intervals pass on a healthy connection with no reconnect.
    let healthy = tokio::time::timeout(Duration::from_millis(300), seen.recv()).await;
    assert!(healthy.is_err(), "{healthy:?}");
    silent.store(true, std::sync::atomic::Ordering::SeqCst);
    let reconnected = tokio::time::timeout(Duration::from_secs(10), seen.recv()).await;
    assert_eq!(reconnected, Ok(Some("accepted")));
    listener.abort();
}
