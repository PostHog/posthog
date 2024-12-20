use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use thiserror::Error;

#[derive(Debug, Serialize, Deserialize)]
pub struct ExecOptions {
    pub globals: Option<HashMap<String, serde_json::Value>>,
    pub functions: Option<HashMap<String, fn(Vec<serde_json::Value>) -> serde_json::Value>>,
    pub async_functions: Option<HashMap<String, fn(Vec<serde_json::Value>) -> std::pin::Pin<Box<dyn std::future::Future<Output = serde_json::Value>>>>>,
    pub timeout: Option<u64>,
    pub max_async_steps: Option<u64>,
    pub memory_limit: Option<u64>,
}

impl Default for ExecOptions {
    fn default() -> Self {
        ExecOptions {
            globals: None,
            functions: None,
            async_functions: None,
            timeout: Some(5000),
            max_async_steps: Some(100),
            memory_limit: Some(64 * 1024 * 1024),
        }
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ExecResult {
    pub result: serde_json::Value,
    pub finished: bool,
    pub error: Option<String>,
    pub async_function_name: Option<String>,
    pub async_function_args: Option<Vec<serde_json::Value>>,
}

#[derive(Debug, Error)]
pub enum ExecError {
    #[error("Execution error: {0}")]
    ExecutionError(String),
}

pub fn exec_sync(bytecode: &[u8], options: &ExecOptions) -> Result<ExecResult, ExecError> {
    let result = exec(bytecode, options)?;
    if result.finished {
        Ok(result)
    } else {
        Err(ExecError::ExecutionError("Unexpected async function call".to_string()))
    }
}

pub async fn exec_async(bytecode: &[u8], options: &ExecOptions) -> Result<ExecResult, ExecError> {
    let mut vm_state: Option<ExecResult> = None;
    loop {
        let result = exec(bytecode, options)?;
        if result.finished {
            return Ok(result);
        }
        if let Some(async_function_name) = &result.async_function_name {
            if let Some(async_function) = options.async_functions.as_ref().and_then(|f| f.get(async_function_name)) {
                let async_result = async_function(result.async_function_args.clone().unwrap_or_default()).await;
                vm_state = Some(ExecResult {
                    result: async_result,
                    finished: false,
                    error: None,
                    async_function_name: None,
                    async_function_args: None,
                });
            } else {
                return Err(ExecError::ExecutionError(format!("Invalid async function call: {}", async_function_name)));
            }
        } else {
            return Err(ExecError::ExecutionError("Invalid async function call".to_string()));
        }
    }
}

fn exec(bytecode: &[u8], options: &ExecOptions) -> Result<ExecResult, ExecError> {
    // Placeholder implementation
    Ok(ExecResult {
        result: serde_json::Value::Null,
        finished: true,
        error: None,
        async_function_name: None,
        async_function_args: None,
    })
}
