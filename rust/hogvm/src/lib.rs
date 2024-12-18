use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::runtime::Runtime;

mod execute;
mod operation;
mod utils;

#[derive(Debug, Serialize, Deserialize)]
pub struct HogVM {
    bytecode: Vec<u8>,
    globals: Option<serde_json::Value>,
}

impl HogVM {
    pub fn new(bytecode: Vec<u8>, globals: Option<serde_json::Value>) -> Self {
        HogVM { bytecode, globals }
    }

    pub fn execute(&self) -> Result<serde_json::Value, HogVMError> {
        let rt = Runtime::new().map_err(|e| HogVMError::RuntimeError(e.to_string()))?;
        rt.block_on(async { self.execute_async().await })
    }

    pub async fn execute_async(&self) -> Result<serde_json::Value, HogVMError> {
        let options = execute::ExecOptions {
            globals: self.globals.clone(),
            ..Default::default()
        };
        let result = execute::exec_async(&self.bytecode, &options).await?;
        Ok(result.result)
    }
}

#[derive(Debug, Error)]
pub enum HogVMError {
    #[error("Runtime error: {0}")]
    RuntimeError(String),
    #[error("Execution error: {0}")]
    ExecutionError(String),
}
