use serde::{Deserialize, Serialize};

use crate::error_tracking::FrameData;

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ExceptionData {
    pub r#type: String,
    pub value: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub frames: Option<Vec<FrameData>>,
}
