use serde_json::Value;

use crate::error::Error;

pub struct VmState {}

pub enum ExecutionContext {}

type ExecutionResult = Result<Option<Value>, Error>;

pub fn execute(state: &mut VmState, context: &ExecutionContext) -> ExecutionResult {
    Ok(None)
}
