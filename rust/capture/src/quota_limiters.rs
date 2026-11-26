use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_redis::{Client, LazyRedisClient};
use common_types::HasEventName;
use limiters::observation::spawn_observation;
use limiters::redis::{QuotaResource, RedisLimiter, ServiceName, QUOTA_LIMITER_CACHE_KEY};
use metrics::counter;
use tracing::{error, info};

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
// The experiments billing limit check keeps a copy of these predicates
// to tell which exposure events the events limit doesn't drop, in
// products/experiments/backend/health/checks/billing_limit.py. Update both.
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum QuotaReadMode {
    Disabled,
    Shadow,
    Live,
}

impl QuotaReadMode {
    fn as_str(self) -> &'static str {
        match self {
            QuotaReadMode::Disabled => "disabled",
            QuotaReadMode::Shadow => "shadow",
            QuotaReadMode::Live => "live",
        }
    }
}

pub struct QuotaRedisClients {
    pub limiters: Arc<dyn Client + Send + Sync>,
    pub observations: Option<Arc<dyn Client + Send + Sync>>,
}

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
    pub fn build_redis_clients(
        config: &Config,
        shared_redis: Arc<dyn Client + Send + Sync>,
    ) -> QuotaRedisClients {
        let requested = match config.quota_limiting_redis_read_mode.as_str() {
            "disabled" => QuotaReadMode::Disabled,
            "shadow" => QuotaReadMode::Shadow,
            "live" => QuotaReadMode::Live,
            _ => {
                error!("QUOTA_LIMITING_REDIS_READ_MODE must be disabled, shadow or live; reading quota limits from REDIS_URL only");
                QuotaReadMode::Disabled
            }
        };
        let copy = match requested {
            QuotaReadMode::Disabled => None,
            QuotaReadMode::Shadow | QuotaReadMode::Live => build_copy_client(config),
        };
        let (mode, clients) = match (requested, copy) {
            (QuotaReadMode::Live, Some(copy)) => (
                QuotaReadMode::Live,
                QuotaRedisClients {
                    limiters: copy,
                    observations: None,
                },
            ),
            (QuotaReadMode::Shadow, Some(copy)) => (
                QuotaReadMode::Shadow,
                QuotaRedisClients {
                    limiters: shared_redis,
                    observations: Some(copy),
                },
            ),
            _ => (
                QuotaReadMode::Disabled,
                QuotaRedisClients {
                    limiters: shared_redis,
                    observations: None,
                },
            ),
        };
        info!(mode = mode.as_str(), "quota limits read mode");
        clients
    }

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

        Self {
            capture_mode: config.capture_mode,
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

    pub fn spawn_observations(&self, redis: Arc<dyn Client + Send + Sync>) {
        let global = Self::get_resource_for_mode(self.capture_mode);
        let scoped = self
            .scoped_limiters
            .iter()
            .map(|limiter| limiter.resource().clone());
        for resource in std::iter::once(global).chain(scoped) {
            spawn_observation(
                self.redis_timeout,
                redis.clone(),
                QUOTA_LIMITER_CACHE_KEY.to_string(),
                self.redis_key_prefix.clone(),
                resource,
                ServiceName::Capture,
            );
        }
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
            CaptureMode::Events | CaptureMode::Ai | CaptureMode::Import => QuotaResource::Events,
            CaptureMode::Recordings => QuotaResource::Recordings,
        }
    }
}

fn build_copy_client(config: &Config) -> Option<Arc<dyn Client + Send + Sync>> {
    let Some(url) = config.quota_limiting_redis_url.clone() else {
        error!("QUOTA_LIMITING_REDIS_READ_MODE needs QUOTA_LIMITING_REDIS_URL; reading quota limits from REDIS_URL only");
        return None;
    };
    let response_timeout = timeout_or_fallback(
        config.quota_limiting_redis_response_timeout_ms,
        config.redis_response_timeout_ms,
    );
    let connection_timeout = timeout_or_fallback(
        config.quota_limiting_redis_connection_timeout_ms,
        config.redis_connection_timeout_ms,
    );
    let (Some(response_timeout), Some(connection_timeout)) = (response_timeout, connection_timeout)
    else {
        error!("the quota limiting Redis timeouts must not be 0; reading quota limits from REDIS_URL only");
        return None;
    };
    match LazyRedisClient::new(url, response_timeout, connection_timeout) {
        Ok(client) => Some(Arc::new(client)),
        Err(error) => {
            error!(%error, "invalid QUOTA_LIMITING_REDIS_URL; reading quota limits from REDIS_URL only");
            None
        }
    }
}

/// The copy client has no "no timeout" value, and a zero timeout fails every connect.
fn timeout_or_fallback(timeout_ms: Option<u64>, fallback_ms: u64) -> Option<Duration> {
    let timeout_ms = timeout_ms.filter(|ms| *ms > 0).unwrap_or(fallback_ms);
    (timeout_ms > 0).then(|| Duration::from_millis(timeout_ms))
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

#[cfg(test)]
mod tests {
    use std::io;
    use std::sync::Mutex;

    use common_redis::MockRedisClient;
    use rstest::rstest;

    use super::*;

    const COPY_URL: &str = "redis://:copy-secret@192.0.2.1:6379";
    const MODE: &str = "QUOTA_LIMITING_REDIS_READ_MODE";
    const URL: &str = "QUOTA_LIMITING_REDIS_URL";

    #[derive(Clone, Default)]
    struct Logs(Arc<Mutex<Vec<u8>>>);

    impl io::Write for Logs {
        fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
            self.0.lock().unwrap().extend_from_slice(buf);
            Ok(buf.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    impl Logs {
        fn lines(&self) -> Vec<String> {
            String::from_utf8(self.0.lock().unwrap().clone())
                .unwrap()
                .lines()
                .map(str::to_string)
                .collect()
        }
    }

    #[rstest]
    #[case::override_wins(Some(50), 100, Some(50))]
    #[case::zero_override_falls_back(Some(0), 100, Some(100))]
    #[case::unset_override_falls_back(None, 100, Some(100))]
    #[case::zero_fallback_is_refused(None, 0, None)]
    fn timeout_override_wins_over_the_shared_timeout(
        #[case] timeout_ms: Option<u64>,
        #[case] fallback_ms: u64,
        #[case] expected_ms: Option<u64>,
    ) {
        assert_eq!(
            timeout_or_fallback(timeout_ms, fallback_ms),
            expected_ms.map(Duration::from_millis)
        );
    }

    #[rstest]
    #[case::unset(&[(URL, COPY_URL)], QuotaReadMode::Disabled, false)]
    #[case::disabled(&[(MODE, "disabled"), (URL, COPY_URL)], QuotaReadMode::Disabled, false)]
    #[case::shadow(&[(MODE, "shadow"), (URL, COPY_URL)], QuotaReadMode::Shadow, false)]
    #[case::live(&[(MODE, "live"), (URL, COPY_URL)], QuotaReadMode::Live, false)]
    #[case::unknown(&[(MODE, "observe"), (URL, COPY_URL)], QuotaReadMode::Disabled, true)]
    #[case::other_case(&[(MODE, "Live"), (URL, COPY_URL)], QuotaReadMode::Disabled, true)]
    #[case::live_without_url(&[(MODE, "live")], QuotaReadMode::Disabled, true)]
    #[case::live_with_empty_url(&[(MODE, "live"), (URL, "")], QuotaReadMode::Disabled, true)]
    #[case::shadow_without_url(&[(MODE, "shadow")], QuotaReadMode::Disabled, true)]
    #[case::invalid_url(
        &[(MODE, "live"), (URL, "redis://:copy-secret@192.0.2.1:port")],
        QuotaReadMode::Disabled,
        true
    )]
    #[case::zero_override_falls_back(
        &[(MODE, "live"), (URL, COPY_URL), ("QUOTA_LIMITING_REDIS_RESPONSE_TIMEOUT_MS", "0")],
        QuotaReadMode::Live,
        false
    )]
    #[case::zero_fallback(
        &[(MODE, "live"), (URL, COPY_URL), ("REDIS_CONNECTION_TIMEOUT_MS", "0")],
        QuotaReadMode::Disabled,
        true
    )]
    #[case::override_replaces_zero_fallback(
        &[
            (MODE, "live"),
            (URL, COPY_URL),
            ("REDIS_CONNECTION_TIMEOUT_MS", "0"),
            ("QUOTA_LIMITING_REDIS_CONNECTION_TIMEOUT_MS", "1000"),
        ],
        QuotaReadMode::Live,
        false
    )]
    fn read_mode_picks_the_quota_limiter_client(
        #[case] env: &[(&str, &str)],
        #[case] mode: QuotaReadMode,
        #[case] logs_error: bool,
    ) {
        let env: HashMap<String, String> = [("REDIS_URL", "redis://localhost:6379/")]
            .iter()
            .chain(env)
            .map(|(key, value)| (key.to_string(), value.to_string()))
            .collect();
        let config: Config = envconfig::Envconfig::init_from_hashmap(&env).unwrap();
        let shared: Arc<dyn Client + Send + Sync> = Arc::new(MockRedisClient::new());
        let logs = Logs::default();
        let writer = logs.clone();
        let subscriber = tracing_subscriber::fmt()
            .with_writer(move || writer.clone())
            .with_ansi(false)
            .without_time()
            .with_target(false)
            .finish();

        let clients = tracing::subscriber::with_default(subscriber, || {
            CaptureQuotaLimiter::build_redis_clients(&config, shared.clone())
        });

        assert_eq!(
            Arc::ptr_eq(&clients.limiters, &shared),
            mode != QuotaReadMode::Live
        );
        assert_eq!(
            clients
                .observations
                .is_some_and(|copy| !Arc::ptr_eq(&copy, &shared)),
            mode == QuotaReadMode::Shadow
        );
        let lines = logs.lines();
        assert!(
            lines.iter().all(|line| !line.contains("copy-secret")),
            "{lines:?}"
        );
        assert_eq!(
            lines
                .iter()
                .filter(|line| line.trim_start().starts_with("INFO"))
                .collect::<Vec<_>>(),
            [&format!(
                " INFO quota limits read mode mode=\"{}\"",
                mode.as_str()
            )]
        );
        assert_eq!(
            lines.iter().any(|line| line.starts_with("ERROR")),
            logs_error,
            "{lines:?}"
        );
    }
}
