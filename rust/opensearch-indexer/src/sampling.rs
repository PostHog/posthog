use std::{
    borrow::Cow,
    collections::{HashMap, HashSet},
    hash::{DefaultHasher, Hash, Hasher},
};

use chrono::{DateTime, Utc};
use common_redis::{Client, CustomRedisError};
use serde::Deserialize;

use crate::{config::Config, types::IndexDoc};

/// TTL for the daily counter key. 24h + 1h overhang absorbs clock skew so the
/// previous day's key is gone before any indexer restart could re-touch it.
const COUNTER_TTL_SECONDS: u64 = 25 * 3600;

/// Per-team sampling override (floor count + above-floor rate). Loaded from the
/// `OPENSEARCH_INDEXER_TEAM_OVERRIDES` envvar (JSON map) at startup.
#[derive(Clone, Debug, Copy, Deserialize)]
pub struct TeamOverride {
    pub floor: u64,
    pub rate: f64,
}

/// Outcome of the sampling decision. The four variants distinguish *why* the
/// event indexes (or doesn't) so callers can label per-decision metrics without
/// reclassifying.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Decision {
    Drop,
    IndexFloor,
    IndexSample,
    IndexError,
}

/// Snapshot of sampling parameters resolved at process start. The clock is
/// injected so day-boundary behavior is testable.
#[derive(Clone)]
pub struct SamplingConfig {
    pub(crate) default_floor: u64,
    pub(crate) default_above_floor_rate: f64,
    pub(crate) deny_teams: HashSet<i32>,
    pub(crate) overrides: HashMap<i32, TeamOverride>,
    pub(crate) now_utc: fn() -> DateTime<Utc>,
}

impl std::fmt::Debug for SamplingConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SamplingConfig")
            .field("default_floor", &self.default_floor)
            .field("default_above_floor_rate", &self.default_above_floor_rate)
            .field("deny_teams", &self.deny_teams)
            .field("overrides", &self.overrides)
            .finish()
    }
}

impl SamplingConfig {
    pub fn from_config(c: &Config) -> Self {
        Self {
            default_floor: c.default_floor,
            default_above_floor_rate: c.default_above_floor_rate,
            deny_teams: c.deny_teams.teams.clone(),
            overrides: c.team_overrides.overrides.clone(),
            now_utc: Utc::now,
        }
    }

    fn resolve(&self, team_id: i32) -> (u64, f64) {
        self.overrides
            .get(&team_id)
            .map(|o| (o.floor, o.rate))
            .unwrap_or((self.default_floor, self.default_above_floor_rate))
    }
}

/// 0..1000 bucket for the given key. Stable across processes within a single
/// Rust toolchain version (DefaultHasher::new() seeds with fixed zero keys, so
/// all pods agree on the trace_id -> bucket mapping). The Rust standard library
/// does NOT guarantee this hash output across compiler versions, so a toolchain
/// bump can shift every team's bucket assignment in lockstep.
fn stable_hash_bucket(key: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    key.hash(&mut hasher);
    hasher.finish() % 1_000
}

pub(crate) async fn decide(
    redis: &(dyn Client + Send + Sync),
    config: &SamplingConfig,
    doc: &IndexDoc,
) -> Result<Decision, CustomRedisError> {
    if config.deny_teams.contains(&doc.team_id) {
        return Ok(Decision::Drop);
    }
    if doc.is_error {
        return Ok(Decision::IndexError);
    }

    let (floor, rate) = config.resolve(doc.team_id);

    let date = (config.now_utc)().format("%Y-%m-%d").to_string();
    let key = format!("opensearch_indexer:counter:{}:{}", doc.team_id, date);
    let raw_count = redis.incr_with_expire(key, COUNTER_TTL_SECONDS).await?;

    // INCR is monotonic-positive in Redis; a negative or overflowing value is a
    // protocol-level surprise (broken proxy, bad mock). Surface as a parse error
    // so the caller's fail-open path takes over, instead of silently treating
    // it as "way past floor".
    let count: u64 = u64::try_from(raw_count).map_err(|_| {
        CustomRedisError::ParseError(format!("incr_with_expire returned non-positive: {raw_count}"))
    })?;

    // Floor accounting and trace-bucket sampling are independent. A trace whose
    // spans straddle the floor count can split: the head spans land as
    // IndexFloor, the tail bucket-decides. In practice high-volume teams burn
    // the floor in seconds, so the cohesion gap is bounded to ~one trace per
    // team per day.
    if count <= floor {
        return Ok(Decision::IndexFloor);
    }

    let bucket_key: Cow<'_, str> = match &doc.trace_id {
        Some(t) => Cow::Borrowed(t.as_str()),
        None => Cow::Owned(doc.event_uuid.to_string()),
    };
    let bucket = stable_hash_bucket(&bucket_key);
    let threshold = (rate.clamp(0.0, 1.0) * 1_000.0) as u64;
    Ok(if bucket < threshold {
        Decision::IndexSample
    } else {
        Decision::Drop
    })
}

#[cfg(test)]
mod tests {
    use std::time::Instant;

    use chrono::Utc;
    use common_redis::MockRedisClient;
    use uuid::Uuid;

    use super::*;

    fn fixture_doc(team_id: i32, trace_id: Option<&str>, is_error: bool) -> IndexDoc {
        IndexDoc {
            timestamp: "2024-01-01T12:00:00.000Z".to_string(),
            trace_id: trace_id.map(String::from),
            team_id,
            model: None,
            provider: None,
            tool_names: Vec::new(),
            is_error,
            cost: None,
            latency_ms: None,
            input: None,
            output: None,
            error: None,
            event_uuid: Uuid::new_v4(),
            parsed_at: Instant::now(),
        }
    }

    fn config_with(floor: u64, rate: f64, overrides: HashMap<i32, TeamOverride>) -> SamplingConfig {
        SamplingConfig {
            default_floor: floor,
            default_above_floor_rate: rate,
            deny_teams: HashSet::new(),
            overrides,
            now_utc: Utc::now,
        }
    }

    fn key_for(team_id: i32) -> String {
        format!(
            "opensearch_indexer:counter:{}:{}",
            team_id,
            Utc::now().format("%Y-%m-%d")
        )
    }

    #[tokio::test]
    async fn deny_team_drops_without_incr() {
        let redis = MockRedisClient::new();
        let mut config = config_with(10, 0.5, HashMap::new());
        config.deny_teams.insert(42);

        let doc = fixture_doc(42, Some("t-1"), false);
        let decision = decide(&redis, &config, &doc).await.unwrap();
        assert_eq!(decision, Decision::Drop);
        assert!(
            redis
                .get_calls()
                .iter()
                .all(|c| c.op != "incr_with_expire"),
            "deny-list short-circuit must not call Redis"
        );
    }

    #[tokio::test]
    async fn error_event_indexes_without_incr() {
        let redis = MockRedisClient::new();
        let config = config_with(10, 0.5, HashMap::new());

        let doc = fixture_doc(42, Some("t-1"), true);
        let decision = decide(&redis, &config, &doc).await.unwrap();
        assert_eq!(decision, Decision::IndexError);
        assert!(
            redis
                .get_calls()
                .iter()
                .all(|c| c.op != "incr_with_expire"),
            "error events must not consume floor budget"
        );
    }

    #[tokio::test]
    async fn count_at_floor_indexes_floor() {
        let mut redis = MockRedisClient::new();
        let team_id = 42;
        redis = redis.incr_with_expire_ret(&key_for(team_id), Ok(10));
        let config = config_with(10, 0.0, HashMap::new());

        let doc = fixture_doc(team_id, Some("t-1"), false);
        let decision = decide(&redis, &config, &doc).await.unwrap();
        assert_eq!(decision, Decision::IndexFloor);
    }

    #[tokio::test]
    async fn count_above_floor_with_rate_one_samples() {
        let mut redis = MockRedisClient::new();
        let team_id = 42;
        redis = redis.incr_with_expire_ret(&key_for(team_id), Ok(11));
        let config = config_with(10, 1.0, HashMap::new());

        let doc = fixture_doc(team_id, Some("t-1"), false);
        let decision = decide(&redis, &config, &doc).await.unwrap();
        assert_eq!(decision, Decision::IndexSample);
    }

    #[tokio::test]
    async fn count_above_floor_with_rate_zero_drops() {
        let mut redis = MockRedisClient::new();
        let team_id = 42;
        redis = redis.incr_with_expire_ret(&key_for(team_id), Ok(11));
        let config = config_with(10, 0.0, HashMap::new());

        let doc = fixture_doc(team_id, Some("t-1"), false);
        let decision = decide(&redis, &config, &doc).await.unwrap();
        assert_eq!(decision, Decision::Drop);
    }

    #[tokio::test]
    async fn trace_cohesive_sampling() {
        let mut redis = MockRedisClient::new();
        let team_id = 42;
        // Both events bump the same counter key; mock returns the same count
        // for any number of calls.
        redis = redis.incr_with_expire_ret(&key_for(team_id), Ok(11));
        let config = config_with(10, 0.5, HashMap::new());

        let span_a = fixture_doc(team_id, Some("trace-shared"), false);
        let span_b = fixture_doc(team_id, Some("trace-shared"), false);
        let d_a = decide(&redis, &config, &span_a).await.unwrap();
        let d_b = decide(&redis, &config, &span_b).await.unwrap();
        assert_eq!(d_a, d_b, "spans of one trace must share the decision");
    }

    #[tokio::test]
    async fn redis_error_propagates() {
        let mut redis = MockRedisClient::new();
        let team_id = 42;
        redis = redis.incr_with_expire_ret(&key_for(team_id), Err(CustomRedisError::Timeout));
        let config = config_with(10, 0.5, HashMap::new());

        let doc = fixture_doc(team_id, Some("t-1"), false);
        let err = decide(&redis, &config, &doc).await.unwrap_err();
        assert!(matches!(err, CustomRedisError::Timeout));
    }

    #[tokio::test]
    async fn key_format_includes_team_and_date() {
        let mut redis = MockRedisClient::new();
        let team_id = 99;
        redis = redis.incr_with_expire_ret(&key_for(team_id), Ok(1));
        let config = config_with(10, 0.5, HashMap::new());

        let doc = fixture_doc(team_id, Some("t-1"), false);
        let _ = decide(&redis, &config, &doc).await.unwrap();

        let calls = redis.get_calls();
        let incr_call = calls
            .iter()
            .find(|c| c.op == "incr_with_expire")
            .expect("decide() should have called incr_with_expire");
        let today = Utc::now().format("%Y-%m-%d").to_string();
        assert_eq!(
            incr_call.key,
            format!("opensearch_indexer:counter:99:{today}")
        );
    }

    #[tokio::test]
    async fn team_override_uses_team_specific_floor_and_rate() {
        let mut redis = MockRedisClient::new();
        let team_a = 42;
        let team_b = 99;
        redis = redis
            .incr_with_expire_ret(&key_for(team_a), Ok(150))
            .incr_with_expire_ret(&key_for(team_b), Ok(50));

        let mut overrides = HashMap::new();
        overrides.insert(
            team_a,
            TeamOverride {
                floor: 100,
                rate: 1.0,
            },
        );
        let config = config_with(10, 0.0, overrides);

        // Team A: count=150, override floor=100, rate=1.0 -> above floor, full sample.
        let doc_a = fixture_doc(team_a, Some("ta-1"), false);
        assert_eq!(
            decide(&redis, &config, &doc_a).await.unwrap(),
            Decision::IndexSample
        );

        // Team B: count=50, default floor=10, rate=0.0 -> above floor, drop.
        let doc_b = fixture_doc(team_b, Some("tb-1"), false);
        assert_eq!(
            decide(&redis, &config, &doc_b).await.unwrap(),
            Decision::Drop
        );
    }

    #[tokio::test]
    async fn deny_short_circuits_override() {
        let redis = MockRedisClient::new();
        let team_id = 42;

        let mut overrides = HashMap::new();
        overrides.insert(
            team_id,
            TeamOverride {
                floor: 100,
                rate: 1.0,
            },
        );
        let mut config = config_with(10, 0.0, overrides);
        config.deny_teams.insert(team_id);

        let doc = fixture_doc(team_id, Some("t-1"), false);
        assert_eq!(
            decide(&redis, &config, &doc).await.unwrap(),
            Decision::Drop
        );
    }

    #[tokio::test]
    async fn error_short_circuits_override() {
        let redis = MockRedisClient::new();
        let team_id = 42;

        let mut overrides = HashMap::new();
        overrides.insert(
            team_id,
            TeamOverride {
                floor: 100,
                rate: 1.0,
            },
        );
        let config = config_with(10, 0.0, overrides);

        let doc = fixture_doc(team_id, Some("t-1"), true);
        assert_eq!(
            decide(&redis, &config, &doc).await.unwrap(),
            Decision::IndexError
        );
    }

    // ---- New tests added in stage D review ----

    #[tokio::test]
    async fn none_trace_id_with_rate_zero_drops_past_floor() {
        // Tests the bucket_key fallback to event_uuid when trace_id is None.
        // With rate=0.0 the threshold is 0, so any bucket value drops.
        let mut redis = MockRedisClient::new();
        let team_id = 42;
        redis = redis.incr_with_expire_ret(&key_for(team_id), Ok(11));
        let config = config_with(10, 0.0, HashMap::new());

        let doc = fixture_doc(team_id, None, false);
        let decision = decide(&redis, &config, &doc).await.unwrap();
        assert_eq!(decision, Decision::Drop);
    }

    #[tokio::test]
    async fn none_trace_id_with_rate_one_indexes_past_floor() {
        // Symmetric to the drop case: trace_id=None, rate=1.0, past floor -> sample.
        let mut redis = MockRedisClient::new();
        let team_id = 42;
        redis = redis.incr_with_expire_ret(&key_for(team_id), Ok(11));
        let config = config_with(10, 1.0, HashMap::new());

        let doc = fixture_doc(team_id, None, false);
        let decision = decide(&redis, &config, &doc).await.unwrap();
        assert_eq!(decision, Decision::IndexSample);
    }

    #[test]
    fn none_trace_id_distinct_event_uuids_bucket_distinctly() {
        // The fallback path computes the bucket from event_uuid. If two
        // distinct UUIDs hashed to the same bucket, this test would not
        // exercise the fallback meaningfully. Pin two UUIDs whose buckets
        // differ; this is a sanity check on the test fixtures themselves.
        let bucket_a = stable_hash_bucket(&Uuid::nil().to_string());
        let bucket_b = stable_hash_bucket(&Uuid::from_u128(1).to_string());
        assert_ne!(
            bucket_a, bucket_b,
            "fixture UUIDs must bucket distinctly for the fallback test to be meaningful"
        );
    }

    #[test]
    fn stable_hash_bucket_in_range() {
        // Bucket must always be 0..1000 regardless of input.
        for input in ["", "x", "very-long-trace-id-string", "00000000-0000-0000-0000-000000000000"] {
            let b = stable_hash_bucket(input);
            assert!(b < 1_000, "bucket {b} for {input:?} out of range");
        }
    }

    #[test]
    fn stable_hash_bucket_pinned_known_inputs() {
        // Regression guard against Rust toolchain changes to DefaultHasher.
        // If this fails after a toolchain bump, the bucket assignments for
        // every team have shifted in lockstep. Decide whether to accept the
        // new buckets (update the values below) or move to a versioned hash.
        assert_eq!(stable_hash_bucket("trace-shared"), 355);
        assert_eq!(
            stable_hash_bucket("00000000-0000-0000-0000-000000000000"),
            721
        );
        assert_eq!(
            stable_hash_bucket("00000000-0000-0000-0000-000000000001"),
            472
        );
    }

    #[tokio::test]
    async fn negative_count_treated_as_parse_error() {
        // INCR is monotonic-positive in Redis. A negative return is a protocol
        // surprise; the defensive cast must surface it as a ParseError so the
        // caller's fail-open path takes over.
        let mut redis = MockRedisClient::new();
        let team_id = 42;
        redis = redis.incr_with_expire_ret(&key_for(team_id), Ok(-1));
        let config = config_with(10, 0.5, HashMap::new());

        let doc = fixture_doc(team_id, Some("t-1"), false);
        let err = decide(&redis, &config, &doc).await.unwrap_err();
        assert!(
            matches!(err, CustomRedisError::ParseError(_)),
            "expected ParseError for negative count, got {err:?}"
        );
    }

    #[tokio::test]
    async fn injected_clock_drives_daily_key() {
        // Day-boundary determinism: the date in the counter key comes from the
        // injected clock, not chrono::Utc::now() directly.
        fn fixed_2024_03_15() -> DateTime<Utc> {
            DateTime::parse_from_rfc3339("2024-03-15T12:00:00Z")
                .unwrap()
                .with_timezone(&Utc)
        }

        let pinned_key = "opensearch_indexer:counter:42:2024-03-15";
        let mut redis = MockRedisClient::new();
        redis = redis.incr_with_expire_ret(pinned_key, Ok(1));

        let mut config = config_with(10, 0.5, HashMap::new());
        config.now_utc = fixed_2024_03_15;

        let doc = fixture_doc(42, Some("t-1"), false);
        decide(&redis, &config, &doc).await.unwrap();

        let calls = redis.get_calls();
        let key_seen = calls
            .iter()
            .find(|c| c.op == "incr_with_expire")
            .expect("decide() should have called incr_with_expire");
        assert_eq!(key_seen.key, pinned_key);
    }
}
