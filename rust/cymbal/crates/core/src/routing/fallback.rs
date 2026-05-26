//! Transport-neutral fallback and attempt-failure classification.
//!
//! These types describe the safe response to a single attempt failure: try
//! another candidate, retry the original items, or surface a terminal error.
//! Mapping concrete transport errors (tonic codes, timeouts, etc.) into these
//! categories is the transport layer's job and lives in `cymbal-server`.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AttemptFailureKind {
    /// The caller rejected the endpoint before any remote work was attempted,
    /// for example because a local circuit breaker was open.
    PreCallEjected,
    /// The remote executor rejected the request before starting item work
    /// because it could not reserve capacity.
    PreWorkResourceExhausted,
    /// The remote executor explicitly rejected the request before item work
    /// for a non-capacity reason that is still safe to retry elsewhere.
    PreWorkRejected,
    /// The caller timed out after sending work and cannot prove whether item
    /// side effects happened.
    AmbiguousTimeout,
    /// The transport failed after the request may have reached the executor.
    AmbiguousTransport,
    /// The executor returned item-level failures; these should stay attached
    /// to the original items rather than trigger endpoint fallback.
    RemoteItemErrors,
}

impl AttemptFailureKind {
    pub fn is_pre_work(self) -> bool {
        matches!(
            self,
            Self::PreCallEjected | Self::PreWorkResourceExhausted | Self::PreWorkRejected
        )
    }

    pub fn is_ambiguous(self) -> bool {
        matches!(self, Self::AmbiguousTimeout | Self::AmbiguousTransport)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FallbackDecision {
    TryNextCandidate,
    RetryOriginalItems { retry_after_ms: Option<u64> },
    TerminalError { retryable: bool },
}

impl FallbackDecision {
    pub fn should_try_next_candidate(self) -> bool {
        matches!(self, Self::TryNextCandidate)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FallbackPolicy {
    pub allow_pre_work_fallback: bool,
    pub allow_ambiguous_fallback: bool,
    /// Maximum number of already-completed fallback attempts. `None` leaves
    /// candidate count entirely to the routing policy.
    pub max_attempts: Option<usize>,
}

impl FallbackPolicy {
    pub fn pre_work_only() -> Self {
        Self {
            allow_pre_work_fallback: true,
            allow_ambiguous_fallback: false,
            max_attempts: None,
        }
    }

    pub fn no_fallback() -> Self {
        Self {
            allow_pre_work_fallback: false,
            allow_ambiguous_fallback: false,
            max_attempts: Some(0),
        }
    }

    pub fn decide(
        &self,
        failure: AttemptFailureKind,
        completed_fallback_attempts: usize,
    ) -> FallbackDecision {
        let attempts_exhausted = self
            .max_attempts
            .is_some_and(|max_attempts| completed_fallback_attempts >= max_attempts);

        if !attempts_exhausted
            && ((failure.is_pre_work() && self.allow_pre_work_fallback)
                || (failure.is_ambiguous() && self.allow_ambiguous_fallback))
        {
            return FallbackDecision::TryNextCandidate;
        }

        match failure {
            AttemptFailureKind::RemoteItemErrors => {
                FallbackDecision::TerminalError { retryable: false }
            }
            AttemptFailureKind::PreCallEjected
            | AttemptFailureKind::PreWorkResourceExhausted
            | AttemptFailureKind::PreWorkRejected
            | AttemptFailureKind::AmbiguousTimeout
            | AttemptFailureKind::AmbiguousTransport => FallbackDecision::RetryOriginalItems {
                retry_after_ms: None,
            },
        }
    }
}
