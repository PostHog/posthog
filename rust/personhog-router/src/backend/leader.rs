use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use bytes::Bytes;
use dashmap::DashMap;
use http::{HeaderMap, HeaderValue, Method, Uri, Version};
use http_body_util::{BodyExt, Full};
use metrics::{counter, histogram};
use tokio::sync::RwLock;
use tonic::body::BoxBody;
use tonic::transport::Channel;
use tonic::{Code, Status};
use tower::{Service, ServiceExt};

use personhog_common::grpc::{current_client_name, SEMANTIC_REFUSAL_METADATA_KEY};

/// Set by the leader on any write it refuses because a lifecycle op holds
/// the person, alongside the holding op's id. Mirrored here rather than
/// imported: the router forwards these opaquely and must not take a
/// dependency on the leader crate to do it.
const FENCED_METADATA_KEY: &str = "x-person-fenced";
const FENCED_OP_ID_METADATA_KEY: &str = "x-person-fenced-op-id";
const FENCED_CREATOR_METADATA_KEY: &str = "x-person-fenced-creator";
use personhog_common::partitioning::partition_for_person;

use super::stash::{StashDecision, StashTable};
use crate::grpc_http::{grpc_error_response, grpc_status_code};

pub type AddressResolver = Arc<dyn Fn(&str) -> Option<String> + Send + Sync>;

/// gRPC path prefix for the leader service; raw forwards target
/// `{LEADER_PREFIX}{method}`.
const LEADER_PREFIX: &str = "/personhog.leader.v1.PersonHogLeader/";

/// How long to wait after a bounced forward attempt before the next one.
/// Both bounce conditions clear on their own — a fence in
/// watch-propagation time, a transport failure as the target pod comes
/// up — so the cadence only needs to outpace the caller's latency bound,
/// not be aggressive. Shared by the direct path's re-entrant retry loop
/// and the drain's wave loop so the two paths settle at the same rate.
pub(crate) const BOUNCE_BACKOFF: Duration = Duration::from_millis(150);

/// Consecutive bounces after which a retry loop gives up — the direct path
/// returns a definitive `UNAVAILABLE` (the client's own retry may reach
/// a healthier router), the drain yields its lane to the reconcile pass.
pub(crate) const MAX_CONSECUTIVE_BOUNCES: u32 = 4;

/// Why a forward attempt produced no outcome, and what that implies for
/// the request's delivery state. All reasons share retry mechanics; they
/// are distinguished because they sit at different points on the
/// replay-safety spectrum, and only `Transport` leaves the delivery
/// state ambiguous.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BounceReason {
    /// The partition could not be routed at all — no assignment in the
    /// table, or no address for the owner — so nothing was sent.
    /// Definitively not applied; transiently normal at startup and
    /// during ownership gaps.
    Unrouted,
    /// The target refused the request at admission — a write fence or a
    /// not-owned partition — before any work. Definitively not applied.
    Fenced,
    /// The transport failed with no response after the request may have
    /// been sent — the leader might have applied it. The next attempt
    /// is an at-least-once replay.
    Transport,
}

impl BounceReason {
    pub fn label(self) -> &'static str {
        match self {
            BounceReason::Unrouted => "unrouted",
            BounceReason::Fenced => "fenced",
            BounceReason::Transport => "transport",
        }
    }
}

/// Which of the router's two forward paths issued a send: `Direct` for a
/// request forwarded from its own handler task, `Stash` for a parked
/// request forwarded by the drain. Carried as the `path` label on the
/// channel-call and retry metrics so the two paths read separately.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ForwardPath {
    Direct,
    Stash,
}

impl ForwardPath {
    pub fn label(self) -> &'static str {
        match self {
            ForwardPath::Direct => "direct",
            ForwardPath::Stash => "stash",
        }
    }
}

/// What one classified forward attempt concluded. `Delivered` covers
/// every response the leader actually produced — success or error, it is
/// a real outcome the caller must hand to the client (an error status
/// like `UNAVAILABLE` is also the leader's backpressure signal, which
/// retrying would invert). `Bounced` means no outcome exists and the
/// caller's retry mechanism decides what happens next.
pub enum ForwardDecision {
    Delivered {
        response: http::Response<BoxBody>,
        call_ms: f64,
    },
    Bounced(BounceReason),
    /// Any non-semantic FAILED_PRECONDITION, carrying the refusal's own
    /// metadata. Most are partition-level refusals during a handoff and
    /// carry no person keys at all; the case the metadata exists for is a
    /// person held by a lifecycle op. Such a fence never clears on its own —
    /// only an explicit retry from the caller driving that op resumes it —
    /// so when the retries run out, the identity of the holder is the one
    /// thing that lets that caller tell "keep waiting" from "this one is
    /// mine to finish". Bouncing without it hands back generic retry advice
    /// that is wrong for the only party who can act on it.
    BouncedFenced {
        headers: HeaderMap,
    },
}

/// Static configuration for `LeaderBackend`. Bundles the knobs that come
/// from `Config` so the constructor stays narrow as we add fields.
pub struct LeaderBackendConfig {
    pub num_partitions: u32,
    pub timeout: Duration,
}

/// Backend that routes person writes and strong reads to leader pods
/// based on Kafka-compatible partitioning of person_id.
pub struct LeaderBackend {
    /// Read-only handle to the routing table (partition → pod_name).
    routing_table: Arc<RwLock<HashMap<u32, String>>>,
    /// Cached gRPC channels keyed by pod gRPC address. All leader traffic —
    /// strong reads and writes — forwards raw request frames over these
    /// channels.
    channels: DashMap<String, Channel>,
    /// Resolves pod_name → gRPC address.
    address_resolver: AddressResolver,
    config: LeaderBackendConfig,
    /// Per-partition stash queue used to buffer writes during partition
    /// handoffs. Consulted before every write; normal operation has no stash
    /// entries and hits the dashmap miss-path once per request.
    stash: StashTable,
}

/// Whether a bounce leaves the write's fate in doubt.
///
/// Only a transport failure does: the leader may have applied the frame
/// before the connection broke. Every other bounce is a refusal the
/// leader made before touching anything — including the fenced class,
/// which carries one exception (a window fenced with its own commit
/// outcome unknown) that is deliberately not counted here, since
/// admission refusals are the ordinary traffic of every handoff and
/// counting the class would swamp the signal.
pub(crate) fn counts_as_possibly_applied(reason: BounceReason) -> bool {
    match reason {
        BounceReason::Transport => true,
        BounceReason::Fenced | BounceReason::Unrouted => false,
    }
}

impl LeaderBackend {
    pub fn new(
        routing_table: Arc<RwLock<HashMap<u32, String>>>,
        address_resolver: AddressResolver,
        config: LeaderBackendConfig,
        stash: StashTable,
    ) -> Self {
        assert!(
            config.num_partitions > 0,
            "num_partitions must be > 0 to avoid division by zero in partition_for_person"
        );
        Self {
            routing_table,
            channels: DashMap::new(),
            address_resolver,
            config,
            stash,
        }
    }

    /// Clone of the stash table, for wiring into the `StashHandler`
    /// implementation.
    pub fn stash_table(&self) -> StashTable {
        self.stash.clone()
    }

    /// Remove the cached gRPC channel for a pod so the next request
    /// reconnects. Called during partition handoff cutover to drop the
    /// connection to the old leader pod.
    pub fn clear_client_cache(&self, pod_name: &str) {
        if let Some(address) = (self.address_resolver)(pod_name) {
            self.channels.remove(&address);
        }
    }

    /// Compute the Kafka partition for a person using murmur2.
    /// The key is `team_id:person_id`, matching the Kafka topic key.
    pub fn partition_for_person(&self, team_id: i64, person_id: i64) -> u32 {
        partition_for_person(team_id, person_id, self.config.num_partitions)
    }

    /// Resolve the leader gRPC channel for a given partition, building and
    /// caching a lazy channel on first use. All leader traffic — strong
    /// reads and writes — forwards raw requests over this channel.
    pub async fn resolve_leader_channel(&self, partition: u32) -> Result<Channel, Status> {
        let pod_name = self
            .routing_table
            .read()
            .await
            .get(&partition)
            .cloned()
            .ok_or_else(|| {
                Status::unavailable(format!("no leader assigned for partition {partition}"))
            })?;

        let address = (self.address_resolver)(&pod_name).ok_or_else(|| {
            Status::unavailable(format!("cannot resolve address for pod {pod_name}"))
        })?;

        if let Some(channel) = self.channels.get(&address) {
            return Ok(channel.clone());
        }

        // The connect deadline matters independently of the request
        // timeout: dialing a pod whose IP has been unassigned black-holes
        // at TCP connect (no RST ever arrives), and the request timeout
        // only starts once a connection exists.
        let channel = Channel::from_shared(address.clone())
            .map_err(|e| Status::internal(format!("invalid leader address: {e}")))?
            .timeout(self.config.timeout)
            .connect_timeout(self.config.timeout)
            .tcp_nodelay(true)
            .connect_lazy();
        self.channels.insert(address, channel.clone());
        Ok(channel)
    }

    /// Send a raw gRPC request frame over an already-resolved channel —
    /// a single delivery attempt, no internal retries. The partition
    /// travels in the `x-partition` header the leader reads in place of
    /// a body field; the client's own headers (`x-client-name`,
    /// `x-caller-tag`, etc.) are forwarded verbatim. A leader response
    /// that carries a gRPC error is returned as `Ok` — only transport
    /// failures surface as `Err`. On success also returns the channel
    /// round-trip time, used by the read path's network-overhead metric.
    ///
    /// Retry policy lives with the callers of `forward_classified`, both
    /// of which re-check routing state between attempts: the direct
    /// path's re-entrant loop in `forward_or_stash` and the stash path's
    /// drain wave loop.
    /// A blind retry here would re-send without seeing a stash window
    /// that opened during the backoff, so this layer deliberately stays
    /// single-attempt.
    async fn send_frame(
        &self,
        mut channel: Channel,
        forward_path: ForwardPath,
        method: &'static str,
        partition: u32,
        headers: &HeaderMap,
        frame: &Bytes,
    ) -> Result<(http::Response<BoxBody>, f64), Status> {
        let path = format!("{LEADER_PREFIX}{method}");
        let partition_header = HeaderValue::from(partition);
        let client = current_client_name();

        let ready_start = Instant::now();
        let ready_result = channel.ready().await;
        let ready_outcome = if ready_result.is_ok() { "ok" } else { "error" };
        histogram!(
            "personhog_router_channel_ready_wait_ms",
            "method" => method,
            "client" => client.clone(),
            "outcome" => ready_outcome,
            "path" => forward_path.label(),
        )
        .record(ready_start.elapsed().as_secs_f64() * 1000.0);
        let ready = ready_result
            .map_err(|e| Status::unavailable(format!("leader channel not ready: {e}")))?;

        let body = BoxBody::new(Full::new(frame.clone()).map_err(|never| match never {}));
        let mut req = http::Request::new(body);
        *req.method_mut() = Method::POST;
        *req.uri_mut() = Uri::builder()
            .path_and_query(path)
            .build()
            .expect("leader path is a valid URI");
        *req.version_mut() = Version::HTTP_2;
        *req.headers_mut() = headers.clone();
        req.headers_mut().insert("x-partition", partition_header);

        let call_start = Instant::now();
        let call_result = ready.call(req).await;
        let call_ms = call_start.elapsed().as_secs_f64() * 1000.0;
        let call_outcome = if call_result.is_ok() { "ok" } else { "error" };
        histogram!(
            "personhog_router_channel_call_ms",
            "method" => method,
            "client" => client,
            "outcome" => call_outcome,
            "path" => forward_path.label(),
        )
        .record(call_ms);
        let response =
            call_result.map_err(|e| Status::unavailable(format!("leader backend error: {e}")))?;
        Ok((response, call_ms))
    }

    /// One classified forward attempt: resolve the target, send the
    /// frame, and decide what the result means. This is the single
    /// shared reading of leader responses — the direct path's retry loop
    /// and the drain's wave loop both build on it, so the two paths can
    /// never drift in how they interpret the same response.
    ///
    /// Resolution happens here, before the send, so its failures
    /// classify as `Unrouted` — nothing touched the wire, and the
    /// request's delivery state is not ambiguous the way a mid-send
    /// transport failure's is.
    pub async fn forward_classified(
        &self,
        forward_path: ForwardPath,
        method: &'static str,
        partition: u32,
        headers: &HeaderMap,
        frame: &Bytes,
    ) -> ForwardDecision {
        let channel = match self.resolve_leader_channel(partition).await {
            Ok(channel) => channel,
            Err(_status) => return ForwardDecision::Bounced(BounceReason::Unrouted),
        };
        match self
            .send_frame(channel, forward_path, method, partition, headers, frame)
            .await
        {
            // A bare FailedPrecondition is a routing-race rejection
            // ("fenced for handoff", "partition not owned", a person
            // fence that clears in healer time) — it classifies as a
            // bounce rather than an outcome. Almost all are refusals at
            // admission, where nothing was attempted; the exception is a
            // window fenced with its own commit outcome unknown, whose
            // record may already be in the changelog. That case is not
            // counted as a possible replay: admission refusals are the
            // ordinary traffic of every handoff, so counting the class
            // would swamp the signal it exists to carry. The one carve-out
            // is a semantic refusal (the leader's fail-closed verification
            // rejections, marked by metadata): that is a final answer
            // about the request, and bouncing it would exhaust into a
            // retriable UNAVAILABLE the caller loops on forever.
            Ok((response, call_ms))
                if grpc_status_code(&response) == Some(Code::FailedPrecondition as i32) =>
            {
                if response
                    .headers()
                    .contains_key(SEMANTIC_REFUSAL_METADATA_KEY)
                {
                    ForwardDecision::Delivered { response, call_ms }
                } else {
                    ForwardDecision::BouncedFenced {
                        headers: response.headers().clone(),
                    }
                }
            }
            Ok((response, call_ms)) => ForwardDecision::Delivered { response, call_ms },
            Err(_status) => ForwardDecision::Bounced(BounceReason::Transport),
        }
    }

    /// Forward a leader-path request, honoring the per-partition stash
    /// and retrying bounced attempts. While a handoff for this partition
    /// is in a non-terminal phase the stash is open and the request
    /// parks until drain replays it to the new owner (or its deadline
    /// expires); otherwise it forwards. Returns the final gRPC response
    /// — the leader's, or a router-generated error when the stash is
    /// full or dropped — plus the channel round-trip time when the
    /// request forwarded directly (`None` for stashed requests, whose
    /// latency is dominated by the handoff wait and tracked by the
    /// stash-wait histogram instead).
    ///
    /// A bounced attempt (fence rejection or transport failure — see
    /// [`ForwardDecision`]) does not surface to the client. The request
    /// is held in this task, the loop backs off briefly, and the next
    /// iteration starts from the stash check — not a blind re-send —
    /// because a bounce usually means the router's routing view is
    /// stale and the backoff gives the watch time to deliver what the
    /// leader already knew. By the re-attempt, one of three worlds
    /// holds: a stash window opened (the request parks and rides the
    /// handoff — the race becomes the normal path), the table flipped
    /// (the re-resolve targets the new owner), or nothing changed yet
    /// (re-send, possibly bounce again). Each re-attempt is counted by
    /// `personhog_router_forward_retries_total` under the reason that
    /// caused it. After `MAX_CONSECUTIVE_BOUNCES` the request fails with
    /// a definitive `UNAVAILABLE`, counted by
    /// `personhog_router_forward_retries_exhausted_total`, so a router
    /// whose view never updates (a dead watch) can't hold requests
    /// forever — the client's own retry may land on a healthy router.
    ///
    /// A transport bounce marks the request possibly-applied: the leader
    /// may have processed it without us seeing the response, so any
    /// further forward — here or by the drain if it parks — is an
    /// at-least-once replay, covered by the redelivery contract in
    /// `personhog-leader`'s README.
    pub async fn forward_or_stash(
        &self,
        method: &'static str,
        partition: u32,
        key: (i64, i64),
        headers: HeaderMap,
        frame: Bytes,
    ) -> (http::Response<BoxBody>, Option<f64>) {
        let mut consecutive_bounces = 0u32;
        // Whether any attempt may have reached the leader and been applied,
        // which the stash needs in order to treat a replay as at-least-once
        // rather than exactly-once.
        let mut possibly_applied = false;
        loop {
            // The stash module emits its own enqueued/rejected counters
            // at the source; we don't double-count here. It borrows the
            // frame and headers, cloning only when the request actually
            // parks, so the steady-state forward path copies nothing.
            match self
                .stash
                .enqueue_or_forward(partition, method, &frame, &headers, key, possibly_applied)
                .await
            {
                StashDecision::Stashed(rx) => {
                    let response = rx.await.unwrap_or_else(|_| {
                        grpc_error_response(
                            Code::Unavailable,
                            "router stash dropped before handoff completed",
                        )
                    });
                    return (response, None);
                }
                StashDecision::Rejected => {
                    return (
                        grpc_error_response(
                            Code::Unavailable,
                            &format!("router stash full for partition {partition}"),
                        ),
                        None,
                    );
                }
                StashDecision::Forward => {}
            }

            match self
                .forward_classified(ForwardPath::Direct, method, partition, &headers, &frame)
                .await
            {
                ForwardDecision::Delivered { response, call_ms } => {
                    return (response, Some(call_ms));
                }
                decision
                @ (ForwardDecision::Bounced(_) | ForwardDecision::BouncedFenced { .. }) => {
                    let reason = match &decision {
                        ForwardDecision::Bounced(reason) => *reason,
                        _ => BounceReason::Fenced,
                    };
                    if counts_as_possibly_applied(reason) {
                        possibly_applied = true;
                    }
                    consecutive_bounces += 1;
                    if consecutive_bounces >= MAX_CONSECUTIVE_BOUNCES {
                        // Labelled by the reason that ended it: exhausting on
                        // a fence makes the caller drop its operation and ack,
                        // exhausting on transport makes it redeliver. An
                        // unlabelled count cannot separate a lost merge from a
                        // retried one.
                        counter!(
                            "personhog_router_forward_retries_exhausted_total",
                            "reason" => reason.label(),
                        )
                        .increment(1);
                        // The message follows what actually ended the
                        // request. A refusal carrying fence metadata names a
                        // lifecycle holder; a bare FAILED_PRECONDITION is the
                        // handoff/ownership majority the Fenced class also
                        // carries, and calling that a lifecycle operation
                        // points triage at ops that do not exist.
                        let held_by_op = matches!(
                            &decision,
                            ForwardDecision::BouncedFenced { headers }
                                if headers.contains_key(FENCED_METADATA_KEY)
                        );
                        let mut response = grpc_error_response(
                            Code::Unavailable,
                            if held_by_op {
                                "person is held by a lifecycle operation; retries exhausted"
                            } else if matches!(reason, BounceReason::Fenced) {
                                "leader refused the write precondition (handoff or ownership); retries exhausted"
                            } else {
                                "leader unreachable or transitioning; retry"
                            },
                        );
                        // Only the fence keys travel, and only from the
                        // bounce that actually ended the request. The caller
                        // reads them to recognise its own operation, and
                        // every other header on the refusal belongs to a
                        // response we are not forwarding. Taking them from
                        // this decision rather than a remembered one is what
                        // keeps a leader that died after being fenced from
                        // coming back labelled as a person somebody holds —
                        // a verdict callers ack rather than retry.
                        if let ForwardDecision::BouncedFenced { headers: fence } = &decision {
                            for key in [
                                FENCED_METADATA_KEY,
                                FENCED_OP_ID_METADATA_KEY,
                                FENCED_CREATOR_METADATA_KEY,
                            ] {
                                if let Some(value) = fence.get(key) {
                                    response.headers_mut().insert(key, value.clone());
                                }
                            }
                        }
                        return (response, None);
                    }
                    counter!(
                        "personhog_router_forward_retries_total",
                        "path" => ForwardPath::Direct.label(),
                        "reason" => reason.label()
                    )
                    .increment(1);
                    tokio::time::sleep(BOUNCE_BACKOFF).await;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{counts_as_possibly_applied, BounceReason};

    /// Only a transport failure leaves the write's fate in doubt, and
    /// the distinction drives the replay counter operators consult when
    /// deciding whether a duplicate write is possible. It had no test at
    /// all while it lived inline in the forward loop, where reaching it
    /// needs a live leader and a metrics recorder.
    #[test]
    fn only_a_transport_bounce_leaves_the_write_in_doubt() {
        assert!(counts_as_possibly_applied(BounceReason::Transport));
        assert!(!counts_as_possibly_applied(BounceReason::Fenced));
        assert!(!counts_as_possibly_applied(BounceReason::Unrouted));
    }

    use super::*;

    fn test_config(num_partitions: u32) -> LeaderBackendConfig {
        LeaderBackendConfig {
            num_partitions,
            timeout: Duration::from_secs(5),
        }
    }

    #[tokio::test]
    async fn resolve_leader_returns_unavailable_when_no_assignment() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let resolver: AddressResolver = Arc::new(|_| Some("http://localhost:50053".to_string()));
        let backend = LeaderBackend::new(
            routing_table,
            resolver,
            test_config(8),
            StashTable::with_bounds(usize::MAX, usize::MAX),
        );

        let partition = backend.partition_for_person(1, 42);
        let result = backend.resolve_leader_channel(partition).await;
        assert!(result.is_err());
        assert_eq!(result.unwrap_err().code(), tonic::Code::Unavailable);
    }

    /// An unroutable partition (empty table at startup, an ownership
    /// gap) rides the bounce budget — giving the routing view time to
    /// arrive, or a stash window time to open — and then fails with a
    /// definitive retryable `UNAVAILABLE`, never hanging and never a
    /// non-retryable code.
    #[tokio::test]
    async fn an_unrouted_partition_bounces_then_fails_unavailable() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let resolver: AddressResolver = Arc::new(|_| Some("http://localhost:50053".to_string()));
        let backend = LeaderBackend::new(
            routing_table,
            resolver,
            test_config(8),
            StashTable::with_bounds(usize::MAX, usize::MAX),
        );

        let partition = backend.partition_for_person(1, 42);
        let (response, call_ms) = backend
            .forward_or_stash(
                "UpdatePersonProperties",
                partition,
                (1, 42),
                HeaderMap::new(),
                Bytes::from_static(b"x"),
            )
            .await;
        assert!(call_ms.is_none());
        assert_eq!(
            crate::grpc_http::grpc_status_code(&response),
            Some(Code::Unavailable as i32)
        );
    }

    #[tokio::test]
    async fn resolve_leader_returns_unavailable_when_address_unresolvable() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let backend = LeaderBackend::new(
            Arc::clone(&routing_table),
            Arc::new(|_| None), // resolver returns None
            test_config(8),
            StashTable::with_bounds(usize::MAX, usize::MAX),
        );

        let partition = backend.partition_for_person(1, 42);
        routing_table
            .write()
            .await
            .insert(partition, "leader-0".to_string());

        let partition = backend.partition_for_person(1, 42);
        let result = backend.resolve_leader_channel(partition).await;
        assert!(result.is_err());
        assert_eq!(result.unwrap_err().code(), tonic::Code::Unavailable);
    }

    #[tokio::test]
    async fn resolve_leader_returns_client_when_assigned() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let resolver: AddressResolver = Arc::new(|_| Some("http://localhost:50053".to_string()));
        let backend = LeaderBackend::new(
            Arc::clone(&routing_table),
            resolver,
            test_config(8),
            StashTable::with_bounds(usize::MAX, usize::MAX),
        );

        let partition = backend.partition_for_person(1, 42);
        routing_table
            .write()
            .await
            .insert(partition, "leader-0".to_string());

        let partition = backend.partition_for_person(1, 42);
        let result = backend.resolve_leader_channel(partition).await;
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn resolve_leader_caches_channel() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let resolver: AddressResolver = Arc::new(|_| Some("http://localhost:50053".to_string()));
        let backend = LeaderBackend::new(
            Arc::clone(&routing_table),
            resolver,
            test_config(8),
            StashTable::with_bounds(usize::MAX, usize::MAX),
        );

        let partition = backend.partition_for_person(1, 42);
        routing_table
            .write()
            .await
            .insert(partition, "leader-0".to_string());

        let partition = backend.partition_for_person(1, 42);
        let _channel1 = backend.resolve_leader_channel(partition).await.unwrap();
        assert_eq!(backend.channels.len(), 1);

        let _channel2 = backend.resolve_leader_channel(partition).await.unwrap();
        assert_eq!(backend.channels.len(), 1); // still 1, cached
    }

    /// When the partition's stash is open and full, `forward_or_stash`
    /// must short-circuit with an UNAVAILABLE gRPC response instead of
    /// forwarding, so callers see a retryable status rather than getting
    /// their write silently dropped.
    #[tokio::test]
    async fn forward_or_stash_returns_unavailable_when_stash_full() {
        let routing_table = Arc::new(RwLock::new(HashMap::new()));
        let resolver: AddressResolver = Arc::new(|_| Some("http://localhost:50053".to_string()));
        // `max_messages = 0` rejects any enqueue once the stash is open.
        let stash = StashTable::with_bounds(0, usize::MAX);
        let backend = LeaderBackend::new(
            Arc::clone(&routing_table),
            resolver,
            test_config(8),
            stash.clone(),
        );

        // Determine which partition this request lands on, then open the
        // stash for that exact partition.
        let partition = backend.partition_for_person(1, 42);
        stash.begin_stash(partition).await;

        let (response, call_ms) = backend
            .forward_or_stash(
                "UpdatePersonProperties",
                partition,
                (1, 42),
                HeaderMap::new(),
                Bytes::new(),
            )
            .await;

        assert_eq!(
            response.headers().get("grpc-status").unwrap(),
            &format!("{}", Code::Unavailable as i32),
            "rejection must surface as UNAVAILABLE so callers retry"
        );
        assert!(call_ms.is_none(), "no forward happened, so no call time");
    }
}
