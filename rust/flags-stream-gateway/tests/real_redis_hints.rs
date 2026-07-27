//! Real-infrastructure hint-path test (plan §2.12): `MockRedisClient` cannot
//! mock a raw pub/sub connection, so this runs against the local-stack Redis and
//! stays `#[ignore]`-gated. It proves the full path: SUBSCRIBE on the primary →
//! receive a published cache-ready signal → confirm-read the etag → apply.

use std::collections::HashMap;
use std::str::FromStr;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use common_hypercache::{HyperCacheConfig, HyperCacheReader};
use common_redis::{Client, RedisClient};
use lifecycle::{ComponentOptions, Manager};
use tokio_util::sync::CancellationToken;

use flags_stream_gateway::domain::{CacheKind, Etag, Topic, VersionState};
use flags_stream_gateway::registry::TopicRegistry;
use flags_stream_gateway::trigger::hints::{run_hints, HintConfig};
use flags_stream_gateway::trigger::Tier;

const REDIS_URL: &str = "redis://localhost:6379/";
const ETAG: &str = "0123456789abcdef";

#[tokio::test]
#[ignore = "requires local Redis (rust/docker-compose.yml); run with --ignored"]
async fn hint_applies_after_confirm_read_over_real_pubsub() {
    let client: Arc<dyn Client + Send + Sync> = Arc::new(
        RedisClient::new(REDIS_URL.to_string())
            .await
            .expect("local redis reachable"),
    );

    // Unique team per run so reruns never observe a previous run's state.
    let team_id = (SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock after epoch")
        .as_millis()
        % 1_000_000) as i32;

    // Write the etag key the confirm-read will verify. RedisClient's default
    // Pickle format matches what `get_etag` decodes.
    let etag_key = format!("posthog:1:cache/teams/{team_id}/feature_flags/flags.json:etag");
    client
        .set(etag_key.clone(), ETAG.to_string())
        .await
        .expect("etag write");

    let hc_config = HyperCacheConfig::new(
        "feature_flags".to_string(),
        "flags.json".to_string(),
        "us-east-1".to_string(),
        "posthog".to_string(),
    );
    let reader = Arc::new(
        HyperCacheReader::new(client.clone(), hc_config)
            .await
            .expect("reader builds"),
    );

    let registry = Arc::new(TopicRegistry::new());
    let topic = Topic {
        team_id,
        kind: CacheKind::RemoteEval,
    };
    let mut rx = registry.subscribe(topic);

    let token = CancellationToken::new();
    let mut manager = Manager::builder("hints-real-redis-test")
        .with_trap_signals(false)
        .with_prestop_check(false)
        .with_shutdown_token(token.clone())
        .with_global_shutdown_timeout(Duration::from_secs(10))
        .build();
    let handle = manager.register("hints:test", ComponentOptions::new());
    let monitor = manager.monitor_background();

    let tier = Tier {
        name: "shared",
        kinds: vec![CacheKind::RemoteEval],
        pubsub_url: REDIS_URL.to_string(),
        readers: HashMap::from([(CacheKind::RemoteEval, reader)]),
    };
    let task = tokio::spawn(run_hints(
        handle,
        registry.clone(),
        tier,
        HintConfig::default(),
        Duration::from_secs(30),
    ));

    // There is no signal for "SUBSCRIBE established", so publish in a bounded
    // retry loop until the hint lands (pub/sub is at-most-once by design).
    let payload = format!(
        r#"{{"v":1,"team_id":{team_id},"namespace":"feature_flags","value":"flags.json","etag":"{ETAG}","written_at":"2026-07-26T12:00:00Z"}}"#
    );
    let mut applied = false;
    for _ in 0..50 {
        client
            .publish(
                "hypercache:ready:feature_flags:flags.json".to_string(),
                payload.clone(),
            )
            .await
            .expect("publish");
        if let Ok(Ok(())) = tokio::time::timeout(Duration::from_millis(100), rx.changed()).await {
            applied = true;
            break;
        }
    }
    assert!(applied, "hint was never applied within the retry budget");
    assert_eq!(
        *rx.borrow(),
        VersionState::Known(Etag::from_str(ETAG).expect("valid etag"))
    );

    client.del(etag_key).await.ok();
    token.cancel();
    tokio::time::timeout(Duration::from_secs(5), task)
        .await
        .expect("hints task exits on shutdown")
        .expect("hints task joins");
    monitor.wait().await.ok();
}
