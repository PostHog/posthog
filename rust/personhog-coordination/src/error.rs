use thiserror::Error;

#[derive(Error, Debug)]
pub enum Error {
    #[error(transparent)]
    Store(#[from] assignment_coordination::error::Error),

    #[error("key not found: {0}")]
    NotFound(String),

    #[error("handoff failed for partition {partition}: {reason}")]
    HandoffFailed { partition: u32, reason: String },

    #[error("lease renewal margin exhausted: no confirmed renewal in {0:?}")]
    LeaseMarginExhausted(std::time::Duration),
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

    /// The etcd error underneath, when etcd is what failed.
    pub fn etcd_error(&self) -> Option<&etcd_client::Error> {
        match self {
            Self::Store(assignment_coordination::error::Error::Etcd(e)) => Some(e),
            _ => None,
        }
    }

    /// Whether losing the election lease is what ended this term. An
    /// abdication is the protocol working — a successor takes over and
    /// reconciles — so it is not evidence that this process is unhealthy.
    pub fn is_leadership_lost(&self) -> bool {
        matches!(
            self,
            Self::Store(assignment_coordination::error::Error::LeadershipLost)
        )
    }

    /// Whether a lease ended the session, by expiring in etcd or by its
    /// renewal margin running out. A new session is the remedy.
    pub fn is_lease_lost(&self) -> bool {
        self.is_leadership_lost() || matches!(self, Self::LeaseMarginExhausted(_))
    }
}

pub type Result<T> = std::result::Result<T, Error>;
