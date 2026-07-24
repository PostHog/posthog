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
    /// Maximum extra distinct ids per entry.
    pub max_extra_distinct_ids: usize,
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
    // The persons DB stores team_id as int4 and the storage layer narrows
    // with `as i32` — an unchecked value above i32::MAX would wrap and read
    // or write another tenant's rows.
    if entry.team_id <= 0 || entry.team_id > i32::MAX as i64 {
        return Err(Status::invalid_argument(
            "team_id must be a positive 32-bit integer",
        ));
    }
    validate_distinct_id(limits, &entry.distinct_id)?;
    if entry.extra_distinct_ids.len() > limits.max_extra_distinct_ids {
        return Err(Status::invalid_argument(format!(
            "entry has {} extra distinct ids, exceeding maximum {}",
            entry.extra_distinct_ids.len(),
            limits.max_extra_distinct_ids
        )));
    }
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

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(team_id: i64) -> GetOrCreatePersonEntry {
        GetOrCreatePersonEntry {
            team_id,
            distinct_id: "user-1".to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn team_id_must_fit_the_int4_column_without_wrapping() {
        let limits = RequestLimits {
            max_batch_size: 10,
            max_distinct_id_length: 400,
            max_extra_distinct_ids: 5000,
        };
        for ok in [1, i32::MAX as i64] {
            assert!(validate_entry(&limits, &entry(ok)).is_ok(), "{ok}");
        }
        // 2^32 + 1 wraps to team 1 under `as i32`; the rest are the
        // boundary and sign cases around the valid range.
        for bad in [0, -1, i32::MAX as i64 + 1, (1 << 32) + 1, i64::MAX] {
            assert!(validate_entry(&limits, &entry(bad)).is_err(), "{bad}");
        }
    }

    #[test]
    fn extra_distinct_ids_are_capped_per_entry() {
        let limits = RequestLimits {
            max_batch_size: 10,
            max_distinct_id_length: 400,
            max_extra_distinct_ids: 3,
        };
        let with_extras = |n: usize| GetOrCreatePersonEntry {
            extra_distinct_ids: (0..n).map(|i| format!("extra-{i}")).collect(),
            ..entry(1)
        };
        assert!(validate_entry(&limits, &with_extras(3)).is_ok());
        assert!(validate_entry(&limits, &with_extras(4)).is_err());
    }
}
