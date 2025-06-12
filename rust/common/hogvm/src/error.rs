use serde_json::Value;
use thiserror::Error;

// TBH this is probably need to be broken up somehow
#[derive(Debug, Error, Clone)]
#[non_exhaustive]
pub enum VmError {
    #[error("Expected operation, got {0:?}")]
    NotAnOperation(Value),
    #[error("Invalid operation {0:?}")]
    InvalidOperation(Value),
    #[error("Unexpected end of program at address {0}")]
    EndOfProgram(usize),
    #[error("Invalid value of type {0}, expected {1}")]
    InvalidValue(String, String),
    #[error("Stack overflow")]
    StackOverflow,
    #[error("Stack underflow")]
    StackUnderflow,
    #[error("Stack index out of bounds")]
    StackIndexOutOfBounds,
    #[error("Unknown Global {0}")]
    UnknownGlobal(String),
    #[error("Unknown property {0}")]
    UnknownProperty(String),
    #[error("Division by zero")]
    DivisionByZero,
    #[error("Cannot coerce types {0} and {1}")]
    CannotCoerce(String, String),
    #[error("Invalid number {0}")]
    InvalidNumber(String),
    #[error("Not implemented: {0}")]
    NotImplemented(String),
    #[error("Heap index out of bounds")]
    HeapIndexOutOfBounds,
    #[error("Use after free")]
    UseAfterFree,
    #[error("Expected object")]
    ExpectedObject,
    #[error("Unexpected pop try")]
    UnexpectedPopTry,
    #[error("Cannot throw value, it is not of type Object, or is missing a 'type' or 'message' property")]
    InvalidException,
    #[error("Uncaught exception: {0}: {1}")]
    UncaughtException(String, String),
    #[error("Invalid index, expected positive, non-zero integer")]
    InvalidIndex,
    #[error("Cycle detected")]
    CycleDetected,
    #[error("Array index {0} out of bounds, array length {1}")]
    IndexOutOfBounds(usize, usize),
    #[error("Out of resource: {0}")]
    OutOfResource(String),
    #[error("Invalid bytecode: {0}")]
    InvalidBytecode(String),
    #[error("Invalid call: {0}")]
    InvalidCall(String),
    #[error("No frame")]
    NoFrame,
    #[error("Capture index out of bounds: {0}")]
    CaptureOutOfBounds(usize),
    #[error("Not enough arguments for function {0}: {1} available, {2} required")]
    NotEnoughArguments(String, usize, usize),
    #[error("Unknown function {0}")]
    UnknownFunction(String),
    #[error("Native call failed: {0}")]
    NativeCallFailed(String),
    #[error("Invalid regex {0}: {1}")]
    InvalidRegex(String, String),
    #[error("Integer overflow")]
    IntegerOverflow,
    #[error("Unknown symbol {0}")]
    UnknownSymbol(String),
    #[error("{0}")]
    Other(String),
}
