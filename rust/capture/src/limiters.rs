use std::sync::Arc;
use std::time::Duration;

use common_redis::RedisClient;
use common_types::RawEvent;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY};

use crate::{
    api::CaptureError,
    config::CaptureMode,
    config::Config,
    prometheus::{report_dropped_events, report_quota_limit_exceeded},
    v0_request::ProcessingContext,
};

#[derive(Clone)]
struct ScopedLimiter {
    resource: QuotaResource,
    limiter: RedisLimiter,
    // predicate supplied here should match RawEvents TO BE DROPPED
    // if the limit for this team/token has been exceeded
    event_matcher: Box<dyn Fn(&RawEvent) -> bool + Send + Sync>,
}

impl ScopedLimiter {
    fn new(
        resource: QuotaResource,
        redis_limiter: RedisLimiter,
        event_matcher: Box<dyn Fn(&RawEvent) -> bool + Send + Sync>,
    ) -> Self {
        Self {
            resource,
            limiter,
            event_matcher,
        }
    }

    async fn is_limited(&self, context: &ProcessingContext) -> bool {
        self.limiter.is_limited(context.token.as_str()).await
    }

    async fn partition_events(&self, events: &Vec<RawEvent>) -> (Vec<&RawEvent>, Vec<&RawEvent>) {
        events.iter().partition(|e| (self.event_matcher)(e))
    }
}

#[derive(Clone)]
pub struct CaptureQuotaLimiter {
    capture_mode: CaptureMode,

    redis_key_prefix: Option<String>,

    redis_client: Arc<RedisClient>,

    // these are scoped to a specific event subset (e.g. survey events, AI events, etc.)
    // and ONLY filter out those events if the quota is exceeded. Add new scoped limiters
    // to this list as needed
    scoped_limiters: Vec<ScopedLimiter>,

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
        .expect(&format!(
            "failed to create global limiter: {:?}",
            &config.capture_mode
        ));

        Self {
            capture_mode: config.capture_mode,
            redis_key_prefix: config.redis_key_prefix.clone(),
            redis_client: redis_client.clone(),
            billing_limiter,
            scoped_limiters: vec![],
        }
    }

    pub fn add_scoped_limiter(
        mut self,
        resource: QuotaResource,
        event_matcher: Box<dyn Fn(&RawEvent) -> bool + Send + Sync>,
    ) -> Self {
        let limiter = ScopedLimiter::new(
            resource.clone(),
            RedisLimiter::new(
                Duration::from_secs(5),
                self.redis_client.clone(),
                QUOTA_LIMITER_CACHE_KEY.to_string(),
                self.redis_key_prefix.clone(),
                resource.clone(),
                ServiceName::Capture,
            )
            .expect(&format!("failed to create scoped limiter: {:?}", resource)),
            event_matcher,
        );
        self.scoped_limiters.push(limiter);

        self
    }

    pub async fn check_and_filter(
        &self,
        token: Option<&str>,
        events: Vec<RawEvent>,
    ) -> Result<Vec<RawEvent>, CaptureError> {
        let token = match token {
            Some(token) => token,
            None => return Ok(events),
        };

        let mut filtered_events = events;
        let mut retained_events: Vec<&RawEvent> = vec![];

        // for each scoped limiter, if the token is found in Redis,
        // only drop events matching the limiter's filter predicate
        for limiter in self.scoped_limiters.iter() {
            let (matched_events, unmatched_events) =
                limiter.partition_events(&filtered_events).await;

            if limiter.limiter.is_limited(token).await {
                // retain only events that this limiter doesn't drop
                filtered_events = unmatched_events.into_iter().map(|e| e.to_owned()).collect();

                // report quota limit exceeded for this limiter
                let dropped_count = matched_events.len() as u64;
                if dropped_count > 0 {
                    let dropped_events_tag = format!("{}_over_quota", limiter.resource.as_str());
                    report_quota_limit_exceeded(&limiter.resource, dropped_count);
                    report_dropped_events(&dropped_events_tag, dropped_count);
                }
            } else {
                // keep the events this limiter matched around for global limiter
                // to return in the event the global limit is exceeded for this token (team)
                // this way each scoped limiter is independent of the all-or-nothing global limit
                retained_events.extend(matched_events.into_iter());
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
            let global_resource_tag = Self::get_resource_for_mode(self.capture_mode);
            let dropped_events_tag = format!("{:?}_over_quota", global_resource_tag.as_str());

            report_quota_limit_exceeded(&global_resource_tag, dropped_count);
            report_dropped_events(&dropped_events_tag, dropped_count);

            // if the global limit was exceeded, we should return only
            // events the scoped limiters didn't already drop, or the
            // sentinel error if there are no retained events
            if retained_events.is_empty() {
                return Err(CaptureError::BillingLimit);
            } else {
                return Ok(retained_events);
            }
        }

        // if the scoped limiters didn't empty the batch by this point,
        // and the global billing limit wasn't exceeded, return the
        // remaining events
        Ok(filtered_events)
    }

    fn get_resource_for_mode(mode: CaptureMode) -> QuotaResource {
        match mode {
            CaptureMode::Events => QuotaResource::Events,
            CaptureMode::Recordings => QuotaResource::Recordings,
        }
    }
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
