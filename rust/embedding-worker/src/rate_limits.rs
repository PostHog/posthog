use std::{collections::HashMap, sync::Arc, time::Duration};

use chrono::{DateTime, Utc};
use common_types::embedding::{ApiLimits, EmbeddingModel};
use metrics::{counter, gauge};
use reqwest::header::HeaderMap;
use tokio::{sync::Mutex, time::Instant};

use crate::metrics_utils::{LIMITS_UPDATED, LIMIT_BALANCE};

struct Bucket {
    per_minute: usize,
    capacity: f64,
    balance: f64,
}

impl Bucket {
    fn new(per_minute: usize, largest_request: usize) -> Self {
        Self {
            per_minute,
            capacity: (per_minute as f64 / 60.0).max(largest_request as f64),
            balance: 0.0,
        }
    }

    fn refill(&mut self, elapsed: Duration) {
        self.balance = (self.balance + elapsed.as_secs_f64() * self.per_minute as f64 / 60.0)
            .min(self.capacity);
    }

    fn wait_for(&self, amount: usize) -> Duration {
        Duration::from_secs_f64(
            (amount as f64 - self.balance).max(0.0) * 60.0 / self.per_minute as f64,
        )
    }

    fn observe(&mut self, limit: usize, remaining: Option<usize>, largest_request: usize) {
        self.per_minute = limit;
        self.capacity = (limit as f64 / 60.0).max(largest_request as f64);
        self.balance = self.balance.min(self.capacity);
        if let Some(remaining) = remaining {
            self.balance = self.balance.min(remaining as f64);
        }
    }
}

struct Budget {
    requests: Bucket,
    tokens: Bucket,
    updated_at: Instant,
    blocked_until: Instant,
}

impl Budget {
    fn new(limits: &ApiLimits, model: EmbeddingModel) -> Self {
        Self {
            requests: Bucket::new(limits.requests_per_minute, 1),
            tokens: Bucket::new(limits.tokens_per_minute, model.model_input_window()),
            updated_at: Instant::now(),
            blocked_until: Instant::now(),
        }
    }

    fn refill(&mut self, now: Instant) {
        let elapsed = now.saturating_duration_since(self.updated_at);
        self.requests.refill(elapsed);
        self.tokens.refill(elapsed);
        self.updated_at = now.max(self.updated_at);
    }

    fn defer(&mut self, delay: Duration) {
        let Some(until) = Instant::now().checked_add(delay) else {
            return;
        };
        self.blocked_until = self.blocked_until.max(until);
        self.requests.balance = 0.0;
        self.tokens.balance = 0.0;
        self.updated_at = self.blocked_until;
    }
}

pub struct RateLimits {
    local_limits: ApiLimits,
    budgets: Mutex<HashMap<&'static str, Arc<ModelBudget>>>,
}

struct ModelBudget {
    state: Mutex<Budget>,
    queue: Mutex<()>,
}

impl RateLimits {
    pub fn new(local_limits: ApiLimits) -> anyhow::Result<Self> {
        anyhow::ensure!(
            local_limits.requests_per_minute > 0 && local_limits.tokens_per_minute > 0,
            "Embedding rate limits must be positive"
        );
        Ok(Self {
            local_limits,
            budgets: Mutex::new(HashMap::new()),
        })
    }

    async fn budget(&self, model: EmbeddingModel) -> Arc<ModelBudget> {
        self.budgets
            .lock()
            .await
            .entry(model.limits_key())
            .or_insert_with(|| {
                Arc::new(ModelBudget {
                    state: Mutex::new(Budget::new(&self.local_limits, model)),
                    queue: Mutex::new(()),
                })
            })
            .clone()
    }

    pub async fn acquire(&self, model: EmbeddingModel, tokens: usize) {
        let budget = self.budget(model).await;
        let _turn = budget.queue.lock().await;
        loop {
            let delay = {
                let mut budget = budget.state.lock().await;
                let now = Instant::now();
                if now < budget.blocked_until {
                    budget.blocked_until - now
                } else {
                    budget.refill(now);
                    let delay = budget
                        .requests
                        .wait_for(1)
                        .max(budget.tokens.wait_for(tokens));
                    if delay.is_zero() {
                        budget.requests.balance -= 1.0;
                        budget.tokens.balance -= tokens as f64;
                        gauge!(LIMIT_BALANCE, "key" => model.limits_key(), "type" => "requests")
                            .set(budget.requests.balance);
                        gauge!(LIMIT_BALANCE, "key" => model.limits_key(), "type" => "tokens")
                            .set(budget.tokens.balance);
                        return;
                    }
                    delay
                }
            };
            tokio::time::sleep(delay).await;
        }
    }

    pub async fn observe(
        &self,
        model: EmbeddingModel,
        headers: &HeaderMap,
        throttle: Option<Duration>,
    ) {
        let budget = self.budget(model).await;
        let mut budget = budget.state.lock().await;
        budget.refill(Instant::now());

        let requests = header_number(headers, "x-ratelimit-limit-requests")
            .filter(|limit| *limit > 0)
            .unwrap_or(budget.requests.per_minute)
            .min(self.local_limits.requests_per_minute);
        let tokens = header_number(headers, "x-ratelimit-limit-tokens")
            .filter(|limit| *limit > 0)
            .unwrap_or(budget.tokens.per_minute)
            .min(self.local_limits.tokens_per_minute);
        if requests != budget.requests.per_minute || tokens != budget.tokens.per_minute {
            counter!(LIMITS_UPDATED, "key" => model.limits_key()).increment(1);
        }
        budget.requests.observe(
            requests,
            header_number(headers, "x-ratelimit-remaining-requests"),
            1,
        );
        budget.tokens.observe(
            tokens,
            header_number(headers, "x-ratelimit-remaining-tokens"),
            model.model_input_window(),
        );
        if let Some(delay) = throttle.or_else(|| exhausted_reset(headers)) {
            budget.defer(delay);
        }
    }
}

fn header<'a>(headers: &'a HeaderMap, key: &str) -> Option<&'a str> {
    headers.get(key)?.to_str().ok()
}

fn header_number(headers: &HeaderMap, key: &str) -> Option<usize> {
    header(headers, key)?.parse().ok()
}

fn seconds(value: &str) -> Option<Duration> {
    Duration::try_from_secs_f64(value.parse().ok()?)
        .ok()
        .filter(|duration| !duration.is_zero())
}

fn exhausted_reset(headers: &HeaderMap) -> Option<Duration> {
    [
        (
            "x-ratelimit-remaining-requests",
            "x-ratelimit-reset-requests",
        ),
        ("x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens"),
    ]
    .into_iter()
    .filter(|(remaining, _)| header_number(headers, remaining) == Some(0))
    .filter_map(|(_, reset)| humantime::parse_duration(header(headers, reset)?).ok())
    .max()
}

pub fn retry_after(headers: &HeaderMap) -> Option<Duration> {
    retry_after_at(headers, Utc::now())
}

fn retry_after_at(headers: &HeaderMap, now: DateTime<Utc>) -> Option<Duration> {
    let delay = header(headers, "retry-after-ms")
        .and_then(seconds)
        .map(|duration| duration.div_f64(1000.0))
        .or_else(|| {
            let value = header(headers, "retry-after")?;
            seconds(value).or_else(|| {
                DateTime::parse_from_rfc2822(value)
                    .ok()?
                    .signed_duration_since(now)
                    .to_std()
                    .ok()
            })
        })
        .or_else(|| exhausted_reset(headers));
    delay.filter(|delay| !delay.is_zero())
}

#[cfg(test)]
mod tests {
    use futures::poll;
    use reqwest::header::HeaderValue;

    use super::*;

    const MODEL: EmbeddingModel = EmbeddingModel::OpenAITextEmbeddingSmall;

    fn headers(values: &[(&'static str, &str)]) -> HeaderMap {
        values
            .iter()
            .map(|(key, value)| {
                (
                    reqwest::header::HeaderName::from_static(key),
                    HeaderValue::from_str(value).unwrap(),
                )
            })
            .collect()
    }

    fn limits() -> RateLimits {
        RateLimits::new(ApiLimits {
            requests_per_minute: 600,
            tokens_per_minute: 60_000,
        })
        .unwrap()
    }

    #[test]
    fn parses_retry_headers_and_only_uses_exhausted_resets() {
        let now = DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let cases = [
            (
                vec![("retry-after", "1.5")],
                Some(Duration::from_millis(1500)),
            ),
            (
                vec![("retry-after-ms", "250"), ("retry-after", "9")],
                Some(Duration::from_millis(250)),
            ),
            (
                vec![("retry-after", "Mon, 01 Jan 2024 00:00:05 GMT")],
                Some(Duration::from_secs(5)),
            ),
            (
                vec![
                    ("retry-after", "NaN"),
                    ("x-ratelimit-remaining-requests", "0"),
                    ("x-ratelimit-reset-requests", "1m2s"),
                ],
                Some(Duration::from_secs(62)),
            ),
            (
                vec![
                    ("x-ratelimit-remaining-requests", "0"),
                    ("x-ratelimit-reset-requests", "250ms"),
                    ("x-ratelimit-remaining-tokens", "8"),
                    ("x-ratelimit-reset-tokens", "1h"),
                ],
                Some(Duration::from_millis(250)),
            ),
            (
                vec![
                    ("x-ratelimit-remaining-requests", "0"),
                    ("x-ratelimit-reset-requests", "1s"),
                    ("x-ratelimit-remaining-tokens", "0"),
                    ("x-ratelimit-reset-tokens", "2.5s"),
                ],
                Some(Duration::from_millis(2500)),
            ),
            (vec![("retry-after", "-1")], None),
            (vec![("retry-after", "inf")], None),
            (vec![("x-ratelimit-reset-requests", "broken")], None),
        ];
        for (values, expected) in cases {
            assert_eq!(
                retry_after_at(&headers(&values), now),
                expected,
                "{values:?}"
            );
        }
    }

    #[tokio::test(start_paused = true)]
    async fn provider_ceiling_does_not_expand_local_rate_or_startup_burst() {
        let limits = limits();
        let start = Instant::now();
        limits.acquire(MODEL, 1).await;
        assert!(start.elapsed() >= Duration::from_millis(100));
        limits
            .observe(
                MODEL,
                &headers(&[
                    ("x-ratelimit-limit-requests", "6000"),
                    ("x-ratelimit-limit-tokens", "600000"),
                    ("x-ratelimit-remaining-requests", "6000"),
                ]),
                None,
            )
            .await;
        for _ in 0..9 {
            limits.acquire(MODEL, 1).await;
        }
        assert!(start.elapsed() >= Duration::from_secs(1));

        tokio::time::advance(Duration::from_secs(60)).await;
        for _ in 0..10 {
            limits.acquire(MODEL, 1).await;
        }
        let next = limits.acquire(MODEL, 1);
        tokio::pin!(next);
        assert!(poll!(&mut next).is_pending());
        tokio::time::timeout(Duration::from_millis(200), next)
            .await
            .unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn exhausted_headers_delay_queued_requests_without_blocking_updates() {
        for (remaining, reset) in [
            (
                "x-ratelimit-remaining-requests",
                "x-ratelimit-reset-requests",
            ),
            ("x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens"),
        ] {
            let limits = limits();
            limits.acquire(MODEL, 1).await;
            let pending = limits.acquire(MODEL, 1);
            tokio::pin!(pending);
            assert!(poll!(&mut pending).is_pending());
            limits
                .observe(MODEL, &headers(&[(remaining, "0"), (reset, "2s")]), None)
                .await;
            tokio::time::advance(Duration::from_secs(1)).await;
            limits
                .observe(MODEL, &HeaderMap::new(), Some(Duration::from_secs(2)))
                .await;
            limits
                .observe(MODEL, &headers(&[(remaining, "9999")]), None)
                .await;
            tokio::time::advance(Duration::from_secs(1)).await;
            assert!(poll!(&mut pending).is_pending());

            limits
                .acquire(EmbeddingModel::OpenAITextEmbeddingLarge, 1)
                .await;
            assert!(poll!(&mut pending).is_pending());
            let resumed = Instant::now();
            pending.await;
            assert!(resumed.elapsed() >= Duration::from_millis(900));
        }
    }

    #[tokio::test(start_paused = true)]
    async fn lower_provider_limits_and_token_costs_control_subsequent_requests() {
        let limits = limits();
        limits.acquire(MODEL, 1000).await;
        limits
            .observe(
                MODEL,
                &headers(&[
                    ("x-ratelimit-limit-requests", "600"),
                    ("x-ratelimit-limit-tokens", "30000"),
                ]),
                None,
            )
            .await;
        let start = Instant::now();
        limits.acquire(MODEL, 1000).await;
        assert!(start.elapsed() >= Duration::from_secs(2));
    }

    #[tokio::test(start_paused = true)]
    async fn queued_requests_do_not_starve_large_inputs_and_can_be_cancelled() {
        for cancel_first in [false, true] {
            let limits = limits();
            let mut large = Box::pin(limits.acquire(MODEL, 4000));
            let mut small = Box::pin(limits.acquire(MODEL, 1));
            assert!(poll!(&mut large).is_pending());
            assert!(poll!(&mut small).is_pending());
            tokio::time::advance(Duration::from_secs(1)).await;
            assert!(poll!(&mut small).is_pending());
            if cancel_first {
                drop(large);
            } else {
                large.await;
            }
            tokio::time::timeout(Duration::from_millis(200), small)
                .await
                .unwrap();
        }
    }
}
