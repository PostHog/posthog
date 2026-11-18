use std::collections::HashMap;
use std::sync::Arc;
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

use personhog_common::partitioning::partition_for_person;
use personhog_coordination::changelog::LiveChangelog;

use super::AddressResolver;
use crate::grpc_http::{grpc_error_response, grpc_status_code};

const REPLICA_PREFIX: &str = "/personhog.replica.v1.PersonHogReplica/";

/// One follower coordination instance: every partition has one owner in it.
pub struct FollowerInstance {
    pub name: Arc<str>,
    pub table: Arc<RwLock<HashMap<u32, String>>>,
    pub addresses: AddressResolver,
}

/// Sends a person read to a follower of the person's partition. Followers serve reads
/// only, so every instance's owner of a partition is as good as another's: a refusal or
/// a failure on one moves on to the next.
pub struct FollowerBackend {
    /// In preference order: the router's own zone first.
    instances: Vec<FollowerInstance>,
    changelog: LiveChangelog,
    channels: DashMap<String, Channel>,
    timeout: Duration,
}

impl FollowerBackend {
    pub fn new(
        instances: Vec<FollowerInstance>,
        changelog: LiveChangelog,
        timeout: Duration,
    ) -> Self {
        Self {
            instances,
            changelog,
            channels: DashMap::new(),
            timeout,
        }
    }

    pub async fn forward(
        &self,
        method: &'static str,
        (team_id, person_id): (i64, i64),
        headers: &HeaderMap,
        frame: &Bytes,
    ) -> (http::Response<BoxBody>, Option<f64>) {
        let (partitions, epoch) = self.changelog.layout();
        let partition = partition_for_person(team_id, person_id, partitions);
        let mut refused = false;
        for instance in &self.instances {
            let attempt = self
                .attempt(instance, method, partition, epoch, headers, frame)
                .await;
            let outcome = match &attempt {
                Some((response, _)) if !moves_on(response) => "served",
                Some(_) => "refused",
                None => "unreachable",
            };
            counter!(
                "personhog_router_follower_attempts_total",
                "instance" => Arc::clone(&instance.name),
                "outcome" => outcome,
            )
            .increment(1);
            match attempt {
                Some((response, call_ms)) if outcome == "served" => {
                    return (response, Some(call_ms));
                }
                Some(_) => refused = true,
                None => {}
            }
        }
        // Retryable whatever the last refusal was: a follower that is behind, or one this
        // router's config has not caught up with, is expected to answer a later attempt.
        let reason = if refused {
            "no follower is current"
        } else {
            "no follower is reachable"
        };
        let response = grpc_error_response(
            Code::Unavailable,
            &format!("{reason} for partition {partition}"),
        );
        (response, None)
    }

    /// One follower's answer, or `None` when the instance has no reachable owner.
    async fn attempt(
        &self,
        instance: &FollowerInstance,
        method: &'static str,
        partition: u32,
        epoch: u64,
        headers: &HeaderMap,
        frame: &Bytes,
    ) -> Option<(http::Response<BoxBody>, f64)> {
        let owner = instance.table.read().await.get(&partition).cloned()?;
        let address = (instance.addresses)(&owner)?;
        let channel = match self.channels.get(&address) {
            Some(channel) => channel.clone(),
            None => {
                let channel = Channel::from_shared(address.clone())
                    .ok()?
                    .timeout(self.timeout)
                    .connect_timeout(self.timeout)
                    .tcp_nodelay(true)
                    .connect_lazy();
                self.channels.entry(address).or_insert(channel).clone()
            }
        };

        let body = BoxBody::new(Full::new(frame.clone()).map_err(|never| match never {}));
        let mut request = http::Request::new(body);
        *request.method_mut() = Method::POST;
        *request.uri_mut() = Uri::builder()
            .path_and_query(format!("{REPLICA_PREFIX}{method}"))
            .build()
            .ok()?;
        *request.version_mut() = Version::HTTP_2;
        *request.headers_mut() = headers.clone();
        request
            .headers_mut()
            .insert("x-partition", HeaderValue::from(partition));
        request
            .headers_mut()
            .insert("x-changelog-epoch", HeaderValue::from(epoch));

        let started = Instant::now();
        let mut channel = channel;
        // Bounded here as well as on the channel: an owner that cannot be connected to
        // must cost one attempt whatever is queued on its channel.
        let answered = async { channel.ready().await.ok()?.call(request).await.ok() };
        let response = tokio::time::timeout(self.timeout, answered).await.ok()??;
        let (parts, body) = response.into_parts();
        let response = http::Response::from_parts(parts, BoxBody::new(body));
        Some((response, started.elapsed().as_secs_f64() * 1000.0))
    }
}

/// A follower that is behind, mid-rebuild or no longer the owner refuses with one of
/// these, and another instance's owner may still answer.
fn moves_on(response: &http::Response<BoxBody>) -> bool {
    matches!(
        grpc_status_code(response),
        Some(code) if code == Code::Unavailable as i32 || code == Code::FailedPrecondition as i32
    )
}
