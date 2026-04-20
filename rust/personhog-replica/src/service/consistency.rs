use personhog_proto::personhog::types::v1::{ConsistencyLevel, ReadOptions};
use tonic::Status;

use crate::storage;

/// Check if the read options request strong consistency
pub fn is_strong_consistency(read_options: &Option<ReadOptions>) -> bool {
    read_options
        .as_ref()
        .map(|opts| opts.consistency() == ConsistencyLevel::Strong)
        .unwrap_or(false)
}

/// Convert read options to storage consistency level
pub fn to_storage_consistency(
    read_options: &Option<ReadOptions>,
) -> storage::postgres::ConsistencyLevel {
    if is_strong_consistency(read_options) {
        storage::postgres::ConsistencyLevel::Strong
    } else {
        storage::postgres::ConsistencyLevel::Eventual
    }
}

/// Reject requests for strong consistency on person-related endpoints.
/// The replica service cannot serve strong consistency for person data because
/// the person table is cached/managed by the leader service.
#[allow(clippy::result_large_err)]
pub fn reject_strong_consistency(read_options: &Option<ReadOptions>) -> Result<(), Status> {
    if is_strong_consistency(read_options) {
        return Err(Status::failed_precondition(
            "This endpoint cannot serve strong consistency. Person data is only available \
             with eventual consistency from the replica service. Use the leader service \
             for strong consistency requirements.",
        ));
    }
    Ok(())
}
