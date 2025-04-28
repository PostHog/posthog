use crate::api::{
    auth::authenticate_personal_api_key, errors::FlagError,
    flag_definition_types::FlagDefinitionsResponse, permissions::has_permission,
    request_handler::RequestContext,
};
use crate::client::database::Client;
use crate::flags::flag_group_type_mapping::GroupTypeMappingCache;
use crate::flags::flag_service::FlagService;
use std::sync::Arc;

pub async fn process_flags_definitions_request(
    context: &RequestContext,
) -> Result<FlagDefinitionsResponse, FlagError> {
    let api_key =
        authenticate_personal_api_key(context.state.reader.as_ref(), &context.request).await?;

    if let Err(e) = has_permission(&api_key, "feature_flag", &["feature_flag:read"]) {
        return Err(FlagError::InvalidScopes(e.to_string()));
    }

    // TODO: Quota limited check.

    // TODO: Query the flag definitions from the cache/database
    let flag_service = FlagService::new(context.state.redis.clone(), context.state.reader.clone());
    let project_id = api_key.project_id.unwrap();
    let all_flags = flag_service.get_flags_from_cache_or_pg(project_id).await?;

    let group_type_mapping =
        get_sorted_group_type_mapping(project_id, context.state.reader.clone()).await?;

    let response = FlagDefinitionsResponse {
        request_id: context.request.id,
        flags: all_flags.flags,
        group_type_mapping,
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
