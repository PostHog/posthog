use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_redis::Client;
use common_types::HasEventName;
use limiters::redis::{
    QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY,
    QUOTA_LIMITING_SUSPENDED_CACHE_KEY,
};
use metrics::counter;

use crate::{
    api::CaptureError,
    config::CaptureMode,
    config::Config,
    prometheus::{
        report_quota_limit_exceeded, CAPTURE_EVENTS_ADMITTED_DURING_BILLING_GRACE_PERIOD_TOTAL,
        CAPTURE_EVENTS_DROPPED_TOTAL,
    },
};

#[derive(Clone, Copy)]
pub struct EventInfo<'a> {
    pub name: &'a str,
    pub has_product_tour_id: bool,
}

impl<'a> EventInfo<'a> {
    /// Builds an `EventInfo` from any `HasEventName` event. `product_tour_id_key`
    /// is the property key to probe for `has_product_tour_id` — callers differ on
    /// this because v0 events carry a raw `$`-prefixed property map (key
    /// `"$product_tour_id"`) while v1's `WrappedEvent` promotes it to a
    /// structured field checked via the unprefixed `"product_tour_id"` key.
    pub fn from_event<T: HasEventName>(event: &'a T, product_tour_id_key: &str) -> Self {
        Self {
            name: event.event_name(),
            has_product_tour_id: event.has_property(product_tour_id_key),
        }
    }
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

    grace_period_limiter: RedisLimiter,
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
            Self::get_resource_for_mode(config.capture_mode),
            ServiceName::Capture,
        )
        .expect(&err_msg);
        let grace_period_err_msg = format!(
            "failed to create billing grace period limiter: {:?}",
            &config.capture_mode
        );
        let grace_period_limiter = RedisLimiter::new(
            redis_timeout,
            redis_client.clone(),
            QUOTA_LIMITING_SUSPENDED_CACHE_KEY.to_string(),
            config.redis_key_prefix.clone(),
            Self::get_resource_for_mode(config.capture_mode),
            ServiceName::Capture,
        )
        .expect(&grace_period_err_msg);

        Self {
            capture_mode: config.capture_mode,
            redis_timeout,
            redis_key_prefix: config.redis_key_prefix.clone(),
            redis_client: redis_client.clone(),
            global_limiter,
            grace_period_limiter,
            scoped_limiters: vec![],
        }
    }

    pub fn add_scoped_limiter<F>(mut self, resource: QuotaResource, event_matcher: F) -> Self
    where
        F: Fn(EventInfo) -> bool + Send + Sync + Clone + 'static,
    {
        let err_msg = format!("failed to create scoped limiter: {resource:?}");
        let grace_period_err_msg =
            format!("failed to create scoped billing grace period limiter: {resource:?}");
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
            RedisLimiter::new(
                self.redis_timeout,
                self.redis_client.clone(),
                QUOTA_LIMITING_SUSPENDED_CACHE_KEY.to_string(),
                self.redis_key_prefix.clone(),
                resource,
                ServiceName::Capture,
            )
            .expect(&grace_period_err_msg),
            event_matcher,
        );
        self.scoped_limiters.push(Box::new(limiter));

        self
    }

    /// Drops events over quota for `token`, reports the admitted events, and
    /// returns the rest.
    pub async fn check_and_filter<T: HasEventName>(
        &self,
        token: &str,
        events: Vec<T>,
    ) -> Result<Vec<T>, CaptureError> {
        self.check_and_filter_impl(token, events, true).await
    }

    pub(crate) async fn check_and_filter_without_reporting<T: HasEventName>(
        &self,
        token: &str,
        events: Vec<T>,
    ) -> Result<Vec<T>, CaptureError> {
        self.check_and_filter_impl(token, events, false).await
    }

    async fn check_and_filter_impl<T: HasEventName>(
        &self,
        token: &str,
        events: Vec<T>,
        report_admission: bool,
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
                EventInfo::from_event(event, "$product_tour_id")
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
            let global_resource_tag = Self::get_resource_for_mode(self.capture_mode);
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
                if report_admission {
                    self.report_grace_period_admission(token, &retained_events)
                        .await;
                }
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
        if report_admission {
            self.report_grace_period_admission(token, &filtered_events)
                .await;
        }
        Ok(filtered_events)
    }

    pub async fn report_global_grace_period_admission(&self, token: &str, event_count: u64) {
        if event_count == 0 || !self.is_in_global_grace_period(token).await {
            return;
        }

        self.count_global_grace_admission(event_count);
    }

    /// Increments the global grace-admission counter unconditionally — callers
    /// must already know `token` is in the global grace period (e.g. via a
    /// snapshot they took earlier) so this doesn't re-probe Redis/DashMap state.
    pub(crate) fn count_global_grace_admission(&self, event_count: u64) {
        if event_count == 0 {
            return;
        }

        counter!(
            CAPTURE_EVENTS_ADMITTED_DURING_BILLING_GRACE_PERIOD_TOTAL,
            "resource" => Self::get_resource_for_mode(self.capture_mode).as_str()
        )
        .increment(event_count);
    }

    pub async fn report_grace_period_admission<T: HasEventName>(&self, token: &str, events: &[T]) {
        if events.is_empty() {
            return;
        }

        // Grace-period membership is a handful of orgs at a time and each check is
        // an in-memory DashMap read (no Redis round-trip), so it's cheap to probe
        // every limiter up front and skip the EventInfo allocation entirely when
        // this token isn't in any grace period — the common case on every request.
        let scoped_in_grace = self.scoped_limiters_in_grace_period(token).await;
        let is_global_grace = self.is_in_global_grace_period(token).await;
        if scoped_in_grace.is_empty() && !is_global_grace {
            return;
        }

        let event_infos: Vec<EventInfo> = events
            .iter()
            .map(|event| EventInfo::from_event(event, "$product_tour_id"))
            .collect();
        self.report_grace_period_admission_for_event_infos(
            &event_infos,
            &scoped_in_grace,
            is_global_grace,
        )
        .await;
    }

    /// Reports grace-period admissions for pre-built `EventInfo`s against a
    /// `scoped_in_grace` set and global-grace value the caller already
    /// computed (e.g. via `scoped_limiters_in_grace_period` and
    /// `is_in_global_grace_period`) — callers that also need those for a
    /// skip-guard should compute them once and pass both here, so the same
    /// values drive the guard and the counting rather than triggering a
    /// second, possibly-inconsistent lookup per report.
    pub(crate) async fn report_grace_period_admission_for_event_infos(
        &self,
        event_infos: &[EventInfo<'_>],
        scoped_in_grace: &[usize],
        is_global_grace: bool,
    ) {
        if event_infos.is_empty() {
            return;
        }

        let mut unreported_indices: Vec<usize> = (0..event_infos.len()).collect();

        // Scoped resources take precedence so each admitted event is counted once,
        // even when both scoped and global grace periods overlap.
        for &limiter_idx in scoped_in_grace {
            let Some(limiter) = self.scoped_limiters.get(limiter_idx) else {
                debug_assert!(
                    false,
                    "scoped_in_grace index out of bounds — indices must come from this \
                     same instance's scoped_limiters_in_grace_period"
                );
                continue;
            };
            let (matched_indices, unmatched_indices) =
                limiter.partition_event_indices(event_infos, &unreported_indices);
            if !matched_indices.is_empty() {
                counter!(
                    CAPTURE_EVENTS_ADMITTED_DURING_BILLING_GRACE_PERIOD_TOTAL,
                    "resource" => limiter.resource().as_str()
                )
                .increment(matched_indices.len() as u64);
            }
            unreported_indices = unmatched_indices;
        }

        if is_global_grace {
            self.count_global_grace_admission(unreported_indices.len() as u64);
        }
    }

    /// True if `token` is in the global grace period for this capture mode's
    /// resource and not currently hard-limited — a token in both sets (a
    /// transient skew while the billing writer updates them) counts as
    /// limited, not in grace. Scoped grace periods are checked separately via
    /// `scoped_limiters_in_grace_period` — combine both to know whether
    /// there's any grace-admission work to do for `token`.
    pub(crate) async fn is_in_global_grace_period(&self, token: &str) -> bool {
        self.grace_period_limiter.is_limited(token).await
            && !self.global_limiter.is_limited(token).await
    }

    /// Returns the indices into `self.scoped_limiters` that are currently in
    /// their grace period for `token`. Exposed so callers that also need a
    /// skip-guard (e.g. the v1 shim) can compute this once and pass it into
    /// `report_grace_period_admission_for_event_infos` rather than triggering
    /// a second lookup per scoped limiter.
    pub(crate) async fn scoped_limiters_in_grace_period(&self, token: &str) -> Vec<usize> {
        let mut in_grace = Vec::new();
        for (i, limiter) in self.scoped_limiters.iter().enumerate() {
            if limiter.is_in_grace_period(token).await && !limiter.is_limited(token).await {
                in_grace.push(i);
            }
        }
        in_grace
    }

    /// Check if a token is limited for a specific quota resource bucket.
    /// Checks the global limiter directly if the resource matches the capture
    /// mode's global resource, otherwise finds the matching scoped limiter.
    /// Each call targets exactly one DashMap — the caller controls ordering.
    pub async fn is_quota_limited_v1(&self, token: &str, resource: &QuotaResource) -> bool {
        // Global resource — direct check, no loop
        if *resource == Self::get_resource_for_mode(self.capture_mode) {
            return self.global_limiter.is_limited(token).await;
        }
        // Scoped resource — find the matching limiter
        for limiter in &self.scoped_limiters {
            if *limiter.resource() == *resource {
                return limiter.is_limited(token).await;
            }
        }
        false
    }

    pub fn get_resource_for_mode(mode: CaptureMode) -> QuotaResource {
        match mode {
            CaptureMode::Events | CaptureMode::Ai => QuotaResource::Events,
            CaptureMode::Recordings => QuotaResource::Recordings,
        }
    }
}

#[async_trait::async_trait]
trait ScopedLimiterTrait: Send + Sync {
    async fn is_limited(&self, token: &str) -> bool;
    async fn is_in_grace_period(&self, token: &str) -> bool;
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
    grace_period_limiter: RedisLimiter,
    // predicate supplied here should match events TO BE DROPPED
    // if the limit for this team/token has been exceeded
    event_matcher: F,
}

impl<F> ScopedLimiter<F>
where
    F: Fn(EventInfo) -> bool + Send + Sync + Clone,
{
    fn new(
        resource: QuotaResource,
        limiter: RedisLimiter,
        grace_period_limiter: RedisLimiter,
        event_matcher: F,
    ) -> Self {
        Self {
            resource,
            limiter,
            grace_period_limiter,
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

    async fn is_in_grace_period(&self, token: &str) -> bool {
        self.grace_period_limiter.is_limited(token).await
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
