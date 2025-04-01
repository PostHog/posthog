use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum Error {
    #[error(transparent)]
    VM(#[from] VmError),
}

#[derive(Debug, Error)]
pub enum VmError {
    #[error("Expected operation, got {0:?}")]
    NotAnOperation(Value),
    #[error("Invalid operation {0:?}")]
    InvalidOperation(Value),
    #[error("Unexpected end of program at address {0}")]
    EndOfProgram(usize),
    #[error("Invalid value of type {0}, expected {1}")]
    InvalidValue(String, String),
    #[error("Stack overflow at address {0}")]
    StackOverflow(usize),
    #[error("Stack underflow at address {0}")]
    StackUnderflow(usize),
    #[error("Unknown Global {0}")]
    UnknownGlobal(String),
    #[error("Division by zero")]
    DivisionByZero,
    #[error("Cannot coerce types {0} and {1}")]
    CannotCoerce(String, String),
    #[error("Invalid number {0}")]
    InvalidNumber(String),
    #[error("Not implemented: {0}")]
    NotImplemented(String),
}
