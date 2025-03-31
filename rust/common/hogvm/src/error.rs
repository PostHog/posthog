use thiserror::Error;

#[derive(Debug, Error)]
pub enum InputError {
    #[error("OpCode {0} not supported")]
    InvalidOperation(u32),
}

#[derive(Debug, Error)]
pub enum Error {
    #[error("Input error: {0}")]
    Input(InputError),
}
