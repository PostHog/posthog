//! Diagnostics shared by native and headless view hosts.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum FailureKind {
    SignIn,
    Permission,
    MissingTool,
    Logic,
    Network,
    Timeout,
    #[default]
    Unknown,
}

impl FailureKind {
    pub fn http_status(code: u16) -> Option<Self> {
        match code {
            401 => Some(Self::SignIn),
            403 => Some(Self::Permission),
            408 | 504 => Some(Self::Timeout),
            429 | 500..=599 => Some(Self::Network),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct HostError {
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<FailureKind>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capability: Option<String>,
}
impl HostError {
    pub fn classified(kind: FailureKind, message: impl Into<String>) -> Self {
        Self {
            kind: Some(kind),
            ..Self::from(message.into())
        }
    }
}
impl From<String> for HostError {
    fn from(message: String) -> Self {
        Self {
            message,
            kind: None,
            source: None,
            capability: None,
        }
    }
}
impl From<&str> for HostError {
    fn from(message: &str) -> Self {
        message.to_owned().into()
    }
}
impl From<HostError> for String {
    fn from(error: HostError) -> Self {
        error.message
    }
}
impl std::fmt::Display for HostError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for HostError {}
