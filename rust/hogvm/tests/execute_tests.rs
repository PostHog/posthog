use crate::execute::{exec_async, exec_sync, ExecOptions};
use serde_json::json;
use tokio::runtime::Runtime;

#[test]
fn test_exec_sync() {
    let bytecode = vec![1, 2, 3, 4];
    let options = ExecOptions::default();
    let result = exec_sync(&bytecode, &options).unwrap();
    assert_eq!(result.result, json!(null));
    assert!(result.finished);
    assert!(result.error.is_none());
}

#[test]
fn test_exec_async() {
    let bytecode = vec![1, 2, 3, 4];
    let options = ExecOptions::default();
    let rt = Runtime::new().unwrap();
    let result = rt.block_on(exec_async(&bytecode, &options)).unwrap();
    assert_eq!(result.result, json!(null));
    assert!(result.finished);
    assert!(result.error.is_none());
}

#[test]
fn test_bytecode_operations() {
    let bytecode = vec![1, 2, 3, 4];
    let options = ExecOptions::default();
    let result = exec_sync(&bytecode, &options).unwrap();
    assert_eq!(result.result, json!(null));
    assert!(result.finished);
    assert!(result.error.is_none());
}

#[test]
fn test_error_handling() {
    let bytecode = vec![1, 2, 3, 4];
    let options = ExecOptions::default();
    let result = exec_sync(&bytecode, &options);
    assert!(result.is_err());
}
