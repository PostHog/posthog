//! Exception-pipeline event contracts.
//!
//! These types model the typed boundary between the exception pipeline's
//! stages: an [`InputEvent`] flowing in, the rate-limit gate output that
//! either keeps the event in the pipeline or short-circuits it to a terminal
//! result, and the per-event [`EventResult`] that the pipeline ultimately
//! emits. They live in `cymbal-domain` (rather than `cymbal-core`) because
//! they describe the exception domain; `cymbal-core` only provides the
//! generic stage framework that this contract is plugged into.
//!
//! The remote stage wire shapes are kept stable: the `StagePayload::TYPE`
//! strings still report the `cymbal.core` namespace. `StageType.namespace`
//! is just a label on the wire, so moving the Rust module out of
//! `cymbal-core` does not break the registry assertions, snapshots, remote
//! codecs, or generated Node bindings.

use cymbal_core::{IdentifiedItem, Metadata, StagePayload, StageType};
use serde::{Deserialize, Serialize};

use crate::ExceptionProperties;

pub const RATE_LIMITING_STAGE_ID: &str = "rate-limiting:v1";
pub const RATE_LIMITING_STAGE_TYPE: StageType = StageType {
    namespace: "cymbal.stage",
    name: "rate-limiting",
    version: 1,
};
pub const MISSING_TEAM_ID_DROP_REASON: &str = "missing_team_id";
pub const TEAM_ID_RATE_LIMIT_DROP_REASON: &str = "rate_limited:team_id";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InputEvent {
    pub event_id: String,
    pub team_id: i64,
    pub properties: ExceptionProperties,
}

impl StagePayload for InputEvent {
    const TYPE: StageType = StageType {
        namespace: "cymbal.core",
        name: "InputEvent",
        version: 2,
    };
}

/// Pre-resolution team rate-limiter stage output.
///
/// The `rate-limiting:v1` stage is an internal Cymbal gate keyed by `team_id`.
/// It intentionally does not change the public `ProcessExceptionBatch` request:
/// Node still sends event-oriented batches and still receives final per-event
/// `drop` / `retry` / `error` outcomes through the existing response stream.
///
/// Allowed events carry the original `InputEvent` plus the limiter decision that
/// was observed, so reporting mode can record a would-have-dropped decision
/// without dropping. Terminal outcomes bypass resolution/grouping/linking and
/// are merged back by the orchestrator as final `EventResult`s. This keeps the
/// downstream linear `InputEvent -> ResolvedEvent` contract free of dropped
/// events while preserving one final public outcome per input event.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum RateLimitGateOutput {
    Allowed(RateLimitAllowedEvent),
    Terminal(EventResult),
}

impl StagePayload for RateLimitGateOutput {
    const TYPE: StageType = StageType {
        namespace: "cymbal.core",
        name: "RateLimitGateOutput",
        version: 2,
    };
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RateLimitAllowedEvent {
    pub event: InputEvent,
    pub decision: RateLimitDecision,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RateLimitMode {
    Disabled,
    Reporting,
    Enforcing,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RateLimitDecision {
    /// Limiter disabled by config: allow and do not consume limiter capacity.
    Disabled,
    /// Missing `team_id`: allow because there is no stable tenant key.
    ///
    /// Public API ingestion drops missing-team events before they become
    /// `InputEvent`s. This variant remains for older remote/internal callers
    /// that still surface the rate-limit decision directly.
    MissingTeamId,
    /// Limiter checked the `team_id` key and allowed the event.
    Allowed { team_id: i64 },
    /// Limiter checked the `team_id` key and found it over limit.
    Limited { team_id: i64, reason: String },
    /// Limiter infrastructure failed: fail open and let the event continue.
    LimiterError { message: String },
}

impl RateLimitGateOutput {
    /// Apply the stable team-id limiter policy to a computed decision.
    ///
    /// Intended behavior for `rate-limiting:v1`:
    /// - missing `team_id` allows the event (`MissingTeamId`),
    /// - disabled limiter allows the event (`Disabled`),
    /// - limiter infrastructure errors fail open (`LimiterError`),
    /// - enforced limits drop with `rate_limited:team_id`, and
    /// - reporting mode records `Limited` decisions without dropping.
    pub fn from_team_id_decision(
        event: InputEvent,
        mode: RateLimitMode,
        decision: RateLimitDecision,
    ) -> Self {
        match mode {
            RateLimitMode::Disabled => Self::allowed(event, RateLimitDecision::Disabled),
            RateLimitMode::Reporting => Self::allowed(event, decision),
            RateLimitMode::Enforcing => match decision {
                RateLimitDecision::Limited { reason, .. } => Self::drop(event.event_id, reason),
                decision => Self::allowed(event, decision),
            },
        }
    }

    pub fn allowed(event: InputEvent, decision: RateLimitDecision) -> Self {
        Self::Allowed(RateLimitAllowedEvent { event, decision })
    }

    pub fn drop(event_id: String, reason: String) -> Self {
        Self::Terminal(EventResult {
            event_id,
            outcome: EventOutcome::Drop { reason },
        })
    }

    pub fn event_id(&self) -> &str {
        match self {
            Self::Allowed(allowed) => &allowed.event.event_id,
            Self::Terminal(result) => &result.event_id,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EventResult {
    pub event_id: String,
    pub outcome: EventOutcome,
}

impl StagePayload for EventResult {
    const TYPE: StageType = StageType {
        namespace: "cymbal.core",
        name: "EventResult",
        version: 2,
    };
}

impl IdentifiedItem for EventResult {
    fn item_id(&self) -> &str {
        self.event_id.as_str()
    }
}

// `EventOutcome::Next` carries the resolved `ExceptionProperties` (~384 bytes)
// while the failure variants are only a handful of strings/options. Boxing the
// dominant success variant would add an allocation on the happy path for every
// processed event and ripple through every construction and destructuring
// site across the stage crates; instead we accept the size disparity and keep
// the wire shape stable.
#[allow(clippy::large_enum_variant)]
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum EventOutcome {
    Next {
        properties: Option<ExceptionProperties>,
        metadata: Metadata,
    },
    Drop {
        reason: String,
    },
    Retry {
        reason: String,
        retry_after_ms: Option<u64>,
    },
    Error {
        message: String,
        code: Option<String>,
        retryable: Option<bool>,
    },
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn moved_event_contract_payload_type_strings_remain_stable() {
        assert_eq!(InputEvent::TYPE.to_string(), "cymbal.core.InputEvent@2");
        assert_eq!(
            RateLimitGateOutput::TYPE.to_string(),
            "cymbal.core.RateLimitGateOutput@2"
        );
        assert_eq!(EventResult::TYPE.to_string(), "cymbal.core.EventResult@2");
    }

    fn input_event(team_id: i64) -> InputEvent {
        InputEvent {
            event_id: "event-1".to_string(),
            team_id,
            properties: ExceptionProperties::default(),
        }
    }

    #[test]
    fn rate_limit_gate_allows_missing_team_id() {
        let output = RateLimitGateOutput::from_team_id_decision(
            input_event(0),
            RateLimitMode::Enforcing,
            RateLimitDecision::MissingTeamId,
        );

        assert!(matches!(
            output,
            RateLimitGateOutput::Allowed(RateLimitAllowedEvent {
                decision: RateLimitDecision::MissingTeamId,
                ..
            })
        ));
    }

    #[test]
    fn rate_limit_gate_disabled_mode_allows_without_preserving_limited_decision() {
        let output = RateLimitGateOutput::from_team_id_decision(
            input_event(2),
            RateLimitMode::Disabled,
            RateLimitDecision::Limited {
                team_id: 2,
                reason: TEAM_ID_RATE_LIMIT_DROP_REASON.to_string(),
            },
        );

        assert!(matches!(
            output,
            RateLimitGateOutput::Allowed(RateLimitAllowedEvent {
                decision: RateLimitDecision::Disabled,
                ..
            })
        ));
    }

    #[test]
    fn rate_limit_gate_limiter_errors_fail_open() {
        let output = RateLimitGateOutput::from_team_id_decision(
            input_event(2),
            RateLimitMode::Enforcing,
            RateLimitDecision::LimiterError {
                message: "redis unavailable".to_string(),
            },
        );

        assert!(matches!(
            output,
            RateLimitGateOutput::Allowed(RateLimitAllowedEvent {
                decision: RateLimitDecision::LimiterError { .. },
                ..
            })
        ));
    }

    #[test]
    fn rate_limit_gate_enforced_limits_drop_with_stable_reason() {
        let output = RateLimitGateOutput::from_team_id_decision(
            input_event(2),
            RateLimitMode::Enforcing,
            RateLimitDecision::Limited {
                team_id: 2,
                reason: TEAM_ID_RATE_LIMIT_DROP_REASON.to_string(),
            },
        );

        assert_eq!(output.event_id(), "event-1");
        assert_eq!(
            output,
            RateLimitGateOutput::Terminal(EventResult {
                event_id: "event-1".to_string(),
                outcome: EventOutcome::Drop {
                    reason: TEAM_ID_RATE_LIMIT_DROP_REASON.to_string(),
                },
            })
        );
    }

    #[test]
    fn rate_limit_gate_reporting_mode_records_limited_decisions_without_dropping() {
        let output = RateLimitGateOutput::from_team_id_decision(
            input_event(2),
            RateLimitMode::Reporting,
            RateLimitDecision::Limited {
                team_id: 2,
                reason: TEAM_ID_RATE_LIMIT_DROP_REASON.to_string(),
            },
        );

        assert!(matches!(
            output,
            RateLimitGateOutput::Allowed(RateLimitAllowedEvent {
                decision: RateLimitDecision::Limited { team_id: 2, .. },
                ..
            })
        ));
    }
}
