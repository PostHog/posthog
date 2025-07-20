 use serde::{Deserialize, Serialize};
 use std::collections::HashMap;

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryEvent {
     pub event_id: String,
     pub timestamp: Option<f64>,
     pub platform: Option<String>,
     pub level: Option<String>,
     pub logger: Option<String>,
     pub transaction: Option<String>,
     pub server_name: Option<String>,
     pub release: Option<String>,
     pub environment: Option<String>,
     pub message: Option<String>,
     pub modules: Option<HashMap<String, String>>,
     pub extra: Option<HashMap<String, serde_json::Value>>,
     pub tags: Option<HashMap<String, String>>,
     pub contexts: Option<SentryContexts>,
     pub request: Option<SentryRequest>,
     pub exception: Option<SentryExceptionContainer>,
     pub breadcrumbs: Option<Vec<SentryBreadcrumb>>,
     pub user: Option<SentryUser>,
     pub sdk: Option<SentrySdk>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryExceptionContainer {
     pub values: Option<Vec<SentryException>>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryException {
     #[serde(rename = "type")]
     pub exception_type: Option<String>,
     pub value: Option<String>,
     pub module: Option<String>,
     pub thread_id: Option<i32>,
     pub mechanism: Option<SentryMechanism>,
     pub stacktrace: Option<SentryStacktrace>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryMechanism {
     #[serde(rename = "type")]
     pub mechanism_type: String,
     pub description: Option<String>,
     pub help_link: Option<String>,
     pub handled: Option<bool>,
     pub synthetic: Option<bool>,
     pub meta: Option<HashMap<String, serde_json::Value>>,
     pub data: Option<HashMap<String, serde_json::Value>>,
     pub exception_id: Option<i32>,
     pub parent_id: Option<i32>,
     pub is_exception_group: Option<bool>,
     pub source: Option<String>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryStacktrace {
     pub frames: Option<Vec<SentryStackFrame>>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryStackFrame {
     pub filename: Option<String>,
     pub function: Option<String>,
     pub raw_function: Option<String>,
     pub module: Option<String>,
     pub lineno: Option<i32>,
     pub colno: Option<i32>,
     pub abs_path: Option<String>,
     pub context_line: Option<String>,
     pub pre_context: Option<Vec<String>>,
     pub post_context: Option<Vec<String>>,
     pub in_app: Option<bool>,
     pub vars: Option<HashMap<String, serde_json::Value>>,
     pub instruction_addr: Option<String>,
     pub addr_mode: Option<String>,
     pub platform: Option<String>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryContexts {
     pub os: Option<SentryOsContext>,
     pub runtime: Option<SentryRuntimeContext>,
     pub trace: Option<SentryTraceContext>,
     pub device: Option<HashMap<String, serde_json::Value>>,
     pub app: Option<HashMap<String, serde_json::Value>>,
     pub browser: Option<HashMap<String, serde_json::Value>>,
     pub gpu: Option<HashMap<String, serde_json::Value>>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryOsContext {
     pub name: Option<String>,
     pub version: Option<String>,
     pub build: Option<String>,
     pub kernel_version: Option<String>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryRuntimeContext {
     pub name: Option<String>,
     pub version: Option<String>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryTraceContext {
     pub span_id: Option<String>,
     pub trace_id: Option<String>,
     pub op: Option<String>,
     pub status: Option<String>,
     pub data: Option<HashMap<String, serde_json::Value>>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryRequest {
     pub url: Option<String>,
     pub method: Option<String>,
     pub data: Option<serde_json::Value>,
     pub query_string: Option<String>,
     pub cookies: Option<String>,
     pub headers: Option<HashMap<String, Vec<String>>>,
     pub env: Option<HashMap<String, String>>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryBreadcrumb {
     pub timestamp: Option<f64>,
     pub message: Option<String>,
     pub category: Option<String>,
     pub level: Option<String>,
     pub data: Option<HashMap<String, serde_json::Value>>,
     #[serde(rename = "type")]
     pub breadcrumb_type: Option<String>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryUser {
     pub id: Option<String>,
     pub email: Option<String>,
     pub ip_address: Option<String>,
     pub username: Option<String>,
     pub name: Option<String>,
     pub data: Option<HashMap<String, serde_json::Value>>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentrySdk {
     pub name: Option<String>,
     pub version: Option<String>,
     pub integrations: Option<Vec<String>>,
     pub packages: Option<Vec<SentryPackage>>,
 }

 #[derive(Debug, Deserialize, Serialize)]
 pub struct SentryPackage {
     pub name: Option<String>,
     pub version: Option<String>,
 }