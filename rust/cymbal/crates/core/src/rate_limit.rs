//! Domain-agnostic rate-limit admission primitives.
//!
//! Product crates own keys, storage backends, metrics, and terminal-result
//! mapping. This module only standardizes the common admission vocabulary:
//! disabled/reporting/enforcing modes, generic limiter decisions, key
//! extraction, and the fail-open rule for infrastructure errors.

use async_trait::async_trait;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RateLimitMode {
    Disabled,
    Reporting,
    Enforcing,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RateLimitDecision<K> {
    /// Limiter disabled by config: allow and do not consume limiter capacity.
    Disabled,
    /// No stable admission key was available for this item.
    MissingKey,
    /// Limiter checked the key and allowed the item.
    Allowed { key: K },
    /// Limiter checked the key and found it over limit.
    Limited { key: K, reason: String },
    /// Limiter infrastructure failed. Callers should fail open.
    LimiterError { message: String },
}

pub trait RateLimitKeyExtractor<T>: Send + Sync {
    type Key: Clone + Send + Sync + 'static;

    fn key(&self, item: &T) -> Option<Self::Key>;
}

#[async_trait]
pub trait RateLimiter<K>: Send + Sync
where
    K: Clone + Send + Sync + 'static,
{
    async fn check(&self, key: &K, cost: u64) -> RateLimitDecision<K>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RateLimitApplication<T, K> {
    /// The item should continue through the product pipeline with the observed
    /// decision attached if the product wants to expose/report it.
    Continue {
        item: T,
        decision: RateLimitDecision<K>,
    },
    /// The item was limited in enforcing mode. Product code maps this to its
    /// own terminal DTO/drop reason.
    Limited {
        item: T,
        decision: RateLimitDecision<K>,
    },
}

impl<T, K> RateLimitApplication<T, K> {
    pub fn decision(&self) -> &RateLimitDecision<K> {
        match self {
            Self::Continue { decision, .. } | Self::Limited { decision, .. } => decision,
        }
    }
}

pub async fn evaluate_rate_limit<T, E>(
    item: &T,
    mode: RateLimitMode,
    key_extractor: &E,
    limiter: Option<&dyn RateLimiter<E::Key>>,
    cost: u64,
) -> RateLimitDecision<E::Key>
where
    E: RateLimitKeyExtractor<T>,
{
    if mode == RateLimitMode::Disabled {
        return RateLimitDecision::Disabled;
    }

    let Some(key) = key_extractor.key(item) else {
        return RateLimitDecision::MissingKey;
    };

    let Some(limiter) = limiter else {
        return RateLimitDecision::LimiterError {
            message: "rate limiter is enabled but no limiter instance is configured".to_string(),
        };
    };

    limiter.check(&key, cost).await
}

pub fn apply_rate_limit_mode<T, K>(
    item: T,
    mode: RateLimitMode,
    decision: RateLimitDecision<K>,
) -> RateLimitApplication<T, K> {
    match mode {
        RateLimitMode::Disabled => RateLimitApplication::Continue {
            item,
            decision: RateLimitDecision::Disabled,
        },
        RateLimitMode::Reporting => RateLimitApplication::Continue { item, decision },
        RateLimitMode::Enforcing => match decision {
            limited @ RateLimitDecision::Limited { .. } => RateLimitApplication::Limited {
                item,
                decision: limited,
            },
            decision => RateLimitApplication::Continue { item, decision },
        },
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use super::*;

    #[derive(Debug)]
    struct TestItem {
        key: Option<String>,
    }

    struct TestKeyExtractor;

    impl RateLimitKeyExtractor<TestItem> for TestKeyExtractor {
        type Key = String;

        fn key(&self, item: &TestItem) -> Option<Self::Key> {
            item.key.clone()
        }
    }

    struct FakeLimiter {
        decision: RateLimitDecision<String>,
        calls: AtomicUsize,
    }

    impl FakeLimiter {
        fn new(decision: RateLimitDecision<String>) -> Self {
            Self {
                decision,
                calls: AtomicUsize::new(0),
            }
        }

        fn calls(&self) -> usize {
            self.calls.load(Ordering::Acquire)
        }
    }

    #[async_trait]
    impl RateLimiter<String> for FakeLimiter {
        async fn check(&self, _key: &String, cost: u64) -> RateLimitDecision<String> {
            assert_eq!(cost, 1);
            self.calls.fetch_add(1, Ordering::AcqRel);
            self.decision.clone()
        }
    }

    fn item_with_key() -> TestItem {
        TestItem {
            key: Some("tenant:42".to_string()),
        }
    }

    #[tokio::test]
    async fn disabled_mode_continues_without_calling_limiter() {
        let limiter = FakeLimiter::new(RateLimitDecision::Limited {
            key: "tenant:42".to_string(),
            reason: "over_limit".to_string(),
        });
        let decision = evaluate_rate_limit(
            &item_with_key(),
            RateLimitMode::Disabled,
            &TestKeyExtractor,
            Some(&limiter),
            1,
        )
        .await;
        let application = apply_rate_limit_mode(item_with_key(), RateLimitMode::Disabled, decision);

        assert_eq!(limiter.calls(), 0);
        assert!(matches!(
            application,
            RateLimitApplication::Continue {
                decision: RateLimitDecision::Disabled,
                ..
            }
        ));
    }

    #[test]
    fn reporting_mode_continues_limited_decisions() {
        let application = apply_rate_limit_mode(
            item_with_key(),
            RateLimitMode::Reporting,
            RateLimitDecision::Limited {
                key: "tenant:42".to_string(),
                reason: "over_limit".to_string(),
            },
        );

        assert!(matches!(
            application,
            RateLimitApplication::Continue {
                decision: RateLimitDecision::Limited { .. },
                ..
            }
        ));
    }

    #[test]
    fn enforcing_mode_limits_limited_decisions() {
        let application = apply_rate_limit_mode(
            item_with_key(),
            RateLimitMode::Enforcing,
            RateLimitDecision::Limited {
                key: "tenant:42".to_string(),
                reason: "over_limit".to_string(),
            },
        );

        assert!(matches!(
            application,
            RateLimitApplication::Limited {
                decision: RateLimitDecision::Limited { .. },
                ..
            }
        ));
    }

    #[tokio::test]
    async fn missing_key_continues_and_skips_limiter() {
        let item = TestItem { key: None };
        let limiter = FakeLimiter::new(RateLimitDecision::Allowed {
            key: "tenant:42".to_string(),
        });
        let decision = evaluate_rate_limit(
            &item,
            RateLimitMode::Enforcing,
            &TestKeyExtractor,
            Some(&limiter),
            1,
        )
        .await;
        let application = apply_rate_limit_mode(item, RateLimitMode::Enforcing, decision);

        assert_eq!(limiter.calls(), 0);
        assert!(matches!(
            application,
            RateLimitApplication::Continue {
                decision: RateLimitDecision::MissingKey,
                ..
            }
        ));
    }

    #[tokio::test]
    async fn allowed_decisions_continue() {
        let limiter = FakeLimiter::new(RateLimitDecision::Allowed {
            key: "tenant:42".to_string(),
        });
        let decision = evaluate_rate_limit(
            &item_with_key(),
            RateLimitMode::Enforcing,
            &TestKeyExtractor,
            Some(&limiter),
            1,
        )
        .await;
        let application =
            apply_rate_limit_mode(item_with_key(), RateLimitMode::Enforcing, decision);

        assert_eq!(limiter.calls(), 1);
        assert!(matches!(
            application,
            RateLimitApplication::Continue {
                decision: RateLimitDecision::Allowed { .. },
                ..
            }
        ));
    }

    #[tokio::test]
    async fn limited_decisions_are_reported_by_limiter() {
        let limiter = FakeLimiter::new(RateLimitDecision::Limited {
            key: "tenant:42".to_string(),
            reason: "over_limit".to_string(),
        });
        let decision = evaluate_rate_limit(
            &item_with_key(),
            RateLimitMode::Enforcing,
            &TestKeyExtractor,
            Some(&limiter),
            1,
        )
        .await;

        assert_eq!(limiter.calls(), 1);
        assert!(matches!(decision, RateLimitDecision::Limited { .. }));
    }

    #[tokio::test]
    async fn limiter_errors_fail_open_in_enforcing_mode() {
        let limiter = FakeLimiter::new(RateLimitDecision::LimiterError {
            message: "redis unavailable".to_string(),
        });
        let decision = evaluate_rate_limit(
            &item_with_key(),
            RateLimitMode::Enforcing,
            &TestKeyExtractor,
            Some(&limiter),
            1,
        )
        .await;
        let application =
            apply_rate_limit_mode(item_with_key(), RateLimitMode::Enforcing, decision);

        assert_eq!(limiter.calls(), 1);
        assert!(matches!(
            application,
            RateLimitApplication::Continue {
                decision: RateLimitDecision::LimiterError { .. },
                ..
            }
        ));
    }
}
