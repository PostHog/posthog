use std::collections::{HashMap, HashSet};
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant};

use bytes::Bytes;
use dashmap::DashMap;
use http::{HeaderMap, HeaderValue, Method, Uri, Version};
use http_body_util::{BodyExt, Full};
use metrics::counter;
use tokio::sync::RwLock;
use tonic::body::BoxBody;
use tonic::transport::Channel;
use tonic::Code;
use tower::{Service, ServiceExt};

use personhog_common::client::{CHANGELOG_EPOCH_HEADER, PARTITION_HEADER};
use personhog_common::partitioning::partition_for_person;
use personhog_coordination::changelog::LiveChangelog;

use super::AddressResolver;
use crate::grpc_http::grpc_status_code;

const REPLICA_PREFIX: &str = "/personhog.replica.v1.PersonHogReplica/";

/// One follower coordination instance: every partition has one owner in it.
pub struct FollowerInstance {
    pub name: Arc<str>,
    pub table: Arc<RwLock<HashMap<u32, String>>>,
    pub addresses: AddressResolver,
}

/// Sends a person read to a follower of the person's partition. Followers serve reads
/// only, so every instance's owner of a partition is as good as another's, and a follower
/// answers every read it receives. A read no follower could be asked in time belongs to
/// any replica.
pub struct FollowerBackend {
    joined: OnceLock<Joined>,
    channels: DashMap<String, Channel>,
    connect_timeout: Duration,
    request_timeout: Duration,
}

struct Joined {
    /// In preference order: the router's own zone first.
    instances: Vec<FollowerInstance>,
    changelog: LiveChangelog,
}

enum Attempt {
    Answered(http::Response<BoxBody>, f64),
    /// The instance has no owner of the partition that could be connected to.
    Unreachable,
    /// The owner answered that it cannot take the request, as one shedding load does.
    Unavailable,
    TimedOut,
}

impl Attempt {
    fn label(&self) -> &'static str {
        match self {
            Self::Answered(..) => "answered",
            Self::Unreachable => "unreachable",
            Self::Unavailable => "unavailable",
            Self::TimedOut => "timed_out",
        }
    }
}

impl FollowerBackend {
    /// A backend with no followers to ask until [`Self::join`].
    pub fn new(connect_timeout: Duration, request_timeout: Duration) -> Self {
        Self {
            joined: OnceLock::new(),
            channels: DashMap::new(),
            connect_timeout,
            request_timeout,
        }
    }

    /// Start asking these instances, in this order.
    pub fn join(&self, instances: Vec<FollowerInstance>, changelog: LiveChangelog) {
        drop(self.joined.set(Joined {
            instances,
            changelog,
        }));
    }

    /// A follower's answer, or `None` when none could be asked in time.
    pub async fn forward(
        &self,
        method: &'static str,
        (team_id, person_id): (i64, i64),
        headers: &HeaderMap,
        frame: &Bytes,
    ) -> Option<(http::Response<BoxBody>, f64)> {
        let joined = self.joined.get()?;
        let (partitions, epoch) = joined.changelog.layout();
        let partition = partition_for_person(team_id, person_id, partitions);
        for instance in &joined.instances {
            let attempt = self
                .attempt(joined, instance, method, partition, epoch, headers, frame)
                .await;
            counter!(
                "personhog_router_follower_attempts_total",
                "instance" => Arc::clone(&instance.name),
                "outcome" => attempt.label(),
            )
            .increment(1);
            match attempt {
                Attempt::Answered(response, call_ms) => return Some((response, call_ms)),
                // That follower may still be reading, and another would repeat its work.
                Attempt::TimedOut => return None,
                Attempt::Unreachable | Attempt::Unavailable => {}
            }
        }
        None
    }

    /// Drop the channels to addresses no instance lists as an owner's any more, which a
    /// follower leaves behind each time it restarts.
    async fn forget_unlisted_channels(&self, joined: &Joined) {
        let mut listed = HashSet::new();
        for instance in &joined.instances {
            for owner in instance.table.read().await.values() {
                listed.extend((instance.addresses)(owner));
            }
        }
        self.channels.retain(|address, _| listed.contains(address));
    }

    #[allow(clippy::too_many_arguments)]
    async fn attempt(
        &self,
        joined: &Joined,
        instance: &FollowerInstance,
        method: &'static str,
        partition: u32,
        epoch: u64,
        headers: &HeaderMap,
        frame: &Bytes,
    ) -> Attempt {
        let Some(owner) = instance.table.read().await.get(&partition).cloned() else {
            return Attempt::Unreachable;
        };
        let Some(address) = (instance.addresses)(&owner) else {
            return Attempt::Unreachable;
        };
        let mut channel = match self.channels.get(&address) {
            Some(channel) => channel.clone(),
            None => {
                let Ok(endpoint) = Channel::from_shared(address.clone()) else {
                    return Attempt::Unreachable;
                };
                let channel = endpoint
                    .connect_timeout(self.connect_timeout)
                    .tcp_nodelay(true)
                    .connect_lazy();
                self.forget_unlisted_channels(joined).await;
                self.channels.entry(address).or_insert(channel).clone()
            }
        };

        let body = BoxBody::new(Full::new(frame.clone()).map_err(|never| match never {}));
        let mut request = http::Request::new(body);
        *request.method_mut() = Method::POST;
        let Ok(uri) = Uri::builder()
            .path_and_query(format!("{REPLICA_PREFIX}{method}"))
            .build()
        else {
            return Attempt::Unreachable;
        };
        *request.uri_mut() = uri;
        *request.version_mut() = Version::HTTP_2;
        *request.headers_mut() = headers.clone();
        request
            .headers_mut()
            .insert(PARTITION_HEADER, HeaderValue::from(partition));
        request
            .headers_mut()
            .insert(CHANGELOG_EPOCH_HEADER, HeaderValue::from(epoch));

        let started = Instant::now();
        // Readiness is a place in the channel's queue, which fills behind an owner that
        // cannot be connected to. The request is bounded here and not on the channel, so
        // a timeout is told apart from a failed connection.
        match tokio::time::timeout(self.connect_timeout, channel.ready()).await {
            Ok(Ok(_)) => {}
            Ok(Err(_)) | Err(_) => return Attempt::Unreachable,
        }
        match tokio::time::timeout(self.request_timeout, channel.call(request)).await {
            Ok(Ok(response)) => {
                if grpc_status_code(&response) == Some(Code::Unavailable as i32) {
                    return Attempt::Unavailable;
                }
                let (parts, body) = response.into_parts();
                let response = http::Response::from_parts(parts, BoxBody::new(body));
                Attempt::Answered(response, started.elapsed().as_secs_f64() * 1000.0)
            }
            Ok(Err(_)) => Attempt::Unreachable,
            Err(_) => Attempt::TimedOut,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use personhog_coordination::types::ChangelogConfig;

    use super::*;

    #[tokio::test]
    async fn a_channel_to_an_address_no_owner_has_any_more_is_dropped() {
        let address = Arc::new(Mutex::new("http://127.0.0.1:1".to_string()));
        let listed = Arc::clone(&address);
        let backend = FollowerBackend::new(Duration::from_millis(50), Duration::from_millis(50));
        backend.join(
            vec![FollowerInstance {
                name: Arc::from("zone"),
                table: Arc::new(RwLock::new(HashMap::from([(0, "follower-0".to_string())]))),
                addresses: Arc::new(move |_pod: &str| Some(listed.lock().unwrap().clone())),
            }],
            LiveChangelog::new(ChangelogConfig::new("personhog_updates", 1)),
        );
        let (headers, frame) = (HeaderMap::new(), Bytes::new());
        let read = || backend.forward("GetPerson", (1, 42), &headers, &frame);

        read().await;
        // The follower restarts on another address.
        *address.lock().unwrap() = "http://127.0.0.1:2".to_string();
        read().await;

        let kept: Vec<String> = backend
            .channels
            .iter()
            .map(|channel| channel.key().clone())
            .collect();
        assert_eq!(kept, ["http://127.0.0.1:2"]);
    }
}
