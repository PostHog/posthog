mod detection;
mod discovery;
pub mod types;
mod watcher;

pub use detection::classify_departure;
pub use discovery::{discover_controller, DiscoveryError};
pub use types::{ClusterIntent, ControllerKind, ControllerRef, DepartureReason, PodInfo};
pub use watcher::{K8sAwareness, K8sAwarenessError};
