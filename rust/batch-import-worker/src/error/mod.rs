use thiserror::Error;
use tracing::debug;

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

// Use this to inject a user facing error message into the error chain
// Our main thread can extract this from an error chain and display it to the user
impl<T, E: std::error::Error + Send + Sync + 'static> ToUserError<T> for Result<T, E> {
    fn user_error(self, msg: impl Into<String>) -> anyhow::Result<T> {
        self.map_err(|e| anyhow::Error::from(e).context(UserError::new(msg)))
    }
}

const DEFAULT_USER_ERROR_MESSAGE: &str = "An unknown error occurred";

pub fn get_user_message(error: &anyhow::Error) -> &str {
    if let Some(user_error) = error.downcast_ref::<UserError>() {
        debug!("Found UserError at root: {}", user_error.msg);
        return &user_error.msg;
    }
    
    let mut source = error.source();
    while let Some(err) = source {
        debug!("Checking source error: {}", err);
        if let Some(user_error) = err.downcast_ref::<UserError>() {
            debug!("Found UserError in source chain: {}", user_error.msg);
            return &user_error.msg;
        }
        source = err.source();
    }
    
    DEFAULT_USER_ERROR_MESSAGE
}
