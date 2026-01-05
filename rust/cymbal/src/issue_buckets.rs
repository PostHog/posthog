use chrono::{DateTime, SecondsFormat, Utc};
use common_redis::Client;
use std::collections::HashMap;
use tracing::warn;
use uuid::Uuid;

const ISSUE_BUCKET_TTL_SECONDS: usize = 60 * 60;
const ISSUE_BUCKET_INTERVAL_MINUTES: i64 = 5;

fn round_datetime_to_minutes(datetime: DateTime<Utc>, minutes: i64) -> DateTime<Utc> {
    assert!(minutes > 0, "minutes must be > 0");
    let bucket_seconds = minutes * 60;
    let now_ts = datetime.timestamp();
    let rounded_ts = now_ts - now_ts.rem_euclid(bucket_seconds);
    DateTime::<Utc>::from_timestamp(rounded_ts, 0).expect("rounded timestamp is always valid")
}

pub(crate) fn get_rounded_to_minutes(datetime: DateTime<Utc>, minutes: i64) -> String {
    round_datetime_to_minutes(datetime, minutes).to_rfc3339_opts(SecondsFormat::Secs, true)
}

pub fn get_now_rounded_to_minutes(minutes: i64) -> String {
    get_rounded_to_minutes(Utc::now(), minutes)
}

pub(crate) async fn try_increment_issue_buckets(
    redis: &(dyn Client + Send + Sync),
    issue_counts: HashMap<Uuid, u32>,
) {
    if issue_counts.is_empty() {
        return;
    }

    let now_rounded_to_minutes = get_now_rounded_to_minutes(ISSUE_BUCKET_INTERVAL_MINUTES);
    let items: Vec<(String, i64)> = issue_counts
        .into_iter()
        .map(|(issue_id, count)| {
            (
                format!("issue-buckets:{issue_id}-{now_rounded_to_minutes}"),
                count as i64,
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

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

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
}
