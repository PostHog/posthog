//! DNS-backed connection manager for remote Cymbal stages.
//!
//! Owns long-lived tonic channels keyed by `(target, resolved pod address)`
//! plus the supporting state — refreshed endpoint lists, observed load,
//! circuit breakers — that the dispatcher consults before sending a batch.
//! Refresh is driven externally (one-shot or via [`Self::spawn_refresh_loop`])
//! so callers control the resolution cadence.

use std::collections::{HashMap, HashSet};
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use cymbal_api::cymbal::v1::StageLoad;
use cymbal_core::routing::{
    pick_candidates_with_rng, CapacitySnapshot, EndpointStateMap, RemoteRoutingConfig, RoutingKey,
    RoutingMode, RoutingPolicy,
};
use tokio::net::lookup_host;
use tokio::sync::RwLock;
use tokio::task::JoinHandle;
use tonic::transport::{Channel, Endpoint};
use tonic::Status;

use crate::observability::{stage_load_from_metadata, REMOTE_ENDPOINT_LOAD_SKIPPED_PRIMARY};

use super::circuit::RemoteTargetCircuit;
use super::client::{RemoteStageClient, RemoteStageConfig, RemoteStageConnectionOptions};
use super::load::{
    endpoint_capacity_from_load, record_endpoint_load_metrics, EndpointLoadKey,
    EndpointObservedLoad,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RemoteStageTarget {
    pub name: String,
    pub dns_name: String,
    pub port: u16,
    pub scheme: String,
}

impl RemoteStageTarget {
    pub fn new(name: impl Into<String>, dns_name: impl Into<String>, port: u16) -> Self {
        Self {
            name: name.into(),
            dns_name: dns_name.into(),
            port,
            scheme: "http".to_string(),
        }
    }

    pub fn with_scheme(
        name: impl Into<String>,
        dns_name: impl Into<String>,
        port: u16,
        scheme: impl Into<String>,
    ) -> Self {
        Self {
            name: name.into(),
            dns_name: dns_name.into(),
            port,
            scheme: scheme.into(),
        }
    }
}

#[derive(Debug)]
pub enum RemoteStageConnectionError {
    Resolve {
        dns_name: String,
        port: u16,
        source: std::io::Error,
    },
    NoResolvedAddresses {
        dns_name: String,
        port: u16,
    },
    InvalidEndpoint {
        endpoint: String,
        source: tonic::transport::Error,
    },
    UnknownTarget(String),
}

impl Display for RemoteStageConnectionError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            RemoteStageConnectionError::Resolve {
                dns_name,
                port,
                source,
            } => write!(
                formatter,
                "failed to resolve remote stage target {dns_name}:{port}: {source}"
            ),
            RemoteStageConnectionError::NoResolvedAddresses { dns_name, port } => write!(
                formatter,
                "remote stage target {dns_name}:{port} resolved no addresses"
            ),
            RemoteStageConnectionError::InvalidEndpoint { endpoint, source } => {
                write!(
                    formatter,
                    "invalid remote stage endpoint {endpoint}: {source}"
                )
            }
            RemoteStageConnectionError::UnknownTarget(target) => {
                write!(formatter, "unknown remote stage target {target}")
            }
        }
    }
}

impl Error for RemoteStageConnectionError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            RemoteStageConnectionError::Resolve { source, .. } => Some(source),
            RemoteStageConnectionError::InvalidEndpoint { source, .. } => Some(source),
            RemoteStageConnectionError::NoResolvedAddresses { .. }
            | RemoteStageConnectionError::UnknownTarget(_) => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ResolvedRemoteEndpoint {
    address: SocketAddr,
    scheme: String,
}

impl ResolvedRemoteEndpoint {
    fn new(address: SocketAddr, scheme: impl Into<String>) -> Self {
        Self {
            address,
            scheme: scheme.into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct EndpointClientKey {
    target_name: String,
    address: SocketAddr,
}

impl EndpointClientKey {
    fn new(target_name: impl Into<String>, address: SocketAddr) -> Self {
        Self {
            target_name: target_name.into(),
            address,
        }
    }

    fn metric_target(&self) -> String {
        format!("{}@{}", self.target_name, self.address)
    }
}

/// Borrowed inputs for [`RemoteStageConnectionManager::record_load_skipped_primary`].
/// Grouped into a struct so the helper stays under the clippy
/// `too_many_arguments` ceiling.
struct LoadSkippedPrimaryArgs<'a> {
    target_name: &'a str,
    stage_id: &'a str,
    routing_key: &'a RoutingKey,
    policy: &'a RoutingPolicy,
    addresses: &'a [SocketAddr],
    endpoint_states: &'a EndpointStateMap<SocketAddr>,
    candidates: &'a [SocketAddr],
}

#[derive(Debug, Clone)]
pub struct RemoteStageConnectionManager {
    endpoints: Arc<RwLock<HashMap<String, Vec<ResolvedRemoteEndpoint>>>>,
    endpoint_channels: Arc<RwLock<HashMap<EndpointClientKey, Channel>>>,
    circuits: Arc<RwLock<HashMap<EndpointClientKey, RemoteTargetCircuit>>>,
    endpoint_loads: Arc<RwLock<HashMap<EndpointLoadKey, EndpointObservedLoad>>>,
    options: RemoteStageConnectionOptions,
    routing_config: RemoteRoutingConfig,
}

impl Default for RemoteStageConnectionManager {
    fn default() -> Self {
        Self {
            endpoints: Arc::new(RwLock::new(HashMap::new())),
            endpoint_channels: Arc::new(RwLock::new(HashMap::new())),
            circuits: Arc::new(RwLock::new(HashMap::new())),
            endpoint_loads: Arc::new(RwLock::new(HashMap::new())),
            options: RemoteStageConnectionOptions::default(),
            routing_config: RemoteRoutingConfig::default(),
        }
    }
}

impl RemoteStageConnectionManager {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_options(options: RemoteStageConnectionOptions) -> Self {
        Self {
            endpoints: Arc::new(RwLock::new(HashMap::new())),
            endpoint_channels: Arc::new(RwLock::new(HashMap::new())),
            circuits: Arc::new(RwLock::new(HashMap::new())),
            endpoint_loads: Arc::new(RwLock::new(HashMap::new())),
            options,
            routing_config: RemoteRoutingConfig::default(),
        }
    }

    pub fn with_options_and_routing(
        options: RemoteStageConnectionOptions,
        routing_config: RemoteRoutingConfig,
    ) -> Self {
        Self {
            endpoints: Arc::new(RwLock::new(HashMap::new())),
            endpoint_channels: Arc::new(RwLock::new(HashMap::new())),
            circuits: Arc::new(RwLock::new(HashMap::new())),
            endpoint_loads: Arc::new(RwLock::new(HashMap::new())),
            options,
            routing_config,
        }
    }

    pub fn options(&self) -> &RemoteStageConnectionOptions {
        &self.options
    }

    pub fn routing_policy_for_stage(&self, stage_id: &str) -> RoutingPolicy {
        self.routing_config.policy_for_stage(stage_id)
    }

    pub async fn refresh_target(
        &self,
        target: &RemoteStageTarget,
    ) -> Result<(), RemoteStageConnectionError> {
        let mut addresses = resolve_headless_service(&target.dns_name, target.port).await?;
        addresses.sort();
        addresses.dedup();
        tracing::debug!(
            target = %target.name,
            dns_name = %target.dns_name,
            port = target.port,
            resolved_addresses = addresses.len(),
            "refreshing remote stage target"
        );
        let endpoints = addresses
            .into_iter()
            .map(|addr| ResolvedRemoteEndpoint::new(addr, target.scheme.clone()))
            .collect::<Vec<_>>();
        self.replace_target_endpoints(&target.name, endpoints).await;

        Ok(())
    }

    pub async fn refresh_targets(
        &self,
        targets: &[RemoteStageTarget],
    ) -> Result<(), RemoteStageConnectionError> {
        let mut grouped_targets: HashMap<&str, Vec<&RemoteStageTarget>> = HashMap::new();
        for target in targets {
            grouped_targets
                .entry(target.name.as_str())
                .or_default()
                .push(target);
        }

        for (target_name, targets) in grouped_targets {
            let mut endpoints = Vec::new();
            for target in targets {
                let mut addresses = resolve_headless_service(&target.dns_name, target.port).await?;
                addresses.sort();
                addresses.dedup();
                tracing::debug!(
                    target = %target.name,
                    dns_name = %target.dns_name,
                    port = target.port,
                    resolved_addresses = addresses.len(),
                    "refreshing remote stage target endpoint"
                );
                endpoints.extend(
                    addresses
                        .into_iter()
                        .map(|addr| ResolvedRemoteEndpoint::new(addr, target.scheme.clone())),
                );
            }
            endpoints.sort_by_key(|endpoint| endpoint.address);
            endpoints.dedup_by_key(|endpoint| endpoint.address);

            let endpoint_count = endpoints.len();
            self.replace_target_endpoints(target_name, endpoints).await;
            tracing::debug!(
                target = target_name,
                endpoints = endpoint_count,
                "refreshed remote stage target"
            );
        }

        Ok(())
    }

    pub fn spawn_refresh_loop(
        &self,
        targets: Vec<RemoteStageTarget>,
        interval: Duration,
    ) -> JoinHandle<()> {
        let manager = self.clone();

        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(interval);

            loop {
                ticker.tick().await;
                if let Err(error) = manager.refresh_targets(&targets).await {
                    tracing::warn!(?error, "failed to refresh remote stage targets");
                }
            }
        })
    }

    pub async fn client_for(
        &self,
        target_name: &str,
        config: RemoteStageConfig,
    ) -> Result<RemoteStageClient, Status> {
        let candidates = self
            .candidate_endpoints(
                target_name,
                &config.stage_id,
                &RoutingKey::new(target_name.to_string()),
                &RoutingPolicy::random(),
            )
            .await?;
        let Some(endpoint) = candidates.first().copied() else {
            return Err(Status::unavailable(format!(
                "remote stage target {target_name} has no available endpoints"
            )));
        };

        self.client_for_endpoint(target_name, config, endpoint)
            .await
    }

    pub async fn candidate_endpoints(
        &self,
        target_name: &str,
        stage_id: &str,
        routing_key: &RoutingKey,
        policy: &RoutingPolicy,
    ) -> Result<Vec<SocketAddr>, Status> {
        let Some(endpoints) = self.endpoints.read().await.get(target_name).cloned() else {
            return Err(Status::unavailable(format!(
                "unknown remote stage target {target_name}"
            )));
        };

        let all_addresses = endpoints
            .into_iter()
            .map(|endpoint| endpoint.address)
            .collect::<Vec<_>>();
        // Filter to endpoints that have either never been probed yet, or whose
        // most recent probe advertised this `stage_id`. Older endpoints that
        // don't fill `served_stage_ids` advertise an empty set, which we treat
        // as "unknown" and leave in the candidate pool.
        let addresses = self
            .filter_by_advertised_capability(target_name, stage_id, all_addresses)
            .await;
        if addresses.is_empty() {
            return Err(Status::unavailable(format!(
                "no remote stage endpoint for target {target_name} advertises stage {stage_id}"
            )));
        }
        let endpoint_states = if self.routing_config.use_observed_load() {
            self.endpoint_states_from_load(target_name, stage_id, &addresses)
                .await
        } else {
            EndpointStateMap::new()
        };
        let mut rng = rand::thread_rng();
        let candidates = pick_candidates_with_rng(
            stage_id,
            routing_key,
            &addresses,
            &endpoint_states,
            policy,
            &mut rng,
        );
        self.record_load_skipped_primary(LoadSkippedPrimaryArgs {
            target_name,
            stage_id,
            routing_key,
            policy,
            addresses: &addresses,
            endpoint_states: &endpoint_states,
            candidates: &candidates,
        });

        Ok(candidates)
    }

    pub async fn candidate_endpoints_for_stage(
        &self,
        target_name: &str,
        stage_id: &str,
        routing_key: &RoutingKey,
    ) -> Result<Vec<SocketAddr>, Status> {
        let policy = self.routing_policy_for_stage(stage_id);
        self.candidate_endpoints(target_name, stage_id, routing_key, &policy)
            .await
    }

    pub(crate) async fn endpoint_addresses_for_target(
        &self,
        target_name: &str,
    ) -> Result<Vec<SocketAddr>, Status> {
        let Some(endpoints) = self.endpoints.read().await.get(target_name).cloned() else {
            return Err(Status::unavailable(format!(
                "unknown remote stage target {target_name}"
            )));
        };

        Ok(endpoints
            .into_iter()
            .map(|endpoint| endpoint.address)
            .collect())
    }

    pub(crate) async fn endpoint_capacity_snapshot(
        &self,
        target_name: &str,
        stage_id: &str,
        addresses: &[SocketAddr],
    ) -> CapacitySnapshot<SocketAddr> {
        let loads = self.endpoint_loads.read().await;
        CapacitySnapshot::new(
            addresses
                .iter()
                .map(|address| {
                    let key = EndpointLoadKey::new(
                        target_name.to_string(),
                        stage_id.to_string(),
                        *address,
                    );
                    endpoint_capacity_from_load(*address, loads.get(&key))
                })
                .collect(),
        )
    }

    pub async fn record_endpoint_load(
        &self,
        target_name: &str,
        address: SocketAddr,
        stage_id: &str,
        load: StageLoad,
    ) {
        record_endpoint_load_metrics(stage_id, target_name, address, &load);
        let key = EndpointLoadKey::new(target_name.to_string(), stage_id.to_string(), address);
        self.endpoint_loads
            .write()
            .await
            .insert(key, EndpointObservedLoad::new(load));
    }

    pub async fn record_endpoint_status_load(
        &self,
        target_name: &str,
        address: SocketAddr,
        stage_id: &str,
        status: &Status,
    ) {
        if let Some(load) = stage_load_from_metadata(status.metadata()) {
            self.record_endpoint_load(target_name, address, stage_id, load)
                .await;
        }
    }

    pub async fn observed_endpoint_load(
        &self,
        target_name: &str,
        stage_id: &str,
        address: SocketAddr,
    ) -> Option<StageLoad> {
        let key = EndpointLoadKey::new(target_name.to_string(), stage_id.to_string(), address);
        self.endpoint_loads
            .read()
            .await
            .get(&key)
            .filter(|load| load.is_fresh())
            .map(|load| load.load.clone())
    }

    pub async fn client_for_endpoint(
        &self,
        target_name: &str,
        config: RemoteStageConfig,
        address: SocketAddr,
    ) -> Result<RemoteStageClient, Status> {
        tracing::debug!(target = target_name, endpoint = %address, stage_id = %config.stage_id, "creating remote stage client");
        if let Some(retry_after_ms) = self
            .endpoint_circuit_retry_after_ms(target_name, address)
            .await
        {
            return Err(Status::unavailable(format!(
                "remote stage circuit open for target {target_name} endpoint {address}; retry_after_ms={retry_after_ms}"
            )));
        }

        let endpoint = self.resolved_endpoint(target_name, address).await?;
        let key = EndpointClientKey::new(target_name.to_string(), address);
        let channel = {
            let mut channels = self.endpoint_channels.write().await;
            if let Some(channel) = channels.get(&key).cloned() {
                channel
            } else {
                let channel =
                    endpoint_for_address(&endpoint.scheme, endpoint.address, &self.options)
                        .map_err(|error| Status::unavailable(error.to_string()))?
                        .connect_lazy();
                channels.insert(key.clone(), channel.clone());
                channel
            }
        };

        Ok(RemoteStageClient::from_channel(config, channel))
    }

    pub async fn record_success(&self, target_name: &str, address: SocketAddr) {
        let mut circuits = self.circuits.write().await;
        let key = EndpointClientKey::new(target_name.to_string(), address);
        let circuit = circuits
            .entry(key.clone())
            .or_insert_with(RemoteTargetCircuit::new);
        circuit.record_success(&key.metric_target());
    }

    pub async fn record_failure(
        &self,
        target_name: &str,
        address: SocketAddr,
        reason: &'static str,
    ) {
        let mut circuits = self.circuits.write().await;
        let key = EndpointClientKey::new(target_name.to_string(), address);
        let circuit = circuits
            .entry(key.clone())
            .or_insert_with(RemoteTargetCircuit::new);
        circuit.record_failure(&key.metric_target(), reason);
    }

    pub async fn endpoint_circuit_retry_after_ms(
        &self,
        target_name: &str,
        address: SocketAddr,
    ) -> Option<u64> {
        let mut circuits = self.circuits.write().await;
        let key = EndpointClientKey::new(target_name.to_string(), address);
        let circuit = circuits
            .entry(key.clone())
            .or_insert_with(RemoteTargetCircuit::new);
        circuit.retry_after_ms(&key.metric_target())
    }

    async fn replace_target_endpoints(
        &self,
        target_name: &str,
        endpoints: Vec<ResolvedRemoteEndpoint>,
    ) {
        let live_addresses = endpoints
            .iter()
            .map(|endpoint| endpoint.address)
            .collect::<HashSet<_>>();

        self.endpoints
            .write()
            .await
            .insert(target_name.to_string(), endpoints.clone());

        {
            let mut channels = self.endpoint_channels.write().await;
            channels.retain(|key, _| {
                key.target_name != target_name || live_addresses.contains(&key.address)
            });
        }

        let mut circuits = self.circuits.write().await;
        circuits.retain(|key, _| {
            key.target_name != target_name || live_addresses.contains(&key.address)
        });
        {
            let mut loads = self.endpoint_loads.write().await;
            loads.retain(|key, _| {
                key.target_name != target_name || live_addresses.contains(&key.address)
            });
        }
        for endpoint in endpoints {
            let key = EndpointClientKey::new(target_name.to_string(), endpoint.address);
            circuits
                .entry(key.clone())
                .or_insert_with(RemoteTargetCircuit::new)
                .record_state(&key.metric_target());
        }
    }

    async fn resolved_endpoint(
        &self,
        target_name: &str,
        address: SocketAddr,
    ) -> Result<ResolvedRemoteEndpoint, Status> {
        let Some(endpoints) = self.endpoints.read().await.get(target_name).cloned() else {
            return Err(Status::unavailable(format!(
                "unknown remote stage target {target_name}"
            )));
        };

        endpoints
            .into_iter()
            .find(|endpoint| endpoint.address == address)
            .ok_or_else(|| {
                Status::unavailable(format!(
                    "remote stage target {target_name} endpoint {address} is no longer resolved"
                ))
            })
    }

    async fn endpoint_states_from_load(
        &self,
        target_name: &str,
        stage_id: &str,
        addresses: &[SocketAddr],
    ) -> EndpointStateMap<SocketAddr> {
        let mut loads = self.endpoint_loads.write().await;
        let live_addresses = addresses.iter().copied().collect::<HashSet<_>>();
        loads.retain(|key, load| {
            key.target_name != target_name
                || key.stage_id != stage_id
                || (live_addresses.contains(&key.address) && load.is_fresh())
        });

        addresses
            .iter()
            .filter_map(|address| {
                let key =
                    EndpointLoadKey::new(target_name.to_string(), stage_id.to_string(), *address);
                loads.get(&key).map(|load| (*address, load.local_state()))
            })
            .collect()
    }

    /// Drop endpoints whose last observed load explicitly advertised a
    /// `served_stage_ids` set that does **not** include `stage_id`. This is
    /// the version-skew guard: callers built against `resolution:v2` should
    /// not be routed to a pod that only advertises `resolution:v1`.
    ///
    /// Endpoints with no observation or with an empty `served_stage_ids`
    /// (older pods that don't advertise capability yet) are preserved — empty
    /// means "unknown", not "serves nothing".
    async fn filter_by_advertised_capability(
        &self,
        target_name: &str,
        stage_id: &str,
        addresses: Vec<SocketAddr>,
    ) -> Vec<SocketAddr> {
        let loads = self.endpoint_loads.read().await;
        addresses
            .into_iter()
            .filter(|address| {
                let key =
                    EndpointLoadKey::new(target_name.to_string(), stage_id.to_string(), *address);
                let Some(observed) = loads.get(&key) else {
                    return true;
                };
                if !observed.is_fresh() {
                    return true;
                }
                let advertised = &observed.load.served_stage_ids;
                advertised.is_empty() || advertised.iter().any(|served| served == stage_id)
            })
            .collect()
    }

    fn record_load_skipped_primary(&self, args: LoadSkippedPrimaryArgs<'_>) {
        let LoadSkippedPrimaryArgs {
            target_name,
            stage_id,
            routing_key,
            policy,
            addresses,
            endpoint_states,
            candidates,
        } = args;
        if !routing_key.has_affinity() || matches!(policy.mode, RoutingMode::Random) {
            return;
        }

        let mut rng = rand::thread_rng();
        let unloaded_candidates = pick_candidates_with_rng(
            stage_id,
            routing_key,
            addresses,
            &EndpointStateMap::new(),
            policy,
            &mut rng,
        );
        let Some(unloaded_primary) = unloaded_candidates.first().copied() else {
            return;
        };
        if candidates.first() == Some(&unloaded_primary) {
            return;
        }
        if !endpoint_states
            .get(&unloaded_primary)
            .is_some_and(|state| state.overloaded)
        {
            return;
        }

        let endpoint_label = unloaded_primary.to_string();
        metrics::counter!(
            REMOTE_ENDPOINT_LOAD_SKIPPED_PRIMARY,
            "stage" => stage_id.to_string(),
            "target" => target_name.to_string(),
            "endpoint" => endpoint_label.clone(),
        )
        .increment(1);
        tracing::info!(
            stage_id,
            target = target_name,
            skipped_endpoint = %endpoint_label,
            "remote stage skipped affinity primary because observed load is saturated"
        );
    }
}

pub async fn resolve_headless_service(
    dns_name: &str,
    port: u16,
) -> Result<Vec<SocketAddr>, RemoteStageConnectionError> {
    let addresses = lookup_host((dns_name, port))
        .await
        .map_err(|source| RemoteStageConnectionError::Resolve {
            dns_name: dns_name.to_string(),
            port,
            source,
        })?
        .collect::<Vec<_>>();

    if addresses.is_empty() {
        return Err(RemoteStageConnectionError::NoResolvedAddresses {
            dns_name: dns_name.to_string(),
            port,
        });
    }

    Ok(addresses)
}

fn endpoint_for_address(
    scheme: &str,
    address: SocketAddr,
    options: &RemoteStageConnectionOptions,
) -> Result<Endpoint, RemoteStageConnectionError> {
    let endpoint = format!("{scheme}://{address}");
    endpoint_from_uri(endpoint, options)
}

fn endpoint_from_uri(
    endpoint: String,
    options: &RemoteStageConnectionOptions,
) -> Result<Endpoint, RemoteStageConnectionError> {
    let mut endpoint = Endpoint::from_shared(endpoint.clone())
        .map_err(|source| RemoteStageConnectionError::InvalidEndpoint { endpoint, source })?
        .connect_timeout(options.connect_timeout)
        .tcp_keepalive(options.tcp_keepalive)
        .keep_alive_timeout(options.keep_alive_timeout)
        .keep_alive_while_idle(true);

    if let Some(interval) = options.http2_keep_alive_interval {
        endpoint = endpoint.http2_keep_alive_interval(interval);
    }

    Ok(endpoint)
}

#[cfg(test)]
mod tests {
    use cymbal_api::cymbal::v1::cymbal_stage_runtime_server::{
        CymbalStageRuntime, CymbalStageRuntimeServer,
    };
    use cymbal_api::cymbal::v1::{StageBatch, StageBatchResult, StageItemResult, StageLoad};
    use cymbal_core::{Metadata, StagePayload};
    use cymbal_domain::{EventResult, InputEvent};
    use cymbal_grouping::GROUPING_STAGE_ID;
    use cymbal_linking::LINKING_STAGE_ID;
    use cymbal_resolution::RESOLUTION_STAGE_ID;
    use tokio::net::TcpListener;
    use tokio_stream::wrappers::TcpListenerStream;
    use tonic::transport::Server;
    use tonic::{Request, Response};

    use super::*;
    use crate::remote::client::{RemoteStageClient, RemoteStageItem};
    use cymbal_core::BatchContext;

    #[derive(Debug, Default)]
    struct EchoStageService;

    #[derive(Debug)]
    struct NamedEchoStageService {
        label: String,
    }

    #[tonic::async_trait]
    impl CymbalStageRuntime for EchoStageService {
        async fn process_stage(
            &self,
            request: Request<StageBatch>,
        ) -> Result<Response<StageBatchResult>, Status> {
            let results = request
                .into_inner()
                .items
                .into_iter()
                .map(|item| StageItemResult {
                    item_id: item.item_id,
                    r#type: item.r#type,
                    payload: item.payload,
                })
                .collect();

            Ok(Response::new(StageBatchResult {
                results,
                errors: Vec::new(),
                load: None,
            }))
        }
    }

    #[tonic::async_trait]
    impl CymbalStageRuntime for NamedEchoStageService {
        async fn process_stage(
            &self,
            request: Request<StageBatch>,
        ) -> Result<Response<StageBatchResult>, Status> {
            let label = self.label.clone();
            let results = request
                .into_inner()
                .items
                .into_iter()
                .map(|item| StageItemResult {
                    item_id: item.item_id,
                    r#type: item.r#type,
                    payload: label.as_bytes().to_vec(),
                })
                .collect();

            Ok(Response::new(StageBatchResult {
                results,
                errors: Vec::new(),
                load: None,
            }))
        }
    }

    async fn start_test_stage_server() -> std::net::SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();

        tokio::spawn(async move {
            Server::builder()
                .add_service(CymbalStageRuntimeServer::new(EchoStageService))
                .serve_with_incoming(TcpListenerStream::new(listener))
                .await
                .unwrap();
        });

        addr
    }

    async fn start_named_test_stage_server(label: &str) -> std::net::SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let service = NamedEchoStageService {
            label: label.to_string(),
        };

        tokio::spawn(async move {
            Server::builder()
                .add_service(CymbalStageRuntimeServer::new(service))
                .serve_with_incoming(TcpListenerStream::new(listener))
                .await
                .unwrap();
        });

        addr
    }

    async fn process_test_item(client: &mut RemoteStageClient) -> StageBatchResult {
        client
            .process_items(
                BatchContext {
                    batch_id: "batch-1".to_string(),
                    metadata: Metadata::new(),
                },
                vec![RemoteStageItem::new(
                    "event-1",
                    InputEvent::TYPE,
                    br#"{"event":"$exception"}"#.to_vec(),
                )],
            )
            .await
            .unwrap()
    }

    fn assert_echoed_test_item(batch: &StageBatchResult) {
        assert_eq!(batch.results.len(), 1);
        assert!(batch.errors.is_empty());
        let item = &batch.results[0];
        assert_eq!(item.item_id, "event-1");
        assert_eq!(item.r#type, InputEvent::TYPE.to_string());
    }

    fn first_item_payload(batch: &StageBatchResult) -> String {
        assert_eq!(batch.results.len(), 1);
        assert!(batch.errors.is_empty());
        let item = &batch.results[0];
        String::from_utf8(item.payload.clone()).unwrap()
    }

    #[tokio::test]
    async fn remote_stage_client_sends_batch_to_stage_service() {
        let addr = start_test_stage_server().await;
        let config = RemoteStageConfig::new(
            format!("http://{addr}"),
            "remote:v1",
            InputEvent::TYPE,
            EventResult::TYPE,
        );
        let mut client = RemoteStageClient::connect(config).await.unwrap();

        let messages = process_test_item(&mut client).await;

        assert_echoed_test_item(&messages);
    }

    #[tokio::test]
    async fn remote_stage_connection_manager_resolves_dns_and_builds_client() {
        let addr = start_test_stage_server().await;
        let manager = RemoteStageConnectionManager::new();
        let target = RemoteStageTarget::new("resolution", "127.0.0.1", addr.port());
        manager.refresh_target(&target).await.unwrap();
        let config = RemoteStageConfig::new(
            format!("http://{addr}"),
            "remote:v1",
            InputEvent::TYPE,
            EventResult::TYPE,
        );
        let mut client = manager.client_for("resolution", config).await.unwrap();

        let messages = process_test_item(&mut client).await;

        assert_echoed_test_item(&messages);
    }

    #[tokio::test]
    async fn remote_stage_connection_manager_keeps_duplicate_target_name_endpoints() {
        let first_addr = start_named_test_stage_server("linking-1").await;
        let second_addr = start_named_test_stage_server("linking-2").await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("linking", "127.0.0.1", first_addr.port()),
                RemoteStageTarget::new("linking", "127.0.0.1", second_addr.port()),
            ])
            .await
            .unwrap();
        let config = RemoteStageConfig::new(
            "http://linking",
            "remote:v1",
            InputEvent::TYPE,
            EventResult::TYPE,
        );

        let mut first_client = manager
            .client_for_endpoint("linking", config.clone(), first_addr)
            .await
            .unwrap();
        let mut second_client = manager
            .client_for_endpoint("linking", config.clone(), second_addr)
            .await
            .unwrap();

        assert_eq!(
            first_item_payload(&process_test_item(&mut first_client).await),
            "linking-1"
        );
        assert_eq!(
            first_item_payload(&process_test_item(&mut second_client).await),
            "linking-2"
        );
    }

    #[tokio::test]
    async fn routing_policy_application_uses_stage_specific_candidate_limits() {
        let first_addr = start_named_test_stage_server("first").await;
        let second_addr = start_named_test_stage_server("second").await;
        let manager = RemoteStageConnectionManager::with_options_and_routing(
            RemoteStageConnectionOptions::default(),
            RemoteRoutingConfig::new(RoutingPolicy::affinity_first())
                .with_stage_policy(RESOLUTION_STAGE_ID, RoutingPolicy::affinity_first())
                .with_stage_policy(LINKING_STAGE_ID, RoutingPolicy::strict_affinity()),
        );
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("stages", "127.0.0.1", first_addr.port()),
                RemoteStageTarget::new("stages", "127.0.0.1", second_addr.port()),
            ])
            .await
            .unwrap();

        let resolution_candidates = manager
            .candidate_endpoints_for_stage("stages", RESOLUTION_STAGE_ID, &RoutingKey::team_id(2))
            .await
            .unwrap();
        let linking_candidates = manager
            .candidate_endpoints_for_stage("stages", LINKING_STAGE_ID, &RoutingKey::team_id(2))
            .await
            .unwrap();

        assert_eq!(resolution_candidates.len(), 2);
        assert_eq!(linking_candidates.len(), 1);
        assert!(resolution_candidates.contains(&linking_candidates[0]));
    }

    #[tokio::test]
    async fn endpoint_picker_skips_endpoint_with_saturated_load() {
        let primary_addr = start_named_test_stage_server("primary").await;
        let fallback_addr = start_named_test_stage_server("fallback").await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", primary_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", fallback_addr.port()),
            ])
            .await
            .unwrap();
        let mut routing_key = None;
        for team_id in 1..500 {
            let key = RoutingKey::team_id(team_id);
            let candidates = manager
                .candidate_endpoints(
                    "resolution",
                    RESOLUTION_STAGE_ID,
                    &key,
                    &RoutingPolicy::affinity_first(),
                )
                .await
                .unwrap();
            if candidates.first() == Some(&primary_addr) {
                routing_key = Some(key);
                break;
            }
        }
        let routing_key = routing_key.unwrap();

        manager
            .record_endpoint_load(
                "resolution",
                primary_addr,
                RESOLUTION_STAGE_ID,
                StageLoad {
                    current_in_flight_stage_batches: 4,
                    max_in_flight_stage_batches: 4,
                    overloaded: true,
                    ..Default::default()
                },
            )
            .await;

        let candidates = manager
            .candidate_endpoints(
                "resolution",
                RESOLUTION_STAGE_ID,
                &routing_key,
                &RoutingPolicy::affinity_first(),
            )
            .await
            .unwrap();

        assert_eq!(candidates, vec![fallback_addr]);
    }

    #[tokio::test]
    async fn default_load_signal_does_not_change_affinity_primary() {
        let first_addr = start_named_test_stage_server("first").await;
        let second_addr = start_named_test_stage_server("second").await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", first_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", second_addr.port()),
            ])
            .await
            .unwrap();
        let key = RoutingKey::team_id(42);
        let before = manager
            .candidate_endpoints(
                "resolution",
                RESOLUTION_STAGE_ID,
                &key,
                &RoutingPolicy::affinity_first(),
            )
            .await
            .unwrap();

        manager
            .record_endpoint_load(
                "resolution",
                before[0],
                RESOLUTION_STAGE_ID,
                StageLoad {
                    current_in_flight_stage_batches: 0,
                    max_in_flight_stage_batches: 0,
                    overloaded: false,
                    ..Default::default()
                },
            )
            .await;

        let after = manager
            .candidate_endpoints(
                "resolution",
                RESOLUTION_STAGE_ID,
                &key,
                &RoutingPolicy::affinity_first(),
            )
            .await
            .unwrap();

        assert_eq!(after, before);
    }

    #[tokio::test]
    async fn event_capacity_observations_are_per_stage_and_endpoint() {
        let first_addr = start_named_test_stage_server("first").await;
        let second_addr = start_named_test_stage_server("second").await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("stages", "127.0.0.1", first_addr.port()),
                RemoteStageTarget::new("stages", "127.0.0.1", second_addr.port()),
            ])
            .await
            .unwrap();

        manager
            .record_endpoint_load(
                "stages",
                first_addr,
                RESOLUTION_STAGE_ID,
                StageLoad {
                    current_in_flight_items: 8,
                    max_in_flight_items: 8,
                    ..Default::default()
                },
            )
            .await;
        manager
            .record_endpoint_load(
                "stages",
                second_addr,
                RESOLUTION_STAGE_ID,
                StageLoad {
                    current_in_flight_items: 1,
                    max_in_flight_items: 8,
                    ..Default::default()
                },
            )
            .await;
        manager
            .record_endpoint_load(
                "stages",
                first_addr,
                GROUPING_STAGE_ID,
                StageLoad {
                    current_in_flight_items: 0,
                    max_in_flight_items: 8,
                    ..Default::default()
                },
            )
            .await;

        let resolution_first_load = manager
            .observed_endpoint_load("stages", RESOLUTION_STAGE_ID, first_addr)
            .await
            .unwrap();
        let resolution_second_load = manager
            .observed_endpoint_load("stages", RESOLUTION_STAGE_ID, second_addr)
            .await
            .unwrap();
        let grouping_first_load = manager
            .observed_endpoint_load("stages", GROUPING_STAGE_ID, first_addr)
            .await
            .unwrap();

        assert_eq!(resolution_first_load.current_in_flight_items, 8);
        assert_eq!(resolution_second_load.current_in_flight_items, 1);
        assert_eq!(grouping_first_load.current_in_flight_items, 0);

        let resolution_candidates = manager
            .candidate_endpoints(
                "stages",
                RESOLUTION_STAGE_ID,
                &RoutingKey::team_id(42),
                &RoutingPolicy::affinity_first(),
            )
            .await
            .unwrap();
        assert_eq!(resolution_candidates, vec![second_addr]);

        let grouping_candidates = manager
            .candidate_endpoints(
                "stages",
                GROUPING_STAGE_ID,
                &RoutingKey::team_id(42),
                &RoutingPolicy::affinity_first(),
            )
            .await
            .unwrap();
        assert!(grouping_candidates.contains(&first_addr));
        assert!(grouping_candidates.contains(&second_addr));
    }

    #[tokio::test]
    async fn remote_stage_connection_manager_refresh_loop_replaces_target_addresses() {
        let first_addr = start_named_test_stage_server("old-resolution").await;
        let second_addr = start_named_test_stage_server("new-resolution").await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[RemoteStageTarget::new(
                "resolution",
                "127.0.0.1",
                first_addr.port(),
            )])
            .await
            .unwrap();
        let config = RemoteStageConfig::new(
            "http://resolution",
            "remote:v1",
            InputEvent::TYPE,
            EventResult::TYPE,
        );
        let mut client = manager
            .client_for("resolution", config.clone())
            .await
            .unwrap();
        assert_eq!(
            first_item_payload(&process_test_item(&mut client).await),
            "old-resolution"
        );

        let refresh_handle = manager.spawn_refresh_loop(
            vec![RemoteStageTarget::new(
                "resolution",
                "127.0.0.1",
                second_addr.port(),
            )],
            Duration::from_millis(10),
        );

        let mut refreshed = false;
        for _ in 0..50 {
            tokio::time::sleep(Duration::from_millis(20)).await;
            let mut client = manager
                .client_for("resolution", config.clone())
                .await
                .unwrap();
            if first_item_payload(&process_test_item(&mut client).await) == "new-resolution" {
                refreshed = true;
                break;
            }
        }
        refresh_handle.abort();

        assert!(
            refreshed,
            "expected DNS refresh loop to replace target channel"
        );
    }

    #[tokio::test]
    async fn advertised_capability_keeps_endpoint_when_stage_is_listed() {
        let addr = start_named_test_stage_server("ok").await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[RemoteStageTarget::new(
                "resolution",
                "127.0.0.1",
                addr.port(),
            )])
            .await
            .unwrap();

        manager
            .record_endpoint_load(
                "resolution",
                addr,
                RESOLUTION_STAGE_ID,
                StageLoad {
                    served_stage_ids: vec![RESOLUTION_STAGE_ID.to_string()],
                    ..Default::default()
                },
            )
            .await;

        let candidates = manager
            .candidate_endpoints(
                "resolution",
                RESOLUTION_STAGE_ID,
                &RoutingKey::team_id(1),
                &RoutingPolicy::affinity_first(),
            )
            .await
            .unwrap();

        assert_eq!(candidates, vec![addr]);
    }

    #[tokio::test]
    async fn advertised_capability_drops_endpoint_when_stage_is_missing() {
        let v1_only = start_named_test_stage_server("v1-only").await;
        let v2_capable = start_named_test_stage_server("v2-capable").await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", v1_only.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", v2_capable.port()),
            ])
            .await
            .unwrap();

        // The v1-only pod advertises a different stage_id than the dispatcher
        // is asking for, simulating mid-rollout version skew. It must be
        // filtered out of the candidate pool.
        manager
            .record_endpoint_load(
                "resolution",
                v1_only,
                "resolution:v2",
                StageLoad {
                    served_stage_ids: vec!["resolution:v1".to_string()],
                    ..Default::default()
                },
            )
            .await;
        manager
            .record_endpoint_load(
                "resolution",
                v2_capable,
                "resolution:v2",
                StageLoad {
                    served_stage_ids: vec!["resolution:v2".to_string()],
                    ..Default::default()
                },
            )
            .await;

        let candidates = manager
            .candidate_endpoints(
                "resolution",
                "resolution:v2",
                &RoutingKey::team_id(7),
                &RoutingPolicy::affinity_first(),
            )
            .await
            .unwrap();

        assert_eq!(candidates, vec![v2_capable]);
    }

    #[tokio::test]
    async fn advertised_capability_treats_empty_set_as_unknown() {
        // Older pods (or pods that haven't been probed yet) report an empty
        // `served_stage_ids`. The dispatcher must NOT interpret that as "serves
        // nothing" — that would break rollouts where the load advertisement
        // hasn't landed everywhere yet.
        let addr = start_named_test_stage_server("legacy").await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[RemoteStageTarget::new(
                "resolution",
                "127.0.0.1",
                addr.port(),
            )])
            .await
            .unwrap();

        manager
            .record_endpoint_load(
                "resolution",
                addr,
                RESOLUTION_STAGE_ID,
                StageLoad {
                    served_stage_ids: Vec::new(),
                    ..Default::default()
                },
            )
            .await;

        let candidates = manager
            .candidate_endpoints(
                "resolution",
                RESOLUTION_STAGE_ID,
                &RoutingKey::team_id(1),
                &RoutingPolicy::affinity_first(),
            )
            .await
            .unwrap();

        assert_eq!(candidates, vec![addr]);
    }

    #[tokio::test]
    async fn advertised_capability_returns_unavailable_when_no_endpoint_advertises_stage() {
        let addr = start_named_test_stage_server("v1-only").await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[RemoteStageTarget::new(
                "resolution",
                "127.0.0.1",
                addr.port(),
            )])
            .await
            .unwrap();

        manager
            .record_endpoint_load(
                "resolution",
                addr,
                "resolution:v2",
                StageLoad {
                    served_stage_ids: vec!["resolution:v1".to_string()],
                    ..Default::default()
                },
            )
            .await;

        let err = manager
            .candidate_endpoints(
                "resolution",
                "resolution:v2",
                &RoutingKey::team_id(1),
                &RoutingPolicy::affinity_first(),
            )
            .await
            .unwrap_err();

        assert_eq!(err.code(), tonic::Code::Unavailable);
    }
}
