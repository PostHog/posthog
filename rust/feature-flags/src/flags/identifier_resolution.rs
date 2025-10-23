/// Identifier resolution for feature flag evaluation.
///
/// This module provides the abstraction layer for resolving which identifier to use
/// for feature flag bucketing. The goal is to keep identifier type decisions at the
/// boundary, allowing core evaluation logic to work generically with resolved identifiers.
///
/// Key principle: "Handle identifier type selection at the service boundary. Core
/// evaluation logic should work with a generic bucketing identifier without knowing
/// if it's a distinct_id, group_key, or other identifier types."
use crate::api::errors::FlagError;
use crate::flags::flag_group_type_mapping::{GroupTypeIndex, GroupTypeMappingCache};
use crate::flags::flag_models::FeatureFlag;
use serde_json::Value;
use std::collections::HashMap;

/// Type of identifier being used for bucketing.
///
/// This is primarily for observability and metrics - core evaluation logic
/// doesn't branch on this, it just uses the resolved identifier string.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IdentifierType {
    /// Person identifier using distinct_id
    PersonDistinctId,
    /// Group identifier using group_key
    Group,
}

/// Resolved identifier context for a specific flag evaluation.
///
/// This struct represents the outcome of resolving which identifier to use
/// for a flag's bucketing, given the flag's configuration and the request context.
///
/// ## Design Philosophy
///
/// This abstraction keeps identifier resolution at the boundary. Once created,
/// core evaluation logic (hashing, property matching) works generically with
/// the resolved values without needing to know the source.
///
/// ## Fields
///
/// - `identifier`: The resolved identifier string to use for hashing
/// - `identifier_type`: Type information for observability only
/// - `property_overrides`: Unified property access for this evaluation
/// - Original context fields: Preserved for database queries if needed
#[derive(Debug, Clone)]
pub struct FlagIdentifierContext {
    /// The resolved identifier to use for hashing/bucketing.
    /// This is what gets passed to the hash function.
    pub identifier: String,

    /// Type of identifier (for metrics/logging only).
    /// Core logic doesn't branch on this.
    pub identifier_type: IdentifierType,

    /// Unified property overrides for this flag evaluation.
    /// Contains the appropriate property set based on identifier type.
    pub property_overrides: Option<HashMap<String, Value>>,

    /// Original distinct_id from the request.
    /// Preserved for database lookups when needed.
    pub original_distinct_id: String,

    /// Original group key, if this is a group-based flag.
    pub original_group_key: Option<String>,

    /// Original group type index, if this is a group-based flag.
    pub original_group_type_index: Option<GroupTypeIndex>,
}

/// Resolve which identifier to use for a specific flag evaluation.
///
/// This is THE BOUNDARY where identifier type decisions are made.
/// Everything downstream works with the resolved FlagIdentifierContext.
///
/// ## Arguments
///
/// * `feature_flag` - The flag being evaluated
/// * `distinct_id` - Person identifier from the request
/// * `groups` - Group identifiers from the request
/// * `person_property_overrides` - Property overrides for person-based flags
/// * `group_property_overrides` - Property overrides for group-based flags
/// * `hash_key_overrides` - Hash key overrides for experience continuity
/// * `group_type_mapping_cache` - Cache for resolving group type names to indices
///
/// ## Returns
///
/// Returns `Ok(Some(context))` if identifier can be resolved, `Ok(None)` if the
/// flag cannot be evaluated (e.g., required group not provided), or `Err` on errors.
///
/// ## Design Notes
///
/// - This function handles all the "if person vs group" logic
/// - Downstream code just uses `context.identifier` - no branching needed
/// - Easy to extend: adding new identifier types just means adding branches here
#[allow(clippy::too_many_arguments)]
pub fn resolve_identifier_for_flag(
    feature_flag: &FeatureFlag,
    distinct_id: &str,
    groups: &HashMap<String, Value>,
    person_property_overrides: &Option<HashMap<String, Value>>,
    group_property_overrides: &Option<HashMap<String, HashMap<String, Value>>>,
    hash_key_overrides: Option<&HashMap<String, String>>,
    group_type_mapping_cache: &GroupTypeMappingCache,
) -> Result<Option<FlagIdentifierContext>, FlagError> {
    // Group-based flags: resolve to group_key
    if let Some(group_type_index) = feature_flag.get_group_type_index() {
        // Get the group type name from the index
        let group_type_name = group_type_mapping_cache
            .get_group_type_index_to_type_map()?
            .get(&group_type_index);

        // If we can't find the group type, the flag cannot be evaluated
        let group_type_name = match group_type_name {
            Some(name) => name,
            None => return Ok(None),
        };

        // Get the group key from the request
        let group_key = groups.get(group_type_name);

        // Extract the identifier string from the group key value
        let (identifier, original_group_key) = match group_key {
            Some(Value::String(s)) => (s.clone(), Some(s.clone())),
            Some(Value::Number(n)) => {
                let as_string = n.to_string();
                (as_string.clone(), Some(as_string))
            }
            Some(_) => {
                // For any other JSON type (bool, array, object, null), use empty string
                // NB: we currently use empty string ("") as the hashed identifier for group flags without a group key,
                // and we want to maintain parity with the old service so hash values don't change
                ("".to_string(), None)
            }
            None => ("".to_string(), None),
        };

        // Resolve property overrides for this group
        let property_overrides = group_property_overrides
            .as_ref()
            .and_then(|overrides| overrides.get(group_type_name))
            .cloned();

        return Ok(Some(FlagIdentifierContext {
            identifier,
            identifier_type: IdentifierType::Group,
            property_overrides,
            original_distinct_id: distinct_id.to_string(),
            original_group_key,
            original_group_type_index: Some(group_type_index),
        }));
    }

    // Person-based flags: resolve to distinct_id (with optional hash key override)

    // Check for hash key override (experience continuity)
    let identifier = if feature_flag.ensure_experience_continuity.unwrap_or(false) {
        // If experience continuity is enabled, check for override
        hash_key_overrides
            .and_then(|overrides| overrides.get(&feature_flag.key))
            .map(|override_val| override_val.clone())
            .unwrap_or_else(|| distinct_id.to_string())
    } else {
        // No experience continuity, use distinct_id
        distinct_id.to_string()
    };

    Ok(Some(FlagIdentifierContext {
        identifier,
        identifier_type: IdentifierType::PersonDistinctId,
        property_overrides: person_property_overrides.clone(),
        original_distinct_id: distinct_id.to_string(),
        original_group_key: None,
        original_group_type_index: None,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_models::{FeatureFlag, FlagFilters};
    use std::collections::HashMap;

    fn create_test_flag(key: &str, group_type_index: Option<i32>) -> FeatureFlag {
        FeatureFlag {
            id: 1,
            team_id: 1,
            name: Some(key.to_string()),
            key: key.to_string(),
            filters: FlagFilters {
                groups: vec![],
                multivariate: None,
                aggregation_group_type_index: group_type_index,
                payloads: None,
                super_groups: None,
                holdout_groups: None,
            },
            deleted: false,
            active: true,
            ensure_experience_continuity: Some(false),
            version: Some(1),
            evaluation_runtime: None,
            evaluation_tags: None,
        }
    }

    #[test]
    fn test_resolve_person_flag_with_distinct_id() {
        let flag = create_test_flag("test-flag", None);
        let group_type_mapping_cache = GroupTypeMappingCache::new(1);
        let person_overrides: Option<HashMap<String, Value>> = None;
        let group_overrides: Option<HashMap<String, HashMap<String, Value>>> = None;

        let result = resolve_identifier_for_flag(
            &flag,
            "user_123",
            &HashMap::new(),
            &person_overrides,
            &group_overrides,
            None,
            &group_type_mapping_cache,
        )
        .unwrap();

        assert!(result.is_some());
        let context = result.unwrap();
        assert_eq!(context.identifier, "user_123");
        assert_eq!(context.identifier_type, IdentifierType::PersonDistinctId);
        assert_eq!(context.original_distinct_id, "user_123");
    }

    #[test]
    fn test_resolve_person_flag_with_hash_key_override() {
        let mut flag = create_test_flag("test-flag", None);
        flag.ensure_experience_continuity = Some(true);

        let mut hash_key_overrides = HashMap::new();
        hash_key_overrides.insert("test-flag".to_string(), "anon_123".to_string());

        let group_type_mapping_cache = GroupTypeMappingCache::new(1);
        let person_overrides: Option<HashMap<String, Value>> = None;
        let group_overrides: Option<HashMap<String, HashMap<String, Value>>> = None;

        let result = resolve_identifier_for_flag(
            &flag,
            "user_123",
            &HashMap::new(),
            &person_overrides,
            &group_overrides,
            Some(&hash_key_overrides),
            &group_type_mapping_cache,
        )
        .unwrap();

        assert!(result.is_some());
        let context = result.unwrap();
        assert_eq!(context.identifier, "anon_123"); // Uses override!
        assert_eq!(context.identifier_type, IdentifierType::PersonDistinctId);
        assert_eq!(context.original_distinct_id, "user_123");
    }

    #[test]
    fn test_resolve_group_flag() {
        let flag = create_test_flag("test-flag", Some(0)); // group_type_index = 0

        let mut groups = HashMap::new();
        groups.insert(
            "project".to_string(),
            Value::String("project_456".to_string()),
        );

        // Create a group type mapping cache with the mapping
        let mut group_type_mapping_cache = GroupTypeMappingCache::new(1);
        let types_to_indexes = [("project".to_string(), 0)].into_iter().collect();
        let indexes_to_types = [(0, "project".to_string())].into_iter().collect();
        group_type_mapping_cache.set_test_mappings(types_to_indexes, indexes_to_types);
        let person_overrides: Option<HashMap<String, Value>> = None;
        let group_overrides: Option<HashMap<String, HashMap<String, Value>>> = None;

        let result = resolve_identifier_for_flag(
            &flag,
            "user_123",
            &groups,
            &person_overrides,
            &group_overrides,
            None,
            &group_type_mapping_cache,
        )
        .unwrap();

        assert!(result.is_some());
        let context = result.unwrap();
        assert_eq!(context.identifier, "project_456");
        assert_eq!(context.identifier_type, IdentifierType::Group);
        assert_eq!(context.original_distinct_id, "user_123");
        assert_eq!(context.original_group_type_index, Some(0));
    }

    #[test]
    fn test_resolve_group_flag_without_group_provided() {
        let flag = create_test_flag("test-flag", Some(0));

        // Create group type mapping but don't provide the group in request
        let mut group_type_mapping_cache = GroupTypeMappingCache::new(1);
        let types_to_indexes = [("project".to_string(), 0)].into_iter().collect();
        let indexes_to_types = [(0, "project".to_string())].into_iter().collect();
        group_type_mapping_cache.set_test_mappings(types_to_indexes, indexes_to_types);
        let person_overrides: Option<HashMap<String, Value>> = None;
        let group_overrides: Option<HashMap<String, HashMap<String, Value>>> = None;

        let result = resolve_identifier_for_flag(
            &flag,
            "user_123",
            &HashMap::new(), // No groups provided
            &person_overrides,
            &group_overrides,
            None,
            &group_type_mapping_cache,
        )
        .unwrap();

        // Should still return a context but with empty string identifier
        assert!(result.is_some());
        let context = result.unwrap();
        assert_eq!(context.identifier, "");
    }

    #[test]
    fn test_resolve_with_person_property_overrides() {
        let flag = create_test_flag("test-flag", None);

        let mut person_props = HashMap::new();
        person_props.insert("age".to_string(), Value::Number(25.into()));

        let group_type_mapping_cache = GroupTypeMappingCache::new(1);
        let group_overrides: Option<HashMap<String, HashMap<String, Value>>> = None;

        let result = resolve_identifier_for_flag(
            &flag,
            "user_123",
            &HashMap::new(),
            &Some(person_props.clone()),
            &group_overrides,
            None,
            &group_type_mapping_cache,
        )
        .unwrap();

        assert!(result.is_some());
        let context = result.unwrap();
        assert_eq!(context.identifier, "user_123");
        assert!(context.property_overrides.is_some());
        assert_eq!(context.property_overrides.unwrap().len(), 1);
    }
}
