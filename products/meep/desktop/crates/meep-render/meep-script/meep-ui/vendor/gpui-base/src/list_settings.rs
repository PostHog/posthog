use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// Global settings for list presentation behavior.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
#[non_exhaustive]
pub struct ListSettings {
    /// Whether list items use the active highlight style by default.
    pub active_highlight: bool,
}

impl Default for ListSettings {
    fn default() -> Self {
        Self {
            active_highlight: true,
        }
    }
}
