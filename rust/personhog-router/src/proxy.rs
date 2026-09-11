use std::collections::{BTreeMap, HashMap};
use std::convert::Infallible;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::{Duration, Instant};

use bytes::Bytes;
use http_body::Frame;
use http_body_util::{BodyExt, Full};
use metrics::{counter, histogram};
use personhog_common::grpc::{
    current_caller_tag, current_client_name, ClientInFlightGuard, GZIP_OVERHEAD_HEADER,
    PROCESSING_TIME_HEADER, SEMANTIC_REFUSAL_METADATA_KEY,
};
use personhog_proto::personhog::types::v1::{
    FencePersonsRequest, FencePersonsResponse, ReleaseFenceItem, ReleaseFencesRequest,
};
use rand::Rng;
use tonic::body::BoxBody;
use tonic::Code;
use tower::{Service, ServiceExt};

use crate::backend::{ForwardDecision, ForwardPath, LeaderBackend, ReplicaBackend};
use crate::config::RetryConfig;
use crate::grpc_http::{
    decode_unary_frame, decode_unary_response, encode_unary_frame, encode_unary_response,
    grpc_error_response, grpc_status_code, is_grpc_error_response,
};

const SERVICE_PREFIX: &str = "/personhog.service.v1.PersonHogService/";
const REPLICA_PREFIX: &str = "/personhog.replica.v1.PersonHogReplica/";

pub const KNOWN_METHODS: &[&str] = &[
    "CheckCohortMembership",
    "CountCohortMembers",
    "CountGroupTypeMappings",
    "CreateGroup",
    "DeleteCohortMember",
    "DeleteCohortMembersBulk",
    "DeleteGroupTypeMapping",
    "DeleteGroupTypeMappingsBatchForTeam",
    "DeleteGroupsBatchForTeam",
    "DeleteHashKeyOverridesByTeams",
    "DeletePersons",
    "DeletePersonsBatchForTeam",
    "FencePerson",
    "FencePersons",
    "FoldPersonDocument",
    "GetDistinctIdsForPerson",
    "GetDistinctIdsForPersons",
    "GetGroup",
    "GetGroupTypeMappingByDashboardId",
    "GetGroupTypeMappingsByProjectId",
    "GetGroupTypeMappingsByProjectIds",
    "GetGroupTypeMappingsByTeamId",
    "GetGroupTypeMappingsByTeamIds",
    "GetGroups",
    "GetGroupsBatch",
    "GetHashKeyOverrideContext",
    "GetPerson",
    "GetPersonByDistinctId",
    "GetPersonByUuid",
    "GetPersons",
    "GetPersonsByDistinctIds",
    "GetPersonsByDistinctIdsInTeam",
    "GetPersonsByUuids",
    "InsertCohortMembers",
    "ListCohortMemberIds",
    "ListGroups",
    "ReleaseFence",
    "ReleaseFences",
    "SetPersonDistinctIdVersionFloor",
    "SetPersonVersionFloor",
    "SplitPerson",
    "UpdateGroup",
    "UpdateGroupTypeMapping",
    "UpdatePersonProperties",
    "UpsertHashKeyOverrides",
];

fn is_known_method(name: &str) -> bool {
    KNOWN_METHODS.binary_search(&name).is_ok()
}

pub struct RawProxyService {
    inner: Arc<RawProxyInner>,
}

struct RawProxyInner {
    replica: Arc<ReplicaBackend>,
    leader: Option<Arc<LeaderBackend>>,
    retry_config: RetryConfig,
    max_recv_message_size: usize,
    response_size_warn_bytes: usize,
}

impl RawProxyService {
    pub fn new(
        replica: Arc<ReplicaBackend>,
        leader: Option<Arc<LeaderBackend>>,
        retry_config: RetryConfig,
        max_recv_message_size: usize,
        response_size_warn_bytes: usize,
    ) -> Self {
        Self {
            inner: Arc::new(RawProxyInner {
                replica,
                leader,
                retry_config,
                max_recv_message_size,
                response_size_warn_bytes,
            }),
        }
    }
}

impl Clone for RawProxyService {
    fn clone(&self) -> Self {
        Self {
            inner: self.inner.clone(),
        }
    }
}

impl tonic::server::NamedService for RawProxyService {
    const NAME: &'static str = "personhog.service.v1.PersonHogService";
}

impl Service<http::Request<BoxBody>> for RawProxyService {
    type Response = http::Response<BoxBody>;
    type Error = Infallible;
    type Future = Pin<
        Box<dyn std::future::Future<Output = Result<http::Response<BoxBody>, Infallible>> + Send>,
    >;

    fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, req: http::Request<BoxBody>) -> Self::Future {
        let inner = self.inner.clone();
        Box::pin(async move { Ok(inner.handle(req).await) })
    }
}

impl RawProxyInner {
    async fn handle(&self, req: http::Request<BoxBody>) -> http::Response<BoxBody> {
        let path = req.uri().path().to_string();

        let method_name = match path.strip_prefix(SERVICE_PREFIX) {
            Some(m) => m,
            None => return grpc_error_response(Code::Unimplemented, "unknown service"),
        };

        if !is_known_method(method_name) {
            return grpc_error_response(
                Code::Unimplemented,
                &format!("unknown method: {method_name}"),
            );
        }

        let method: Arc<str> = Arc::from(method_name);
        let client = current_client_name();
        let caller_tag = current_caller_tag();
        let start = Instant::now();

        let (mut response, backend, channel_call_ms) = match method_name {
            "UpdatePersonProperties" => {
                let (resp, call_ms) = self
                    .raw_proxy_to_leader(req, "UpdatePersonProperties")
                    .await;
                (resp, "leader", call_ms)
            }
            // Lifecycle fence RPCs: person writes, so they route to the
            // owning leader and share the handoff stash discipline.
            "FencePerson" => {
                let (resp, call_ms) = self.raw_proxy_to_leader(req, "FencePerson").await;
                (resp, "leader", call_ms)
            }
            "FencePersons" => {
                let (resp, call_ms) = match self
                    .split_batch_to_leaders::<FencePersonsRequest>(req, "FencePersons")
                    .await
                {
                    Ok(outcomes) => {
                        merge_fence_responses(outcomes, self.max_recv_message_size).await
                    }
                    Err(resp) => (resp, None),
                };
                (resp, "leader", call_ms)
            }
            "ReleaseFence" => {
                let (resp, call_ms) = self.raw_proxy_to_leader(req, "ReleaseFence").await;
                (resp, "leader", call_ms)
            }
            "ReleaseFences" => {
                let (resp, call_ms) = match self
                    .split_batch_to_leaders::<ReleaseFencesRequest>(req, "ReleaseFences")
                    .await
                {
                    Ok(outcomes) => aggregate_release_responses(outcomes),
                    Err(resp) => (resp, None),
                };
                (resp, "leader", call_ms)
            }
            // The merge saga's document write: leader-routed like every
            // person write.
            "FoldPersonDocument" => {
                let (resp, call_ms) = self.raw_proxy_to_leader(req, "FoldPersonDocument").await;
                (resp, "leader", call_ms)
            }
            "GetPerson" => {
                let is_strong = req
                    .headers()
                    .get("x-read-consistency")
                    .and_then(|v| v.to_str().ok())
                    == Some("strong");

                if is_strong {
                    let (resp, call_ms) = self.raw_proxy_to_leader(req, "GetPerson").await;
                    (resp, "leader", call_ms)
                } else {
                    let (resp, call_ms) = self.raw_proxy_to_replica(req, method.clone()).await;
                    (resp, "replica", call_ms)
                }
            }
            _ => {
                let (resp, call_ms) = self.raw_proxy_to_replica(req, method.clone()).await;
                (resp, "replica", call_ms)
            }
        };

        let duration_ms = start.elapsed().as_secs_f64() * 1000.0;

        counter!(
            "personhog_router_backend_requests_total",
            "method" => method.clone(),
            "backend" => backend,
            "client" => client.clone(),
        )
        .increment(1);

        histogram!(
            "personhog_router_backend_duration_ms",
            "method" => method.clone(),
            "backend" => backend,
            "client" => client.clone(),
            "caller_tag" => caller_tag.clone(),
        )
        .record(duration_ms);

        let processing_ms = response
            .headers_mut()
            .remove(PROCESSING_TIME_HEADER)
            .and_then(|v| v.to_str().ok().and_then(|s| s.parse::<f64>().ok()));

        let gzip_overhead_ms = response
            .headers_mut()
            .remove(GZIP_OVERHEAD_HEADER)
            .and_then(|v| v.to_str().ok().and_then(|s| s.parse::<f64>().ok()));

        if let Some(processing_ms) = processing_ms {
            histogram!(
                "personhog_router_transport_overhead_ms",
                "method" => method.clone(),
                "backend" => backend,
                "client" => client.clone(),
            )
            .record((duration_ms - processing_ms).max(0.0));

            if let Some(call_ms) = channel_call_ms {
                let replica_total_ms = processing_ms + gzip_overhead_ms.unwrap_or(0.0);
                histogram!(
                    "personhog_router_network_overhead_ms",
                    "method" => method.clone(),
                    "backend" => backend,
                    "client" => client.clone(),
                )
                .record((call_ms - replica_total_ms).max(0.0));
            }
        }

        if is_grpc_error_response(&response) {
            counter!(
                "personhog_router_backend_errors_total",
                "method" => method.clone(),
                "backend" => backend,
                "client" => client.clone(),
                "code" => grpc_code_label(grpc_status_code(&response)),
            )
            .increment(1);
        }

        let (parts, body) = response.into_parts();
        let counted = ByteCountedBody::new(
            body,
            method,
            backend,
            client,
            caller_tag,
            self.response_size_warn_bytes,
        );
        http::Response::from_parts(parts, BoxBody::new(counted))
    }

    async fn raw_proxy_to_replica(
        &self,
        req: http::Request<BoxBody>,
        method: Arc<str>,
    ) -> (http::Response<BoxBody>, Option<f64>) {
        let (parts, body) = req.into_parts();

        let collect_start = Instant::now();
        let body_bytes = match collect_body_limited(body, self.max_recv_message_size).await {
            Ok(b) => b,
            Err(resp) => return (resp, None),
        };
        let client = current_client_name();
        histogram!(
            "personhog_router_body_collect_ms",
            "method" => method.clone(),
            "client" => client.clone(),
        )
        .record(collect_start.elapsed().as_secs_f64() * 1000.0);

        let new_path = format!("{REPLICA_PREFIX}{method}");

        let _in_flight = ClientInFlightGuard::new("replica");
        self.forward_with_retry(&parts, &body_bytes, &new_path, method)
            .await
    }

    async fn forward_with_retry(
        &self,
        parts: &http::request::Parts,
        body_bytes: &Bytes,
        new_path: &str,
        method: Arc<str>,
    ) -> (http::Response<BoxBody>, Option<f64>) {
        let mut delay_ms = self.retry_config.initial_backoff_ms;
        let client = current_client_name();

        for attempt in 0..=self.retry_config.max_retries {
            let mut channel = self.replica.channel();

            let ready_start = Instant::now();
            let ready_channel = match channel.ready().await {
                Ok(c) => c,
                Err(e) => {
                    histogram!(
                        "personhog_router_channel_ready_wait_ms",
                        "method" => method.clone(),
                        "client" => client.clone(),
                        "outcome" => "error",
                    )
                    .record(ready_start.elapsed().as_secs_f64() * 1000.0);

                    let is_last = attempt >= self.retry_config.max_retries;
                    if is_last {
                        return (
                            grpc_error_response(
                                Code::Unavailable,
                                &format!("replica channel not ready: {e}"),
                            ),
                            None,
                        );
                    }

                    retry_backoff(&mut delay_ms, &self.retry_config, &method, &client).await;
                    continue;
                }
            };
            histogram!(
                "personhog_router_channel_ready_wait_ms",
                "method" => method.clone(),
                "client" => client.clone(),
                "outcome" => "ok",
            )
            .record(ready_start.elapsed().as_secs_f64() * 1000.0);

            let body = BoxBody::new(Full::new(body_bytes.clone()).map_err(|never| match never {}));

            let mut req = http::Request::new(body);
            *req.method_mut() = parts.method.clone();
            *req.uri_mut() = http::Uri::builder()
                .path_and_query(new_path)
                .build()
                .unwrap();
            *req.version_mut() = parts.version;
            *req.headers_mut() = parts.headers.clone();

            let call_start = Instant::now();
            match ready_channel.call(req).await {
                Ok(response) => {
                    let channel_call_ms = call_start.elapsed().as_secs_f64() * 1000.0;
                    histogram!(
                        "personhog_router_channel_call_ms",
                        "method" => method.clone(),
                        "client" => client.clone(),
                        "outcome" => "ok",
                    )
                    .record(channel_call_ms);
                    return (response, Some(channel_call_ms));
                }
                Err(e) => {
                    histogram!(
                        "personhog_router_channel_call_ms",
                        "method" => method.clone(),
                        "client" => client.clone(),
                        "outcome" => "error",
                    )
                    .record(call_start.elapsed().as_secs_f64() * 1000.0);

                    let is_last = attempt >= self.retry_config.max_retries;
                    if is_last {
                        return (
                            grpc_error_response(
                                Code::Unavailable,
                                &format!("replica backend error: {e}"),
                            ),
                            None,
                        );
                    }

                    retry_backoff(&mut delay_ms, &self.retry_config, &method, &client).await;
                }
            }
        }

        unreachable!()
    }

    /// Raw-forward a leader request — a strong `GetPerson` or an
    /// `UpdatePersonProperties` — to the owning leader pod. The routing key
    /// arrives in the `x-team-id`/`x-person-id` headers stamped by the
    /// client, is hashed to a partition, and the request bytes are forwarded
    /// verbatim with the partition in the `x-partition` header. The body is
    /// never inspected, so client-compressed request frames transit
    /// untouched.
    ///
    /// Both writes and strong reads go through the per-partition stash
    /// during a handoff. Writes must buffer for the no-split-brain
    /// guarantee; strong reads must buffer with them so read-your-write
    /// holds across the handoff — a strong read racing ahead to the old
    /// owner would miss any write parked in the stash before it, and a
    /// read arriving after cutover on a router that hasn't seen Complete
    /// would read the old owner's frozen cache after the new owner has
    /// already accepted writes. Outside a handoff the stash is empty and
    /// requests forward directly, surfacing the channel round-trip time
    /// for the network-overhead metric.
    async fn raw_proxy_to_leader(
        &self,
        req: http::Request<BoxBody>,
        method: &'static str,
    ) -> (http::Response<BoxBody>, Option<f64>) {
        let leader = match &self.leader {
            Some(l) => l.clone(),
            None => {
                return (
                    grpc_error_response(
                        Code::Unimplemented,
                        "leader backend not configured for this router",
                    ),
                    None,
                )
            }
        };

        // Reject requests without a routing key before paying for body
        // collection.
        let (team_id, person_id) = match person_key_from_headers(req.headers()) {
            Ok(key) => key,
            Err(resp) => return (resp, None),
        };

        let (parts, body) = req.into_parts();
        let collect_start = Instant::now();
        let body_bytes = match collect_body_limited(body, self.max_recv_message_size).await {
            Ok(b) => b,
            Err(resp) => return (resp, None),
        };
        histogram!(
            "personhog_router_body_collect_ms",
            "method" => method,
            "client" => current_client_name(),
        )
        .record(collect_start.elapsed().as_secs_f64() * 1000.0);

        let partition = leader.partition_for_person(team_id, person_id);

        let _in_flight = ClientInFlightGuard::new("leader");
        leader
            .forward_or_stash(
                method,
                partition,
                (team_id, person_id),
                parts.headers,
                body_bytes,
            )
            .await
    }

    /// The leader-bound methods whose bodies the router decodes: the router
    /// is what knows which pod owns which partition, so a saga's per-op
    /// batch is split into one sub-request per owning pod here. A pod that
    /// already applied its share stays applied when a sibling fails, and
    /// the saga's retry absorbs that per person. Yields every
    /// sub-request's outcome for the method's own aggregation, or the one
    /// response that ended the call before anything was forwarded.
    async fn split_batch_to_leaders<B: PodSplitBatch>(
        &self,
        req: http::Request<BoxBody>,
        method: &'static str,
    ) -> Result<Vec<(http::Response<BoxBody>, Option<f64>)>, http::Response<BoxBody>> {
        let leader = match &self.leader {
            Some(l) => l.clone(),
            None => {
                return Err(grpc_error_response(
                    Code::Unimplemented,
                    "leader backend not configured for this router",
                ))
            }
        };

        let (parts, body) = req.into_parts();
        let collect_start = Instant::now();
        let body_bytes = collect_body_limited(body, self.max_recv_message_size).await?;
        histogram!(
            "personhog_router_body_collect_ms",
            "method" => method,
            "client" => current_client_name(),
        )
        .record(collect_start.elapsed().as_secs_f64() * 1000.0);

        let mut request: B = decode_unary_frame(&body_bytes)?;
        let items = request.take_items();
        if items.is_empty() {
            return Err(grpc_error_response(
                Code::InvalidArgument,
                &format!("{method} needs at least one person"),
            ));
        }

        let team_id = request.team_id();
        let mut owners: HashMap<u32, Option<String>> = HashMap::new();
        for item in &items {
            let partition = leader.partition_for_person(team_id, B::person_id(item));
            if let std::collections::hash_map::Entry::Vacant(entry) = owners.entry(partition) {
                entry.insert(leader.owner_of_partition(partition).await);
            }
        }
        let groups = group_by_owning_pod(
            items,
            B::person_id,
            |person_id| leader.partition_for_person(team_id, person_id),
            |partition| owners[&partition].clone(),
        );
        histogram!("personhog_router_batch_pods", "method" => method).record(groups.len() as f64);

        // The client's content-length describes its frame, not the
        // re-encoded sub-batches.
        let mut headers = parts.headers;
        headers.remove(http::header::CONTENT_LENGTH);

        let _in_flight = ClientInFlightGuard::new("leader");
        let forwards = groups
            .into_iter()
            .map(|group| forward_group(Arc::clone(&leader), method, &request, group, &headers));
        let outcomes = futures::future::join_all(forwards).await;
        Ok(outcomes.into_iter().flatten().collect())
    }
}

/// A saga batch the router splits by owning pod: its per-person items, and
/// how to rebuild a sub-batch that carries the same op fields.
trait PodSplitBatch: prost::Message + Default + Sync {
    type Item: Clone + Send + Sync;

    fn team_id(&self) -> i64;
    fn take_items(&mut self) -> Vec<Self::Item>;
    fn person_id(item: &Self::Item) -> i64;
    fn with_items(&self, items: Vec<Self::Item>) -> Self;
}

impl PodSplitBatch for FencePersonsRequest {
    type Item = i64;

    fn team_id(&self) -> i64 {
        self.team_id
    }

    fn take_items(&mut self) -> Vec<i64> {
        std::mem::take(&mut self.person_ids)
    }

    fn person_id(item: &i64) -> i64 {
        *item
    }

    fn with_items(&self, person_ids: Vec<i64>) -> Self {
        Self {
            person_ids,
            ..self.clone()
        }
    }
}

impl PodSplitBatch for ReleaseFencesRequest {
    type Item = ReleaseFenceItem;

    fn team_id(&self) -> i64 {
        self.team_id
    }

    fn take_items(&mut self) -> Vec<ReleaseFenceItem> {
        std::mem::take(&mut self.persons)
    }

    fn person_id(item: &ReleaseFenceItem) -> i64 {
        item.person_id
    }

    fn with_items(&self, persons: Vec<ReleaseFenceItem>) -> Self {
        Self {
            persons,
            ..self.clone()
        }
    }
}

/// The items of one saga batch grouped by the pod that owns their
/// partitions, each group keyed by partition. A partition with no owner
/// forms its own group, so its bounce-and-retry does not hold up the
/// persons that can proceed.
fn group_by_owning_pod<T>(
    items: Vec<T>,
    person_id_of: impl Fn(&T) -> i64,
    partition_of: impl Fn(i64) -> u32,
    owner_of: impl Fn(u32) -> Option<String>,
) -> Vec<BTreeMap<u32, Vec<T>>> {
    let mut groups: BTreeMap<String, BTreeMap<u32, Vec<T>>> = BTreeMap::new();
    for item in items {
        let partition = partition_of(person_id_of(&item));
        let key = owner_of(partition).unwrap_or_else(|| format!("unassigned:{partition}"));
        groups
            .entry(key)
            .or_default()
            .entry(partition)
            .or_default()
            .push(item);
    }
    groups.into_values().collect()
}

/// Forward one pod's share of a batch. While every partition in the group
/// is quiet on this router, the group goes as one frame keyed on its first
/// partition; the leader refuses it whole if any of them is not its own or
/// is fenced for handoff, and the router then falls back to one
/// sub-request per partition, each riding its own partition's stash and
/// retry loop, the same discipline a single fence or release gets. A
/// handoff on any partition of the pod therefore costs the batching, never
/// the op.
async fn forward_group<B: PodSplitBatch>(
    leader: Arc<LeaderBackend>,
    method: &'static str,
    batch: &B,
    group: BTreeMap<u32, Vec<B::Item>>,
    headers: &http::HeaderMap,
) -> Vec<(http::Response<BoxBody>, Option<f64>)> {
    let team_id = batch.team_id();
    let frame_for = |items: Vec<B::Item>| encode_unary_frame(&batch.with_items(items));

    if group.len() > 1
        && group
            .keys()
            .all(|partition| !leader.stash_has_entry(*partition))
    {
        let header_partition = *group.keys().next().expect("a group is never empty");
        let frame = frame_for(group.values().flatten().cloned().collect());
        match leader
            .forward_classified(
                ForwardPath::Direct,
                method,
                header_partition,
                headers,
                &frame,
            )
            .await
        {
            ForwardDecision::Delivered { response, call_ms } => {
                return vec![(response, Some(call_ms))];
            }
            // A transport bounce may have applied the grouped frame; the
            // per-partition replays below are at-least-once, which every
            // fence and release absorbs.
            _ => counter!("personhog_router_batch_group_splits_total", "method" => method)
                .increment(1),
        }
    }

    let forwards = group.into_iter().map(|(partition, items)| {
        let key = (team_id, B::person_id(&items[0]));
        let frame = frame_for(items);
        let headers = headers.clone();
        let leader = Arc::clone(&leader);
        async move {
            leader
                .forward_or_stash(method, partition, key, headers, frame)
                .await
        }
    });
    futures::future::join_all(forwards).await
}

/// Every sub-request's outcome sorted for the caller's one answer: the
/// error that stands for the batch, if any, the successes, and the slowest
/// call's time. A semantic refusal outranks any other error, since it is a
/// final answer the saga must not retry past a sibling's transient error.
struct BatchOutcomes {
    error: Option<http::Response<BoxBody>>,
    successes: Vec<http::Response<BoxBody>>,
    call_ms: Option<f64>,
}

fn sort_batch_outcomes(outcomes: Vec<(http::Response<BoxBody>, Option<f64>)>) -> BatchOutcomes {
    let mut call_ms: Option<f64> = None;
    let mut successes = Vec::new();
    let mut error: Option<(http::Response<BoxBody>, bool)> = None;
    for (response, ms) in outcomes {
        call_ms = match (call_ms, ms) {
            (Some(a), Some(b)) => Some(a.max(b)),
            (a, b) => a.or(b),
        };
        if !is_grpc_error_response(&response) {
            successes.push(response);
            continue;
        }
        let semantic = response
            .headers()
            .contains_key(SEMANTIC_REFUSAL_METADATA_KEY);
        if error.as_ref().is_none_or(|(_, kept)| semantic && !kept) {
            error = Some((response, semantic));
        }
    }
    BatchOutcomes {
        error: error.map(|(response, _)| response),
        successes,
        call_ms,
    }
}

/// One answer for a release batch: its error, else one success stands for
/// all, since a release answers nothing.
fn aggregate_release_responses(
    outcomes: Vec<(http::Response<BoxBody>, Option<f64>)>,
) -> (http::Response<BoxBody>, Option<f64>) {
    let sorted = sort_batch_outcomes(outcomes);
    match sorted.error {
        Some(response) => (response, sorted.call_ms),
        None => (
            sorted
                .successes
                .into_iter()
                .next()
                .expect("a non-empty batch forwards to at least one pod"),
            sorted.call_ms,
        ),
    }
}

/// One answer for a fence batch: its error, else the pods' answers
/// concatenated, since each pod fenced a disjoint share of the persons.
async fn merge_fence_responses(
    outcomes: Vec<(http::Response<BoxBody>, Option<f64>)>,
    max_bytes: usize,
) -> (http::Response<BoxBody>, Option<f64>) {
    let sorted = sort_batch_outcomes(outcomes);
    if let Some(response) = sorted.error {
        return (response, sorted.call_ms);
    }
    let mut merged = FencePersonsResponse::default();
    for response in sorted.successes {
        match decode_unary_response::<FencePersonsResponse>(response, max_bytes).await {
            Ok(part) => {
                merged.sealed.extend(part.sealed);
                merged.not_found.extend(part.not_found);
            }
            Err(response) => return (response, sorted.call_ms),
        }
    }
    (encode_unary_response(&merged), sorted.call_ms)
}

/// Static label for an error response's gRPC status, separating expected
/// admission rejections (invalid_argument) from availability and internal
/// failures on the errors counter.
fn grpc_code_label(code: Option<i32>) -> &'static str {
    match code {
        Some(3) => "invalid_argument",
        Some(4) => "deadline_exceeded",
        Some(5) => "not_found",
        Some(8) => "resource_exhausted",
        Some(9) => "failed_precondition",
        Some(13) => "internal",
        Some(14) => "unavailable",
        _ => "other",
    }
}

// ── gRPC body helpers ──────────────────────────────────────────────────

async fn collect_body_limited(
    mut body: BoxBody,
    max_bytes: usize,
) -> Result<Bytes, http::Response<BoxBody>> {
    // Most unary requests arrive as a single DATA frame, which we hand on
    // as-is without copying the payload. Only bodies that span multiple
    // frames (large payloads split at the HTTP/2 frame size) pay for
    // reassembly into a contiguous buffer, which the retry path needs so
    // it can replay the request.
    let mut first: Option<Bytes> = None;
    let mut buf: Vec<u8> = Vec::new();

    while let Some(frame_result) = body.frame().await {
        let frame = frame_result.map_err(|e| {
            grpc_error_response(Code::Internal, &format!("failed to read body: {e}"))
        })?;
        let Ok(data) = frame.into_data() else {
            continue;
        };

        let collected = first.as_ref().map_or(0, Bytes::len) + buf.len();
        if collected + data.len() > max_bytes {
            return Err(grpc_error_response(
                Code::ResourceExhausted,
                &format!("received message larger than max ({max_bytes} bytes)"),
            ));
        }

        if first.is_none() && buf.is_empty() {
            first = Some(data);
        } else {
            if let Some(f) = first.take() {
                buf.reserve(f.len() + data.len());
                buf.extend_from_slice(&f);
            }
            buf.extend_from_slice(&data);
        }
    }

    Ok(match first {
        Some(single_frame) => single_frame,
        None => Bytes::from(buf),
    })
}

/// Shared retry bookkeeping for the raw-forward paths: bump the retry
/// counter, sleep a jittered backoff, and grow the delay toward the cap.
async fn retry_backoff(
    delay_ms: &mut u64,
    retry_config: &RetryConfig,
    method: &Arc<str>,
    client: &Arc<str>,
) {
    counter!(
        "personhog_router_backend_retries_total",
        "method" => method.clone(),
        "status_code" => "unavailable",
        "client" => client.clone(),
    )
    .increment(1);

    let base = *delay_ms / 2;
    let jittered = base + rand::thread_rng().gen_range(0..=base);
    tokio::time::sleep(Duration::from_millis(jittered)).await;
    *delay_ms = (*delay_ms * 2).min(retry_config.max_backoff_ms);
}

/// Routing-key headers stamped by clients on every leader-path request.
/// The router hashes these to a partition instead of inspecting the request
/// body; the leader independently validates them against the decoded body.
const TEAM_ID_HEADER: &str = "x-team-id";
const PERSON_ID_HEADER: &str = "x-person-id";

/// Extract the `(team_id, person_id)` routing key from request headers.
/// A missing or malformed header means the client predates the header
/// contract or the request is malformed, so we fail closed rather than
/// guess a partition.
// `http::Response` is the error type every helper on this path returns; the
// large variant trips `result_large_err`, but boxing here would diverge from
// `collect_body_limited` and friends.
#[allow(clippy::result_large_err)]
fn person_key_from_headers(
    headers: &http::HeaderMap,
) -> Result<(i64, i64), http::Response<BoxBody>> {
    let team_id = i64_header(headers, TEAM_ID_HEADER)?;
    let person_id = i64_header(headers, PERSON_ID_HEADER)?;
    Ok((team_id, person_id))
}

#[allow(clippy::result_large_err)]
fn i64_header(
    headers: &http::HeaderMap,
    name: &'static str,
) -> Result<i64, http::Response<BoxBody>> {
    let value = headers.get(name).ok_or_else(|| {
        grpc_error_response(
            Code::InvalidArgument,
            &format!("missing {name} header required for leader routing"),
        )
    })?;
    value
        .to_str()
        .ok()
        .and_then(|v| v.parse::<i64>().ok())
        .ok_or_else(|| {
            grpc_error_response(
                Code::InvalidArgument,
                &format!("{name} header is not a valid integer"),
            )
        })
}

/// Response body wrapper that counts bytes from DATA frames and records
/// the total to a histogram on drop. Emits a structured warning when the
/// response exceeds `warn_threshold` bytes.
struct ByteCountedBody {
    inner: BoxBody,
    bytes_counted: usize,
    method: Arc<str>,
    backend: &'static str,
    client: Arc<str>,
    caller_tag: Arc<str>,
    warn_threshold: usize,
}

impl ByteCountedBody {
    fn new(
        inner: BoxBody,
        method: Arc<str>,
        backend: &'static str,
        client: Arc<str>,
        caller_tag: Arc<str>,
        warn_threshold: usize,
    ) -> Self {
        Self {
            inner,
            bytes_counted: 0,
            method,
            backend,
            client,
            caller_tag,
            warn_threshold,
        }
    }
}

impl http_body::Body for ByteCountedBody {
    type Data = Bytes;
    type Error = tonic::Status;

    fn poll_frame(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        let this = self.get_mut();
        let result = Pin::new(&mut this.inner).poll_frame(cx);
        if let Poll::Ready(Some(Ok(ref frame))) = result {
            if let Some(data) = frame.data_ref() {
                this.bytes_counted += data.len();
            }
        }
        result
    }
}

impl Drop for ByteCountedBody {
    fn drop(&mut self) {
        histogram!(
            "personhog_router_response_size_bytes",
            "method" => self.method.clone(),
            "backend" => self.backend,
            "client" => self.client.clone(),
            "caller_tag" => self.caller_tag.clone(),
        )
        .record(self.bytes_counted as f64);

        if self.warn_threshold > 0 && self.bytes_counted > self.warn_threshold {
            tracing::warn!(
                response_size_bytes = self.bytes_counted,
                method = %self.method,
                backend = self.backend,
                client = %self.client,
                caller_tag = %self.caller_tag,
                "oversized gRPC response"
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The split is by owning pod, not by partition: two partitions on the
    /// same pod share a group, while an unassigned partition stands alone
    /// so its retry cannot hold the others up.
    #[test]
    fn batch_items_group_by_owning_pod() {
        let person = |person_id| ReleaseFenceItem {
            person_id,
            ..Default::default()
        };
        // The person id doubles as its partition here.
        let owner = |partition: u32| match partition {
            1 | 2 => Some("pod-a".to_string()),
            3 => Some("pod-b".to_string()),
            _ => None,
        };
        let groups = group_by_owning_pod(
            vec![person(1), person(2), person(3), person(4), person(1)],
            ReleaseFencesRequest::person_id,
            |person_id| person_id as u32,
            owner,
        );

        let mut partitions_per_group: Vec<Vec<u32>> = groups
            .iter()
            .map(|group| group.keys().copied().collect())
            .collect();
        partitions_per_group.sort();
        assert_eq!(partitions_per_group, vec![vec![1, 2], vec![3], vec![4]]);
        let pod_a = groups.iter().find(|group| group.len() == 2).unwrap();
        assert_eq!(pod_a[&1].len(), 2, "both persons on partition 1");
    }

    /// Each pod answers for its own share, so the caller's one answer is
    /// every pod's seals and not-founds together; and a pod's error stands
    /// for the batch, with a semantic refusal outranking a transient one
    /// whatever order the pods answered in.
    #[tokio::test]
    async fn fence_responses_merge_every_pod_and_keep_the_semantic_refusal() {
        use personhog_proto::personhog::types::v1::FencedPersonSeal;

        let seal = |person_id| FencedPersonSeal {
            person_id,
            version: 1,
            created_at: 1,
        };
        let pod_a = encode_unary_response(&FencePersonsResponse {
            sealed: vec![seal(1), seal(2)],
            not_found: vec![3],
        });
        let pod_b = encode_unary_response(&FencePersonsResponse {
            sealed: vec![seal(4)],
            not_found: vec![],
        });
        let (merged, call_ms) =
            merge_fence_responses(vec![(pod_a, Some(2.0)), (pod_b, Some(5.0))], 1 << 20).await;
        assert_eq!(
            call_ms,
            Some(5.0),
            "the batch took as long as its slowest pod"
        );
        let merged: FencePersonsResponse = decode_unary_response(merged, 1 << 20)
            .await
            .expect("the merged response decodes");
        let mut sealed: Vec<i64> = merged.sealed.iter().map(|s| s.person_id).collect();
        sealed.sort_unstable();
        assert_eq!(sealed, vec![1, 2, 4]);
        assert_eq!(merged.not_found, vec![3]);

        let transient = grpc_error_response(Code::Unavailable, "leader down");
        let mut semantic = grpc_error_response(Code::FailedPrecondition, "refused");
        semantic.headers_mut().insert(
            SEMANTIC_REFUSAL_METADATA_KEY,
            "no-lifecycle-db".parse().unwrap(),
        );
        let ok = encode_unary_response(&FencePersonsResponse::default());
        let (answer, _) = merge_fence_responses(
            vec![(transient, None), (ok, None), (semantic, None)],
            1 << 20,
        )
        .await;
        assert_eq!(
            grpc_status_code(&answer),
            Some(Code::FailedPrecondition as i32)
        );
        assert!(answer.headers().contains_key(SEMANTIC_REFUSAL_METADATA_KEY));
    }
    use futures::stream;
    use http_body_util::{Empty, StreamBody};

    #[test]
    fn known_method_lookup() {
        assert!(is_known_method("GetPerson"));
        assert!(is_known_method("UpdatePersonProperties"));
        assert!(is_known_method("ListGroups"));
        assert!(is_known_method("CheckCohortMembership"));
        assert!(!is_known_method("FakeMethod"));
        assert!(!is_known_method(""));
    }

    #[test]
    fn known_methods_is_sorted() {
        for window in KNOWN_METHODS.windows(2) {
            assert!(
                window[0] < window[1],
                "KNOWN_METHODS is not sorted: {:?} should come after {:?}",
                window[0],
                window[1],
            );
        }
    }

    #[test]
    fn known_methods_matches_service_proto() {
        let proto = std::fs::read_to_string(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../proto/personhog/service/v1/service.proto"
        ))
        .expect("failed to read service.proto — is the proto directory present?");

        let mut proto_methods: Vec<&str> = proto
            .lines()
            .filter_map(|line| {
                line.trim()
                    .strip_prefix("rpc ")
                    .and_then(|rest| rest.split('(').next())
                    .map(|name| name.trim())
            })
            .collect();
        proto_methods.sort();

        let known: Vec<&str> = KNOWN_METHODS.to_vec();
        assert_eq!(
            known, proto_methods,
            "KNOWN_METHODS is out of sync with service.proto — add/remove entries to match"
        );
    }

    /// Well-formed routing-key headers yield the `(team_id, person_id)`
    /// pair the router hashes for partition placement.
    #[test]
    fn person_key_from_headers_extracts_key() {
        let mut headers = http::HeaderMap::new();
        headers.insert(TEAM_ID_HEADER, "1".parse().unwrap());
        headers.insert(PERSON_ID_HEADER, "42".parse().unwrap());

        let (team_id, person_id) = person_key_from_headers(&headers).expect("valid headers");
        assert_eq!(team_id, 1);
        assert_eq!(person_id, 42);
    }

    /// Missing or malformed routing-key headers fail closed with
    /// InvalidArgument — the router must never guess a partition.
    #[test]
    fn person_key_from_headers_rejects_missing_or_malformed() {
        let cases: [(Option<&str>, Option<&str>, &str); 4] = [
            (None, Some("42"), "missing x-team-id"),
            (Some("1"), None, "missing x-person-id"),
            (Some("abc"), Some("42"), "non-numeric x-team-id"),
            (Some("1"), Some("12.5"), "non-integer x-person-id"),
        ];

        for (team, person, why) in cases {
            let mut headers = http::HeaderMap::new();
            if let Some(v) = team {
                headers.insert(TEAM_ID_HEADER, v.parse().unwrap());
            }
            if let Some(v) = person {
                headers.insert(PERSON_ID_HEADER, v.parse().unwrap());
            }
            let resp = person_key_from_headers(&headers).expect_err(&format!("must reject: {why}"));
            assert_eq!(
                resp.headers().get("grpc-status").unwrap(),
                &format!("{}", Code::InvalidArgument as i32),
                "wrong status for: {why}"
            );
        }
    }

    #[tokio::test]
    async fn collect_body_limited_accepts_within_limit() {
        let data = Bytes::from(vec![0u8; 100]);
        let body = BoxBody::new(Full::new(data.clone()).map_err(|never| match never {}));
        let result = collect_body_limited(body, 100).await;
        assert!(result.is_ok());
        assert_eq!(result.unwrap().len(), 100);
    }

    #[tokio::test]
    async fn collect_body_limited_rejects_over_limit() {
        let data = Bytes::from(vec![0u8; 101]);
        let body = BoxBody::new(Full::new(data).map_err(|never| match never {}));
        let result = collect_body_limited(body, 100).await;
        assert!(result.is_err());
        let resp = result.unwrap_err();
        assert_eq!(
            resp.headers().get("grpc-status").unwrap(),
            &format!("{}", Code::ResourceExhausted as i32),
        );
    }

    #[tokio::test]
    async fn collect_body_limited_accepts_empty() {
        let body = BoxBody::new(Empty::<Bytes>::new().map_err(|never| match never {}));
        let result = collect_body_limited(body, 100).await;
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }

    /// Build a body that yields each chunk as its own DATA frame,
    /// exercising the multi-frame reassembly path (large payloads arrive
    /// split at the HTTP/2 frame size).
    fn multi_frame_body(chunks: Vec<&'static [u8]>) -> BoxBody {
        let frames = chunks
            .into_iter()
            .map(|c| Ok::<_, tonic::Status>(Frame::data(Bytes::from_static(c))));
        BoxBody::new(StreamBody::new(stream::iter(frames)))
    }

    #[tokio::test]
    async fn collect_body_limited_reassembles_multiple_frames() {
        let body = multi_frame_body(vec![b"hello ", b"personhog ", b"world"]);
        let result = collect_body_limited(body, 100).await.unwrap();
        assert_eq!(&result[..], b"hello personhog world");
    }

    #[tokio::test]
    async fn collect_body_limited_rejects_over_limit_across_frames() {
        // Each frame is under the limit; their sum is not.
        let body = multi_frame_body(vec![&[0u8; 60], &[0u8; 60]]);
        let result = collect_body_limited(body, 100).await;
        let resp = result.unwrap_err();
        assert_eq!(
            resp.headers().get("grpc-status").unwrap(),
            &format!("{}", Code::ResourceExhausted as i32),
        );
    }
}
