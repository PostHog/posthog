//! Hints — the latency fast path (plan §2.7, §3.1).
//!
//! A dedicated raw `redis` pub/sub connection to each tier's primary subscribes
//! to the cache-ready channels. Every message is **confirmed against Redis before
//! it is announced**: the hint's embedded etag is never applied directly — only a
//! primary read that matches it is (verify-before-announce). Hint-connection loss
//! degrades to sweep-only latency; the subscriber reconnects with capped
//! exponential backoff and re-`SUBSCRIBE`s (redis-rs does not auto-resubscribe).
//!
//! The parse + confirm + apply decision is factored into [`decide_hint`], a pure
//! unit taking a "read etag" closure, so it is exhaustively testable without a
//! live pub/sub connection. The [`run_hints`] task is the thin I/O shell around it.

use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;

use common_hypercache::{HyperCacheError, KeyType};
use futures::StreamExt;
use lifecycle::Handle;
use serde::Deserialize;

use crate::domain::{CacheKind, Etag, Observation, Topic};
use crate::metrics;
use crate::registry::TopicRegistry;
use crate::trigger::{apply_observation, Tier, TriggerSource};

/// Reconnect backoff ceiling for the pub/sub connection.
const MAX_BACKOFF_MS: u64 = 5_000;
/// Initial reconnect backoff.
const INITIAL_BACKOFF_MS: u64 = 100;

/// A `v1` cache-ready signal (plan §3.1). Deliberately lenient: no
/// `deny_unknown_fields`, so an additive Django-side schema change never causes a
/// fleet-wide hint blackout during a rolling deploy — the etag is confirm-read
/// from Redis anyway. `written_at` is optional so a future producer dropping it
/// degrades to "no lag metric", not a parse failure.
#[derive(Debug, Deserialize)]
struct HintV1 {
    v: u32,
    team_id: common_types::TeamId,
    namespace: String,
    value: String,
    etag: String,
    #[serde(default)]
    written_at: Option<String>,
}

/// Why a hint was dropped before it could be applied — the `reason` label on the
/// hint-dropped counter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HintDropReason {
    /// The payload was not valid JSON.
    InvalidJson,
    /// `v` was not 1.
    UnsupportedVersion,
    /// `namespace` was not `feature_flags`.
    WrongNamespace,
    /// `value` mapped to no kind, or a kind not hosted on this tier.
    UnknownValue,
    /// The confirm-read never matched the hint's etag within the retry budget.
    ConfirmMismatch,
    /// The confirm-read hit a Redis infra error; the sweep repairs.
    ConfirmError,
}

impl HintDropReason {
    fn as_str(self) -> &'static str {
        match self {
            HintDropReason::InvalidJson => "invalid_json",
            HintDropReason::UnsupportedVersion => "unsupported_version",
            HintDropReason::WrongNamespace => "wrong_namespace",
            HintDropReason::UnknownValue => "unknown_value",
            HintDropReason::ConfirmMismatch => "confirm_mismatch",
            HintDropReason::ConfirmError => "confirm_error",
        }
    }
}

/// The outcome of evaluating one hint.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HintDecision {
    /// Confirmed against Redis — apply `etag` for `(team_id, kind)`. `written_at`
    /// (when present) feeds the hint-lag histogram.
    Apply {
        kind: CacheKind,
        team_id: common_types::TeamId,
        etag: Etag,
        written_at: Option<String>,
    },
    /// Dropped; the sweep will repair within one interval.
    Drop(HintDropReason),
}

/// Retry policy for the confirm-read (plan §2.7): a small retry covers the
/// publish/write interleaving from Django's `set_many` pipeline. Injectable so
/// tests run with zero delay.
#[derive(Debug, Clone, Copy)]
pub struct HintConfig {
    pub confirm_retries: u32,
    pub confirm_retry_delay: Duration,
}

impl Default for HintConfig {
    fn default() -> Self {
        Self {
            confirm_retries: 2,
            confirm_retry_delay: Duration::from_millis(100),
        }
    }
}

/// The pure parse + confirm + decide unit (plan §2.7).
///
/// `read_etag` is the injected confirm-read: given a kind and team, it returns the
/// current primary etag (`Ok(Some)`), its absence (`Ok(None)`), or an infra error.
/// It may be called up to `1 + confirm_retries` times, with `confirm_retry_delay`
/// between attempts, until it returns an etag equal to the hint's — the only
/// condition under which the hint is applied.
pub async fn decide_hint<F, Fut>(
    raw: &str,
    tier_kinds: &[CacheKind],
    cfg: &HintConfig,
    read_etag: F,
) -> HintDecision
where
    F: Fn(CacheKind, common_types::TeamId) -> Fut,
    Fut: std::future::Future<Output = Result<Option<String>, HyperCacheError>>,
{
    let hint: HintV1 = match serde_json::from_str(raw) {
        Ok(hint) => hint,
        Err(_) => return HintDecision::Drop(HintDropReason::InvalidJson),
    };
    if hint.v != 1 {
        return HintDecision::Drop(HintDropReason::UnsupportedVersion);
    }
    if hint.namespace != "feature_flags" {
        return HintDecision::Drop(HintDropReason::WrongNamespace);
    }
    let Some(kind) = kind_for_value(&hint.value) else {
        return HintDecision::Drop(HintDropReason::UnknownValue);
    };
    if !tier_kinds.contains(&kind) {
        return HintDecision::Drop(HintDropReason::UnknownValue);
    }

    let mut attempt = 0;
    loop {
        match read_etag(kind, hint.team_id).await {
            Ok(Some(read)) if read == hint.etag => {
                return match Etag::from_str(&read) {
                    Ok(etag) => HintDecision::Apply {
                        kind,
                        team_id: hint.team_id,
                        etag,
                        written_at: hint.written_at,
                    },
                    // A matching-but-unparseable etag would be a corrupt write; do
                    // not enter the state machine — the sweep handles it.
                    Err(_) => HintDecision::Drop(HintDropReason::ConfirmMismatch),
                };
            }
            // Absent or a mismatch — retry within budget.
            Ok(_) => {}
            // Infra error — drop; the sweep repairs (plan §2.7).
            Err(_) => return HintDecision::Drop(HintDropReason::ConfirmError),
        }
        if attempt >= cfg.confirm_retries {
            return HintDecision::Drop(HintDropReason::ConfirmMismatch);
        }
        attempt += 1;
        tokio::time::sleep(cfg.confirm_retry_delay).await;
    }
}

/// Map a HyperCache value name to its kind, or `None` if it names no kind.
fn kind_for_value(value: &str) -> Option<CacheKind> {
    [CacheKind::Definitions, CacheKind::RemoteEval]
        .into_iter()
        .find(|kind| kind.hypercache_value() == value)
}

/// The topic of a well-formed v1 hint for a kind on this tier that no receiver
/// on this pod watches — the caller records `no_subscribers` and skips the
/// confirm-read entirely. Anything malformed or off-tier returns `None` and
/// flows through [`decide_hint`] so drop reasons stay exact. The parse is
/// duplicated deliberately: `decide_hint`'s pure logic stays intact (the
/// short-circuit lives at the call site) and hint payloads are tiny.
fn unwatched_hint_topic(
    raw: &str,
    tier_kinds: &[CacheKind],
    registry: &TopicRegistry,
) -> Option<Topic> {
    let hint: HintV1 = serde_json::from_str(raw).ok()?;
    if hint.v != 1 || hint.namespace != "feature_flags" {
        return None;
    }
    let kind = kind_for_value(&hint.value)?;
    if !tier_kinds.contains(&kind) {
        return None;
    }
    let topic = Topic {
        team_id: hint.team_id,
        kind,
    };
    if registry.has_receivers(topic) {
        None
    } else {
        Some(topic)
    }
}

/// Convert a `written_at` RFC3339 timestamp to publish→now lag in milliseconds,
/// clamped at zero (clock skew must not record a negative lag).
fn lag_ms(written_at: &str) -> Option<f64> {
    let published = chrono::DateTime::parse_from_rfc3339(written_at).ok()?;
    let elapsed = chrono::Utc::now().signed_duration_since(published.with_timezone(&chrono::Utc));
    Some(elapsed.num_milliseconds().max(0) as f64)
}

/// Run the hints subscriber for one tier until shutdown, reconnecting with capped
/// exponential backoff. Registered as an advisory lifecycle component, so it
/// reports health on a timer but never triggers app shutdown (plan §2.11).
pub async fn run_hints(
    handle: Handle,
    registry: Arc<TopicRegistry>,
    tier: Tier,
    cfg: HintConfig,
    report_interval: Duration,
) {
    let _scope = handle.process_scope();
    let mut report = tokio::time::interval(report_interval);
    report.tick().await; // consume the immediate first tick
    let mut backoff_ms = INITIAL_BACKOFF_MS;

    loop {
        if handle.is_shutting_down() {
            return;
        }

        match connect_and_subscribe(&tier).await {
            Ok(mut pubsub) => {
                backoff_ms = INITIAL_BACKOFF_MS;
                handle.report_healthy();
                let mut messages = pubsub.on_message();
                loop {
                    tokio::select! {
                        _ = handle.shutdown_recv() => return,
                        _ = report.tick() => handle.report_healthy(),
                        message = messages.next() => match message {
                            Some(message) => {
                                handle.report_healthy();
                                process_message(&message, &registry, &tier, &cfg).await;
                            }
                            // Connection closed (e.g. failover) — reconnect.
                            None => break,
                        }
                    }
                }
            }
            Err(e) => tracing::warn!(
                tier = tier.name,
                error = %e,
                "hints pub/sub connect failed; backing off"
            ),
        }

        tokio::select! {
            _ = tokio::time::sleep(Duration::from_millis(backoff_ms)) => {}
            _ = handle.shutdown_recv() => return,
        }
        backoff_ms = (backoff_ms * 2).min(MAX_BACKOFF_MS);
    }
}

/// Open a raw pub/sub connection to the tier's primary and subscribe to every
/// ready channel the tier's kinds publish on.
async fn connect_and_subscribe(tier: &Tier) -> Result<redis::aio::PubSub, redis::RedisError> {
    let client = redis::Client::open(tier.pubsub_url.as_str())?;
    let mut pubsub = client.get_async_pubsub().await?;
    for kind in &tier.kinds {
        pubsub.subscribe(kind.ready_channel()).await?;
    }
    Ok(pubsub)
}

/// Decode one pub/sub message, confirm it against Redis, and apply or drop it.
async fn process_message(
    message: &redis::Msg,
    registry: &TopicRegistry,
    tier: &Tier,
    cfg: &HintConfig,
) {
    let payload: String = match message.get_payload() {
        Ok(payload) => payload,
        Err(_) => {
            metrics::hint_dropped("invalid_payload");
            return;
        }
    };

    // Short-circuit BEFORE the confirm-read: every pod receives every hint, so
    // skipping topics nobody here watches avoids the K teams × P pods confirm-GET
    // multiplier (plan §7). Malformed/off-tier hints fall through to decide_hint
    // for exact drop accounting.
    if let Some(topic) = unwatched_hint_topic(&payload, &tier.kinds, registry) {
        metrics::observation(topic.kind, metrics::SOURCE_HINT, "no_subscribers");
        return;
    }

    let decision = decide_hint(&payload, &tier.kinds, cfg, |kind, team_id| async move {
        match tier.readers.get(&kind) {
            Some(reader) => reader.get_etag(&KeyType::int(team_id)).await,
            None => Ok(None),
        }
    })
    .await;

    match decision {
        HintDecision::Apply {
            kind,
            team_id,
            etag,
            written_at,
        } => {
            apply_observation(
                registry,
                Topic { team_id, kind },
                Observation::Present(etag),
                TriggerSource::Hint,
            );
            if let Some(written_at) = written_at {
                if let Some(lag) = lag_ms(&written_at) {
                    metrics::hint_lag_ms(lag);
                }
            }
        }
        HintDecision::Drop(reason) => metrics::hint_dropped(reason.as_str()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const HINT_A: &str = "0123456789abcdef";
    const HINT_B: &str = "fedcba9876543210";

    fn fast_cfg() -> HintConfig {
        HintConfig {
            confirm_retries: 2,
            confirm_retry_delay: Duration::ZERO,
        }
    }

    fn valid_hint(etag: &str) -> String {
        format!(
            r#"{{"v":1,"team_id":123,"namespace":"feature_flags","value":"flags.json","etag":"{etag}","written_at":"2026-07-26T12:00:00Z"}}"#
        )
    }

    #[tokio::test]
    async fn valid_hint_with_matching_confirm_read_applies() {
        let decision = decide_hint(
            &valid_hint(HINT_A),
            &[CacheKind::RemoteEval],
            &fast_cfg(),
            |_, _| async { Ok(Some(HINT_A.to_string())) },
        )
        .await;
        assert_eq!(
            decision,
            HintDecision::Apply {
                kind: CacheKind::RemoteEval,
                team_id: 123,
                etag: Etag::from_str(HINT_A).unwrap(),
                written_at: Some("2026-07-26T12:00:00Z".to_string()),
            }
        );
    }

    #[tokio::test]
    async fn persistent_confirm_mismatch_is_dropped() {
        // The confirm-read never converges on the hint's etag → dropped after the
        // retry budget; the sweep repairs.
        let decision = decide_hint(
            &valid_hint(HINT_A),
            &[CacheKind::RemoteEval],
            &fast_cfg(),
            |_, _| async { Ok(Some(HINT_B.to_string())) },
        )
        .await;
        assert_eq!(
            decision,
            HintDecision::Drop(HintDropReason::ConfirmMismatch)
        );
    }

    #[tokio::test]
    async fn future_version_is_dropped_without_reading() {
        let raw = r#"{"v":2,"team_id":123,"namespace":"feature_flags","value":"flags.json","etag":"0123456789abcdef"}"#;
        let decision = decide_hint(raw, &[CacheKind::RemoteEval], &fast_cfg(), |_, _| async {
            panic!("confirm-read must not run for an unsupported version");
            #[allow(unreachable_code)]
            Ok(None)
        })
        .await;
        assert_eq!(
            decision,
            HintDecision::Drop(HintDropReason::UnsupportedVersion)
        );
    }

    #[tokio::test]
    async fn kind_not_on_tier_is_dropped() {
        // A flags.json (remote_eval) hint arriving on a definitions-only tier.
        let decision = decide_hint(
            &valid_hint(HINT_A),
            &[CacheKind::Definitions],
            &fast_cfg(),
            |_, _| async { Ok(Some(HINT_A.to_string())) },
        )
        .await;
        assert_eq!(decision, HintDecision::Drop(HintDropReason::UnknownValue));
    }

    #[tokio::test]
    async fn confirm_infra_error_is_dropped() {
        let decision = decide_hint(
            &valid_hint(HINT_A),
            &[CacheKind::RemoteEval],
            &fast_cfg(),
            |_, _| async { Err(HyperCacheError::Timeout("boom".to_string())) },
        )
        .await;
        assert_eq!(decision, HintDecision::Drop(HintDropReason::ConfirmError));
    }

    // Cross-language contract: the shared v1 fixture must parse, and adding an
    // unknown field must NOT break parsing (the deliberate producer-strict /
    // consumer-lenient asymmetry, plan §3.1). Parsed here through the real
    // consumer path (`decide_hint`) with a matching confirm-read.
    const FIXTURE: &str =
        include_str!("../../../feature-flags/tests/fixtures/hypercache_ready_v1.json");

    #[tokio::test]
    async fn fixture_parses_and_applies() {
        // The fixture's etag is 0123456789abcdef and value is flags.json.
        let decision = decide_hint(
            FIXTURE,
            &[CacheKind::RemoteEval],
            &fast_cfg(),
            |_, _| async { Ok(Some(HINT_A.to_string())) },
        )
        .await;
        assert!(
            matches!(
                decision,
                HintDecision::Apply {
                    kind: CacheKind::RemoteEval,
                    team_id: 123,
                    ..
                }
            ),
            "fixture should parse and apply, got {decision:?}"
        );
    }

    #[tokio::test]
    async fn fixture_with_unknown_field_still_parses() {
        // Inject a field the consumer does not know about — it must be ignored.
        let with_extra = FIXTURE.trim_end().trim_end_matches('}').to_string()
            + r#","some_future_field":"ignored"}"#;
        let decision = decide_hint(
            &with_extra,
            &[CacheKind::RemoteEval],
            &fast_cfg(),
            |_, _| async { Ok(Some(HINT_A.to_string())) },
        )
        .await;
        assert!(
            matches!(decision, HintDecision::Apply { .. }),
            "unknown field must not break parsing, got {decision:?}"
        );
    }

    #[test]
    fn unwatched_hint_short_circuits_only_valid_on_tier_hints() {
        let registry = TopicRegistry::new();
        let raw = valid_hint(HINT_A); // team 123, flags.json → RemoteEval

        // Valid, on-tier, nobody watching → short-circuit with the topic.
        let topic = unwatched_hint_topic(&raw, &[CacheKind::RemoteEval], &registry)
            .expect("unwatched valid hint short-circuits");
        assert_eq!(
            topic,
            Topic {
                team_id: 123,
                kind: CacheKind::RemoteEval
            }
        );

        // A live receiver disables the short-circuit: the confirm-read must run.
        let _rx = registry.subscribe(topic);
        assert!(unwatched_hint_topic(&raw, &[CacheKind::RemoteEval], &registry).is_none());

        // Malformed and off-tier hints fall through to decide_hint's accounting.
        assert!(unwatched_hint_topic("{not json", &[CacheKind::RemoteEval], &registry).is_none());
        assert!(unwatched_hint_topic(&raw, &[CacheKind::Definitions], &registry).is_none());
    }
}
