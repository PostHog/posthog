use crate::api::{
    auth::authenticate_personal_api_key, errors::FlagError,
    flag_definition_types::FlagDefinitionsResponse, permissions::has_permission,
    request_handler::RequestContext,
};
use crate::client::database::Client;
use crate::cohorts::cohort_cache_manager::CohortCacheManager;
use crate::flags::flag_group_type_mapping::GroupTypeMappingCache;
use crate::flags::flag_service::FlagService;
use crate::flags::flag_models::FeatureFlag;
use limiters::redis::ServiceName;
use std::{collections::HashMap, sync::Arc};
use std::collections::HashSet;
use serde_json;

pub async fn process_flags_definitions_request(
    context: &RequestContext,
) -> Result<FlagDefinitionsResponse, FlagError> {
    let api_key =
        authenticate_personal_api_key(context.state.reader.as_ref(), &context.request).await?;

    if let Err(e) = has_permission(&api_key, "feature_flag", &["feature_flag:read"]) {
        return Err(FlagError::InvalidScopes(e.to_string()));
    }

    let billing_limited = context
        .state
        .billing_limiter
        .is_limited(api_key.project_api_key.as_str())
        .await;
    if billing_limited {
        // return an empty FlagsResponse with a quotaLimited field called "feature_flags"
        // TODO docs
        return Ok(FlagDefinitionsResponse {
            flags: vec![],
            group_type_mapping: HashMap::new(),
            quota_limited: Some(vec![ServiceName::FeatureFlags.as_string()]),
            request_id: context.request.id,
            cohorts: HashMap::new(),
        });
    }

    let flag_service = FlagService::new(context.state.redis.clone(), context.state.reader.clone());
    let project_id = api_key.project_id.unwrap();
    let all_flags = flag_service.get_flags_from_cache_or_pg(project_id).await?;

    // TODO: We should only send cohorts for flags that have filter properties that reference cohorts
    let cohorts = if context.request.meta.send_cohorts.unwrap_or(false) {
        get_cohorts_for_flags(&all_flags.flags, project_id, context.state.reader.clone()).await?
    } else {
        HashMap::new()
    };

    let group_type_mapping =
        get_sorted_group_type_mapping(project_id, context.state.reader.clone()).await?;

    let response = FlagDefinitionsResponse {
        request_id: context.request.id,
        flags: all_flags.flags,
        group_type_mapping,
        quota_limited: None,
        cohorts,
    };

    return Ok(response);
}

async fn get_sorted_group_type_mapping(
    project_id: i64,
    reader: Arc<dyn Client + Send + Sync>,
) -> Result<std::collections::HashMap<String, String>, FlagError> {
    let mut group_type_mapping_cache = GroupTypeMappingCache::new(project_id);
    group_type_mapping_cache.init(reader).await?;
    let mapping = group_type_mapping_cache.get_group_type_index_to_type_map()?;
    let mut mapping_vec: Vec<_> = mapping.iter().collect();
    mapping_vec.sort_by_key(|(idx, _)| *idx);
    Ok(mapping_vec
        .into_iter()
        .map(|(idx, name)| (idx.to_string(), name.clone()))
        .collect())
}

fn get_cohort_ids_for_flags(flags: &Vec<FeatureFlag>) -> HashSet<i32> {
    let mut cohort_ids = HashSet::new();
    for flag in flags {
        for condition in &flag.filters.groups {
            if let Some(properties) = &condition.properties {
                for property in properties {
                    if property.prop_type == "cohort" {
                        if let Some(value) = &property.value {
                            if let Some(cohort_id) = value.as_str().and_then(|s| s.parse::<i32>().ok()) {
                                cohort_ids.insert(cohort_id);
                            }
                        }   
                    }
                }
            }
        }
    }
    cohort_ids
}

async fn get_cohorts_for_flags(flags: &Vec<FeatureFlag>, project_id: i64, reader: Arc<dyn Client + Send + Sync>) -> Result<HashMap<String, serde_json::Value>, FlagError> {
    // First collect all cohort IDs referenced in flag conditions
    let cohort_ids = get_cohort_ids_for_flags(flags);

    // If no cohorts are referenced, return empty map
    if cohort_ids.is_empty() {
        return Ok(HashMap::new());
    }

    // Get all cohorts and filter to just the ones we need
    let cohort_cache = CohortCacheManager::new(reader, None, None);
    let all_cohorts = cohort_cache.get_cohorts(project_id).await?;
    
    // Transform into the expected format, filtering to only referenced cohorts
    let cohorts = all_cohorts
        .into_iter()
        .filter(|cohort| cohort_ids.contains(&cohort.id))
        .filter_map(|cohort| cohort.filters.map(|f| (cohort.id.to_string(), f)))
        .collect();

    Ok(cohorts)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_models::{FeatureFlag, FlagPropertyGroup};
    use crate::properties::property_models::PropertyFilter;
    use serde_json::json;
    use crate::flags::flag_models::FlagFilters;

    #[test]
    fn test_get_cohort_ids_for_flags() {
        let flags = vec![
            FeatureFlag {
                filters: FlagFilters {
                    groups: vec![
                        FlagPropertyGroup {
                            properties: Some(vec![
                                PropertyFilter {
                                    prop_type: "cohort".to_string(),
                                    value: Some(json!("123")),
                                    key: "".to_string(),
                                    operator: None,
                                    group_type_index: None,
                                    negation: Some(false),
                                }
                            ]),
                            ..Default::default()
                        }
                    ],
                    ..Default::default()
                },
                id: 0,                    // Add minimum required fields
                team_id: 0,
                key: "test".to_string(),
                name: Some("test".to_string()),
                active: true,
                deleted: false,
                ensure_experience_continuity: false,
                version: Some(1),
            }
        ];

        let cohort_ids = get_cohort_ids_for_flags(&flags);
        assert_eq!(cohort_ids, vec![123].into_iter().collect::<HashSet<_>>());
    }

    #[test]
    fn test_get_cohort_ids_empty_flags() {
        let flags = vec![];
        let cohort_ids = get_cohort_ids_for_flags(&flags);
        assert!(cohort_ids.is_empty());
    }

    #[test]
    fn test_get_cohort_ids_no_cohort_properties() {
        let flags = vec![
            FeatureFlag {
                filters: FlagFilters {
                    groups: vec![
                        FlagPropertyGroup {
                            properties: Some(vec![
                                PropertyFilter {
                                    prop_type: "person".to_string(),
                                    value: Some(json!("value")),
                                    key: "".to_string(),
                                    operator: None,
                                    group_type_index: None,
                                    negation: Some(false),
                                }
                            ]),
                            ..Default::default()
                        }
                    ],
                    ..Default::default()
                },
                id: 0,                    // Add minimum required fields
                team_id: 0,
                key: "test".to_string(),
                name: Some("test".to_string()),
                active: true,
                deleted: false,
                ensure_experience_continuity: false,
                version: Some(1),
            }
        ];

        let cohort_ids = get_cohort_ids_for_flags(&flags);
        assert!(cohort_ids.is_empty());
    }
}
