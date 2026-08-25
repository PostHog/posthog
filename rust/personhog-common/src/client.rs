//! Shared client for the router's public PersonHogService.
//!
//! The router routes leader-bound calls by hashing the person routing
//! headers — it never decodes request bodies — so every caller must stamp
//! `x-team-id`/`x-person-id` on property writes and strong reads. This
//! client owns that contract so callers cannot get it wrong.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use tonic::transport::{Channel, Endpoint};
use tonic::{Request, Status};

use personhog_proto::personhog::service::v1::person_hog_service_client::PersonHogServiceClient;
use personhog_proto::personhog::types::v1::{
    ConsistencyLevel, FencePersonRequest, FencePersonResponse, FoldPersonDocumentRequest,
    FoldPersonDocumentResponse, GetPersonRequest, Person, ReadOptions, ReleaseFenceRequest,
    ReleaseFenceResponse, UpdatePersonPropertiesRequest, UpdatePersonPropertiesResponse,
};

/// Routing headers for leader-bound calls through the router.
pub const TEAM_ID_HEADER: &str = "x-team-id";
pub const PERSON_ID_HEADER: &str = "x-person-id";
pub const READ_CONSISTENCY_HEADER: &str = "x-read-consistency";

const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);

/// Channels opened per router URL when the caller does not choose. One is
/// correct only for low-rate callers; see `with_channels`.
pub const DEFAULT_ROUTER_CHANNELS: usize = 1;

#[derive(Clone)]
pub struct RouterClient {
    /// One tonic channel is one TCP connection, and a Kubernetes Service
    /// pins a connection to a single backend pod for its lifetime. A
    /// single-channel client therefore sends everything this process
    /// produces to one router pod, however many pods exist. Holding
    /// several channels spreads the load across as many pods, and gives
    /// each connection its own HTTP/2 stream budget and flow-control
    /// windows.
    clients: Vec<PersonHogServiceClient<Channel>>,
    /// Shared across clones so round-robin continues across them rather
    /// than every clone restarting at the first channel.
    next: Arc<AtomicUsize>,
    request_timeout: Duration,
}

impl RouterClient {
    /// Connect lazily to the router over a single channel; the first RPC
    /// establishes the connection.
    pub fn new(
        router_url: &str,
        request_timeout: Duration,
    ) -> Result<Self, tonic::transport::Error> {
        Self::with_channels(router_url, request_timeout, DEFAULT_ROUTER_CHANNELS)
    }

    /// Connect lazily over `channels` connections, selected round-robin
    /// per request. Callers driving meaningful request rates want more
    /// than one: a single connection caps them at one router pod's
    /// capacity no matter how many pods are running. A count below one is
    /// treated as one.
    pub fn with_channels(
        router_url: &str,
        request_timeout: Duration,
        channels: usize,
    ) -> Result<Self, tonic::transport::Error> {
        let clients = (0..channels.max(1))
            .map(|_| {
                let channel = Endpoint::from_shared(router_url.to_string())?
                    .connect_timeout(CONNECT_TIMEOUT)
                    .tcp_nodelay(true)
                    .connect_lazy();
                Ok(PersonHogServiceClient::new(channel))
            })
            .collect::<Result<Vec<_>, tonic::transport::Error>>()?;
        Ok(Self {
            clients,
            next: Arc::new(AtomicUsize::new(0)),
            request_timeout,
        })
    }

    /// The next channel in round-robin order. Selection is load-oblivious:
    /// a stalled connection still takes its share, which is acceptable
    /// because every channel targets the same interchangeable pod set.
    fn client(&self) -> PersonHogServiceClient<Channel> {
        let idx = self.next.fetch_add(1, Ordering::Relaxed) % self.clients.len();
        self.clients[idx].clone()
    }

    /// Leader-routed property write. The routing headers are stamped from
    /// the request's own team_id/person_id.
    pub async fn update_person_properties(
        &self,
        request: UpdatePersonPropertiesRequest,
    ) -> Result<UpdatePersonPropertiesResponse, Status> {
        let request = self.build_update_request(request);
        self.client()
            .update_person_properties(request)
            .await
            .map(|response| response.into_inner())
    }

    /// Person read. Strong reads route to the owning leader and therefore
    /// carry the routing headers plus the strong-consistency opt-in;
    /// eventual reads go to the replica with no headers.
    pub async fn get_person(
        &self,
        team_id: i64,
        person_id: i64,
        consistency: ConsistencyLevel,
    ) -> Result<Option<Person>, Status> {
        let request = self.build_get_person_request(team_id, person_id, consistency);
        self.client()
            .get_person(request)
            .await
            .map(|response| response.into_inner().person)
    }

    /// Leader-routed lifecycle fence (saga runner only): freeze the person
    /// and return its sealed state.
    pub async fn fence_person(
        &self,
        request: FencePersonRequest,
    ) -> Result<FencePersonResponse, Status> {
        let (team_id, person_id) = (request.team_id, request.person_id);
        let mut request = Request::new(request);
        request.set_timeout(self.request_timeout);
        stamp_person_routing_headers(&mut request, team_id, person_id);
        self.client()
            .fence_person(request)
            .await
            .map(|response| response.into_inner())
    }

    /// Leader-routed fence release (saga runner only): committed produces
    /// the death document, aborted resumes the person's normal life.
    pub async fn release_fence(
        &self,
        request: ReleaseFenceRequest,
    ) -> Result<ReleaseFenceResponse, Status> {
        let (team_id, person_id) = (request.team_id, request.person_id);
        let mut request = Request::new(request);
        request.set_timeout(self.request_timeout);
        stamp_person_routing_headers(&mut request, team_id, person_id);
        self.client()
            .release_fence(request)
            .await
            .map(|response| response.into_inner())
    }

    /// Leader-routed merge fold (saga runner only): fold sealed source
    /// snapshots into the target's document and return the folded result.
    pub async fn fold_person_document(
        &self,
        request: FoldPersonDocumentRequest,
    ) -> Result<FoldPersonDocumentResponse, Status> {
        let (team_id, person_id) = (request.team_id, request.person_id);
        let mut request = Request::new(request);
        request.set_timeout(self.request_timeout);
        stamp_person_routing_headers(&mut request, team_id, person_id);
        self.client()
            .fold_person_document(request)
            .await
            .map(|response| response.into_inner())
    }

    fn build_update_request(
        &self,
        request: UpdatePersonPropertiesRequest,
    ) -> Request<UpdatePersonPropertiesRequest> {
        let (team_id, person_id) = (request.team_id, request.person_id);
        let mut request = Request::new(request);
        request.set_timeout(self.request_timeout);
        stamp_person_routing_headers(&mut request, team_id, person_id);
        request
    }

    fn build_get_person_request(
        &self,
        team_id: i64,
        person_id: i64,
        consistency: ConsistencyLevel,
    ) -> Request<GetPersonRequest> {
        let mut request = Request::new(GetPersonRequest {
            team_id,
            person_id,
            read_options: Some(ReadOptions {
                consistency: consistency.into(),
                ..Default::default()
            }),
        });
        request.set_timeout(self.request_timeout);
        if consistency == ConsistencyLevel::Strong {
            stamp_person_routing_headers(&mut request, team_id, person_id);
            request.metadata_mut().insert(
                READ_CONSISTENCY_HEADER,
                tonic::metadata::MetadataValue::from_static("strong"),
            );
        }
        request
    }
}

/// Stamp the person routing headers the router hashes for leader routing.
pub fn stamp_person_routing_headers<T>(request: &mut Request<T>, team_id: i64, person_id: i64) {
    let metadata = request.metadata_mut();
    metadata.insert(
        TEAM_ID_HEADER,
        team_id
            .to_string()
            .parse()
            .expect("numeric header is valid metadata"),
    );
    metadata.insert(
        PERSON_ID_HEADER,
        person_id
            .to_string()
            .parse()
            .expect("numeric header is valid metadata"),
    );
}

/// The router fails leader-bound calls closed on missing headers and would
/// misroute on wrong ones, so the header decisions per routing branch are
/// pinned here: leader-bound requests (writes, strong reads) must carry the
/// person routing headers, replica-bound reads must not.
#[cfg(test)]
mod tests {
    use rstest::rstest;

    use super::*;

    fn client() -> RouterClient {
        RouterClient::new("http://127.0.0.1:1", Duration::from_secs(1))
            .expect("lazy client construction cannot fail on a valid url")
    }

    /// A single connection is pinned to one router pod by the Service, so
    /// a pooled client must actually hand out different channels — and
    /// keep doing so across clones, which is how callers hold it.
    #[tokio::test]
    async fn requests_round_robin_across_the_pool_including_clones() {
        let client = RouterClient::with_channels("http://127.0.0.1:1", Duration::from_secs(1), 4)
            .expect("lazy client construction cannot fail on a valid url");

        let first = client.next.load(Ordering::Relaxed);
        for _ in 0..4 {
            drop(client.clone().client());
        }
        assert_eq!(client.next.load(Ordering::Relaxed), first + 4);
    }

    /// Zero would panic on the modulo; callers reading it from config get
    /// the single-channel behavior instead.
    #[tokio::test]
    async fn a_channel_count_below_one_still_yields_a_usable_client() {
        let client = RouterClient::with_channels("http://127.0.0.1:1", Duration::from_secs(1), 0)
            .expect("lazy client construction cannot fail on a valid url");
        assert_eq!(client.clients.len(), 1);
        drop(client.client());
    }

    // Channel construction (even lazy) needs a Tokio reactor, hence async tests.
    #[tokio::test]
    async fn update_request_carries_the_routing_headers() {
        let request = client().build_update_request(UpdatePersonPropertiesRequest {
            team_id: 7,
            person_id: 42,
            ..Default::default()
        });
        let metadata = request.metadata();
        assert_eq!(metadata.get(TEAM_ID_HEADER).unwrap(), "7");
        assert_eq!(metadata.get(PERSON_ID_HEADER).unwrap(), "42");
        assert!(metadata.get(READ_CONSISTENCY_HEADER).is_none());
    }

    #[rstest]
    #[case::strong(ConsistencyLevel::Strong, true)]
    #[case::eventual(ConsistencyLevel::Eventual, false)]
    #[case::unspecified(ConsistencyLevel::Unspecified, false)]
    #[tokio::test]
    async fn get_person_request_headers_follow_the_routing_branch(
        #[case] consistency: ConsistencyLevel,
        #[case] leader_bound: bool,
    ) {
        let request = client().build_get_person_request(7, 42, consistency);
        let metadata = request.metadata();
        if leader_bound {
            assert_eq!(metadata.get(TEAM_ID_HEADER).unwrap(), "7");
            assert_eq!(metadata.get(PERSON_ID_HEADER).unwrap(), "42");
            assert_eq!(metadata.get(READ_CONSISTENCY_HEADER).unwrap(), "strong");
        } else {
            assert!(metadata.get(TEAM_ID_HEADER).is_none());
            assert!(metadata.get(PERSON_ID_HEADER).is_none());
            assert!(metadata.get(READ_CONSISTENCY_HEADER).is_none());
        }
    }
}
