use serde::{self, Deserialize, Serialize};

#[derive(Debug, Deserialize, Serialize, Clone, Hash, Eq, PartialEq)]
pub struct FrameId {
    pub raw_id: String,
    #[serde(skip)]
    pub team_id: i32,
}

impl FrameId {
    pub fn new(raw_id: String, team_id: i32) -> Self {
        FrameId { raw_id, team_id }
    }

    pub fn placeholder() -> Self {
        FrameId {
            raw_id: "placeholder".to_string(),
            team_id: 0,
        }
    }
}

// We emit a single, unified representation of a frame, which is what we pass on to users.
#[derive(Debug, Clone, Serialize, Deserialize, Eq, PartialEq)]
pub struct FrameData {
    pub raw_id: String,       // The raw frame id this was resolved from
    pub mangled_name: String, // Mangled name of the function
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<u32>, // Line the function is define on, if known
    #[serde(skip_serializing_if = "Option::is_none")]
    pub column: Option<u32>, // Column the function is defined on, if known
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>, // Generally, the file the function is defined in
    pub in_app: bool,         // We hard-require clients to tell us this?
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resolved_name: Option<String>, // The name of the function, after symbolification
    pub lang: String,         // The language of the frame. Always known (I guess?)
    pub resolved: bool,       // Did we manage to resolve the frame?

    #[serde(default)] // Defaults to false
    pub synthetic: bool, // Some SDKs construct stack traces, or partially reconstruct them. This flag indicates whether the frame is synthetic or not.
}
