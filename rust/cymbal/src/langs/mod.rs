use serde::{Deserialize, Serialize};

pub mod custom;
pub mod dart;
pub mod go;
pub mod hermes;
pub mod java;
pub mod js;
pub mod node;
pub mod python;
pub mod ruby;
pub mod utils;

// Some metadata is common across all languages, so we define it here. In some
// platforms, these may always default to false.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize, Default)]
pub struct CommonFrameMetadata {
    #[serde(default = "default_in_app")]
    pub in_app: bool, // Whether the frame is part of application or library code
    #[serde(default)]
    pub synthetic: bool, // Whether the frame is synthetic or not
}

fn default_in_app() -> bool {
    true
}
