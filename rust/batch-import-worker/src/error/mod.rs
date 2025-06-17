use thiserror::Error;
// use std::error::Error as StdError;

// Use .user_error() to inject a user facing error message into the error chain
// Our main thread can extract this from an error chain and display it to the user
#[derive(Error, Debug, Clone)]
#[error("User Error: {msg}")]
pub struct UserError {
    pub msg: String,
}

impl UserError {
    pub fn new(msg: impl Into<String>) -> Self {
        Self { msg: msg.into() }
    }
}

pub trait ToUserError<T> {
    fn user_error(self, msg: impl Into<String>) -> anyhow::Result<T>;
}

impl<T, E: std::error::Error + Send + Sync + 'static> ToUserError<T> for Result<T, E> {
    fn user_error(self, msg: impl Into<String>) -> anyhow::Result<T> {
        self.map_err(|e| {
            anyhow::Error::from(e).context(UserError::new(msg))
        })
    }
}

pub fn get_user_message(error: &anyhow::Error) -> &str {
    for cause in error.chain() {
        if let Some(user_error) = cause.downcast_ref::<UserError>() {
            return &user_error.msg;
        }
    }
    "An unknown error occurred"
}