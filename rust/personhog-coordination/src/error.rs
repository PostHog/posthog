use thiserror::Error;

#[derive(Error, Debug)]
pub enum Error {
    #[error(transparent)]
    Store(#[from] assignment_coordination::error::Error),

    #[error("key not found: {0}")]
    NotFound(String),

    #[error("handoff failed for partition {partition}: {reason}")]
    HandoffFailed { partition: u32, reason: String },
}

impl From<serde_json::Error> for Error {
    fn from(e: serde_json::Error) -> Self {
        Self::Store(e.into())
    }
}

impl From<etcd_client::Error> for Error {
    fn from(e: etcd_client::Error) -> Self {
        Self::Store(e.into())
    }
}

impl Error {
    pub fn invalid_state(msg: impl Into<String>) -> Self {
        Self::Store(assignment_coordination::error::Error::InvalidState(
            msg.into(),
        ))
    }

    pub fn leadership_lost() -> Self {
        Self::Store(assignment_coordination::error::Error::LeadershipLost)
    }
}

pub type Result<T> = std::result::Result<T, Error>;
