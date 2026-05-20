use std::convert::Infallible;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Instant;

use bytes::Bytes;
use http::{HeaderMap, HeaderValue};
use http_body::Frame;
use http_body_util::{BodyExt, Empty, Full};
use metrics::{counter, histogram};
use personhog_common::grpc::{current_client_name, ClientInFlightGuard};
use personhog_proto::personhog::types::v1::{GetPersonRequest, UpdatePersonPropertiesRequest};
use prost::Message;
use rand::Rng;
use tonic::body::BoxBody;
use tonic::Code;
use tower::{Service, ServiceExt};

use crate::backend::{LeaderBackend, LeaderOps, ReplicaBackend};
use crate::config::RetryConfig;

const SERVICE_PREFIX: &str = "/personhog.service.v1.PersonHogService/";
const REPLICA_PREFIX: &str = "/personhog.replica.v1.PersonHogReplica/";

const KNOWN_METHODS: &[&str] = &[
    "CheckCohortMembership",
    "CountCohortMembers",
    "CreateGroup",
    "DeleteCohortMember",
    "DeleteCohortMembersBulk",
    "DeleteGroupTypeMapping",
    "DeleteGroupTypeMappingsBatchForTeam",
    "DeleteGroupsBatchForTeam",
    "DeleteHashKeyOverridesByTeams",
    "DeletePersons",
    "DeletePersonsBatchForTeam",
    "GetDistinctIdsForPerson",
    "GetDistinctIdsForPersons",
    "GetGroup",
    "GetGroups",
    "GetGroupTypeMappingByDashboardId",
    "GetGroupTypeMappingsByProjectId",
    "GetGroupTypeMappingsByProjectIds",
    "GetGroupTypeMappingsByTeamId",
    "GetGroupTypeMappingsByTeamIds",
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
}

impl RawProxyService {
    pub fn new(
        replica: Arc<ReplicaBackend>,
        leader: Option<Arc<LeaderBackend>>,
        retry_config: RetryConfig,
    ) -> Self {
        Self {
            inner: Arc::new(RawProxyInner {
                replica,
                leader,
                retry_config,
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
    type Future =
        Pin<Box<dyn std::future::Future<Output = Result<http::Response<BoxBody>, Infallible>> + Send>>;

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

        let client = current_client_name();
        let start = Instant::now();

        let (response, backend) = match method_name {
            "UpdatePersonProperties" => {
                (self.handle_update_person_properties(req).await, "leader")
            }
            "GetPerson" => {
                let is_strong = req
                    .headers()
                    .get("x-read-consistency")
                    .and_then(|v| v.to_str().ok())
                    == Some("strong");

                if is_strong {
                    (self.handle_get_person_strong(req).await, "leader")
                } else {
                    (
                        self.raw_proxy_to_replica(req, method_name).await,
                        "replica",
                    )
                }
            }
            _ => (
                self.raw_proxy_to_replica(req, method_name).await,
                "replica",
            ),
        };

        let duration_ms = start.elapsed().as_secs_f64() * 1000.0;

        counter!(
            "personhog_router_backend_requests_total",
            "method" => method_name.to_string(),
            "backend" => backend,
            "client" => client.clone(),
        )
        .increment(1);

        histogram!(
            "personhog_router_backend_duration_ms",
            "method" => method_name.to_string(),
            "backend" => backend,
            "client" => client.clone(),
        )
        .record(duration_ms);

        if is_grpc_error_response(&response) {
            counter!(
                "personhog_router_backend_errors_total",
                "method" => method_name.to_string(),
                "backend" => backend,
                "client" => client,
            )
            .increment(1);
        }

        response
    }

    async fn raw_proxy_to_replica(
        &self,
        req: http::Request<BoxBody>,
        method: &str,
    ) -> http::Response<BoxBody> {
        let (parts, body) = req.into_parts();

        let body_bytes = match body.collect().await {
            Ok(collected) => collected.to_bytes(),
            Err(e) => {
                return grpc_error_response(
                    Code::Internal,
                    &format!("failed to read request body: {e}"),
                );
            }
        };

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
        method: &str,
    ) -> http::Response<BoxBody> {
        let mut delay_ms = self.retry_config.initial_backoff_ms;

        for attempt in 0..=self.retry_config.max_retries {
            let channel = self.replica.next_raw_channel();

            let body = BoxBody::new(
                Full::new(body_bytes.clone()).map_err(|never| match never {}),
            );

            let mut req = http::Request::new(body);
            *req.method_mut() = parts.method.clone();
            *req.uri_mut() = http::Uri::builder()
                .path_and_query(new_path)
                .build()
                .unwrap();
            *req.version_mut() = parts.version;
            *req.headers_mut() = parts.headers.clone();

            match channel.oneshot(req).await {
                Ok(response) => return response,
                Err(e) => {
                    let is_last = attempt >= self.retry_config.max_retries;
                    if is_last {
                        return grpc_error_response(
                            Code::Unavailable,
                            &format!("replica backend error: {e}"),
                        );
                    }

                    let client = current_client_name();
                    counter!(
                        "personhog_router_backend_retries_total",
                        "method" => method.to_string(),
                        "status_code" => "unavailable",
                        "client" => client,
                    )
                    .increment(1);

                    let base = delay_ms / 2;
                    let jittered = base + rand::thread_rng().gen_range(0..=base);
                    tokio::time::sleep(std::time::Duration::from_millis(jittered)).await;
                    delay_ms = (delay_ms * 2).min(self.retry_config.max_backoff_ms);
                }
            }
        }

        unreachable!()
    }

    async fn handle_get_person_strong(
        &self,
        req: http::Request<BoxBody>,
    ) -> http::Response<BoxBody> {
        let leader = match &self.leader {
            Some(l) => l,
            None => {
                return grpc_error_response(
                    Code::Unimplemented,
                    "leader backend not configured for this router",
                )
            }
        };

        let body_bytes = match collect_request_body(req).await {
            Ok(b) => b,
            Err(resp) => return resp,
        };
        let request: GetPersonRequest = match decode_grpc_message(&body_bytes) {
            Ok(m) => m,
            Err(resp) => return resp,
        };

        match leader.get_person(request).await {
            Ok(response) => encode_grpc_response(&response),
            Err(status) => grpc_error_response(status.code(), status.message()),
        }
    }

    async fn handle_update_person_properties(
        &self,
        req: http::Request<BoxBody>,
    ) -> http::Response<BoxBody> {
        let leader = match &self.leader {
            Some(l) => l,
            None => {
                return grpc_error_response(
                    Code::Unimplemented,
                    "leader backend not configured for this router",
                )
            }
        };

        let body_bytes = match collect_request_body(req).await {
            Ok(b) => b,
            Err(resp) => return resp,
        };
        let request: UpdatePersonPropertiesRequest = match decode_grpc_message(&body_bytes) {
            Ok(m) => m,
            Err(resp) => return resp,
        };

        match leader.update_person_properties(request).await {
            Ok(response) => encode_grpc_response(&response),
            Err(status) => grpc_error_response(status.code(), status.message()),
        }
    }
}

// ── gRPC body helpers ──────────────────────────────────────────────────

async fn collect_request_body(
    req: http::Request<BoxBody>,
) -> Result<Bytes, http::Response<BoxBody>> {
    let (_, body) = req.into_parts();
    body.collect()
        .await
        .map(|collected| collected.to_bytes())
        .map_err(|e| grpc_error_response(Code::Internal, &format!("failed to read body: {e}")))
}

fn decode_grpc_message<M: Message + Default>(body: &Bytes) -> Result<M, http::Response<BoxBody>> {
    if body.len() < 5 {
        return Err(grpc_error_response(Code::Internal, "gRPC frame too short"));
    }

    if body[0] != 0 {
        return Err(grpc_error_response(
            Code::Unimplemented,
            "compressed requests not supported for typed proxy path",
        ));
    }

    let len = u32::from_be_bytes([body[1], body[2], body[3], body[4]]) as usize;
    if body.len() < 5 + len {
        return Err(grpc_error_response(Code::Internal, "gRPC frame truncated"));
    }

    M::decode(&body[5..5 + len])
        .map_err(|e| grpc_error_response(Code::Internal, &format!("proto decode error: {e}")))
}

fn encode_grpc_response<M: Message>(msg: &M) -> http::Response<BoxBody> {
    let encoded = msg.encode_to_vec();
    let mut buf = Vec::with_capacity(5 + encoded.len());
    buf.push(0); // not compressed
    buf.extend_from_slice(&(encoded.len() as u32).to_be_bytes());
    buf.extend(encoded);

    let mut trailers = HeaderMap::new();
    trailers.insert("grpc-status", HeaderValue::from_static("0"));

    let body = GrpcResponseBody {
        data: Some(Bytes::from(buf)),
        trailers: Some(trailers),
    };

    let mut response = http::Response::new(BoxBody::new(body));
    response
        .headers_mut()
        .insert("content-type", HeaderValue::from_static("application/grpc"));
    response
}

fn grpc_error_response(code: Code, message: &str) -> http::Response<BoxBody> {
    let body = BoxBody::new(Empty::<Bytes>::new().map_err(|never| match never {}));
    let mut response = http::Response::new(body);
    response
        .headers_mut()
        .insert("content-type", HeaderValue::from_static("application/grpc"));
    response
        .headers_mut()
        .insert("grpc-status", HeaderValue::from(code as i32));
    if !message.is_empty() {
        let encoded = percent_encode_grpc(message);
        if let Ok(val) = encoded.parse::<HeaderValue>() {
            response.headers_mut().insert("grpc-message", val);
        }
    }
    response
}

fn is_grpc_error_response(response: &http::Response<BoxBody>) -> bool {
    response
        .headers()
        .get("grpc-status")
        .and_then(|v| v.to_str().ok())
        .is_some_and(|s| s != "0")
}

fn percent_encode_grpc(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char);
            }
            _ => {
                const HEX: &[u8; 16] = b"0123456789ABCDEF";
                out.push('%');
                out.push(HEX[(b >> 4) as usize] as char);
                out.push(HEX[(b & 0xf) as usize] as char);
            }
        }
    }
    out
}

/// HTTP body that yields one data frame followed by one trailers frame.
/// Used for constructing gRPC responses from typed leader calls.
struct GrpcResponseBody {
    data: Option<Bytes>,
    trailers: Option<HeaderMap>,
}

impl http_body::Body for GrpcResponseBody {
    type Data = Bytes;
    type Error = tonic::Status;

    fn poll_frame(
        self: Pin<&mut Self>,
        _cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        let this = self.get_mut();
        if let Some(data) = this.data.take() {
            Poll::Ready(Some(Ok(Frame::data(data))))
        } else if let Some(trailers) = this.trailers.take() {
            Poll::Ready(Some(Ok(Frame::trailers(trailers))))
        } else {
            Poll::Ready(None)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn decode_grpc_message_roundtrip() {
        let msg = GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: None,
        };
        let encoded = msg.encode_to_vec();
        let mut buf = Vec::with_capacity(5 + encoded.len());
        buf.push(0);
        buf.extend_from_slice(&(encoded.len() as u32).to_be_bytes());
        buf.extend(encoded);

        let decoded: GetPersonRequest = decode_grpc_message(&Bytes::from(buf)).unwrap();
        assert_eq!(decoded.team_id, 1);
        assert_eq!(decoded.person_id, 42);
    }

    #[test]
    fn decode_grpc_message_too_short() {
        let result: Result<GetPersonRequest, _> =
            decode_grpc_message(&Bytes::from_static(&[0, 0, 0, 0]));
        assert!(result.is_err());
    }

    #[test]
    fn decode_grpc_message_compressed_rejected() {
        let result: Result<GetPersonRequest, _> =
            decode_grpc_message(&Bytes::from_static(&[1, 0, 0, 0, 0]));
        assert!(result.is_err());
    }

    #[test]
    fn decode_grpc_message_truncated() {
        let result: Result<GetPersonRequest, _> =
            decode_grpc_message(&Bytes::from_static(&[0, 0, 0, 0, 10]));
        assert!(result.is_err());
    }

    #[test]
    fn encode_grpc_response_has_correct_headers() {
        use personhog_proto::personhog::types::v1::GetPersonResponse;

        let msg = GetPersonResponse { person: None };
        let response = encode_grpc_response(&msg);

        assert_eq!(
            response.headers().get("content-type").unwrap(),
            "application/grpc"
        );
    }

    #[test]
    fn grpc_error_response_sets_status_and_message() {
        let response = grpc_error_response(Code::NotFound, "person not found");
        assert_eq!(
            response.headers().get("grpc-status").unwrap(),
            &format!("{}", Code::NotFound as i32),
        );
        let msg = response
            .headers()
            .get("grpc-message")
            .unwrap()
            .to_str()
            .unwrap();
        assert!(msg.contains("person"));
    }

    #[test]
    fn grpc_error_response_ok_not_flagged_as_error() {
        let ok = grpc_error_response(Code::Ok, "");
        assert!(!is_grpc_error_response(&ok));
    }

    #[test]
    fn grpc_error_response_flagged_as_error() {
        let err = grpc_error_response(Code::NotFound, "not found");
        assert!(is_grpc_error_response(&err));
    }

    #[test]
    fn percent_encode_grpc_preserves_safe_chars() {
        assert_eq!(percent_encode_grpc("hello"), "hello");
        assert_eq!(percent_encode_grpc("a-b_c.d~e"), "a-b_c.d~e");
    }

    #[test]
    fn percent_encode_grpc_encodes_special_chars() {
        assert_eq!(percent_encode_grpc("hello world"), "hello%20world");
        assert_eq!(percent_encode_grpc("a/b"), "a%2Fb");
        assert_eq!(percent_encode_grpc("a:b"), "a%3Ab");
    }
}
