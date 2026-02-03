use serde::{Deserialize, Serialize};

use crate::types::{stacktrace::Stacktrace, Mechanism};

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Exception {
    #[serde(rename = "id", skip_serializing_if = "Option::is_none")]
    pub exception_id: Option<String>,
    #[serde(rename = "type")]
    pub exception_type: String,
    #[serde(rename = "value", default)]
    pub exception_message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mechanism: Option<Mechanism>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub module: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub thread_id: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none", rename = "stacktrace")]
    pub stack: Option<Stacktrace>,
}
