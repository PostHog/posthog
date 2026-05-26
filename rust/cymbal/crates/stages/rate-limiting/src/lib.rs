//! Cymbal team rate-limiting gate.
//!
//! This crate owns the reusable pre-resolution gate for exception events. It is
//! intentionally keyed only by numeric `team_id`, so Redis keys never include
//! user-controlled event payload strings.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use chrono::Utc;
use common_redis::Client as RedisClient;
use cymbal_core::{
    apply_rate_limit_mode, evaluate_rate_limit, run_buffered, PipelineStage,
    RateLimitApplication as CoreRateLimitApplication, RateLimitDecision as CoreRateLimitDecision,
    RateLimitKeyExtractor, RateLimitMode, RateLimiter, StageConcurrencyLimiter, StageError,
    StageInput, StageType,
};
use cymbal_domain::{
    InputEvent, RateLimitDecision, RateLimitGateOutput, RATE_LIMITING_STAGE_ID,
    RATE_LIMITING_STAGE_TYPE, TEAM_ID_RATE_LIMIT_DROP_REASON,
};
use envconfig::Envconfig;
use limiters::{EvalResult, GlobalRateLimiter, GlobalRateLimiterConfig, GlobalRateLimiterImpl};

const RATE_LIMIT_DECISIONS_COUNTER: &str = "cymbal_rate_limit_decisions_total";
const DEFAULT_REDIS_KEY_PREFIX: &str = "@ph/grl/cymbal/error_tracking/team_id";
const DEFAULT_RATE_LIMITING_STAGE_CONCURRENCY: usize = 32;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RateLimitingConfig {
    pub enabled: bool,
    pub reporting_only: bool,
    pub threshold: u64,
    pub window_interval: Duration,
    pub redis_key_prefix: String,
    pub redis_key_ttl: Duration,
    pub sync_interval: Duration,
    pub tick_interval: Duration,
    pub local_cache_ttl: Duration,
    pub local_cache_idle_timeout: Duration,
    pub local_cache_max_entries: u64,
    pub channel_capacity: usize,
}

impl Default for RateLimitingConfig {
    fn default() -> Self {
        let window_interval = Duration::from_secs(60);
        Self {
            enabled: false,
            reporting_only: false,
            threshold: 1_000_000,
            window_interval,
            redis_key_prefix: DEFAULT_REDIS_KEY_PREFIX.to_string(),
            redis_key_ttl: window_interval.mul_f64(2.0),
            sync_interval: Duration::from_secs(15),
            tick_interval: Duration::from_secs(1),
            local_cache_ttl: Duration::from_secs(600),
            local_cache_idle_timeout: Duration::from_secs(300),
            local_cache_max_entries: 100_000,
            channel_capacity: 1_000_000,
        }
    }
}

#[derive(Envconfig, Clone, Debug)]
struct RateLimitingEnvConfig {
    #[envconfig(default = "false")]
    cymbal_rate_limit_enabled: bool,
    #[envconfig(default = "false")]
    cymbal_rate_limit_reporting_only: bool,
    #[envconfig(default = "1000000")]
    cymbal_rate_limit_threshold: u64,
    #[envconfig(default = "60")]
    cymbal_rate_limit_window_seconds: u64,
    #[envconfig(default = "@ph/grl/cymbal/error_tracking/team_id")]
    cymbal_rate_limit_redis_key_prefix: String,
    #[envconfig(default = "120")]
    cymbal_rate_limit_redis_key_ttl_seconds: u64,
    #[envconfig(default = "15")]
    cymbal_rate_limit_sync_interval_seconds: u64,
    #[envconfig(default = "1000")]
    cymbal_rate_limit_tick_interval_ms: u64,
    #[envconfig(default = "600")]
    cymbal_rate_limit_local_cache_ttl_seconds: u64,
    #[envconfig(default = "300")]
    cymbal_rate_limit_local_cache_idle_timeout_seconds: u64,
    #[envconfig(default = "100000")]
    cymbal_rate_limit_local_cache_max_entries: u64,
    #[envconfig(default = "1000000")]
    cymbal_rate_limit_channel_capacity: usize,
}

impl From<RateLimitingEnvConfig> for RateLimitingConfig {
    fn from(config: RateLimitingEnvConfig) -> Self {
        Self {
            enabled: config.cymbal_rate_limit_enabled,
            reporting_only: config.cymbal_rate_limit_reporting_only,
            threshold: config.cymbal_rate_limit_threshold,
            window_interval: Duration::from_secs(config.cymbal_rate_limit_window_seconds),
            redis_key_prefix: config.cymbal_rate_limit_redis_key_prefix,
            redis_key_ttl: Duration::from_secs(config.cymbal_rate_limit_redis_key_ttl_seconds),
            sync_interval: Duration::from_secs(config.cymbal_rate_limit_sync_interval_seconds),
            tick_interval: Duration::from_millis(config.cymbal_rate_limit_tick_interval_ms),
            local_cache_ttl: Duration::from_secs(config.cymbal_rate_limit_local_cache_ttl_seconds),
            local_cache_idle_timeout: Duration::from_secs(
                config.cymbal_rate_limit_local_cache_idle_timeout_seconds,
            ),
            local_cache_max_entries: config.cymbal_rate_limit_local_cache_max_entries,
            channel_capacity: config.cymbal_rate_limit_channel_capacity,
        }
    }
}

impl Envconfig for RateLimitingConfig {
    // The `envconfig` trait still requires implementing its deprecated `init` method.
    // Keep the compatibility shim minimal and delegate to the non-deprecated path.
    #[allow(deprecated)]
    fn init() -> Result<Self, envconfig::Error>
    where
        Self: Sized,
    {
        Self::init_from_env()
    }

    fn init_from_env() -> Result<Self, envconfig::Error>
    where
        Self: Sized,
    {
        RateLimitingEnvConfig::init_from_env().map(Into::into)
    }

    fn init_from_hashmap(hashmap: &HashMap<String, String>) -> Result<Self, envconfig::Error>
    where
        Self: Sized,
    {
        RateLimitingEnvConfig::init_from_hashmap(hashmap).map(Into::into)
    }
}

impl RateLimitingConfig {
    pub fn mode(&self) -> RateLimitMode {
        if !self.enabled {
            RateLimitMode::Disabled
        } else if self.reporting_only {
            RateLimitMode::Reporting
        } else {
            RateLimitMode::Enforcing
        }
    }

    fn validate(&self) -> Result<(), RateLimitingError> {
        if self.threshold == 0 {
            return Err(RateLimitingError::ConfigInvalid {
                field: "threshold",
                reason: "must be greater than zero".to_string(),
            });
        }
        if self.window_interval.is_zero() {
            return Err(RateLimitingError::ConfigInvalid {
                field: "window_interval",
                reason: "must be greater than zero".to_string(),
            });
        }
        if self.sync_interval.is_zero() {
            return Err(RateLimitingError::ConfigInvalid {
                field: "sync_interval",
                reason: "must be greater than zero".to_string(),
            });
        }
        if self.tick_interval.is_zero() {
            return Err(RateLimitingError::ConfigInvalid {
                field: "tick_interval",
                reason: "must be greater than zero".to_string(),
            });
        }
        if self.redis_key_prefix.trim().is_empty() {
            return Err(RateLimitingError::ConfigInvalid {
                field: "redis_key_prefix",
                reason: "must not be empty".to_string(),
            });
        }
        if self.redis_key_ttl.is_zero() {
            return Err(RateLimitingError::ConfigInvalid {
                field: "redis_key_ttl",
                reason: "must be greater than zero".to_string(),
            });
        }
        if self.local_cache_ttl.is_zero() {
            return Err(RateLimitingError::ConfigInvalid {
                field: "local_cache_ttl",
                reason: "must be greater than zero".to_string(),
            });
        }
        if self.local_cache_idle_timeout.is_zero() {
            return Err(RateLimitingError::ConfigInvalid {
                field: "local_cache_idle_timeout",
                reason: "must be greater than zero".to_string(),
            });
        }
        if self.local_cache_max_entries == 0 {
            return Err(RateLimitingError::ConfigInvalid {
                field: "local_cache_max_entries",
                reason: "must be greater than zero".to_string(),
            });
        }
        if self.channel_capacity == 0 {
            return Err(RateLimitingError::ConfigInvalid {
                field: "channel_capacity",
                reason: "must be greater than zero".to_string(),
            });
        }
        Ok(())
    }

    fn to_global_rate_limiter_config(&self) -> GlobalRateLimiterConfig {
        GlobalRateLimiterConfig {
            global_threshold: self.threshold,
            window_interval: self.window_interval,
            sync_interval: self.sync_interval,
            tick_interval: self.tick_interval,
            redis_key_prefix: self.redis_key_prefix.clone(),
            global_cache_ttl: self.redis_key_ttl,
            local_cache_ttl: self.local_cache_ttl,
            local_cache_idle_timeout: self.local_cache_idle_timeout,
            local_cache_max_entries: self.local_cache_max_entries,
            channel_capacity: self.channel_capacity,
            metrics_scope: "cymbal_error_tracking_team_id".to_string(),
            ..Default::default()
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum RateLimitingError {
    #[error("invalid rate limiting config {field}: {reason}")]
    ConfigInvalid { field: &'static str, reason: String },
    #[error("failed to initialize rate limiter Redis backend: {message}")]
    RedisInitFailed { message: String },
}

#[derive(Clone)]
pub struct RateLimitingStage {
    config: RateLimitingConfig,
    limiter: Option<Arc<dyn GlobalRateLimiter>>,
    stage_concurrency_limiter: StageConcurrencyLimiter,
}

impl std::fmt::Debug for RateLimitingStage {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("RateLimitingStage")
            .field("config", &self.config)
            .field(
                "limiter",
                &self.limiter.as_ref().map(|_| "<dyn GlobalRateLimiter>"),
            )
            .field(
                "stage_concurrency",
                &self.stage_concurrency_limiter.capacity(),
            )
            .finish()
    }
}

impl Default for RateLimitingStage {
    fn default() -> Self {
        Self::disabled()
    }
}

impl RateLimitingStage {
    pub fn disabled() -> Self {
        Self {
            config: RateLimitingConfig::default(),
            limiter: None,
            stage_concurrency_limiter: StageConcurrencyLimiter::new(
                DEFAULT_RATE_LIMITING_STAGE_CONCURRENCY,
            ),
        }
    }

    pub fn with_limiter(config: RateLimitingConfig, limiter: Arc<dyn GlobalRateLimiter>) -> Self {
        Self {
            config,
            limiter: Some(limiter),
            stage_concurrency_limiter: StageConcurrencyLimiter::new(
                DEFAULT_RATE_LIMITING_STAGE_CONCURRENCY,
            ),
        }
    }

    pub fn from_redis(
        config: RateLimitingConfig,
        redis: Arc<dyn RedisClient + Send + Sync>,
    ) -> Result<Self, RateLimitingError> {
        if !config.enabled {
            return Ok(Self {
                config,
                limiter: None,
                stage_concurrency_limiter: StageConcurrencyLimiter::new(
                    DEFAULT_RATE_LIMITING_STAGE_CONCURRENCY,
                ),
            });
        }

        config.validate()?;
        let limiter =
            GlobalRateLimiterImpl::new(config.to_global_rate_limiter_config(), vec![redis])
                .map_err(|error| RateLimitingError::RedisInitFailed {
                    message: error.to_string(),
                })?;
        Ok(Self::with_limiter(config, Arc::new(limiter)))
    }

    pub fn config(&self) -> &RateLimitingConfig {
        &self.config
    }

    /// Cap the number of in-flight per-event rate-limit evaluations across
    /// every `process()` call to this stage on the pod.
    pub fn with_stage_concurrency(mut self, stage_concurrency: usize) -> Self {
        self.stage_concurrency_limiter = StageConcurrencyLimiter::new(stage_concurrency);
        self
    }

    async fn evaluate_event(&self, event: InputEvent) -> RateLimitGateOutput {
        let mode = self.config.mode();
        let core_decision = self.evaluate_decision(&event, mode).await;
        let application = apply_rate_limit_mode(event, mode, core_decision);
        let domain_decision = domain_decision_from_core(application.decision());
        let output = rate_limit_gate_output_from_core_application(application);
        emit_decision(&domain_decision, mode, &output);
        output
    }

    async fn evaluate_decision(
        &self,
        event: &InputEvent,
        mode: RateLimitMode,
    ) -> CoreRateLimitDecision<i64> {
        let key_extractor = TeamIdKeyExtractor;
        let Some(limiter) = self.limiter.as_deref() else {
            return evaluate_rate_limit(event, mode, &key_extractor, None, 1).await;
        };
        let limiter = TeamIdLimiter { limiter };
        evaluate_rate_limit(event, mode, &key_extractor, Some(&limiter), 1).await
    }
}

struct TeamIdKeyExtractor;

impl RateLimitKeyExtractor<InputEvent> for TeamIdKeyExtractor {
    type Key = i64;

    fn key(&self, event: &InputEvent) -> Option<Self::Key> {
        Some(event.team_id)
    }
}

struct TeamIdLimiter<'a> {
    limiter: &'a dyn GlobalRateLimiter,
}

#[async_trait]
impl RateLimiter<i64> for TeamIdLimiter<'_> {
    async fn check(&self, team_id: &i64, cost: u64) -> CoreRateLimitDecision<i64> {
        let key = team_rate_limit_key(*team_id);
        match self.limiter.check_limit(&key, cost, Some(Utc::now())).await {
            EvalResult::Allowed | EvalResult::NotApplicable => {
                CoreRateLimitDecision::Allowed { key: *team_id }
            }
            EvalResult::Limited(_) => CoreRateLimitDecision::Limited {
                key: *team_id,
                reason: TEAM_ID_RATE_LIMIT_DROP_REASON.to_string(),
            },
            EvalResult::FailOpen { reason } => CoreRateLimitDecision::LimiterError {
                message: format!("limiter failed open: {reason:?}"),
            },
        }
    }
}

fn domain_decision_from_core(decision: &CoreRateLimitDecision<i64>) -> RateLimitDecision {
    match decision {
        CoreRateLimitDecision::Disabled => RateLimitDecision::Disabled,
        CoreRateLimitDecision::MissingKey => RateLimitDecision::MissingTeamId,
        CoreRateLimitDecision::Allowed { key } => RateLimitDecision::Allowed { team_id: *key },
        CoreRateLimitDecision::Limited { key, reason } => RateLimitDecision::Limited {
            team_id: *key,
            reason: reason.clone(),
        },
        CoreRateLimitDecision::LimiterError { message } => RateLimitDecision::LimiterError {
            message: message.clone(),
        },
    }
}

fn rate_limit_gate_output_from_core_application(
    application: CoreRateLimitApplication<InputEvent, i64>,
) -> RateLimitGateOutput {
    match application {
        CoreRateLimitApplication::Continue { item, decision } => {
            RateLimitGateOutput::allowed(item, domain_decision_from_core(&decision))
        }
        CoreRateLimitApplication::Limited { item, decision } => match decision {
            CoreRateLimitDecision::Limited { reason, .. } => {
                RateLimitGateOutput::drop(item.event_id, reason)
            }
            decision => RateLimitGateOutput::allowed(item, domain_decision_from_core(&decision)),
        },
    }
}

#[async_trait]
impl PipelineStage for RateLimitingStage {
    type Input = InputEvent;
    type Output = RateLimitGateOutput;

    fn id(&self) -> StageType {
        RATE_LIMITING_STAGE_TYPE
    }

    async fn process(
        &self,
        input: StageInput<Self::Input>,
    ) -> Result<Vec<Self::Output>, StageError> {
        let stage = self.clone();
        run_buffered(&self.stage_concurrency_limiter, input.items, move |event| {
            let stage = stage.clone();
            async move { Ok(stage.evaluate_event(event).await) }
        })
        .await
    }
}

fn team_rate_limit_key(team_id: i64) -> String {
    format!("team_id:{team_id}")
}

fn emit_decision(decision: &RateLimitDecision, mode: RateLimitMode, output: &RateLimitGateOutput) {
    let decision_label = decision_label(decision, output);
    let mode_label = mode_label(mode);
    metrics::counter!(
        RATE_LIMIT_DECISIONS_COUNTER,
        "stage" => RATE_LIMITING_STAGE_ID,
        "decision" => decision_label,
        "mode" => mode_label,
    )
    .increment(1);

    match decision {
        RateLimitDecision::LimiterError { message } => tracing::warn!(
            stage = RATE_LIMITING_STAGE_ID,
            decision = decision_label,
            mode = mode_label,
            error = %message,
            "rate limiter failed open"
        ),
        _ => tracing::debug!(
            stage = RATE_LIMITING_STAGE_ID,
            decision = decision_label,
            mode = mode_label,
            "rate limiter evaluated event"
        ),
    }
}

fn decision_label(decision: &RateLimitDecision, output: &RateLimitGateOutput) -> &'static str {
    match decision {
        RateLimitDecision::Disabled => "disabled",
        RateLimitDecision::MissingTeamId => "missing_team_id",
        RateLimitDecision::Allowed { .. } => "allow",
        RateLimitDecision::Limited { .. } => match output {
            RateLimitGateOutput::Allowed(_) => "report",
            RateLimitGateOutput::Terminal(_) => "drop",
        },
        RateLimitDecision::LimiterError { .. } => "fail_open",
    }
}

fn mode_label(mode: RateLimitMode) -> &'static str {
    match mode {
        RateLimitMode::Disabled => "disabled",
        RateLimitMode::Reporting => "reporting",
        RateLimitMode::Enforcing => "enforcing",
    }
}

#[cfg(test)]
mod tests {
    use std::sync::{Arc, Mutex};

    use async_trait::async_trait;
    use cymbal_core::{BatchContext, Metadata, PipelineStage, StageInput};
    use cymbal_domain::{EventOutcome, ExceptionProperties};
    use limiters::{EvalResult, FailOpenReason, GlobalRateLimitResponse};
    use serde_json::json;

    use super::*;

    #[derive(Clone)]
    struct FakeLimiter {
        result: EvalResult,
        keys: Arc<Mutex<Vec<String>>>,
    }

    impl FakeLimiter {
        fn new(result: EvalResult) -> Self {
            Self {
                result,
                keys: Arc::new(Mutex::new(Vec::new())),
            }
        }

        fn keys(&self) -> Vec<String> {
            self.keys.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl GlobalRateLimiter for FakeLimiter {
        async fn check_limit(
            &self,
            key: &str,
            count: u64,
            _timestamp: Option<chrono::DateTime<Utc>>,
        ) -> EvalResult {
            assert_eq!(count, 1);
            self.keys.lock().unwrap().push(key.to_string());
            self.result.clone()
        }

        async fn check_custom_limit(
            &self,
            _key: &str,
            _count: u64,
            _timestamp: Option<chrono::DateTime<Utc>>,
        ) -> EvalResult {
            EvalResult::NotApplicable
        }

        fn is_custom_key(&self, _key: &str) -> bool {
            false
        }

        fn shutdown(&mut self) {}
    }

    mod fixtures {
        use super::*;

        pub fn config() -> RateLimitingConfig {
            RateLimitingConfig {
                enabled: true,
                threshold: 10,
                ..Default::default()
            }
        }

        pub fn input_event(event_id: &str, team_id: i64) -> InputEvent {
            InputEvent {
                event_id: event_id.to_string(),
                team_id,
                properties: ExceptionProperties::default(),
            }
        }

        pub fn context() -> BatchContext {
            BatchContext {
                batch_id: "batch-1".to_string(),
                metadata: Metadata::new(),
            }
        }
    }

    use fixtures::{config, context, input_event};

    async fn process_one(stage: &RateLimitingStage, event: InputEvent) -> RateLimitGateOutput {
        stage
            .process(StageInput::from_items(context(), vec![event]))
            .await
            .unwrap()
            .into_iter()
            .next()
            .unwrap()
    }

    fn limited_response(key: &str) -> GlobalRateLimitResponse {
        GlobalRateLimitResponse {
            key: key.to_string(),
            current_count: 11.0,
            threshold: 10,
            window_interval: Duration::from_secs(60),
            sync_interval: Duration::from_secs(15),
            is_custom_limited: false,
        }
    }

    #[tokio::test]
    async fn rate_limit_stage_allows_under_limit_events() {
        let limiter = FakeLimiter::new(EvalResult::Allowed);
        let stage = RateLimitingStage::with_limiter(config(), Arc::new(limiter.clone()));

        let output = process_one(&stage, input_event("event-1", 42)).await;

        assert_eq!(limiter.keys(), vec!["team_id:42"]);
        assert!(matches!(
            output,
            RateLimitGateOutput::Allowed(cymbal_domain::RateLimitAllowedEvent {
                decision: RateLimitDecision::Allowed { team_id: 42 },
                ..
            })
        ));
    }

    #[tokio::test]
    async fn rate_limit_stage_drops_over_limit_events_in_enforcing_mode() {
        let limiter = FakeLimiter::new(EvalResult::Limited(limited_response("team_id:42")));
        let stage = RateLimitingStage::with_limiter(config(), Arc::new(limiter));

        let output = process_one(&stage, input_event("event-1", 42)).await;

        assert_eq!(
            output,
            RateLimitGateOutput::Terminal(cymbal_domain::EventResult {
                event_id: "event-1".to_string(),
                outcome: EventOutcome::Drop {
                    reason: TEAM_ID_RATE_LIMIT_DROP_REASON.to_string(),
                },
            })
        );
    }

    #[tokio::test]
    async fn rate_limit_stage_reports_without_dropping_in_reporting_mode() {
        let limiter = FakeLimiter::new(EvalResult::Limited(limited_response("team_id:42")));
        let stage = RateLimitingStage::with_limiter(
            RateLimitingConfig {
                reporting_only: true,
                ..config()
            },
            Arc::new(limiter),
        );

        let output = process_one(&stage, input_event("event-1", 42)).await;

        assert!(matches!(
            output,
            RateLimitGateOutput::Allowed(cymbal_domain::RateLimitAllowedEvent {
                decision: RateLimitDecision::Limited { team_id: 42, .. },
                ..
            })
        ));
    }

    #[tokio::test]
    async fn rate_limit_stage_fails_open_on_limiter_errors() {
        let limiter = FakeLimiter::new(EvalResult::FailOpen {
            reason: FailOpenReason::RedisError,
        });
        let stage = RateLimitingStage::with_limiter(config(), Arc::new(limiter));

        let output = process_one(&stage, input_event("event-1", 42)).await;

        assert!(matches!(
            output,
            RateLimitGateOutput::Allowed(cymbal_domain::RateLimitAllowedEvent {
                decision: RateLimitDecision::LimiterError { .. },
                ..
            })
        ));
    }

    #[tokio::test]
    async fn rate_limit_stage_disabled_allows_without_calling_limiter() {
        let limiter = FakeLimiter::new(EvalResult::Limited(limited_response("team_id:42")));
        let stage = RateLimitingStage::with_limiter(
            RateLimitingConfig {
                enabled: false,
                ..config()
            },
            Arc::new(limiter.clone()),
        );

        let output = process_one(&stage, input_event("event-1", 42)).await;

        assert!(limiter.keys().is_empty());
        assert!(matches!(
            output,
            RateLimitGateOutput::Allowed(cymbal_domain::RateLimitAllowedEvent {
                decision: RateLimitDecision::Disabled,
                ..
            })
        ));
    }

    #[test]
    fn enabled_rate_limiter_rejects_invalid_config() {
        let config = RateLimitingConfig {
            threshold: 0,
            ..config()
        };

        assert!(matches!(
            config.validate(),
            Err(RateLimitingError::ConfigInvalid {
                field: "threshold",
                ..
            })
        ));
    }

    #[tokio::test]
    async fn not_applicable_limiter_result_is_treated_as_allowed() {
        // EvalResult::NotApplicable is mapped to Allowed to ensure that custom
        // key mis-matches in shared limiters never accidentally drop events.
        let limiter = FakeLimiter::new(EvalResult::NotApplicable);
        let stage = RateLimitingStage::with_limiter(config(), Arc::new(limiter));

        let output = process_one(&stage, input_event("event-1", 42)).await;

        assert!(
            matches!(
                output,
                RateLimitGateOutput::Allowed(cymbal_domain::RateLimitAllowedEvent {
                    decision: RateLimitDecision::Allowed { team_id: 42 },
                    ..
                })
            ),
            "NotApplicable must be treated the same as Allowed"
        );
    }

    #[tokio::test]
    async fn rate_limit_key_is_constructed_from_team_id_not_raw_event_content() {
        // The key extractor must produce "team_id:{N}" from the numeric team_id
        // only; it must never include user-controlled event payload strings.
        let limiter = FakeLimiter::new(EvalResult::Allowed);
        let stage = RateLimitingStage::with_limiter(config(), Arc::new(limiter.clone()));
        let mut event = input_event("event-1", 99);
        event.properties = ExceptionProperties::from_map(
            json!({
                "$exception_message": "team_id:INJECTED_VALUE"
            })
            .as_object()
            .unwrap()
            .clone(),
        )
        .unwrap();

        process_one(&stage, event).await;

        assert_eq!(
            limiter.keys(),
            vec!["team_id:99"],
            "limiter key must be derived from team_id only, never from event payload"
        );
    }

    #[tokio::test]
    async fn rate_limit_stage_with_zero_team_id_generates_team_id_zero_key() {
        // At the public API boundary, team_id <= 0 is dropped before events
        // reach the rate-limiting stage. This test documents the stage's own
        // behavior: it still constructs a "team_id:0" key and evaluates the
        // limiter, so callers must guard against invalid team IDs before this
        // stage rather than relying on the stage to reject them.
        let limiter = FakeLimiter::new(EvalResult::Allowed);
        let stage = RateLimitingStage::with_limiter(config(), Arc::new(limiter.clone()));

        process_one(&stage, input_event("event-1", 0)).await;

        assert_eq!(
            limiter.keys(),
            vec!["team_id:0"],
            "zero team_id should produce key team_id:0, not be silently dropped by the stage"
        );
    }
}
