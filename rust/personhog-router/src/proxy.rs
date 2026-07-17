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
    PROCESSING_TIME_HEADER,
};
use rand::Rng;
use tonic::body::BoxBody;
use tonic::Code;
use tower::{Service, ServiceExt};

use crate::backend::{LeaderBackend, ReplicaBackend};
use crate::config::RetryConfig;
use crate::grpc_http::{grpc_error_response, is_grpc_error_response};

const SERVICE_PREFIX: &str = "/personhog.service.v1.PersonHogService/";
const REPLICA_PREFIX: &str = "/personhog.replica.v1.PersonHogReplica/";

pub const KNOWN_METHODS: &[&str] = &[
    "AllocatePersonIds",
    "CheckCohortMembership",
    "CountCohortMembers",
    "CountGroupTypeMappings",
    "CreateGroup",
    "CreatePerson",
    "DeleteCohortMember",
    "DeleteCohortMembersBulk",
    "DeleteGroupTypeMapping",
    "DeleteGroupTypeMappingsBatchForTeam",
    "DeleteGroupsBatchForTeam",
    "DeleteHashKeyOverridesByTeams",
    "DeletePersonlessDistinctIdsBatchForTeam",
    "DeletePersons",
    "DeletePersonsBatchForTeam",
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
            // Person creation routes to the leader like every person-data
            // write; the x-person-id header carries the pre-allocated id
            // (AllocatePersonIds itself is replica-routed via the default
            // arm — sequence bookkeeping, not a person-data write).
            "CreatePerson" => {
                let (resp, call_ms) = self.raw_proxy_to_leader(req, "CreatePerson").await;
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
