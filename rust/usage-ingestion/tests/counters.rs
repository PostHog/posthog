//! Cluster-backed counter checks. Start the dev Valkey cluster first:
//! `docker compose -f docker-compose.dev.yml up -d valkey-cluster`.

use std::sync::Arc;

use chrono::Utc;
use redis::cluster::ClusterClient;
use redis::AsyncCommands;
use usage_ingestion::counters::{
    counter_key, flush, Bucket, CounterAccumulator, CounterScope, CounterStore, RedisCounterStore,
};
use uuid::Uuid;

const SCOPES: i64 = 1_024;

fn redis_url() -> String {
    std::env::var("USAGE_INGESTION_REDIS_URL")
        .unwrap_or_else(|_| "redis://127.0.0.1:6390".to_string())
}

#[tokio::test]
#[ignore = "requires the cluster-enabled Valkey from docker-compose.dev.yml"]
async fn counters_are_atomic_per_scope_and_do_not_cross_slots() {
    let timestamp = Utc::now();
    let organization_id = Uuid::new_v4();
    let usage_key = format!("integration_events_{}", Uuid::new_v4());
    let field = format!("{}:{usage_key}event", usage_key.len());
    let first_team_id = 1_000_000 + (Uuid::new_v4().as_u128() % 1_000_000) as i64;
    let accumulator = CounterAccumulator::default();
    for offset in 0..SCOPES {
        let team_id = first_team_id + offset;
        accumulator
            .add(
                team_id,
                organization_id,
                &usage_key,
                "event",
                offset + 1,
                timestamp,
            )
            .expect("test record should enter the counter accumulator");
    }

    let store: Arc<dyn CounterStore> = Arc::new(
        RedisCounterStore::connect(&redis_url())
            .await
            .expect("failed to connect to Valkey Cluster"),
    );
    let outcome = flush(Arc::clone(&store), accumulator.drain()).await;
    assert_eq!(outcome.dropped, 0);
    assert_eq!(outcome.capped, 0);
    // 1,024 teams plus one shared organization; hour + day, HINCRBY + EXPIRE NX each.
    assert_eq!(outcome.commands, (SCOPES as usize + 1) * 4);

    let client = ClusterClient::new([redis_url()]).expect("invalid Valkey Cluster URL");
    let mut connection = client
        .get_async_connection()
        .await
        .expect("failed to connect to Valkey Cluster");
    let team_scope = CounterScope::Team(first_team_id + SCOPES - 1);
    let hour_key = counter_key(
        &team_scope,
        Bucket::Hour(timestamp.timestamp().div_euclid(3600)),
    );
    let day_key = counter_key(
        &team_scope,
        Bucket::Day(timestamp.timestamp().div_euclid(86400)),
    );
    let hour_slot: u16 = redis::cmd("CLUSTER")
        .arg("KEYSLOT")
        .arg(&hour_key)
        .query_async(&mut connection)
        .await
        .expect("cluster did not report the hourly key slot");
    let day_slot: u16 = redis::cmd("CLUSTER")
        .arg("KEYSLOT")
        .arg(&day_key)
        .query_async(&mut connection)
        .await
        .expect("cluster did not report the daily key slot");
    assert_eq!(
        hour_slot, day_slot,
        "one scope must stay in one cluster slot"
    );
    let other_slot: u16 = redis::cmd("CLUSTER")
        .arg("KEYSLOT")
        .arg(counter_key(
            &CounterScope::Team(first_team_id),
            Bucket::Hour(timestamp.timestamp().div_euclid(3600)),
        ))
        .query_async(&mut connection)
        .await
        .expect("cluster did not report another team key slot");
    assert_ne!(
        hour_slot, other_slot,
        "independent teams should shard separately"
    );

    let quantity: i64 = connection
        .hget(&hour_key, field)
        .await
        .expect("the hourly counter was not written");
    assert_eq!(quantity, SCOPES);
    let hourly_ttl: i64 = redis::cmd("TTL")
        .arg(&hour_key)
        .query_async(&mut connection)
        .await
        .expect("failed to read the hourly TTL");
    assert!((25 * 60 * 60 - 3..=25 * 60 * 60).contains(&hourly_ttl));

    tokio::time::sleep(std::time::Duration::from_secs(1)).await;
    let retry = CounterAccumulator::default();
    retry
        .add(
            first_team_id + SCOPES - 1,
            organization_id,
            "ttl_does_not_refresh",
            "event",
            1,
            timestamp,
        )
        .expect("test retry should enter the counter accumulator");
    let retry_outcome = flush(Arc::clone(&store), retry.drain()).await;
    assert_eq!(retry_outcome.dropped, 0);
    assert_eq!(retry_outcome.capped, 0);
    let retried_hourly_ttl: i64 = redis::cmd("TTL")
        .arg(&hour_key)
        .query_async(&mut connection)
        .await
        .expect("failed to read the hourly TTL after a retry");
    assert!(
        retried_hourly_ttl < hourly_ttl,
        "the hourly TTL was refreshed"
    );
    let daily_ttl: i64 = redis::cmd("TTL")
        .arg(&day_key)
        .query_async(&mut connection)
        .await
        .expect("failed to read the daily TTL");
    assert!((31 * 24 * 60 * 60 - 3..=31 * 24 * 60 * 60).contains(&daily_ttl));

    // The cluster client or server rejects this transaction. The successful writes above
    // therefore prove the production pipeline is not combining different scope hash tags.
    let error = redis::pipe()
        .atomic()
        .cmd("HINCRBY")
        .arg("usage:v1:{scope-a}:h:1")
        .arg("field")
        .arg(1)
        .ignore()
        .cmd("HINCRBY")
        .arg("usage:v1:{scope-b}:h:1")
        .arg("field")
        .arg(1)
        .ignore()
        .query_async::<()>(&mut connection)
        .await
        .expect_err("Valkey Cluster should reject a cross-slot transaction");
    let error = error.to_string();
    assert!(
        error.to_ascii_lowercase().contains("crossslot") || error.contains("same slot"),
        "unexpected cross-slot error: {error}"
    );
}
