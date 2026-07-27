//! Auth and admission (plan §2.8, §2.5).
//!
//! A [`Subscription`] is the single proof that a connection was authenticated,
//! admitted under the per-kind caps, and — for Mode 2 — allowlisted. It is only
//! constructible via [`Authenticator::authorize`], so the two-state connection
//! lifecycle (authorized → streaming) is encoded by type rather than by a phantom
//! typestate machine (plan §2.2).
//!
//! Token → team resolution reads the team-metadata HyperCache **Redis-only**
//! ([`HyperCacheReader::get_typed_redis_only`]): the gateway must not fan out to
//! S3/Postgres on a cold-cache reconnect storm and holds no Postgres pool. The
//! outcome maps to a fail-closed HTTP status ([`DenyReason`]) so a brief
//! post-team-creation cache gap yields 503 and SDKs stay on polling, never a
//! false 401 or an uncaught panic.

use std::net::IpAddr;
use std::num::NonZeroU32;
use std::sync::Arc;

use axum::http::StatusCode;
use common_hypercache::{HyperCacheError, HyperCacheReader, KeyType};
use governor::state::keyed::DefaultKeyedStateStore;
use governor::{clock::DefaultClock, Quota, RateLimiter};
use serde::Deserialize;
use thiserror::Error;
use tokio_util::sync::CancellationToken;

use crate::config::{RuntimeConfig, StaggerWindowSecs};
use crate::domain::{CacheKind, Topic};
use crate::registry::{ConnectionPermit, ConnectionPermits, PermitDenied};

/// `Retry-After` for a 429 denial, in seconds. Sized to the per-IP limiter's
/// one-minute window; a saturated per-token cap uses the same backoff so a
/// denied SDK falls back to polling for a bounded, non-thundering interval.
const RETRY_AFTER_SECS: u64 = 60;

/// A per-IP connect-rate limiter keyed on the client [`IpAddr`]. Governor's GCRA
/// gives the same burst-then-sustain shape as the flags-service limiters.
type IpConnectLimiter = RateLimiter<IpAddr, DefaultKeyedStateStore<IpAddr>, DefaultClock>;

/// A validated project API key from the request boundary — non-empty by
/// construction (parse-don't-validate, plan §2.2). The token is public (it rides
/// the query string because `EventSource` cannot set headers), so it is a lookup
/// key, never a secret to protect here.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProjectToken(String);

/// The `token` query param was empty.
#[derive(Debug, Error, PartialEq, Eq)]
#[error("project token must be non-empty")]
pub struct EmptyTokenError;

impl ProjectToken {
    /// Parse a raw query-param value into a token, rejecting the empty string.
    pub fn parse(raw: &str) -> Result<Self, EmptyTokenError> {
        if raw.is_empty() {
            Err(EmptyTokenError)
        } else {
            Ok(ProjectToken(raw.to_string()))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// The slice of the team-metadata cache payload the gateway needs: just the team
/// id. The payload is the full team metadata JSON; serde ignores every other
/// field (no `deny_unknown_fields`), so schema growth on the Django side never
/// breaks token resolution.
#[derive(Debug, Deserialize)]
struct TeamMetadata {
    id: common_types::TeamId,
}

/// Why a connection was refused, with its fail-closed HTTP mapping (plan §2.6,
/// §2.8). Browser `EventSource` treats every non-200 as fatal by design: the SDK
/// contract is "stream fails ⇒ fall back to polling", which is today's behavior.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
pub enum DenyReason {
    /// Sentinel/unknown token → 401. (An unknown token that was never cached is
    /// indistinguishable from the post-creation gap in a Redis-only probe and
    /// therefore fails closed to 503 via [`TeamCacheUnavailable`] instead.)
    #[error("unknown or unauthorized token")]
    Unauthorized,
    /// `remote_eval` for a team not on the Mode 2 allowlist → 403.
    #[error("team not admitted to remote_eval")]
    Forbidden,
    /// `definitions` per-token connection cap reached → 429 + Retry-After.
    #[error("per-token connection cap reached")]
    TokenCapReached,
    /// `definitions` per-IP connect rate exceeded → 429 + Retry-After.
    #[error("per-IP connect rate exceeded")]
    IpRateLimited,
    /// Per-pod global connection cap reached → 503.
    #[error("global connection cap reached")]
    GlobalCapReached,
    /// The pod is draining → 503 (readiness is already flipping SDKs elsewhere).
    #[error("gateway is draining")]
    Draining,
    /// Team cache absent-for-token or a Redis infra error → 503. Fail closed
    /// without Postgres (plan §2.8); the post-team-creation window lands here.
    #[error("team cache unavailable")]
    TeamCacheUnavailable,
}

impl DenyReason {
    /// The HTTP status this denial maps to.
    pub fn status(self) -> StatusCode {
        match self {
            DenyReason::Unauthorized => StatusCode::UNAUTHORIZED,
            DenyReason::Forbidden => StatusCode::FORBIDDEN,
            DenyReason::TokenCapReached | DenyReason::IpRateLimited => {
                StatusCode::TOO_MANY_REQUESTS
            }
            DenyReason::GlobalCapReached
            | DenyReason::Draining
            | DenyReason::TeamCacheUnavailable => StatusCode::SERVICE_UNAVAILABLE,
        }
    }

    /// `Retry-After` header value in seconds, when the status warrants one.
    pub fn retry_after_secs(self) -> Option<u64> {
        match self {
            DenyReason::TokenCapReached | DenyReason::IpRateLimited => Some(RETRY_AFTER_SECS),
            _ => None,
        }
    }

    /// The static `reason` label for the connect-denial counter (`denied:*`).
    pub fn metric_reason(self) -> &'static str {
        match self {
            DenyReason::Unauthorized => "denied:unauthorized",
            DenyReason::Forbidden => "denied:forbidden",
            DenyReason::TokenCapReached => "denied:token_cap",
            DenyReason::IpRateLimited => "denied:ip_rate",
            DenyReason::GlobalCapReached => "denied:global_cap",
            DenyReason::Draining => "denied:draining",
            DenyReason::TeamCacheUnavailable => "denied:team_cache_unavailable",
        }
    }
}

impl From<PermitDenied> for DenyReason {
    fn from(denied: PermitDenied) -> Self {
        match denied {
            PermitDenied::GlobalCapReached => DenyReason::GlobalCapReached,
            PermitDenied::TokenCapReached => DenyReason::TokenCapReached,
        }
    }
}

/// Proof of an authorized, admitted connection. Constructed only by
/// [`Authenticator::authorize`]. The RAII [`ConnectionPermit`] is released when
/// this value drops — which, once it has moved into the SSE stream, is the client
/// disconnect (plan §2.5).
pub struct Subscription {
    pub topic: Topic,
    pub stagger: StaggerWindowSecs,
    /// Held for the connection's lifetime; released on drop.
    permit: ConnectionPermit,
}

impl Subscription {
    /// Consume the subscription, returning the permit so a caller (the SSE
    /// stream) can hold it for the connection's lifetime.
    pub fn into_permit(self) -> ConnectionPermit {
        self.permit
    }
}

/// Authenticates tokens and admits connections under the per-kind caps (plan
/// §2.5, §2.8).
pub struct Authenticator {
    team_reader: Arc<HyperCacheReader>,
    config: Arc<RuntimeConfig>,
    permits: ConnectionPermits,
    /// `definitions`-only per-IP connect limiter. `None` disables per-IP limiting
    /// (there is deliberately no per-IP or per-token limiting for `remote_eval`,
    /// plan §2.5).
    ip_limiter: Option<Arc<IpConnectLimiter>>,
    /// The pod's shutdown token; a cancelled token denies new connects with 503.
    shutdown: CancellationToken,
}

impl Authenticator {
    pub fn new(
        team_reader: Arc<HyperCacheReader>,
        config: Arc<RuntimeConfig>,
        permits: ConnectionPermits,
        shutdown: CancellationToken,
    ) -> Self {
        // Build the per-IP limiter from the configured per-minute rate. A zero
        // rate disables it (an all-or-nothing 0-burst limiter would reject every
        // connect). `per_minute(n)` gives burst n, sustained n/min — the shape
        // the plan's §2.6 arithmetic assumes for the server tier.
        let ip_limiter = NonZeroU32::new(config.definitions_connect_rate_per_ip_per_minute)
            .map(|rate| Arc::new(RateLimiter::keyed(Quota::per_minute(rate))));
        Self {
            team_reader,
            config,
            permits,
            ip_limiter,
            shutdown,
        }
    }

    /// The only constructor of [`Subscription`].
    ///
    /// Order matters: draining is checked first (cheapest, and a draining pod
    /// should shed load before any Redis work); then the per-IP connect limiter
    /// runs — before the team probe, so an IP connect-flood is throttled without
    /// ever touching the team-metadata Redis tier; then the token is resolved to
    /// a team (needed for the topic and the Mode 2 allowlist); then kind-specific
    /// admission runs so a forbidden or rate-limited connect never consumes a
    /// permit it will not keep.
    pub async fn authorize(
        &self,
        token: ProjectToken,
        kind: CacheKind,
        client_ip: IpAddr,
    ) -> Result<Subscription, DenyReason> {
        if self.shutdown.is_cancelled() {
            return Err(DenyReason::Draining);
        }

        // Server-tier per-IP connect-rate limit (plan §2.5), ahead of any Redis
        // work so the limiter shields the team-metadata tier.
        if kind == CacheKind::Definitions {
            if let Some(limiter) = &self.ip_limiter {
                if limiter.check_key(&client_ip).is_err() {
                    return Err(DenyReason::IpRateLimited);
                }
            }
        }

        let team_id = self.resolve_team(&token).await?;
        let topic = Topic { team_id, kind };

        let permit = match kind {
            CacheKind::Definitions => self.permits.acquire_definitions(token.as_str())?,
            CacheKind::RemoteEval => {
                // Mode 2 admission is the allowlist plus the global cap — no
                // per-token or per-IP limit at the browser tier (plan §2.5).
                if !self.config.is_team_allowlisted_for_remote_eval(team_id) {
                    return Err(DenyReason::Forbidden);
                }
                self.permits.acquire_remote_eval()?
            }
        };

        Ok(Subscription {
            topic,
            stagger: self.config.stagger_for(team_id, kind),
            permit,
        })
    }

    /// Resolve a token to its team via the Redis-only team-metadata probe.
    async fn resolve_team(&self, token: &ProjectToken) -> Result<common_types::TeamId, DenyReason> {
        let key = KeyType::string(token.as_str());
        match self
            .team_reader
            .get_typed_redis_only::<TeamMetadata>(&key)
            .await
        {
            Ok(Some(meta)) => Ok(meta.id),
            // The `__missing__` sentinel: an authenticated "no team" answer.
            Ok(None) => Err(DenyReason::Unauthorized),
            // CacheMiss (key absent), decode failure, timeout, or a Redis infra
            // error — fail closed to 503 without touching Postgres (plan §2.8).
            Err(HyperCacheError::CacheMiss) | Err(_) => Err(DenyReason::TeamCacheUnavailable),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_token_rejects_empty() {
        assert_eq!(ProjectToken::parse(""), Err(EmptyTokenError));
        assert_eq!(ProjectToken::parse("phc_abc").unwrap().as_str(), "phc_abc");
    }

    #[test]
    fn deny_reason_status_mapping_is_fail_closed() {
        assert_eq!(DenyReason::Unauthorized.status(), StatusCode::UNAUTHORIZED);
        assert_eq!(DenyReason::Forbidden.status(), StatusCode::FORBIDDEN);
        assert_eq!(
            DenyReason::TokenCapReached.status(),
            StatusCode::TOO_MANY_REQUESTS
        );
        assert_eq!(
            DenyReason::IpRateLimited.status(),
            StatusCode::TOO_MANY_REQUESTS
        );
        assert_eq!(
            DenyReason::GlobalCapReached.status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(
            DenyReason::Draining.status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(
            DenyReason::TeamCacheUnavailable.status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
    }

    #[test]
    fn only_rate_limit_denials_carry_retry_after() {
        assert_eq!(DenyReason::TokenCapReached.retry_after_secs(), Some(60));
        assert_eq!(DenyReason::IpRateLimited.retry_after_secs(), Some(60));
        assert_eq!(DenyReason::Unauthorized.retry_after_secs(), None);
        assert_eq!(DenyReason::TeamCacheUnavailable.retry_after_secs(), None);
    }

    #[test]
    fn permit_denied_maps_to_deny_reason() {
        assert_eq!(
            DenyReason::from(PermitDenied::GlobalCapReached),
            DenyReason::GlobalCapReached
        );
        assert_eq!(
            DenyReason::from(PermitDenied::TokenCapReached),
            DenyReason::TokenCapReached
        );
    }
}
