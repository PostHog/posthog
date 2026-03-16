use personhog_proto::personhog::{
    service::v1::person_hog_service_client::PersonHogServiceClient,
    types::v1::GetGroupTypeMappingsByTeamIdsRequest,
};
use quick_cache::sync::Cache;
use std::collections::HashMap;
use tonic::transport::Channel;
use tracing::{info, warn};

use crate::{
    config::Config,
    metrics_consts::{GROUP_TYPE_CACHE, PERSONHOG_RESOLVE_DURATION, PERSONHOG_RESOLVE_ERRORS},
    types::{GroupType, Update},
};

pub struct GroupTypeResolver {
    cache: Cache<String, i32>,
    personhog_client: Option<PersonHogServiceClient<Channel>>,
}

impl GroupTypeResolver {
    pub fn new(config: &Config) -> Self {
        let cache = Cache::new(config.group_type_cache_size);

        let personhog_client = if !config.personhog_addr.is_empty() {
            let timeout = std::time::Duration::from_millis(config.personhog_timeout_ms);
            let connect_timeout =
                std::time::Duration::from_millis(config.personhog_connect_timeout_ms);
            match Channel::from_shared(config.personhog_addr.clone()) {
                Ok(endpoint) => {
                    let channel = endpoint
                        .timeout(timeout)
                        .connect_timeout(connect_timeout)
                        .connect_lazy();
                    info!(
                        addr = %config.personhog_addr,
                        timeout_ms = config.personhog_timeout_ms,
                        connect_timeout_ms = config.personhog_connect_timeout_ms,
                        "Created personhog gRPC client"
                    );
                    Some(PersonHogServiceClient::new(channel))
                }
                Err(e) => {
                    warn!(
                        addr = %config.personhog_addr,
                        error = %e,
                        "Failed to create personhog gRPC channel"
                    );
                    None
                }
            }
        } else {
            None
        };

        Self {
            cache,
            personhog_client,
        }
    }

    pub async fn resolve(&self, updates: &mut [Update]) -> Result<(), anyhow::Error> {
        // Collect all unresolved group types that need lookup
        let mut to_resolve: Vec<(usize, String, i32)> = Vec::new();

        // First pass: check cache and collect uncached items
        for (idx, update) in updates.iter_mut().enumerate() {
            let Update::Property(update) = update else {
                continue;
            };
            let Some(GroupType::Unresolved(group_name)) = &update.group_type_index else {
                continue;
            };

            let cache_key = format!("{}:{}", update.team_id, group_name);

            if let Some(index) = self.cache.get(&cache_key) {
                metrics::counter!(GROUP_TYPE_CACHE, &[("action", "hit")]).increment(1);
                update.group_type_index =
                    update.group_type_index.take().map(|gti| gti.resolve(index));
            } else {
                to_resolve.push((idx, group_name.clone(), update.team_id));
            }
        }

        // Batch resolve all uncached group types via personhog
        if !to_resolve.is_empty() {
            let resolved_map = match self.resolve_via_personhog(&to_resolve).await {
                Ok(map) => map,
                Err(e) => {
                    warn!(error = %e, "personhog group type resolution failed");
                    metrics::counter!(PERSONHOG_RESOLVE_ERRORS).increment(1);
                    return Err(e);
                }
            };

            // Second pass: apply resolved group types to updates
            for (idx, group_name, team_id) in to_resolve {
                let cache_key = format!("{team_id}:{group_name}");

                if let Some(&index) = resolved_map.get(&(group_name.clone(), team_id)) {
                    metrics::counter!(GROUP_TYPE_CACHE, &[("action", "miss")]).increment(1);
                    self.cache.insert(cache_key, index);

                    if let Update::Property(update) = &mut updates[idx] {
                        update.group_type_index =
                            update.group_type_index.take().map(|gti| gti.resolve(index));
                    }
                } else {
                    metrics::counter!(GROUP_TYPE_CACHE, &[("action", "fail")]).increment(1);
                    warn!(
                        "Failed to resolve group type index for group name: {group_name} and team id: {team_id}"
                    );

                    if let Update::Property(update) = &mut updates[idx] {
                        update.group_type_index = None;
                    }
                }
            }
        }

        Ok(())
    }

    async fn resolve_via_personhog(
        &self,
        to_resolve: &[(usize, String, i32)],
    ) -> Result<HashMap<(String, i32), i32>, anyhow::Error> {
        let start = std::time::Instant::now();

        let mut client = self
            .personhog_client
            .clone()
            .ok_or_else(|| anyhow::anyhow!("personhog client not configured"))?;

        let unique_team_ids: Vec<i64> = {
            let mut ids: Vec<i32> = to_resolve.iter().map(|(_, _, tid)| *tid).collect();
            ids.sort_unstable();
            ids.dedup();
            ids.into_iter().map(|id| id as i64).collect()
        };

        let mut request = tonic::Request::new(GetGroupTypeMappingsByTeamIdsRequest {
            team_ids: unique_team_ids,
            read_options: None,
        });
        request
            .metadata_mut()
            .insert("x-client-name", "property-defs-rs".parse().unwrap());

        let response = client.get_group_type_mappings_by_team_ids(request).await?;

        let elapsed_ms = start.elapsed().as_millis() as f64;
        metrics::histogram!(PERSONHOG_RESOLVE_DURATION).record(elapsed_ms);

        let mut resolved_map: HashMap<(String, i32), i32> = HashMap::new();
        for team_result in response.into_inner().results {
            let team_id = team_result.key as i32;
            for mapping in team_result.mappings {
                resolved_map.insert((mapping.group_type, team_id), mapping.group_type_index);
            }
        }

        Ok(resolved_map)
    }
}
