use thiserror::Error;

#[derive(Error, Debug)]
pub enum Error {
    #[error("etcd error: {0}")]
    Etcd(#[from] etcd_client::Error),

    #[error("serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("leadership lost")]
    LeadershipLost,

    #[error("invalid state: {0}")]
    InvalidState(String),
}

pub type Result<T> = std::result::Result<T, Error>;
