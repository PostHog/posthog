use common_types::RawEvent;
use limiters::redis::QuotaResource;

use crate::{
    api::CaptureError,
    prometheus::{report_dropped_events, report_quota_limit_exceeded},
    router::State,
    v0_request::ProcessingContext,
};

struct ScopedLimiter {
    resource: QuotaResource,
    limiter: RedisLimiter,
    // predicate supplied here should match RawEvents TO BE DROPPED
    // if the limit for this team/token has been exceeded
    event_matcher: Fn(&RawEvent) -> bool,
}

impl ScopedLimiter {
    fn new(resource: QuotaResource, event_matcher: Fn(&RawEvent) -> bool) -> Self {
        Self { resource, limiter, event_matcher }
    }

    async fn is_limited(&self, context: &ProcessingContext) -> bool {
        self.limiter.is_limited(context.token.as_str()).await
    }

    async fn filter_events(&self, events: Vec<RawEvent>) -> Vec<RawEvent> {
        events.into_iter().partition(|e| !self.event_matcher(context, e)).collect()
    }
}

pub struct CaptureQuotaLimiter {
    capture_mode: CaptureMode,

    // these are scoped to a specific event subset (e.g. survey events, AI events, etc.)
    // and ONLY filter out those events if the quota is exceeded. Add new scoped limiters
    // to this list as needed
    scoped_limiters: Vec<CaptureLimiter>,

    // this is the global billing limiter - if a token matches this limiter bucket,
    // all events are dropped for the incoming payload. Due to this, this limiter
    // IS ALWAYS APPLIED LAST in the chain.
    billing_limiter: RedisLimiter,
}

impl CaptureQuotaLimiter {
    pub fn new(config: &Config, redis_client: Arc<RedisClient>) -> Self {
        let global_billing_limiter = RedisLimiter::new(
            Duration::from_secs(5),
            redis_client.clone(),
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            config.redis_key_prefix.clone(),
            Self::get_resource_for_mode(config.capture_mode),
            ServiceName::Capture,
        )
        .expect("failed to create billing limiter");

        // Survey quota limiting - create for all capture modes (won't be used for recordings but required by router)
        let survey_limiter = RedisLimiter::new(
            Duration::from_secs(5),
            redis_client.clone(),
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            config.redis_key_prefix.clone(),
            QuotaResource::Surveys,
            ServiceName::Capture,
        )
        .expect("failed to create survey limiter");

        // LLM events quota limiting - create for all capture modes
        let llm_events_limiter = RedisLimiter::new(
            Duration::from_secs(5),
            redis_client.clone(),
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            config.redis_key_prefix.clone(),
            QuotaResource::LLMEvents,
            ServiceName::Capture,
        )
        .expect("failed to create AI events limiter");

        Self {
            capture_mode: config.capture_mode,
            billing_limiter,
            scoped_limiters: vec![],
        }
    }

    pub fn add_scoped_limiter(&mut self, resource: QuotaResource, event_matcher: Fn(&RawEvent) -> bool) -> Self {
        let limiter = CaptureLimiter::new(
            resource,
            RedisLimiter::new(
                Duration::from_secs(5),
                redis_client.clone(),
                QUOTA_LIMITER_CACHE_KEY.to_string(),
                config.redis_key_prefix.clone(),
                resource,
                ServiceName::Capture,
            ),
            event_matcher,
        );
        self.scoped_limiters.push(limiter);

        self
    }

    pub async fn check_and_filter(&self, token: Option<&str>, events: Vec<RawEvent>) -> Result<Vec<RawEvent>, CaptureError> {
        let token = match token {
            Some(token) => token,
            None => return Ok(events),
        };

        let mut filtered_events = events;

        // for each scoped limiter, if the token is found in Redis,
        // only drop events matching the limiter's filter predicate
        for limiter in self.scoped_limiters.iter() {
            if !limiter.limiter.is_limited(context.token.as_str()).await {
                continue;
            }
            let prior_count = filtered_events.len();
            filtered_events = limiter.filter_events(filtered_events).await;
            let dropped_count = prior_count - filtered_events.len();
            if dropped_count > 0 {
                let dropped_events_tag = format!("{}_over_quota", limiter.resource.to_string());
                report_quota_limit_exceeded(limiter.resource.to_string(), dropped_count);
                report_dropped_events(dropped_events_tag, dropped_count);
            }
            // if this filtering pass resulted in an empty batch, throw sentinel error
            if filtered_events.is_empty() {
                // TODO(eli): tag these with QuotaResource type?
                return Err(CaptureError::BillingLimit);
            }
        }

        // drop everything if this limiter is exceeded after all others have filtered the batch
        if self.billing_limiter.is_limited(token).await {
            let dropped_count = filtered_events.len() as u64;
            let global_resource_tag = Self::get_resource_for_mode(self.capture_mode).to_string();
            let dropped_events_tag = format!("{}_over_quota", global_resource_tag);

            report_quota_limit_exceeded(global_resource_tag, dropped_count);
            report_dropped_events(dropped_events_tag, dropped_count);

            return Err(CaptureError::BillingLimit);
        }

        Ok(filtered_events)
    }

    fn get_resource_for_mode(mode: CaptureMode) -> QuotaResource {
        match mode {
            CaptureMode::Events => QuotaResource::Events,
            CaptureMode::Recordings => QuotaResource::Recordings,
        }
    }
}

/// Check if an event is a survey-related event that should be subject to survey quota limiting
fn is_survey_event(event_name: &str) -> bool {

}

/// Check if an event is an AI-related event that should be subject to AI quota limiting
fn is_ai_event(event_name: &str) -> bool {
    event_name.starts_with("$ai_")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_survey_event() {
        // Survey events should return true
        assert!(is_survey_event("survey sent"));
        assert!(is_survey_event("survey shown"));
        assert!(is_survey_event("survey dismissed"));

        // Non-survey events should return false
        assert!(!is_survey_event("pageview"));
        assert!(!is_survey_event("$pageview"));
        assert!(!is_survey_event("click"));
        assert!(!is_survey_event("survey_sent")); // underscore variant
        assert!(!is_survey_event("Survey Sent")); // case sensitivity
        assert!(!is_survey_event(""));
    }
}
