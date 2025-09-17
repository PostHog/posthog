use std::fmt;

use crate::kafka::types::PartitionState;

/// Error type for tracking operations
#[derive(Debug)]
pub enum TrackingError {
    /// Message received for partition that is not assigned
    UnassignedPartition { topic: String, partition: i32 },
    /// Message received for partition that is not active (e.g., fenced or revoked)
    InactivePartition {
        topic: String,
        partition: i32,
        state: PartitionState,
    },
}

impl fmt::Display for TrackingError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            TrackingError::UnassignedPartition { topic, partition } => {
                write!(
                    f,
                    "Message for unassigned partition {topic}-{partition}. Partition must be assigned before processing messages."
                )
            }
            TrackingError::InactivePartition {
                topic,
                partition,
                state,
            } => {
                write!(
                    f,
                    "Message for inactive partition {topic}-{partition} (state: {state:?}). Partition must be active to process messages.",
                )
            }
        }
    }
}

impl std::error::Error for TrackingError {}
