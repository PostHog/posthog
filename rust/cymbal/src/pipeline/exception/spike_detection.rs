use std::sync::Arc;

use chrono::{DateTime, Duration, SecondsFormat, Utc};
use common_kafka::kafka_messages::internal_events::{InternalEvent, InternalEventEvent};
use common_kafka::kafka_producer::send_iter_to_kafka;
use common_redis::Client;
use std::collections::HashMap;
use tracing::warn;
use uuid::Uuid;

use crate::app_context::AppContext;

const ISSUE_BUCKET_TTL_SECONDS: usize = 60 * 60;
const ISSUE_BUCKET_INTERVAL_MINUTES: i64 = 5;
const SPIKE_MULTIPLIER: f64 = 10.0;
const NUM_BUCKETS: usize = 12;
const SPIKE_ALERT_COOLDOWN_SECONDS: usize = 10 * 60;

const ISSUE_SPIKING_EVENT: &str = "$error_tracking_issue_spiking";
const MIN_HISTORICAL_BUCKETS_FOR_ISSUE_BASELINE: usize = 1;

fn issue_bucket_key(issue_id: &Uuid, timestamp: &str) -> String {
    format!("issue-buckets:{issue_id}-{timestamp}")
}

fn team_bucket_key(team_id: i32, timestamp: &str) -> String {
    format!("team-buckets:{team_id}-{timestamp}")
}

fn team_issue_set_key(team_id: i32, timestamp: &str) -> String {
    format!("team-issue-set:{team_id}-{timestamp}")
}

fn cooldown_key(issue_id: &Uuid) -> String {
    format!("spike-cooldown:{issue_id}")
}

#[derive(Debug, Clone)]
pub struct SpikingIssue {
    pub issue_id: Uuid,
    pub team_id: i32,
    pub computed_baseline: f64,
    pub current_bucket_value: i64,
}

fn round_datetime_to_minutes(datetime: DateTime<Utc>, minutes: i64) -> DateTime<Utc> {
    assert!(minutes > 0, "minutes must be > 0");
    let bucket_seconds = minutes * 60;
    let now_ts = datetime.timestamp();
    let rounded_ts = now_ts - now_ts.rem_euclid(bucket_seconds);
    DateTime::<Utc>::from_timestamp(rounded_ts, 0).expect("rounded timestamp is always valid")
}

fn get_rounded_to_minutes(datetime: DateTime<Utc>, minutes: i64) -> String {
    round_datetime_to_minutes(datetime, minutes).to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn get_now_rounded_to_minutes(minutes: i64) -> String {
    get_rounded_to_minutes(Utc::now(), minutes)
}

async fn try_increment_issue_buckets(
    redis: &(dyn Client + Send + Sync),
    issue_counts: &HashMap<Uuid, u32>,
) {
    if issue_counts.is_empty() {
        return;
    }

    let now_rounded_to_minutes = get_now_rounded_to_minutes(ISSUE_BUCKET_INTERVAL_MINUTES);
    let items: Vec<(String, i64)> = issue_counts
        .iter()
        .map(|(issue_id, count)| {
            (
                issue_bucket_key(issue_id, &now_rounded_to_minutes),
                *count as i64,
            )
        })
        .collect();

    if let Err(err) = redis
        .batch_incr_by_expire_nx(items, ISSUE_BUCKET_TTL_SECONDS)
        .await
    {
        warn!("Failed to increment issue buckets batch: {err}");
    }
}

async fn try_increment_team_buckets(
    redis: &(dyn Client + Send + Sync),
    issue_team_ids: &HashMap<Uuid, i32>,
    issue_counts: &HashMap<Uuid, u32>,
) {
    if issue_counts.is_empty() {
        return;
    }

    let now_rounded_to_minutes = get_now_rounded_to_minutes(ISSUE_BUCKET_INTERVAL_MINUTES);

    // Aggregate counts per team
    let team_counts: HashMap<i32, u32> =
        issue_counts
            .iter()
            .fold(HashMap::new(), |mut acc, (issue_id, count)| {
                if let Some(&team_id) = issue_team_ids.get(issue_id) {
                    *acc.entry(team_id).or_insert(0) += count;
                }
                acc
            });

    let items: Vec<(String, i64)> = team_counts
        .iter()
        .map(|(team_id, count)| {
            (
                team_bucket_key(*team_id, &now_rounded_to_minutes),
                *count as i64,
            )
        })
        .collect();

    if let Err(err) = redis
        .batch_incr_by_expire_nx(items, ISSUE_BUCKET_TTL_SECONDS)
        .await
    {
        warn!("Failed to increment team buckets batch: {err}");
    }

    // Track unique issues per team bucket using sets
    let issue_set_items: Vec<(String, String)> = issue_counts
        .keys()
        .filter_map(|issue_id| {
            let team_id = issue_team_ids.get(issue_id)?;
            Some((
                team_issue_set_key(*team_id, &now_rounded_to_minutes),
                issue_id.to_string(),
            ))
        })
        .collect();

    if let Err(err) = redis
        .batch_sadd_expire(issue_set_items, ISSUE_BUCKET_TTL_SECONDS)
        .await
    {
        warn!("Failed to add issues to team sets: {err}");
    }
}

pub async fn do_spike_detection(
    context: Arc<AppContext>,
    issue_team_ids: HashMap<Uuid, i32>,
    issue_counts: HashMap<Uuid, u32>,
) {
    if issue_counts.is_empty() {
        return;
    }

    try_increment_issue_buckets(&*context.issue_buckets_redis_client, &issue_counts).await;
    try_increment_team_buckets(
        &*context.issue_buckets_redis_client,
        &issue_team_ids,
        &issue_counts,
    )
    .await;

    let issue_ids: Vec<Uuid> = issue_counts.keys().copied().collect();
    match get_spiking_issues(
        &*context.issue_buckets_redis_client,
        &issue_team_ids,
        issue_ids,
    )
    .await
    {
        Ok(spiking) => {
            emit_spiking_events(&context, spiking).await;
        }
        Err(err) => {
            warn!("Failed to detect spikes: {err}");
        }
    }
}

fn parse_enabled_team_ids(config_value: &str) -> Option<Vec<i32>> {
    if config_value.is_empty() {
        return None;
    }
    Some(
        config_value
            .split(',')
            .filter_map(|s| s.trim().parse::<i32>().ok())
            .collect(),
    )
}

async fn emit_spiking_events(context: &AppContext, spiking: Vec<SpikingIssue>) {
    if spiking.is_empty() {
        return;
    }

    let allowed_team_ids = parse_enabled_team_ids(&context.config.spike_alert_enabled_team_ids);
    let spiking: Vec<SpikingIssue> = match &allowed_team_ids {
        Some(ids) => spiking
            .into_iter()
            .filter(|s| ids.contains(&s.team_id))
            .collect(),
        None => spiking,
    };

    if spiking.is_empty() {
        return;
    }

    let cooldown_keys: Vec<String> = spiking.iter().map(|s| cooldown_key(&s.issue_id)).collect();
    let cooldowns = context
        .issue_buckets_redis_client
        .mget(cooldown_keys)
        .await
        .unwrap_or_else(|e| {
            warn!("Failed to check spike cooldowns: {e}");
            vec![None; spiking.len()]
        });

    let not_on_cooldown: Vec<SpikingIssue> = spiking
        .into_iter()
        .zip(cooldowns.iter())
        .filter(|(_, cooldown)| cooldown.is_none())
        .map(|(spike, _)| spike)
        .collect();

    if not_on_cooldown.is_empty() {
        return;
    }

    let events: Vec<(Uuid, InternalEvent)> = not_on_cooldown
        .iter()
        .filter_map(|spike| {
            let mut event =
                InternalEventEvent::new(ISSUE_SPIKING_EVENT, spike.issue_id, Utc::now(), None);
            event
                .insert_prop("computed_baseline", spike.computed_baseline)
                .ok()?;
            event
                .insert_prop("current_bucket_value", spike.current_bucket_value)
                .ok()?;
            Some((
                spike.issue_id,
                InternalEvent {
                    team_id: spike.team_id,
                    event,
                    person: None,
                },
            ))
        })
        .collect();

    if events.is_empty() {
        return;
    }

    let kafka_events: Vec<&InternalEvent> = events.iter().map(|(_, e)| e).collect();
    let results = send_iter_to_kafka(
        &context.immediate_producer,
        &context.config.internal_events_topic,
        &kafka_events,
    )
    .await;

    let mut cooldowns_to_set: Vec<(String, i64)> = Vec::new();
    for (i, result) in results.into_iter().enumerate() {
        match result {
            Ok(_) => {
                let issue_id = events[i].0;
                cooldowns_to_set.push((cooldown_key(&issue_id), 1));
            }
            Err(e) => {
                warn!("Failed to emit spiking event: {e}");
            }
        }
    }

    if !cooldowns_to_set.is_empty() {
        if let Err(e) = context
            .issue_buckets_redis_client
            .batch_incr_by_expire_nx(cooldowns_to_set, SPIKE_ALERT_COOLDOWN_SECONDS)
            .await
        {
            warn!("Failed to set spike cooldowns: {e}");
        }
    }
}

fn get_bucket_timestamps() -> Vec<String> {
    let now = Utc::now();
    (0..NUM_BUCKETS)
        .map(|i| {
            let offset = Duration::minutes(ISSUE_BUCKET_INTERVAL_MINUTES * i as i64);
            get_rounded_to_minutes(now - offset, ISSUE_BUCKET_INTERVAL_MINUTES)
        })
        .collect()
}

fn compute_team_baseline(exception_values: &[Option<i64>], issue_counts: &[u64]) -> f64 {
    let bucket_rates: Vec<f64> = exception_values
        .iter()
        .zip(issue_counts.iter())
        .filter_map(|(exceptions_opt, &issue_count)| {
            let exceptions = (*exceptions_opt)?;
            if issue_count > 0 {
                Some(exceptions as f64 / issue_count as f64)
            } else {
                None
            }
        })
        .collect();

    if !bucket_rates.is_empty() {
        bucket_rates.iter().sum::<f64>() / bucket_rates.len() as f64
    } else {
        0.0
    }
}

fn compute_issue_baseline(historical_buckets: &[Option<i64>], team_baseline: f64) -> f64 {
    let non_empty_count = historical_buckets.iter().filter(|v| v.is_some()).count();

    if non_empty_count >= MIN_HISTORICAL_BUCKETS_FOR_ISSUE_BASELINE {
        let sum: i64 = historical_buckets.iter().filter_map(|v| *v).sum();
        sum as f64 / non_empty_count as f64
    } else {
        team_baseline
    }
}

fn is_spiking(current_value: i64, baseline: f64) -> bool {
    if baseline == 0.0 {
        current_value > 0
    } else {
        current_value as f64 > baseline * SPIKE_MULTIPLIER
    }
}

async fn get_spiking_issues(
    redis: &(dyn Client + Send + Sync),
    issue_team_ids: &HashMap<Uuid, i32>,
    issue_ids: Vec<Uuid>,
) -> Result<Vec<SpikingIssue>, common_redis::CustomRedisError> {
    if issue_ids.is_empty() {
        return Ok(vec![]);
    }

    let bucket_timestamps = get_bucket_timestamps();
    let unique_team_ids: Vec<i32> = issue_team_ids
        .values()
        .copied()
        .collect::<std::collections::HashSet<_>>()
        .into_iter()
        .collect();

    let (issue_values, team_values, team_issue_counts) =
        fetch_bucket_data(redis, &issue_ids, &unique_team_ids, &bucket_timestamps).await?;

    let team_baselines = compute_team_baselines(&unique_team_ids, &team_values, &team_issue_counts);

    let spiking = issue_ids
        .iter()
        .enumerate()
        .filter_map(|(issue_idx, issue_id)| {
            let team_id = *issue_team_ids.get(issue_id)?;
            let start_idx = issue_idx * NUM_BUCKETS;
            let buckets = &issue_values[start_idx..start_idx + NUM_BUCKETS];

            let current_value = buckets[0].unwrap_or(0);
            let historical = &buckets[1..];
            let team_baseline = *team_baselines.get(&team_id).unwrap_or(&0.0);
            let baseline = compute_issue_baseline(historical, team_baseline);

            if is_spiking(current_value, baseline) {
                Some(SpikingIssue {
                    issue_id: *issue_id,
                    team_id,
                    computed_baseline: baseline,
                    current_bucket_value: current_value,
                })
            } else {
                None
            }
        })
        .collect();

    Ok(spiking)
}

async fn fetch_bucket_data(
    redis: &(dyn Client + Send + Sync),
    issue_ids: &[Uuid],
    team_ids: &[i32],
    timestamps: &[String],
) -> Result<(Vec<Option<i64>>, Vec<Option<i64>>, Vec<u64>), common_redis::CustomRedisError> {
    let issue_keys: Vec<String> = issue_ids
        .iter()
        .flat_map(|id| timestamps.iter().map(move |ts| issue_bucket_key(id, ts)))
        .collect();

    let team_bucket_keys: Vec<String> = team_ids
        .iter()
        .flat_map(|id| timestamps.iter().map(move |ts| team_bucket_key(*id, ts)))
        .collect();

    let team_issue_set_keys: Vec<String> = team_ids
        .iter()
        .flat_map(|id| timestamps.iter().map(move |ts| team_issue_set_key(*id, ts)))
        .collect();

    let all_keys: Vec<String> = issue_keys.into_iter().chain(team_bucket_keys).collect();
    let all_values = redis.mget(all_keys).await?;
    let team_issue_counts = redis.scard_multiple(team_issue_set_keys).await?;

    let all_values: Vec<Option<i64>> = all_values
        .into_iter()
        .map(|opt| opt.and_then(|bytes| std::str::from_utf8(&bytes).ok()?.parse().ok()))
        .collect();

    let issue_values = all_values[..issue_ids.len() * NUM_BUCKETS].to_vec();
    let team_values = all_values[issue_ids.len() * NUM_BUCKETS..].to_vec();

    Ok((issue_values, team_values, team_issue_counts))
}

fn compute_team_baselines(
    team_ids: &[i32],
    team_values: &[Option<i64>],
    team_issue_counts: &[u64],
) -> HashMap<i32, f64> {
    team_ids
        .iter()
        .enumerate()
        .map(|(idx, team_id)| {
            let start = idx * NUM_BUCKETS;
            let exceptions = &team_values[start..start + NUM_BUCKETS];
            let issues = &team_issue_counts[start..start + NUM_BUCKETS];
            (*team_id, compute_team_baseline(exceptions, issues))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use common_redis::MockRedisClient;

    fn bytes(v: i64) -> Vec<u8> {
        v.to_string().into_bytes()
    }

    struct TestContext {
        redis: MockRedisClient,
        issue_id: Uuid,
        team_id: i32,
    }

    impl TestContext {
        fn new() -> Self {
            Self {
                redis: MockRedisClient::new(),
                issue_id: Uuid::new_v4(),
                team_id: 1,
            }
        }

        fn setup_issue_buckets(&mut self, values: &[Option<i64>]) {
            let now = Utc::now();
            for (i, value) in values.iter().enumerate() {
                let offset = Duration::minutes(ISSUE_BUCKET_INTERVAL_MINUTES * i as i64);
                let ts = get_rounded_to_minutes(now - offset, ISSUE_BUCKET_INTERVAL_MINUTES);
                let key = issue_bucket_key(&self.issue_id, &ts);
                self.redis
                    .mget_ret(&key, value.map(|v| v.to_string().into_bytes()));
            }
            for i in values.len()..NUM_BUCKETS {
                let offset = Duration::minutes(ISSUE_BUCKET_INTERVAL_MINUTES * i as i64);
                let ts = get_rounded_to_minutes(now - offset, ISSUE_BUCKET_INTERVAL_MINUTES);
                let key = issue_bucket_key(&self.issue_id, &ts);
                self.redis.mget_ret(&key, None);
            }
        }

        fn setup_team_buckets(&mut self, values: &[Option<i64>], issue_counts: &[u64]) {
            let now = Utc::now();
            for (i, value) in values.iter().enumerate() {
                let offset = Duration::minutes(ISSUE_BUCKET_INTERVAL_MINUTES * i as i64);
                let ts = get_rounded_to_minutes(now - offset, ISSUE_BUCKET_INTERVAL_MINUTES);

                let bucket_key = team_bucket_key(self.team_id, &ts);
                self.redis
                    .mget_ret(&bucket_key, value.map(|v| v.to_string().into_bytes()));

                let issue_count = issue_counts.get(i).copied().unwrap_or(0);
                let issue_set_key = team_issue_set_key(self.team_id, &ts);
                self.redis.scard_ret(&issue_set_key, Ok(issue_count));
            }
            for i in values.len()..NUM_BUCKETS {
                let offset = Duration::minutes(ISSUE_BUCKET_INTERVAL_MINUTES * i as i64);
                let ts = get_rounded_to_minutes(now - offset, ISSUE_BUCKET_INTERVAL_MINUTES);

                let bucket_key = team_bucket_key(self.team_id, &ts);
                self.redis.mget_ret(&bucket_key, None);

                let issue_set_key = team_issue_set_key(self.team_id, &ts);
                self.redis.scard_ret(&issue_set_key, Ok(0));
            }
        }

        fn issue_team_ids(&self) -> HashMap<Uuid, i32> {
            HashMap::from([(self.issue_id, self.team_id)])
        }

        async fn get_spiking(&self) -> Vec<SpikingIssue> {
            get_spiking_issues(&self.redis, &self.issue_team_ids(), vec![self.issue_id])
                .await
                .unwrap()
        }
    }

    #[test]
    fn test_get_rounded_to_minutes_floor_rounding() {
        let dt = Utc.with_ymd_and_hms(2025, 12, 16, 12, 34, 56).unwrap();
        assert_eq!(
            get_rounded_to_minutes(dt, 5),
            "2025-12-16T12:30:00Z".to_string()
        );
    }

    #[test]
    fn test_get_rounded_to_minutes_exact_boundary() {
        let dt = Utc.with_ymd_and_hms(2025, 12, 16, 12, 35, 0).unwrap();
        assert_eq!(
            get_rounded_to_minutes(dt, 5),
            "2025-12-16T12:35:00Z".to_string()
        );
    }

    #[test]
    fn test_get_rounded_to_minutes_12() {
        let dt = Utc.with_ymd_and_hms(2025, 12, 16, 12, 34, 56).unwrap();
        assert_eq!(
            get_rounded_to_minutes(dt, 12),
            "2025-12-16T12:24:00Z".to_string()
        );
    }

    // ISSUE BUCKETS (most recent first): 100, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1
    // TEAM BUCKETS (most recent first):  10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10
    // Issue baseline = 11/11 = 1 (excludes current bucket), current = 100, spike threshold = 10, so SPIKING
    #[tokio::test]
    async fn test_full_history_spike() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[
            Some(100),
            Some(1),
            Some(1),
            Some(1),
            Some(1),
            Some(1),
            Some(1),
            Some(1),
            Some(1),
            Some(1),
            Some(1),
            Some(1),
        ]);
        ctx.setup_team_buckets(
            &[
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
            ],
            &[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        );

        let result = ctx.get_spiking().await;

        assert_eq!(result.len(), 1);
        assert_eq!(result[0].computed_baseline, 1.0);
        assert_eq!(result[0].current_bucket_value, 100);
    }

    // ISSUE BUCKETS (most recent first): 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10
    // TEAM BUCKETS (most recent first):  100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100
    // Issue baseline = 110/11 = 10 (excludes current bucket), current = 10, spike threshold = 100, so NOT SPIKING
    #[tokio::test]
    async fn test_full_history_no_spike() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[
            Some(10),
            Some(10),
            Some(10),
            Some(10),
            Some(10),
            Some(10),
            Some(10),
            Some(10),
            Some(10),
            Some(10),
            Some(10),
            Some(10),
        ]);
        ctx.setup_team_buckets(
            &[
                Some(100),
                Some(100),
                Some(100),
                Some(100),
                Some(100),
                Some(100),
                Some(100),
                Some(100),
                Some(100),
                Some(100),
                Some(100),
                Some(100),
            ],
            &[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        );

        let result = ctx.get_spiking().await;

        assert!(result.is_empty());
    }

    // ISSUE BUCKETS (most recent first): 150, 1
    // TEAM BUCKETS (most recent first):  10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10
    // 1 historical bucket - uses issue baseline = 1/1 = 1
    // Current = 150, spike threshold = 10, so SPIKING
    #[tokio::test]
    async fn test_two_buckets_spike() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[Some(150), Some(1)]);
        ctx.setup_team_buckets(
            &[
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
            ],
            &[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        );

        let result = ctx.get_spiking().await;

        assert_eq!(result.len(), 1);
        assert_eq!(result[0].computed_baseline, 1.0);
        assert_eq!(result[0].current_bucket_value, 150);
    }

    // ISSUE BUCKETS (most recent first): 50, 10
    // TEAM BUCKETS (most recent first):  10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10
    // 1 historical bucket - uses issue baseline = 10/1 = 10
    // Current = 50, spike threshold = 100, so NOT SPIKING
    #[tokio::test]
    async fn test_two_buckets_no_spike() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[Some(50), Some(10)]);
        ctx.setup_team_buckets(
            &[
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
            ],
            &[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        );

        let result = ctx.get_spiking().await;

        assert!(result.is_empty());
    }

    // ISSUE BUCKETS (most recent first): 150
    // TEAM BUCKETS (most recent first):  10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10 (1 unique issue each)
    // 0 historical buckets -> falls back to team baseline = 120 exceptions / 12 unique issues = 10
    // Current = 150, spike threshold = 100, so SPIKING
    #[tokio::test]
    async fn test_one_bucket_spike_team_based() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[Some(150)]);
        ctx.setup_team_buckets(
            &[
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
            ],
            &[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        );

        let result = ctx.get_spiking().await;

        assert_eq!(result.len(), 1);
        assert_eq!(result[0].computed_baseline, 10.0);
        assert_eq!(result[0].current_bucket_value, 150);
    }

    // ISSUE BUCKETS (most recent first): 50
    // TEAM BUCKETS (most recent first):  10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10 (1 unique issue each)
    // 0 historical buckets - falls back to team baseline = 120 exceptions / 12 unique issues = 10
    // Current = 50, spike threshold = 100, so NOT SPIKING
    #[tokio::test]
    async fn test_one_bucket_no_spike_team_based() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[Some(50)]);
        ctx.setup_team_buckets(
            &[
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
            ],
            &[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        );

        let result = ctx.get_spiking().await;

        assert!(result.is_empty());
    }

    // ISSUE BUCKETS (most recent first): (none)
    // TEAM BUCKETS (most recent first):  10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10
    // No issue buckets, so NOT SPIKING
    #[tokio::test]
    async fn test_no_buckets_no_spike() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[]);
        ctx.setup_team_buckets(
            &[
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
                Some(10),
            ],
            &[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        );

        let result = ctx.get_spiking().await;

        assert!(result.is_empty());
    }

    // ISSUE BUCKETS (most recent first): 100
    // TEAM BUCKETS (most recent first):  20, 15, 12, 8 (unique issues: 2, 3, 4, 2)
    // Per-bucket rates: 20/2=10, 15/3=5, 12/4=3, 8/2=4
    // Team baseline = average(10, 5, 3, 4) = 22/4 = 5.5
    // Current = 100, spike threshold = 55, so SPIKING
    #[tokio::test]
    async fn test_team_baseline_average_of_rates() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[Some(100)]);
        ctx.setup_team_buckets(&[Some(20), Some(15), Some(12), Some(8)], &[2, 3, 4, 2]);

        let result = ctx.get_spiking().await;

        assert_eq!(result.len(), 1);
        assert_eq!(result[0].computed_baseline, 5.5);
    }

    // Multi-team, multi-issue stress test
    // Team 1: buckets [10, 20, 30] with issue counts [2, 4, 6] -> rates [5, 5, 5] -> baseline = 5
    // Team 2: buckets [40, 60] with issue counts [2, 3] -> rates [20, 20] -> baseline = 20
    //
    // Issue A (team 1): no history -> team baseline 5, current=60 -> spikes (60 > 50)
    // Issue B (team 1): history [2, 2] -> own baseline 2, current=30 -> spikes (30 > 20)
    // Issue C (team 2): no history -> team baseline 20, current=100 -> NOT spiking (100 < 200)
    // Issue D (team 2): history [10] -> own baseline 10, current=50 -> NOT spiking (50 < 100)
    // Issue E (team 2): no history -> team baseline 20, current=300 -> spikes (300 > 200)
    #[tokio::test]
    async fn test_multi_team_multi_issue() {
        let mut redis = MockRedisClient::new();

        let team_1 = 100;
        let team_2 = 200;

        let issue_a = Uuid::new_v4(); // team 1, no history, should spike
        let issue_b = Uuid::new_v4(); // team 1, has history, should spike
        let issue_c = Uuid::new_v4(); // team 2, no history, should NOT spike
        let issue_d = Uuid::new_v4(); // team 2, has history, should NOT spike
        let issue_e = Uuid::new_v4(); // team 2, no history, should spike

        let issue_team_ids = HashMap::from([
            (issue_a, team_1),
            (issue_b, team_1),
            (issue_c, team_2),
            (issue_d, team_2),
            (issue_e, team_2),
        ]);

        let now = Utc::now();
        let timestamps: Vec<String> = (0..NUM_BUCKETS)
            .map(|i| {
                let offset = Duration::minutes(ISSUE_BUCKET_INTERVAL_MINUTES * i as i64);
                get_rounded_to_minutes(now - offset, ISSUE_BUCKET_INTERVAL_MINUTES)
            })
            .collect();

        // Setup issue buckets
        // Issue A: current=60, no history
        redis.mget_ret(&issue_bucket_key(&issue_a, &timestamps[0]), Some(bytes(60)));
        for ts in &timestamps[1..] {
            redis.mget_ret(&issue_bucket_key(&issue_a, ts), None);
        }

        // Issue B: current=30, history=[2, 2]
        redis.mget_ret(&issue_bucket_key(&issue_b, &timestamps[0]), Some(bytes(30)));
        redis.mget_ret(&issue_bucket_key(&issue_b, &timestamps[1]), Some(bytes(2)));
        redis.mget_ret(&issue_bucket_key(&issue_b, &timestamps[2]), Some(bytes(2)));
        for ts in &timestamps[3..] {
            redis.mget_ret(&issue_bucket_key(&issue_b, ts), None);
        }

        // Issue C: current=100, no history
        redis.mget_ret(
            &issue_bucket_key(&issue_c, &timestamps[0]),
            Some(bytes(100)),
        );
        for ts in &timestamps[1..] {
            redis.mget_ret(&issue_bucket_key(&issue_c, ts), None);
        }

        // Issue D: current=50, history=[10]
        redis.mget_ret(&issue_bucket_key(&issue_d, &timestamps[0]), Some(bytes(50)));
        redis.mget_ret(&issue_bucket_key(&issue_d, &timestamps[1]), Some(bytes(10)));
        for ts in &timestamps[2..] {
            redis.mget_ret(&issue_bucket_key(&issue_d, ts), None);
        }

        // Issue E: current=300, no history
        redis.mget_ret(
            &issue_bucket_key(&issue_e, &timestamps[0]),
            Some(bytes(300)),
        );
        for ts in &timestamps[1..] {
            redis.mget_ret(&issue_bucket_key(&issue_e, ts), None);
        }

        // Setup team 1 buckets: [10, 20, 30, None...] with issue counts [2, 4, 6, 0...]
        // Rates: 10/2=5, 20/4=5, 30/6=5 -> average = 5
        redis.mget_ret(&team_bucket_key(team_1, &timestamps[0]), Some(bytes(10)));
        redis.mget_ret(&team_bucket_key(team_1, &timestamps[1]), Some(bytes(20)));
        redis.mget_ret(&team_bucket_key(team_1, &timestamps[2]), Some(bytes(30)));
        for ts in &timestamps[3..] {
            redis.mget_ret(&team_bucket_key(team_1, ts), None);
        }
        redis.scard_ret(&team_issue_set_key(team_1, &timestamps[0]), Ok(2));
        redis.scard_ret(&team_issue_set_key(team_1, &timestamps[1]), Ok(4));
        redis.scard_ret(&team_issue_set_key(team_1, &timestamps[2]), Ok(6));
        for ts in &timestamps[3..] {
            redis.scard_ret(&team_issue_set_key(team_1, ts), Ok(0));
        }

        // Setup team 2 buckets: [40, 60, None...] with issue counts [2, 3, 0...]
        // Rates: 40/2=20, 60/3=20 -> average = 20
        redis.mget_ret(&team_bucket_key(team_2, &timestamps[0]), Some(bytes(40)));
        redis.mget_ret(&team_bucket_key(team_2, &timestamps[1]), Some(bytes(60)));
        for ts in &timestamps[2..] {
            redis.mget_ret(&team_bucket_key(team_2, ts), None);
        }
        redis.scard_ret(&team_issue_set_key(team_2, &timestamps[0]), Ok(2));
        redis.scard_ret(&team_issue_set_key(team_2, &timestamps[1]), Ok(3));
        for ts in &timestamps[2..] {
            redis.scard_ret(&team_issue_set_key(team_2, ts), Ok(0));
        }

        let result = get_spiking_issues(
            &redis,
            &issue_team_ids,
            vec![issue_a, issue_b, issue_c, issue_d, issue_e],
        )
        .await
        .unwrap();

        // Should have 3 spiking issues: A, B, E
        assert_eq!(result.len(), 3);

        let result_map: HashMap<Uuid, &SpikingIssue> =
            result.iter().map(|s| (s.issue_id, s)).collect();

        // Issue A: team baseline 5, current 60
        let spike_a = result_map.get(&issue_a).expect("Issue A should spike");
        assert_eq!(spike_a.team_id, team_1);
        assert_eq!(spike_a.computed_baseline, 5.0);
        assert_eq!(spike_a.current_bucket_value, 60);

        // Issue B: own baseline 2 (from history [2,2]), current 30
        let spike_b = result_map.get(&issue_b).expect("Issue B should spike");
        assert_eq!(spike_b.team_id, team_1);
        assert_eq!(spike_b.computed_baseline, 2.0);
        assert_eq!(spike_b.current_bucket_value, 30);

        // Issue C should NOT be in results (100 < 20*10=200)
        assert!(!result_map.contains_key(&issue_c));

        // Issue D should NOT be in results (50 < 10*10=100)
        assert!(!result_map.contains_key(&issue_d));

        // Issue E: team baseline 20, current 300
        let spike_e = result_map.get(&issue_e).expect("Issue E should spike");
        assert_eq!(spike_e.team_id, team_2);
        assert_eq!(spike_e.computed_baseline, 20.0);
        assert_eq!(spike_e.current_bucket_value, 300);
    }
}
