use personhog_proto::personhog::{
    service::v1::person_hog_service_client::PersonHogServiceClient,
    types::v1::{ConsistencyLevel, GetGroupTypeMappingsByTeamIdsRequest, ReadOptions},
};
use quick_cache::sync::Cache;
use rand::Rng;
use std::collections::HashMap;
use std::future::Future;
use std::time::Duration;
use tokio::time::sleep;
use tonic::transport::Channel;
use tonic::{Code, Status};
use tracing::{info, warn};

use crate::{
    config::Config,
    metrics_consts::{
        GROUP_TYPE_CACHE, PERSONHOG_ERRORS_TOTAL, PERSONHOG_RESOLVE_DURATION,
        PERSONHOG_RESOLVE_ERRORS, PERSONHOG_RETRIES_TOTAL, PERSONHOG_TERMINAL_ERRORS_TOTAL,
    },
    types::{GroupType, Update},
};

const METHOD: &str = "GetGroupTypeMappingsByTeamIds";
const CLIENT: &str = "property-defs-rs";

fn is_retryable(code: Code) -> bool {
    matches!(
        code,
        Code::Unavailable
            | Code::DeadlineExceeded
            | Code::ResourceExhausted
            | Code::Aborted
            | Code::Internal
            | Code::Unknown
    )
}

/// Retry a gRPC call with exponential backoff and jitter on transient errors.
///
/// Emits `personhog_errors_total` on every failed attempt, `personhog_retries_total`
/// on each retry, and `personhog_terminal_errors_total` when giving up.
async fn with_retry<F, Fut, T>(
    max_retries: u32,
    initial_backoff_ms: u64,
    max_backoff_ms: u64,
    method: &'static str,
    client: &'static str,
    mut make_call: F,
) -> Result<T, Status>
where
    F: FnMut() -> Fut,
    Fut: Future<Output = Result<T, Status>>,
{
    let mut attempt = 0;
    let mut delay_ms = initial_backoff_ms;

    loop {
        match make_call().await {
            Ok(value) => return Ok(value),
            Err(status) => {
                let error_type = format!("{:?}", status.code());

                metrics::counter!(
                    PERSONHOG_ERRORS_TOTAL,
                    "method" => method,
                    "client" => client,
                    "error_type" => error_type.clone(),
                )
                .increment(1);

                if !is_retryable(status.code()) || attempt == max_retries {
                    metrics::counter!(
                        PERSONHOG_TERMINAL_ERRORS_TOTAL,
                        "method" => method,
                        "client" => client,
                        "error_type" => error_type,
                    )
                    .increment(1);
                    return Err(status);
                }

                metrics::counter!(
                    PERSONHOG_RETRIES_TOTAL,
                    "method" => method,
                    "client" => client,
                    "error_type" => error_type,
                )
                .increment(1);

                warn!(
                    method = method,
                    attempt = attempt + 1,
                    max_retries = max_retries,
                    error = %status,
                    "Retrying after transient personhog error"
                );

                let base = delay_ms / 2;
                let jittered_ms = base + rand::thread_rng().gen_range(0..=base);
                sleep(Duration::from_millis(jittered_ms)).await;
                delay_ms = (delay_ms * 2).min(max_backoff_ms);
                attempt += 1;
            }
        }
    }
}

pub struct GroupTypeResolver {
    cache: Cache<String, i32>,
    personhog_client: Option<PersonHogServiceClient<Channel>>,
    max_retries: u32,
    initial_backoff_ms: u64,
    max_backoff_ms: u64,
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
                        max_retries = config.personhog_max_retries,
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
            max_retries: config.personhog_max_retries,
            initial_backoff_ms: config.personhog_initial_backoff_ms,
            max_backoff_ms: config.personhog_max_backoff_ms,
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
                    let error_type = e
                        .downcast_ref::<Status>()
                        .map(|s| format!("{:?}", s.code()))
                        .unwrap_or_else(|| "unknown".to_string());
                    warn!(error = %e, error_type = %error_type, "personhog group type resolution failed");
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

        let client = self
            .personhog_client
            .clone()
            .ok_or_else(|| anyhow::anyhow!("personhog client not configured"))?;

        let unique_team_ids: Vec<i64> = {
            let mut ids: Vec<i32> = to_resolve.iter().map(|(_, _, tid)| *tid).collect();
            ids.sort_unstable();
            ids.dedup();
            ids.into_iter().map(|id| id as i64).collect()
        };

        let build_request = || {
            let consistency = ConsistencyLevel::Eventual;
            let mut request = tonic::Request::new(GetGroupTypeMappingsByTeamIdsRequest {
                team_ids: unique_team_ids.clone(),
                read_options: Some(ReadOptions {
                    consistency: consistency.into(),
                    ..Default::default()
                }),
            });
            let metadata = request.metadata_mut();
            metadata.insert("x-client-name", CLIENT.parse().unwrap());
            metadata.insert(
                "x-caller-tag",
                "property-defs/group-type-resolution".parse().unwrap(),
            );
            metadata.insert(
                "x-read-consistency",
                match consistency {
                    ConsistencyLevel::Strong => "strong",
                    _ => "eventual",
                }
                .parse()
                .unwrap(),
            );
            request
        };

        let response = with_retry(
            self.max_retries,
            self.initial_backoff_ms,
            self.max_backoff_ms,
            METHOD,
            CLIENT,
            || {
                let request = build_request();
                let mut c = client.clone();
                async move { c.get_group_type_mappings_by_team_ids(request).await }
            },
        )
        .await?;

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
