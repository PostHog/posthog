use common_redis::{CustomRedisError, ScriptRunner};
use sha2::{Digest, Sha256};
use uuid::Uuid;

const DAY_SECONDS: i64 = 86_400;
const HISTORY_DAYS: usize = 14;
const COUNTS_LUA: &str = r#"
local count = redis.call('incrby', KEYS[1], tonumber(ARGV[1]))
redis.call('expire', KEYS[1], 1296060)
local result = {count}
for i = 2, #KEYS do
  result[#result + 1] = tonumber(redis.call('get', KEYS[i]) or '0')
end
return result
"#;

#[derive(Debug, Clone, Copy)]
pub struct ProjectRule {
    pub multiplier: f64,
    pub floor: u64,
    pub keep_percent: u8,
}

impl Default for ProjectRule {
    fn default() -> Self {
        Self {
            multiplier: 3.0,
            floor: 500,
            keep_percent: 10,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ProjectDecision {
    pub sampled: bool,
    pub baseline: f64,
    pub allowance: u64,
    pub count: u64,
    pub cap_started: bool,
}

impl ProjectRule {
    pub async fn evaluate_batch(
        &self,
        redis: &dyn ScriptRunner,
        team_id: i32,
        day_start: i64,
        uuids: &[Uuid],
    ) -> Result<Vec<ProjectDecision>, CustomRedisError> {
        if uuids.is_empty() {
            return Ok(Vec::new());
        }
        let keys = (0..=HISTORY_DAYS)
            .map(|offset| {
                let day = day_start - offset as i64 * DAY_SECONDS;
                format!("adaptive-ingestion:v1:{{{team_id}}}:project:{day}")
            })
            .collect();
        let counts = redis
            .eval_int_vec(COUNTS_LUA, keys, vec![uuids.len().to_string()])
            .await?;
        if counts.len() != HISTORY_DAYS + 1
            || counts.iter().any(|count| *count < 0)
            || counts[0] < uuids.len() as i64
        {
            return Err(CustomRedisError::ParseError(
                "invalid adaptive project count".into(),
            ));
        }
        let mut history: Vec<u64> = counts[1..].iter().map(|count| *count as u64).collect();
        history.sort_unstable();
        let median =
            (history[HISTORY_DAYS / 2 - 1] as f64 + history[HISTORY_DAYS / 2] as f64) / 2.0;
        let baseline = median.max(self.floor as f64);
        let allowance = (self.multiplier * baseline) as u64;
        let batch_start = counts[0] as u64 - uuids.len() as u64;
        Ok(uuids
            .iter()
            .enumerate()
            .map(|(index, uuid)| {
                let count = batch_start + index as u64 + 1;
                ProjectDecision {
                    sampled: count > allowance && !keep_by_hash(team_id, *uuid, self.keep_percent),
                    baseline,
                    allowance,
                    count,
                    cap_started: allowance.checked_add(1) == Some(count),
                }
            })
            .collect())
    }
}

fn keep_by_hash(team_id: i32, uuid: Uuid, percent: u8) -> bool {
    let mut hasher = Sha256::new();
    hasher.update(b"adaptive-ingestion:project:v1");
    hasher.update(team_id.to_be_bytes());
    hasher.update(uuid.as_bytes());
    let hash = hasher.finalize();
    u64::from_be_bytes(hash[0..8].try_into().expect("sha256 has 32 bytes")) % 100 < percent as u64
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::{start_redis, FakeRunner};

    #[tokio::test]
    async fn daily_cap_uses_median_history_and_stable_sampling() {
        let ids = [Uuid::now_v7(), Uuid::now_v7(), Uuid::now_v7()];
        let counts = vec![153, 10, 10, 10, 10, 10, 10, 50, 50, 50, 50, 50, 50, 50, 50];
        let rule = ProjectRule {
            multiplier: 3.0,
            floor: 1,
            keep_percent: 0,
        };
        let first = rule
            .evaluate_batch(&*FakeRunner::returning(counts.clone()), 7, 0, &ids)
            .await
            .unwrap();
        let second = rule
            .evaluate_batch(&*FakeRunner::returning(counts), 7, 0, &ids)
            .await
            .unwrap();
        assert_eq!(first, second);
        assert_eq!(first[0].baseline, 50.0);
        assert_eq!(first[0].allowance, 150);
        assert_eq!(first[0].count, 151);
        assert!(first[0].cap_started);
        assert!(!first[1].cap_started);
        assert!(first.iter().all(|decision| decision.sampled));
        let cold_start = ProjectRule {
            keep_percent: 0,
            ..ProjectRule::default()
        }
        .evaluate_batch(
            &*FakeRunner::returning(
                std::iter::once(1501)
                    .chain(std::iter::repeat_n(0, HISTORY_DAYS))
                    .collect(),
            ),
            7,
            0,
            &ids,
        )
        .await
        .unwrap();
        assert_eq!(cold_start[0].baseline, 500.0);
        assert_eq!(cold_start[0].allowance, 1500);
        assert!(cold_start[2].sampled);
        assert!(rule
            .evaluate_batch(&*FakeRunner::returning(vec![]), 7, 0, &[])
            .await
            .unwrap()
            .is_empty());
    }

    #[test]
    fn sample_hash_is_stable_for_the_same_event() {
        let uuid = Uuid::from_u128(1);
        assert!(!keep_by_hash(7, uuid, 1));
        assert!(keep_by_hash(7, uuid, 10));
    }

    #[tokio::test]
    #[ignore = "requires Docker for Redis container"]
    async fn project_counts_reset_on_utc_day_boundaries() {
        let (redis, _container) = start_redis().await;
        let rule = ProjectRule {
            multiplier: 3.0,
            floor: 1,
            keep_percent: 0,
        };
        let ids = [
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
            Uuid::now_v7(),
        ];
        let first = rule.evaluate_batch(&*redis, 7, 0, &ids).await.unwrap();
        assert_eq!(
            first
                .iter()
                .map(|decision| decision.sampled)
                .collect::<Vec<_>>(),
            vec![false, false, false, true]
        );
        let next_day = rule
            .evaluate_batch(&*redis, 7, DAY_SECONDS, &ids)
            .await
            .unwrap();
        assert_eq!(next_day[0].count, 1);
        assert_eq!(next_day[0].baseline, 1.0);
    }
}
