use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_redis::Client;
use common_types::HasEventName;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY};
use metrics::counter;

use crate::{
    api::CaptureError,
    config::CaptureMode,
    config::Config,
    prometheus::{report_quota_limit_exceeded, CAPTURE_EVENTS_DROPPED_TOTAL},
};

#[derive(Clone, Copy)]
pub struct EventInfo<'a> {
    pub name: &'a str,
    pub has_product_tour_id: bool,
}

//
// Add a new predicate function for each new quota limiter you
// add to the CaptureQuotaLimiter. Each should match events by name
// associated with the QuotaResource type you will bind to the
// CaptureQuotaLimiter
//

// for QuotaResource::Exceptions
pub fn is_exception_event(info: EventInfo) -> bool {
    info.name == "$exception"
}

// for QuotaResource::Surveys
pub fn is_survey_event(info: EventInfo) -> bool {
    let is_survey = matches!(
        info.name,
        "survey sent" | "survey shown" | "survey dismissed"
    );
    is_survey && !info.has_product_tour_id
}

// for QuotaResource::LLMEvents
pub fn is_llm_event(info: EventInfo) -> bool {
    info.name.starts_with("$ai_")
}

// TODO: define more limiter predicates here!

/// See server.rs for an example of how to use CaptureQuotaLimiter
/// and to add new scoped limiters to capture
pub struct CaptureQuotaLimiter {
    capture_mode: CaptureMode,

    redis_timeout: Duration,
    redis_key_prefix: Option<String>,
    redis_client: Arc<dyn Client + Send + Sync>,

    // these are scoped to a specific event subset (e.g. survey events, AI events, etc.)
    // and ONLY filter out those events if the quota is exceeded
    scoped_limiters: Vec<Box<dyn ScopedLimiterTrait>>,

    // this is the global billing limiter - if a token matches this limiter bucket,
    // all events are dropped for the incoming payload. Due to this, this limiter
    // IS ALWAYS APPLIED LAST in the chain.
    global_limiter: RedisLimiter,
}

impl CaptureQuotaLimiter {
    pub fn new(
        config: &Config,
        redis_client: Arc<dyn Client + Send + Sync>,
        redis_timeout: Duration,
    ) -> Self {
        let err_msg = format!(
            "failed to create global limiter: {:?}",
            &config.capture_mode
        );
        let global_limiter = RedisLimiter::new(
            redis_timeout,
            redis_client.clone(),
            QUOTA_LIMITER_CACHE_KEY.to_string(),
            config.redis_key_prefix.clone(),
            Self::get_resource_for_mode(config.capture_mode.clone()),
            ServiceName::Capture,
        )
        .expect(&err_msg);

        Self {
            capture_mode: config.capture_mode.clone(),
            redis_timeout,
            redis_key_prefix: config.redis_key_prefix.clone(),
            redis_client: redis_client.clone(),
            global_limiter,
            scoped_limiters: vec![],
        }
    }

    pub fn add_scoped_limiter<F>(mut self, resource: QuotaResource, event_matcher: F) -> Self
    where
        F: Fn(EventInfo) -> bool + Send + Sync + Clone + 'static,
    {
        let err_msg = format!("failed to create scoped limiter: {resource:?}");
        let limiter = ScopedLimiter::new(
            resource.clone(),
            RedisLimiter::new(
                self.redis_timeout,
                self.redis_client.clone(),
                QUOTA_LIMITER_CACHE_KEY.to_string(),
                self.redis_key_prefix.clone(),
                resource.clone(),
                ServiceName::Capture,
            )
            .expect(&err_msg),
            event_matcher,
        );
        self.scoped_limiters.push(Box::new(limiter));

        self
    }

    pub async fn check_and_filter<T: HasEventName>(
        &self,
        token: &str,
        events: Vec<T>,
    ) -> Result<Vec<T>, CaptureError> {
        // avoid undue copying and allocations by caching event batch by index
        let mut indices_to_events: HashMap<usize, T> = HashMap::new();
        let mut filtered_indices: Vec<usize> = vec![];
        let mut retained_indices: Vec<usize> = vec![];
        for (i, event) in events.into_iter().enumerate() {
            indices_to_events.insert(i, event);
            filtered_indices.push(i);
        }

        // Build EventInfo for each event (includes name and property checks for quota limiting)
        // Done after moving events into indices_to_events so we can borrow from there
        let event_infos: Vec<EventInfo> = (0..indices_to_events.len())
            .map(|i| {
                let event = indices_to_events.get(&i).unwrap();
                EventInfo {
                    name: event.event_name(),
                    has_product_tour_id: event.has_property("$product_tour_id"),
                }
            })
            .collect();

        // for each scoped limiter, if the token is found in Redis,
        // only drop events matching the limiter's filter predicate
        for limiter in self.scoped_limiters.iter() {
            let (matched_indices, unmatched_indices) =
                limiter.partition_event_indices(&event_infos, &filtered_indices);

            if limiter.is_limited(token).await {
                // retain only events that this limiter doesn't drop
                filtered_indices = unmatched_indices;

                // report quota limit exceeded for this limiter
                let dropped_count = matched_indices.len() as u64;
                if dropped_count > 0 {
                    report_quota_limit_exceeded(limiter.resource(), dropped_count);
                    let dropped_events_tag = format!("{}_over_quota", limiter.resource().as_str());
                    counter!(CAPTURE_EVENTS_DROPPED_TOTAL, "cause" => dropped_events_tag)
                        .increment(dropped_count);
                }
            } else {
                // keep the events this limiter matched around for global limiter
                // to return in the event the global limit is exceeded for this token (team)
                // this way each scoped limiter is independent of the all-or-nothing global limit
                retained_indices.extend(matched_indices.into_iter());
            }

            // if this filtering pass resulted in an empty batch, throw sentinel error
            if filtered_indices.is_empty() {
                // TODO(eli): tag these with QuotaResource type?
                return Err(CaptureError::BillingLimit);
            }
        }

        // drop everything if this limiter is exceeded after all others have filtered the batch
        if self.global_limiter.is_limited(token).await {
            let dropped_count = filtered_indices.len() as u64;
            let global_resource_tag = Self::get_resource_for_mode(self.capture_mode.clone());
            report_quota_limit_exceeded(&global_resource_tag, dropped_count);
            let dropped_events_tag = format!("{}_over_quota", global_resource_tag.as_str());
            counter!(CAPTURE_EVENTS_DROPPED_TOTAL, "cause" => dropped_events_tag)
                .increment(dropped_count);

            // if the global limit was exceeded, we should return only
            // events the scoped limiters didn't already drop, or the
            // sentinel error if there are no retained events
            if retained_indices.is_empty() {
                return Err(CaptureError::BillingLimit);
            } else {
                let retained_events: Vec<T> = retained_indices
                    .iter()
                    .map(|i| indices_to_events.remove(i).unwrap())
                    .collect();
                return Ok(retained_events);
            }
        }

        // if the scoped limiters didn't empty the batch by this point,
        // and the global billing limit wasn't exceeded, return the
        // remaining events
        let filtered_events: Vec<T> = filtered_indices
            .iter()
            .map(|i| indices_to_events.remove(i).unwrap())
            .collect();
        Ok(filtered_events)
    }

    pub fn get_resource_for_mode(mode: CaptureMode) -> QuotaResource {
        match mode {
            CaptureMode::Events => QuotaResource::Events,
            CaptureMode::Recordings => QuotaResource::Recordings,
        }
    }
}

#[async_trait::async_trait]
trait ScopedLimiterTrait: Send + Sync {
    async fn is_limited(&self, token: &str) -> bool;
    /// Partition indices into (matched, unmatched) based on event info.
    /// `event_infos` is a slice where index i corresponds to the event at index i.
    fn partition_event_indices(
        &self,
        event_infos: &[EventInfo],
        indices: &[usize],
    ) -> (Vec<usize>, Vec<usize>);
    fn resource(&self) -> &QuotaResource;
}

#[derive(Clone)]
struct ScopedLimiter<F> {
    resource: QuotaResource,
    limiter: RedisLimiter,
    // predicate supplied here should match events TO BE DROPPED
    // if the limit for this team/token has been exceeded
    event_matcher: F,
}

impl<F> ScopedLimiter<F>
where
    F: Fn(EventInfo) -> bool + Send + Sync + Clone,
{
    fn new(resource: QuotaResource, limiter: RedisLimiter, event_matcher: F) -> Self {
        Self {
            resource,
            limiter,
            event_matcher,
        }
    }
}

#[async_trait::async_trait]
impl<F> ScopedLimiterTrait for ScopedLimiter<F>
where
    F: Fn(EventInfo) -> bool + Send + Sync + Clone,
{
    async fn is_limited(&self, token: &str) -> bool {
        self.limiter.is_limited(token).await
    }

    fn partition_event_indices(
        &self,
        event_infos: &[EventInfo],
        indices: &[usize],
    ) -> (Vec<usize>, Vec<usize>) {
        indices
            .iter()
            .partition(|&i| (self.event_matcher)(event_infos[*i]))
    }

    fn resource(&self) -> &QuotaResource {
        &self.resource
    }
}
