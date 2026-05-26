//! Shared Cymbal domain types and helpers.

pub mod event;
pub mod exception;
pub mod frame;
pub mod release;
pub mod sanitize;

pub use event::{
    EventOutcome, EventResult, InputEvent, RateLimitAllowedEvent, RateLimitDecision,
    RateLimitGateOutput, RateLimitMode, MISSING_TEAM_ID_DROP_REASON, RATE_LIMITING_STAGE_ID,
    RATE_LIMITING_STAGE_TYPE, TEAM_ID_RATE_LIMIT_DROP_REASON,
};
pub use exception::{
    Exception, ExceptionList, ExceptionProperties, FingerprintRecordPart, Mechanism,
    OutputErrProps, RawErrProps, Stacktrace,
};
pub use frame::{Context, ContextLine, Frame, FrameRecord, RawFrame};
pub use release::{ReleaseInfo, ReleaseRecord};
pub use sanitize::{
    needs_sanitization, recursively_sanitize_properties, sanitize_source_line, sanitize_string,
    SanitizationError,
};
