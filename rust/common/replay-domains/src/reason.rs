/// Response key that carries [`SessionRecordingDisabledReason`].
///
/// A sibling of `sessionRecording`, because `sessionRecording` itself must stay `false`
/// for SDKs that read it as a boolean.
pub const SESSION_RECORDING_DISABLED_REASON_KEY: &str = "sessionRecordingDisabledReason";

/// Why `sessionRecording` is `false` on a `/flags` or `/config` response.
///
/// The three causes look the same to the SDK and to the person who asks why a
/// recording is missing, so the response names the one that applies.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionRecordingDisabledReason {
    /// Session replay is off in the project settings.
    NotEnabled,
    /// The team has authorized domains for replay, and the request is not on one.
    DomainNotAllowed,
    /// The team is over its recordings quota.
    QuotaLimited,
}

impl SessionRecordingDisabledReason {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::NotEnabled => "not_enabled",
            Self::DomainNotAllowed => "domain_not_allowed",
            Self::QuotaLimited => "quota_limited",
        }
    }
}
