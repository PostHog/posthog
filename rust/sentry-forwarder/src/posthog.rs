 use serde::{Deserialize, Serialize};
 use std::collections::HashMap;

 #[derive(Debug, Serialize, Deserialize)]
 pub struct PostHogEvent {
     pub api_key: String,
     pub event: String,
     pub properties: PostHogProperties,
     pub timestamp: Option<String>,
 }

 #[derive(Debug, Serialize, Deserialize)]
 pub struct PostHogProperties {
     pub distinct_id: String,
     #[serde(rename = "$exception_list")]
     pub exception_list: Vec<PostHogException>,
     #[serde(rename = "$exception_level", skip_serializing_if = "Option::is_none")]
     pub exception_level: Option<String>,
     #[serde(rename = "$exception_fingerprint", skip_serializing_if = "Option::is_none")]
     pub exception_fingerprint: Option<String>,
     #[serde(rename = "$exception_personURL", skip_serializing_if = "Option::is_none")]
     pub exception_person_url: Option<String>,
     #[serde(rename = "$exception_DOMException_code", skip_serializing_if = "Option::is_none")]
     pub exception_dom_exception_code: Option<String>,

     // Additional properties from Sentry event
     #[serde(rename = "$current_url", skip_serializing_if = "Option::is_none")]
     pub current_url: Option<String>,
     #[serde(rename = "$os", skip_serializing_if = "Option::is_none")]
     pub os: Option<String>,
     #[serde(rename = "$browser", skip_serializing_if = "Option::is_none")]
     pub browser: Option<String>,
     #[serde(rename = "$device", skip_serializing_if = "Option::is_none")]
     pub device: Option<String>,
     #[serde(rename = "$lib", skip_serializing_if = "Option::is_none")]
     pub lib: Option<String>,
     #[serde(rename = "$lib_version", skip_serializing_if = "Option::is_none")]
     pub lib_version: Option<String>,

     // Sentry-specific metadata
     #[serde(rename = "sentry_event_id", skip_serializing_if = "Option::is_none")]
     pub sentry_event_id: Option<String>,
     #[serde(rename = "sentry_release", skip_serializing_if = "Option::is_none")]
     pub sentry_release: Option<String>,
     #[serde(rename = "sentry_environment", skip_serializing_if = "Option::is_none")]
     pub sentry_environment: Option<String>,
     #[serde(rename = "sentry_platform", skip_serializing_if = "Option::is_none")]
     pub sentry_platform: Option<String>,
     #[serde(rename = "sentry_tags", skip_serializing_if = "Option::is_none")]
     pub sentry_tags: Option<HashMap<String, String>>,

     #[serde(flatten)]
     pub extra: HashMap<String, serde_json::Value>,
 }

 #[derive(Debug, Serialize, Deserialize, Clone)]
 pub struct PostHogException {
     #[serde(rename = "type", skip_serializing_if = "Option::is_none")]
     pub exception_type: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub value: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub module: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub thread_id: Option<i32>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub mechanism: Option<PostHogMechanism>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub stacktrace: Option<PostHogStacktrace>,
 }

 #[derive(Debug, Serialize, Deserialize, Clone)]
 pub struct PostHogMechanism {
     #[serde(skip_serializing_if = "Option::is_none")]
     pub handled: Option<bool>,
     #[serde(rename = "type", skip_serializing_if = "Option::is_none")]
     pub mechanism_type: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub source: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub synthetic: Option<bool>,
 }

 #[derive(Debug, Serialize, Deserialize, Clone)]
 pub struct PostHogStacktrace {
     pub frames: Vec<PostHogStackFrame>,
     #[serde(rename = "type")]
     pub stacktrace_type: String,
 }

 #[derive(Debug, Serialize, Deserialize, Clone)]
 pub struct PostHogStackFrame {
     pub platform: String,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub filename: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub function: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub module: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub lineno: Option<i32>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub colno: Option<i32>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub abs_path: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub context_line: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub pre_context: Option<Vec<String>>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub post_context: Option<Vec<String>>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub in_app: Option<bool>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub instruction_addr: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub addr_mode: Option<String>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub vars: Option<HashMap<String, serde_json::Value>>,
     #[serde(skip_serializing_if = "Option::is_none")]
     pub chunk_id: Option<String>,
 }