use tonic::Status;

use personhog_proto::personhog::types::v1::GetOrCreatePersonEntry;

/// Request-shape limits, sourced from service configuration.
#[derive(Debug, Clone)]
pub struct RequestLimits {
    /// Maximum entries per batch RPC.
    pub max_batch_size: usize,
    /// Maximum accepted distinct_id length in bytes. Must not exceed the
    /// posthog_persondistinctid.distinct_id column limit (varchar(400)).
    pub max_distinct_id_length: usize,
}

// tonic Status is a large Err variant; boxing here would diverge from the
// tonic handler signatures these feed into.
#[allow(clippy::result_large_err)]
pub fn validate_batch_size(limits: &RequestLimits, len: usize) -> Result<(), Status> {
    if len > limits.max_batch_size {
        return Err(Status::invalid_argument(format!(
            "batch size {len} exceeds maximum {}",
            limits.max_batch_size
        )));
    }
    Ok(())
}

#[allow(clippy::result_large_err)]
pub fn validate_entry(
    limits: &RequestLimits,
    entry: &GetOrCreatePersonEntry,
) -> Result<(), Status> {
    if entry.team_id <= 0 {
        return Err(Status::invalid_argument("team_id must be positive"));
    }
    validate_distinct_id(limits, &entry.distinct_id)?;
    for extra in &entry.extra_distinct_ids {
        validate_distinct_id(limits, extra)?;
    }
    Ok(())
}

#[allow(clippy::result_large_err)]
fn validate_distinct_id(limits: &RequestLimits, distinct_id: &str) -> Result<(), Status> {
    if distinct_id.is_empty() {
        return Err(Status::invalid_argument("distinct_id must not be empty"));
    }
    if distinct_id.len() > limits.max_distinct_id_length {
        return Err(Status::invalid_argument(format!(
            "distinct_id exceeds {} bytes",
            limits.max_distinct_id_length
        )));
    }
    Ok(())
}
