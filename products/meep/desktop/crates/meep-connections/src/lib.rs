#![doc = include_str!("../README.md")]
#![deny(missing_docs)]

mod registry;
mod secrets;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

pub use registry::{HealthChecker, Registry, check_all};
pub use secrets::{KeychainSecrets, MemorySecrets, SecretStore};

pub use meep_topic::TopicId;

/// The last known condition of a connected service.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Health {
    /// The service was reachable with the current credentials.
    Ok {
        /// When the check succeeded.
        checked_at: DateTime<Utc>,
    },
    /// The account needs fresh credentials.
    Expired {
        /// When the expiry was first observed.
        since: DateTime<Utc>,
        /// An explanation suitable for the person reconnecting the account.
        detail: String,
    },
    /// The checker could not use the service.
    Failing {
        /// When this failure started.
        since: DateTime<Utc>,
        /// A readable explanation, such as "Can't see Slack".
        detail: String,
    },
}

impl Health {
    /// A short status for display, using the checker's detail when available.
    pub fn summary(&self) -> &str {
        match self {
            Self::Ok { .. } => "Connected",
            Self::Expired { detail, .. } | Self::Failing { detail, .. }
                if !detail.trim().is_empty() =>
            {
                detail
            }
            Self::Expired { .. } => "Sign in again",
            Self::Failing { .. } => "Can't reach the service",
        }
    }
}

/// A connected service account and the topics allowed to use it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Connection {
    /// Webhook arrivals which matched no topic binding.
    #[serde(default)]
    pub unrouted: u64,
    /// Stable key used by watches, grants, and secret storage.
    pub id: String,
    /// Connector kind, such as "slack".
    pub kind: String,
    /// Display name chosen by the host or person.
    pub label: String,
    /// Public account identifier for this connection.
    pub account: String,
    /// Most recent health observation.
    pub health: Health,
    /// Topics explicitly allowed to use this account.
    pub grants: Vec<TopicId>,
}
