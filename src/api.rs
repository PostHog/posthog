use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Deserialize, Serialize)]
pub struct CaptureRequest {
    #[serde(alias = "$token", alias = "api_key")]
    pub token: String,

    pub event: String,
    pub properties: HashMap<String, Value>,
}

#[derive(Debug, Deserialize, Serialize)]
pub enum CaptureResponseCode {
    Ok = 1,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct CaptureResponse {
    pub status: CaptureResponseCode,
}
