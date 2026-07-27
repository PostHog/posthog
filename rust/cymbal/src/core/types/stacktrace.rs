use serde::{Deserialize, Serialize};

use crate::core::types::frames::{Frame, RawFrame};

#[derive(Debug, Deserialize, Serialize, Clone)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Stacktrace {
    Raw { frames: Vec<RawFrame> },
    Resolved { frames: Vec<Frame> },
}
