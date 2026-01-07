use std::sync::Arc;

use chrono::{DateTime, Duration, SecondsFormat, Utc};
use common_kafka::kafka_messages::internal_events::{InternalEvent, InternalEventEvent};
use common_kafka::kafka_producer::send_iter_to_kafka;
use common_redis::Client;
use std::collections::HashMap;
use tracing::warn;
use uuid::Uuid;

use crate::app_context::AppContext;
use crate::issue_resolution::Issue;

const ISSUE_BUCKET_TTL_SECONDS: usize = 60 * 60;
const ISSUE_BUCKET_INTERVAL_MINUTES: i64 = 5;
const SPIKE_MULTIPLIER: f64 = 10.0;
const NUM_BUCKETS: usize = 12;
const SPIKE_ALERT_COOLDOWN_SECONDS: usize = 10 * 60;

const ISSUE_SPIKING_EVENT: &str = "$error_tracking_issue_spiking";
const MIN_HISTORICAL_BUCKETS_FOR_ISSUE_BASELINE: usize = 1;
const MIN_SPIKE_THRESHOLD: i64 = 500;

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
    pub name: Option<String>,
    pub description: Option<String>,
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
    issues_by_id: &HashMap<Uuid, Issue>,
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
                if let Some(issue) = issues_by_id.get(issue_id) {
                    *acc.entry(issue.team_id).or_insert(0) += count;
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
            let issue = issues_by_id.get(issue_id)?;
            Some((
                team_issue_set_key(issue.team_id, &now_rounded_to_minutes),
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
    issues_by_id: HashMap<Uuid, Issue>,
    issue_counts: HashMap<Uuid, u32>,
) {
    if issue_counts.is_empty() {
        return;
    }

    try_increment_issue_buckets(&*context.issue_buckets_redis_client, &issue_counts).await;
    try_increment_team_buckets(
        &*context.issue_buckets_redis_client,
        &issues_by_id,
        &issue_counts,
    )
    .await;

    let issue_ids: Vec<Uuid> = issue_counts.keys().copied().collect();
    match get_spiking_issues(
        &*context.issue_buckets_redis_client,
        &issues_by_id,
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

    let cooldown_items: Vec<(String, String)> = spiking
        .iter()
        .map(|s| (cooldown_key(&s.issue_id), "1".to_string()))
        .collect();
    let lock_results = match context
        .issue_buckets_redis_client
        .batch_set_nx_ex(cooldown_items, SPIKE_ALERT_COOLDOWN_SECONDS)
        .await
    {
        Ok(results) => results,
        Err(e) => {
            warn!("Failed to acquire spike cooldown locks: {e}");
            return;
        }
    };

    let acquired_locks: Vec<SpikingIssue> = spiking
        .into_iter()
        .zip(lock_results)
        .filter_map(|(spike, acquired)| if acquired { Some(spike) } else { None })
        .collect();

    if acquired_locks.is_empty() {
        return;
    }

    let events: Vec<(Uuid, InternalEvent)> = acquired_locks
        .iter()
        .filter_map(|spike| {
            let mut event =
                InternalEventEvent::new(ISSUE_SPIKING_EVENT, spike.issue_id, Utc::now(), None);
            event.insert_prop("name", spike.name.clone()).ok()?;
            event
                .insert_prop("description", spike.description.clone())
                .ok()?;
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

    let failed_keys: Vec<String> = results
        .into_iter()
        .enumerate()
        .filter_map(|(i, result)| {
            if let Err(e) = result {
                warn!("Failed to emit spiking event: {e}");
                Some(cooldown_key(&events[i].0))
            } else {
                None
            }
        })
        .collect();

    if !failed_keys.is_empty() {
        if let Err(e) = context
            .issue_buckets_redis_client
            .batch_del(failed_keys)
            .await
        {
            warn!("Failed to release cooldown locks after Kafka failure: {e}");
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
    if current_value < MIN_SPIKE_THRESHOLD {
        return false;
    }
    current_value as f64 > baseline * SPIKE_MULTIPLIER
}

async fn get_spiking_issues(
    redis: &(dyn Client + Send + Sync),
    issues_by_id: &HashMap<Uuid, Issue>,
    issue_ids: Vec<Uuid>,
) -> Result<Vec<SpikingIssue>, common_redis::CustomRedisError> {
    if issue_ids.is_empty() {
        return Ok(vec![]);
    }

    let bucket_timestamps = get_bucket_timestamps();
    let unique_team_ids: Vec<i32> = issues_by_id
        .values()
        .map(|i| i.team_id)
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
            let issue = issues_by_id.get(issue_id)?;
            let start_idx = issue_idx * NUM_BUCKETS;
            let buckets = &issue_values[start_idx..start_idx + NUM_BUCKETS];

            let current_value = buckets[0].unwrap_or(0);
            let historical = &buckets[1..];
            let team_baseline = *team_baselines.get(&issue.team_id).unwrap_or(&0.0);
            let baseline = compute_issue_baseline(historical, team_baseline);

            if is_spiking(current_value, baseline) {
                Some(SpikingIssue {
                    issue_id: *issue_id,
                    team_id: issue.team_id,
                    name: issue.name.clone(),
                    description: issue.description.clone(),
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

        fn issues_by_id(&self) -> HashMap<Uuid, Issue> {
            HashMap::from([(self.issue_id, self.make_issue())])
        }

        fn make_issue(&self) -> Issue {
            Issue {
                id: self.issue_id,
                team_id: self.team_id,
                status: crate::issue_resolution::IssueStatus::Active,
                name: Some("Test Issue".to_string()),
                description: Some("Test Description".to_string()),
                created_at: Utc::now(),
            }
        }

        async fn get_spiking(&self) -> Vec<SpikingIssue> {
            get_spiking_issues(&self.redis, &self.issues_by_id(), vec![self.issue_id])
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

    // ISSUE BUCKETS (most recent first): 500, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10
    // TEAM BUCKETS (most recent first):  100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100
    // Issue baseline = 110/11 = 10 (excludes current bucket), current = 500, spike threshold = 100, so SPIKING
    #[tokio::test]
    async fn test_full_history_spike() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[
            Some(500),
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

        assert_eq!(result.len(), 1);
        assert_eq!(result[0].computed_baseline, 10.0);
        assert_eq!(result[0].current_bucket_value, 500);
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

    // ISSUE BUCKETS (most recent first): 600, 10
    // TEAM BUCKETS (most recent first):  100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100
    // 1 historical bucket - uses issue baseline = 10/1 = 10
    // Current = 600, spike threshold = 100, so SPIKING
    #[tokio::test]
    async fn test_two_buckets_spike() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[Some(600), Some(10)]);
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

        assert_eq!(result.len(), 1);
        assert_eq!(result[0].computed_baseline, 10.0);
        assert_eq!(result[0].current_bucket_value, 600);
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

    // ISSUE BUCKETS (most recent first): 550
    // TEAM BUCKETS (most recent first):  10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10 (1 unique issue each)
    // 0 historical buckets -> falls back to team baseline = 120 exceptions / 12 unique issues = 10
    // Current = 550, spike threshold = 100, so SPIKING
    #[tokio::test]
    async fn test_one_bucket_spike_team_based() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[Some(550)]);
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
        assert_eq!(result[0].current_bucket_value, 550);
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

    // ISSUE BUCKETS (most recent first): 600
    // TEAM BUCKETS (most recent first):  20, 15, 12, 8 (unique issues: 2, 3, 4, 2)
    // Per-bucket rates: 20/2=10, 15/3=5, 12/4=3, 8/2=4
    // Team baseline = average(10, 5, 3, 4) = 22/4 = 5.5
    // Current = 600, spike threshold = 55, so SPIKING
    #[tokio::test]
    async fn test_team_baseline_average_of_rates() {
        let mut ctx = TestContext::new();
        ctx.setup_issue_buckets(&[Some(600)]);
        ctx.setup_team_buckets(&[Some(20), Some(15), Some(12), Some(8)], &[2, 3, 4, 2]);

        let result = ctx.get_spiking().await;

        assert_eq!(result.len(), 1);
        assert_eq!(result[0].computed_baseline, 5.5);
    }

    // Multi-team, multi-issue stress test
    // Team 1: buckets [100, 200, 300] with issue counts [2, 4, 6] -> rates [50, 50, 50] -> baseline = 50
    // Team 2: buckets [400, 600] with issue counts [2, 3] -> rates [200, 200] -> baseline = 200
    //
    // Issue A (team 1): no history -> team baseline 50, current=600 -> spikes (600 > 500)
    // Issue B (team 1): history [20, 20] -> own baseline 20, current=550 -> spikes (550 > 200)
    // Issue C (team 2): no history -> team baseline 200, current=600 -> NOT spiking (600 < 2000)
    // Issue D (team 2): history [100] -> own baseline 100, current=700 -> NOT spiking (700 < 1000)
    // Issue E (team 2): no history -> team baseline 200, current=2500 -> spikes (2500 > 2000)
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

        let make_issue = |id: Uuid, team_id: i32| Issue {
            id,
            team_id,
            status: crate::issue_resolution::IssueStatus::Active,
            name: Some("Test".to_string()),
            description: Some("Test".to_string()),
            created_at: Utc::now(),
        };

        let issues_by_id = HashMap::from([
            (issue_a, make_issue(issue_a, team_1)),
            (issue_b, make_issue(issue_b, team_1)),
            (issue_c, make_issue(issue_c, team_2)),
            (issue_d, make_issue(issue_d, team_2)),
            (issue_e, make_issue(issue_e, team_2)),
        ]);

        let now = Utc::now();
        let timestamps: Vec<String> = (0..NUM_BUCKETS)
            .map(|i| {
                let offset = Duration::minutes(ISSUE_BUCKET_INTERVAL_MINUTES * i as i64);
                get_rounded_to_minutes(now - offset, ISSUE_BUCKET_INTERVAL_MINUTES)
            })
            .collect();

        // Setup issue buckets
        // Issue A: current=600, no history
        redis.mget_ret(
            &issue_bucket_key(&issue_a, &timestamps[0]),
            Some(bytes(600)),
        );
        for ts in &timestamps[1..] {
            redis.mget_ret(&issue_bucket_key(&issue_a, ts), None);
        }

        // Issue B: current=550, history=[20, 20]
        redis.mget_ret(
            &issue_bucket_key(&issue_b, &timestamps[0]),
            Some(bytes(550)),
        );
        redis.mget_ret(&issue_bucket_key(&issue_b, &timestamps[1]), Some(bytes(20)));
        redis.mget_ret(&issue_bucket_key(&issue_b, &timestamps[2]), Some(bytes(20)));
        for ts in &timestamps[3..] {
            redis.mget_ret(&issue_bucket_key(&issue_b, ts), None);
        }

        // Issue C: current=600, no history (600 < 200*10=2000, not spiking)
        redis.mget_ret(
            &issue_bucket_key(&issue_c, &timestamps[0]),
            Some(bytes(600)),
        );
        for ts in &timestamps[1..] {
            redis.mget_ret(&issue_bucket_key(&issue_c, ts), None);
        }

        // Issue D: current=700, history=[100] (700 < 100*10=1000, not spiking)
        redis.mget_ret(
            &issue_bucket_key(&issue_d, &timestamps[0]),
            Some(bytes(700)),
        );
        redis.mget_ret(
            &issue_bucket_key(&issue_d, &timestamps[1]),
            Some(bytes(100)),
        );
        for ts in &timestamps[2..] {
            redis.mget_ret(&issue_bucket_key(&issue_d, ts), None);
        }

        // Issue E: current=2500, no history
        redis.mget_ret(
            &issue_bucket_key(&issue_e, &timestamps[0]),
            Some(bytes(2500)),
        );
        for ts in &timestamps[1..] {
            redis.mget_ret(&issue_bucket_key(&issue_e, ts), None);
        }

        // Setup team 1 buckets: [100, 200, 300, None...] with issue counts [2, 4, 6, 0...]
        // Rates: 100/2=50, 200/4=50, 300/6=50 -> average = 50
        redis.mget_ret(&team_bucket_key(team_1, &timestamps[0]), Some(bytes(100)));
        redis.mget_ret(&team_bucket_key(team_1, &timestamps[1]), Some(bytes(200)));
        redis.mget_ret(&team_bucket_key(team_1, &timestamps[2]), Some(bytes(300)));
        for ts in &timestamps[3..] {
            redis.mget_ret(&team_bucket_key(team_1, ts), None);
        }
        redis.scard_ret(&team_issue_set_key(team_1, &timestamps[0]), Ok(2));
        redis.scard_ret(&team_issue_set_key(team_1, &timestamps[1]), Ok(4));
        redis.scard_ret(&team_issue_set_key(team_1, &timestamps[2]), Ok(6));
        for ts in &timestamps[3..] {
            redis.scard_ret(&team_issue_set_key(team_1, ts), Ok(0));
        }

        // Setup team 2 buckets: [400, 600, None...] with issue counts [2, 3, 0...]
        // Rates: 400/2=200, 600/3=200 -> average = 200
        redis.mget_ret(&team_bucket_key(team_2, &timestamps[0]), Some(bytes(400)));
        redis.mget_ret(&team_bucket_key(team_2, &timestamps[1]), Some(bytes(600)));
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
            &issues_by_id,
            vec![issue_a, issue_b, issue_c, issue_d, issue_e],
        )
        .await
        .unwrap();

        // Should have 3 spiking issues: A, B, E
        assert_eq!(result.len(), 3);

        let result_map: HashMap<Uuid, &SpikingIssue> =
            result.iter().map(|s| (s.issue_id, s)).collect();

        // Issue A: team baseline 50, current 600
        let spike_a = result_map.get(&issue_a).expect("Issue A should spike");
        assert_eq!(spike_a.team_id, team_1);
        assert_eq!(spike_a.computed_baseline, 50.0);
        assert_eq!(spike_a.current_bucket_value, 600);

        // Issue B: own baseline 20 (from history [20,20]), current 550
        let spike_b = result_map.get(&issue_b).expect("Issue B should spike");
        assert_eq!(spike_b.team_id, team_1);
        assert_eq!(spike_b.computed_baseline, 20.0);
        assert_eq!(spike_b.current_bucket_value, 550);

        // Issue C should NOT be in results (600 < 200*10=2000)
        assert!(!result_map.contains_key(&issue_c));

        // Issue D should NOT be in results (700 < 100*10=1000)
        assert!(!result_map.contains_key(&issue_d));

        // Issue E: team baseline 200, current 2500
        let spike_e = result_map.get(&issue_e).expect("Issue E should spike");
        assert_eq!(spike_e.team_id, team_2);
        assert_eq!(spike_e.computed_baseline, 200.0);
        assert_eq!(spike_e.current_bucket_value, 2500);
    }
}
