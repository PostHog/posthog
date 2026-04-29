use personhog_proto::personhog::types::v1::{ConsistencyLevel, ReadOptions};
use tonic::Status;

/// Categories of data for routing decisions.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DataCategory {
    /// Person table data (person, persondistinctid)
    /// - Reads with EVENTUAL consistency → replica
    /// - Reads with STRONG consistency → leader
    /// - Writes → leader
    PersonData,

    /// Non-person data (hash key overrides, cohorts, groups, group type mappings)
    /// - All reads → replica (any consistency level)
    /// - All writes → replica
    NonPersonData,
}

/// Type of operation being performed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OperationType {
    Read,
    Write,
}

/// The target backend for a routed request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RouteDecision {
    /// Route to personhog-replica (Postgres replicas, or primary for strong consistency on non-person data)
    Replica,
    /// Route to personhog-leader (Kafka-backed cache)
    Leader,
}

/// Determine which backend should handle this request.
///
/// # Routing Rules
///
/// ## Person Data (person, persondistinctid tables)
/// - EVENTUAL consistency reads → Replica
/// - STRONG consistency reads → Leader
/// - Writes → Leader
///
/// ## Non-Person Data (hash_key_overrides, cohort_membership, groups, group_type_mappings)
/// - All reads → Replica (consistency is handled internally by replica)
/// - All writes → Replica
#[allow(clippy::unnecessary_wraps, clippy::result_large_err)]
pub fn route_request(
    category: DataCategory,
    operation: OperationType,
    consistency: Option<ConsistencyLevel>,
) -> Result<RouteDecision, Status> {
    match (category, operation) {
        // Person data routing
        (DataCategory::PersonData, OperationType::Read) => {
            let consistency = consistency.unwrap_or(ConsistencyLevel::Eventual);
            match consistency {
                ConsistencyLevel::Unspecified | ConsistencyLevel::Eventual => {
                    Ok(RouteDecision::Replica)
                }
                ConsistencyLevel::Strong => Ok(RouteDecision::Leader),
            }
        }
        (DataCategory::PersonData, OperationType::Write) => Ok(RouteDecision::Leader),

        // Non-person data always goes to replica
        // The replica handles consistency internally (primary vs replica pool)
        (DataCategory::NonPersonData, OperationType::Read) => Ok(RouteDecision::Replica),
        (DataCategory::NonPersonData, OperationType::Write) => Ok(RouteDecision::Replica),
    }
}

/// Extract consistency level from optional ReadOptions.
pub fn get_consistency(read_options: &Option<ReadOptions>) -> Option<ConsistencyLevel> {
    read_options.as_ref().map(|opts| opts.consistency())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_person_data_eventual_routes_to_replica() {
        let result = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            Some(ConsistencyLevel::Eventual),
        );
        assert_eq!(result.unwrap(), RouteDecision::Replica);
    }

    #[test]
    fn test_person_data_unspecified_routes_to_replica() {
        let result = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            Some(ConsistencyLevel::Unspecified),
        );
        assert_eq!(result.unwrap(), RouteDecision::Replica);
    }

    #[test]
    fn test_person_data_none_consistency_routes_to_replica() {
        let result = route_request(DataCategory::PersonData, OperationType::Read, None);
        assert_eq!(result.unwrap(), RouteDecision::Replica);
    }

    #[test]
    fn test_person_data_strong_routes_to_leader() {
        let result = route_request(
            DataCategory::PersonData,
            OperationType::Read,
            Some(ConsistencyLevel::Strong),
        );
        assert_eq!(result.unwrap(), RouteDecision::Leader);
    }

    #[test]
    fn test_person_data_write_routes_to_leader() {
        let result = route_request(DataCategory::PersonData, OperationType::Write, None);
        assert_eq!(result.unwrap(), RouteDecision::Leader);
    }

    #[test]
    fn test_non_person_data_read_eventual_routes_to_replica() {
        let result = route_request(
            DataCategory::NonPersonData,
            OperationType::Read,
            Some(ConsistencyLevel::Eventual),
        );
        assert_eq!(result.unwrap(), RouteDecision::Replica);
    }

    #[test]
    fn test_non_person_data_read_strong_routes_to_replica() {
        // Non-person data strong consistency is handled internally by replica
        let result = route_request(
            DataCategory::NonPersonData,
            OperationType::Read,
            Some(ConsistencyLevel::Strong),
        );
        assert_eq!(result.unwrap(), RouteDecision::Replica);
    }

    #[test]
    fn test_non_person_data_write_routes_to_replica() {
        let result = route_request(DataCategory::NonPersonData, OperationType::Write, None);
        assert_eq!(result.unwrap(), RouteDecision::Replica);
    }
}
