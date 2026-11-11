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
/// An unanswered call that waited at least this long starts a switch at once.
/// Shorter waits, such as the coordinator's 1s renewals on a busy cluster,
/// count toward FAILURE_THRESHOLD instead.
const UNANSWERED_FLOOR: Duration = Duration::from_secs(2);

/// Whether an etcd error says this member cannot serve: Unavailable,
/// DeadlineExceeded, or a transport failure under the call. Errors about the
/// request itself (NOSPACE, a failed compare, a compacted revision) do not.
pub fn is_member_level(err: &etcd_client::Error) -> bool {
    match err {
        etcd_client::Error::GRpcStatus(status) => {
            matches!(status.code(), Code::Unavailable | Code::DeadlineExceeded)
                || raised_by_connection(status)
        }
        etcd_client::Error::TransportError(_) | etcd_client::Error::IoError(_) => true,
        _ => false,
    }
}

/// `connection` for a failure under the call, otherwise etcd's gRPC code.
pub(crate) fn error_kind(err: &etcd_client::Error) -> &'static str {
    match err {
        etcd_client::Error::GRpcStatus(status) if raised_by_connection(status) => "connection",
        etcd_client::Error::GRpcStatus(status) => match status.code() {
            Code::Unavailable => "unavailable",
            Code::DeadlineExceeded => "deadline_exceeded",
            Code::ResourceExhausted => "resource_exhausted",
            Code::OutOfRange => "out_of_range",
            Code::InvalidArgument => "invalid_argument",
            Code::FailedPrecondition => "failed_precondition",
            Code::NotFound => "not_found",
            Code::Cancelled => "cancelled",
            _ => "other_status",
        },
        etcd_client::Error::TransportError(_) | etcd_client::Error::IoError(_) => "connection",
        _ => "other",
    }
}

/// The Unavailable error etcd answers a require-leader request with when the
/// member has no leader, for the same condition reported another way.
pub fn no_leader_error(message: impl Into<String>) -> etcd_client::Error {
    etcd_client::Error::GRpcStatus(tonic::Status::unavailable(message))
}

/// Whether the client raised this status for a failed connection or HTTP/2
/// stream, whatever its code, rather than etcd sending it.
fn raised_by_connection(status: &tonic::Status) -> bool {
    let mut source = std::error::Error::source(status);
    while let Some(err) = source {
        if err.is::<tonic::transport::Error>()
            || err.is::<h2::Error>()
            || err.is::<std::io::Error>()
        {
            return true;
        }
        source = err.source();
    }
    false
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
    last_failed_refresh: Option<Instant>,
}

/// Clears a flag when dropped, so a task that panics cannot leave it set.
struct ClearOnDrop(Arc<AtomicBool>);

impl Drop for ClearOnDrop {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

/// Moves a client to a different etcd member when the one it is connected
/// to keeps failing while the rest of the cluster may still be healthy.
pub(crate) struct MemberFailover {
    client: Client,
    probe_options: ConnectOptions,
    consecutive_failures: AtomicU32,
    switching: Arc<AtomicBool>,
    refreshing: Arc<AtomicBool>,
    members_known: AtomicBool,
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
            switching: Arc::new(AtomicBool::new(false)),
            refreshing: Arc::new(AtomicBool::new(false)),
            members_known: AtomicBool::new(false),
            state: Mutex::new(State {
                current: endpoints.clone(),
                configured: endpoints,
                members: Vec::new(),
                last_attempt: None,
                last_failed_refresh: None,
            }),
        }
    }

    /// Reads the member list through the connected client, best effort.
    pub(crate) async fn refresh_members(&self) {
        let mut client = self.client.clone();
        let members = match tokio::time::timeout(PROBE_TIMEOUT, client.member_list()).await {
            Ok(Ok(resp)) => member_urls(&resp),
            _ => Vec::new(),
        };
        if members.is_empty() {
            self.lock().last_failed_refresh = Some(Instant::now());
        } else {
            self.set_members(members);
        }
    }

    pub(crate) fn note_success(self: &Arc<Self>) {
        self.consecutive_failures.store(0, Ordering::Relaxed);
        if !self.members_known.load(Ordering::Acquire) {
            self.start_refresh();
        }
    }

    /// Reads the member list in the background once a call succeeds, for a
    /// store that started while etcd could not answer.
    fn start_refresh(self: &Arc<Self>) {
        if self.refreshing.swap(true, Ordering::AcqRel) {
            return;
        }
        let latch = ClearOnDrop(Arc::clone(&self.refreshing));
        if self
            .lock()
            .last_failed_refresh
            .is_some_and(|at| at.elapsed() < MIN_ATTEMPT_INTERVAL)
        {
            return;
        }
        let this = Arc::clone(self);
        tokio::spawn(async move {
            let _latch = latch;
            this.refresh_members().await;
        });
    }

    pub(crate) fn note_failure(self: &Arc<Self>) {
        let failures = self.consecutive_failures.fetch_add(1, Ordering::Relaxed) + 1;
        if failures >= FAILURE_THRESHOLD {
            self.start_switch();
        }
    }

    /// A call that got no answer after `waited`.
    pub(crate) fn note_unanswered(self: &Arc<Self>, waited: Duration) {
        if waited < UNANSWERED_FLOOR {
            self.note_failure();
            return;
        }
        self.consecutive_failures.fetch_add(1, Ordering::Relaxed);
        self.start_switch();
    }

    fn start_switch(self: &Arc<Self>) {
        if self.switching.swap(true, Ordering::AcqRel) {
            return;
        }
        let latch = ClearOnDrop(Arc::clone(&self.switching));
        let this = Arc::clone(self);
        tokio::spawn(async move {
            let _latch = latch;
            this.attempt_switch().await;
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
            let outcome = match self.replace_endpoints(&current, &configured).await {
                Ok(()) => "reconnected",
                Err(()) => "swap_failed",
            };
            metrics::counter!("assignment_coordination_etcd_member_switches_total", "outcome" => outcome)
                .increment(1);
            return;
        }

        for candidate in rotated(candidates) {
            match self.probe(&candidate).await {
                Ok(members) => {
                    if self
                        .replace_endpoints(&current, std::slice::from_ref(&candidate))
                        .await
                        .is_err()
                    {
                        metrics::counter!("assignment_coordination_etcd_member_switches_total", "outcome" => "swap_failed")
                            .increment(1);
                        return;
                    }
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
    /// balanced channel is never empty. Fails, leaving the old endpoints in
    /// place, when an insert fails.
    async fn replace_endpoints(&self, old: &[String], new: &[String]) -> Result<(), ()> {
        for url in new {
            if let Err(error) = self.client.add_endpoint(url).await {
                tracing::error!(%url, %error, "failed to add etcd endpoint; keeping the current one");
                return Err(());
            }
        }
        let mut current = new.to_vec();
        for url in old.iter().filter(|url| !new.contains(url)) {
            if let Err(error) = self.client.remove_endpoint(url).await {
                tracing::error!(%url, %error, "failed to remove etcd endpoint");
                current.push(url.clone());
            }
        }
        self.lock().current = current;
        Ok(())
    }

    fn set_members(&self, members: Vec<String>) {
        self.members_known
            .store(!members.is_empty(), Ordering::Release);
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

    #[cfg(test)]
    pub(crate) fn members_for_test(&self) -> Vec<String> {
        self.lock().members.clone()
    }

    #[cfg(test)]
    pub(crate) fn switching_for_test(&self) -> bool {
        self.switching.load(Ordering::Acquire)
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
    fn error_kinds_separate_broken_connections_from_etcd_answers() {
        let broken_stream =
            tonic::Status::from_error(Box::new(h2::Error::from(h2::Reason::STREAM_CLOSED)));
        assert_eq!(
            error_kind(&etcd_client::Error::GRpcStatus(broken_stream)),
            "connection"
        );
        assert_eq!(
            error_kind(&etcd_client::Error::IoError(std::io::Error::from(
                std::io::ErrorKind::ConnectionReset
            ))),
            "connection"
        );
        assert_eq!(error_kind(&status(Code::Unavailable)), "unavailable");
        assert_eq!(
            error_kind(&status(Code::ResourceExhausted)),
            "resource_exhausted"
        );
        assert_eq!(error_kind(&status(Code::PermissionDenied)), "other_status");
    }

    #[test]
    fn member_level_errors_are_the_ones_a_different_member_could_avoid() {
        assert!(is_member_level(&status(Code::Unavailable)));
        assert!(is_member_level(&status(Code::DeadlineExceeded)));
        assert!(is_member_level(&etcd_client::Error::IoError(
            std::io::Error::from(std::io::ErrorKind::ConnectionReset)
        )));
        let broken_stream =
            tonic::Status::from_error(Box::new(h2::Error::from(h2::Reason::STREAM_CLOSED)));
        assert_eq!(broken_stream.code(), Code::Unknown);
        assert!(is_member_level(&etcd_client::Error::GRpcStatus(
            broken_stream
        )));
        for code in [
            Code::Unknown,
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
