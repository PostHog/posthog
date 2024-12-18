use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum HogVMException {
    #[error("HogVMException: {0}")]
    Exception(String),
}

#[derive(Debug, Error)]
pub enum UncaughtHogVMException {
    #[error("UncaughtHogVMException: {0}")]
    Exception(String),
}

pub fn calculate_cost(object: &serde_json::Value) -> u64 {
    match object {
        serde_json::Value::Null => 1,
        serde_json::Value::Bool(_) => 1,
        serde_json::Value::Number(_) => 1,
        serde_json::Value::String(s) => s.len() as u64,
        serde_json::Value::Array(arr) => arr.iter().map(|v| calculate_cost(v)).sum(),
        serde_json::Value::Object(obj) => obj.iter().map(|(k, v)| k.len() as u64 + calculate_cost(v)).sum(),
    }
}

pub fn convert_js_to_hog(value: &serde_json::Value) -> serde_json::Value {
    value.clone()
}

pub fn convert_hog_to_js(value: &serde_json::Value) -> serde_json::Value {
    value.clone()
}
