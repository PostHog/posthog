use serde::{Deserialize, Deserializer, Serialize};

use crate::core::types::frames::RawFrame;
use crate::core::types::{stacktrace::Stacktrace, Mechanism};

/// Stand-in type for exceptions whose SDK omitted `type`. Dropping the whole
/// event instead would cost its stack trace and its issue grouping.
pub const DEFAULT_EXCEPTION_TYPE: &str = "Error";

fn default_exception_type() -> String {
    DEFAULT_EXCEPTION_TYPE.to_string()
}

/// Some SDKs send an explicit `null` rather than omitting the field, which
/// `#[serde(default)]` alone does not cover.
fn nullable_exception_type<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: Deserializer<'de>,
{
    Ok(Option::<String>::deserialize(deserializer)?.unwrap_or_else(default_exception_type))
}

fn nullable_string<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: Deserializer<'de>,
{
    Ok(Option::<String>::deserialize(deserializer)?.unwrap_or_default())
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Exception {
    #[serde(rename = "id", skip_serializing_if = "Option::is_none")]
    pub exception_id: Option<String>,
    #[serde(
        rename = "type",
        default = "default_exception_type",
        deserialize_with = "nullable_exception_type"
    )]
    pub exception_type: String,
    #[serde(rename = "value", default, deserialize_with = "nullable_string")]
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

impl Exception {
    pub fn get_raw_frame(&self) -> &[RawFrame] {
        self.stack
            .as_ref()
            .map(|s| s.get_raw_frames())
            .unwrap_or_default()
    }

    pub fn get_first_raw_frame(&self) -> Option<&RawFrame> {
        self.get_raw_frame().first()
    }
}
