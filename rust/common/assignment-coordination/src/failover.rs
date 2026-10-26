use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use etcd_client::{Client, ConnectOptions, GetOptions};
use tonic::Code;

/// Consecutive member-level failures that start a switch attempt.
const FAILURE_THRESHOLD: u32 = 3;
/// Minimum gap between switch attempts, so a cluster-wide outage does not
/// turn every failed call into a round of probes.
const MIN_ATTEMPT_INTERVAL: Duration = Duration::from_secs(5);
/// Budget for one probe: connect, one linearizable read, one member list.
const PROBE_TIMEOUT: Duration = Duration::from_secs(3);

/// Whether an etcd error says the member serving this client cannot serve.
///
/// etcd reports "no leader", "request timed out" and "leader changed" as
/// Unavailable, and a connection closed under a call surfaces as Cancelled.
/// Errors about the request itself (NOSPACE, a failed compare, a compacted
/// revision, a missing key) say nothing about the member.
pub fn is_member_level(err: &etcd_client::Error) -> bool {
    match err {
        etcd_client::Error::GRpcStatus(status) => matches!(
            status.code(),
            Code::Unavailable | Code::DeadlineExceeded | Code::Cancelled
        ),
        etcd_client::Error::TransportError(_) | etcd_client::Error::IoError(_) => true,
        _ => false,
    }
}

struct State {
    /// Endpoints currently in the client's balanced channel.
    current: Vec<String>,
    /// The endpoints the store was configured with, used when no member
    /// list is known.
    configured: Vec<String>,
    /// One client URL per voting member, from the last member list read.
    members: Vec<String>,
    last_attempt: Option<Instant>,
}

/// Moves a client to a different etcd member when the one it is connected
/// to keeps failing while the rest of the cluster may still be healthy.
pub(crate) struct MemberFailover {
    client: Client,
    probe_options: ConnectOptions,
    consecutive_failures: AtomicU32,
    switching: AtomicBool,
    state: Mutex<State>,
}

impl MemberFailover {
    pub(crate) fn new(client: Client, options: ConnectOptions, endpoints: Vec<String>) -> Self {
        Self {
            client,
            probe_options: options
                .with_require_leader(true)
                .with_connect_timeout(PROBE_TIMEOUT),
            consecutive_failures: AtomicU32::new(0),
            switching: AtomicBool::new(false),
            state: Mutex::new(State {
                current: endpoints.clone(),
                configured: endpoints,
                members: Vec::new(),
                last_attempt: None,
            }),
        }
    }

    /// Reads the member list through the connected client, best effort.
    pub(crate) async fn refresh_members(&self) {
        let mut client = self.client.clone();
        if let Ok(Ok(resp)) = tokio::time::timeout(PROBE_TIMEOUT, client.member_list()).await {
            self.set_members(member_urls(&resp));
        }
    }

    pub(crate) fn note_success(&self) {
        self.consecutive_failures.store(0, Ordering::Relaxed);
    }

    pub(crate) fn note_failure(self: &Arc<Self>) {
        let failures = self.consecutive_failures.fetch_add(1, Ordering::Relaxed) + 1;
        if failures >= FAILURE_THRESHOLD {
            self.start_switch();
        }
    }

    /// A call that got no answer at all starts a switch attempt at once.
    pub(crate) fn note_unresponsive(self: &Arc<Self>) {
        self.consecutive_failures.fetch_add(1, Ordering::Relaxed);
        self.start_switch();
    }

    fn start_switch(self: &Arc<Self>) {
        if self.switching.swap(true, Ordering::AcqRel) {
            return;
        }
        let this = Arc::clone(self);
        tokio::spawn(async move {
            this.attempt_switch().await;
            this.switching.store(false, Ordering::Release);
        });
    }

    async fn attempt_switch(&self) {
        let (current, candidates) = {
            let mut state = self.lock();
            if state
                .last_attempt
                .is_some_and(|at| at.elapsed() < MIN_ATTEMPT_INTERVAL)
            {
                return;
            }
            state.last_attempt = Some(Instant::now());
            let candidates: Vec<String> = state
                .members
                .iter()
                .filter(|url| !state.current.contains(url))
                .cloned()
                .collect();
            (state.current.clone(), candidates)
        };

        if candidates.is_empty() {
            // No other member is known: reconnect so the configured names
            // resolve again.
            let configured = self.lock().configured.clone();
            tracing::warn!(
                endpoints = ?configured,
                "etcd member keeps failing and no other member is known; reconnecting"
            );
            self.replace_endpoints(&current, &configured).await;
            metrics::counter!("assignment_coordination_etcd_member_switches_total", "outcome" => "reconnected")
                .increment(1);
            return;
        }

        for candidate in rotated(candidates) {
            match self.probe(&candidate).await {
                Ok(members) => {
                    self.replace_endpoints(&current, std::slice::from_ref(&candidate))
                        .await;
                    if !members.is_empty() {
                        self.set_members(members);
                    }
                    self.consecutive_failures.store(0, Ordering::Relaxed);
                    tracing::warn!(
                        from = ?current,
                        to = %candidate,
                        "switched etcd member after repeated failures"
                    );
                    metrics::counter!("assignment_coordination_etcd_member_switches_total", "outcome" => "switched")
                        .increment(1);
                    return;
                }
                Err(error) => {
                    tracing::warn!(%candidate, %error, "etcd member probe failed");
                }
            }
        }
        tracing::warn!(
            current = ?current,
            "etcd member keeps failing and no other member answered a probe; staying"
        );
        metrics::counter!("assignment_coordination_etcd_member_switches_total", "outcome" => "no_healthy_member")
            .increment(1);
    }

    /// Connects to `url` alone and checks it can serve a linearizable read,
    /// which needs a leader and a quorum. Returns its view of the members.
    async fn probe(&self, url: &str) -> Result<Vec<String>, String> {
        let attempt = async {
            let mut client = Client::connect([url], Some(self.probe_options.clone())).await?;
            client
                .get("probe", Some(GetOptions::new().with_count_only()))
                .await?;
            let members = client.member_list().await?;
            Ok::<_, etcd_client::Error>(member_urls(&members))
        };
        match tokio::time::timeout(PROBE_TIMEOUT, attempt).await {
            Ok(Ok(members)) => Ok(members),
            Ok(Err(error)) => Err(error.to_string()),
            Err(_) => Err(format!("no answer within {PROBE_TIMEOUT:?}")),
        }
    }

    /// Inserts the new endpoints before removing the old ones, so the
    /// balanced channel is never empty.
    async fn replace_endpoints(&self, old: &[String], new: &[String]) {
        for url in new {
            if let Err(error) = self.client.add_endpoint(url).await {
                tracing::error!(%url, %error, "failed to add etcd endpoint");
                return;
            }
        }
        for url in old.iter().filter(|url| !new.contains(url)) {
            if let Err(error) = self.client.remove_endpoint(url).await {
                tracing::error!(%url, %error, "failed to remove etcd endpoint");
            }
        }
        self.lock().current = new.to_vec();
    }

    fn set_members(&self, members: Vec<String>) {
        self.lock().members = members;
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, State> {
        self.state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    #[cfg(test)]
    pub(crate) fn set_members_for_test(&self, members: Vec<String>) {
        self.set_members(members);
    }

    #[cfg(test)]
    pub(crate) fn current_for_test(&self) -> Vec<String> {
        self.lock().current.clone()
    }
}

fn member_urls(resp: &etcd_client::MemberListResponse) -> Vec<String> {
    resp.members()
        .iter()
        .filter(|member| !member.is_learner())
        .filter_map(|member| member.client_urls().first().cloned())
        .collect()
}

/// Starts the candidate list at a random member so processes leaving the
/// same member spread across the others.
fn rotated(mut candidates: Vec<String>) -> Vec<String> {
    let mut hasher = RandomState::new().build_hasher();
    hasher.write_u64(0);
    let start = (hasher.finish() as usize) % candidates.len();
    candidates.rotate_left(start);
    candidates
}

#[cfg(test)]
mod tests {
    use super::*;

    fn status(code: Code) -> etcd_client::Error {
        etcd_client::Error::GRpcStatus(tonic::Status::new(code, "test"))
    }

    #[test]
    fn member_level_errors_are_the_ones_a_different_member_could_avoid() {
        assert!(is_member_level(&status(Code::Unavailable)));
        assert!(is_member_level(&status(Code::DeadlineExceeded)));
        assert!(is_member_level(&status(Code::Cancelled)));
        assert!(is_member_level(&etcd_client::Error::IoError(
            std::io::Error::from(std::io::ErrorKind::ConnectionReset)
        )));
        for code in [
            Code::ResourceExhausted,
            Code::FailedPrecondition,
            Code::NotFound,
            Code::InvalidArgument,
            Code::OutOfRange,
            Code::PermissionDenied,
        ] {
            assert!(!is_member_level(&status(code)), "{code:?}");
        }
    }
}
