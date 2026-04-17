use std::{
    collections::HashMap,
    time::{Duration, Instant},
};

use reqwest::StatusCode;
use siphasher::sip::SipHasher13;
use std::hash::{Hash, Hasher};
use tracing::warn;

use crate::{
    error::{RemoteError, UnhandledError},
    metric_consts::{
        DISTRIBUTED_REMOTE_REQUEST_DURATION_SECONDS, DISTRIBUTED_TASKS_TOTAL,
        INTERNAL_RESOLVE_TASKS_TOTAL,
    },
    stages::resolution::LocalResolutionStage,
};

pub mod tasks;

use tasks::{ResolveBatchRequest, ResolveBatchResponse, ResolveTask, ResolveTaskResult};

#[derive(Clone)]
pub struct DistributedContext {
    pub(crate) resolution: LocalResolutionStage,
    http_client: reqwest::Client,
    distributed_headless_host: String,
    distributed_remote_timeout_ms: u64,
    pod_ip: String,
    port: u16,
}

impl DistributedContext {
    pub fn new(app_context: &crate::app_context::AppContext) -> Self {
        let resolution = LocalResolutionStage::from_parts(
            app_context.symbol_resolver.clone(),
            app_context.symbol_resolution_limiter.clone(),
        );
        Self {
            resolution,
            http_client: app_context.http_client.clone(),
            distributed_headless_host: app_context.config.distributed_headless_host.clone(),
            distributed_remote_timeout_ms: app_context.config.distributed_remote_timeout_ms,
            pod_ip: app_context.config.pod_ip.clone(),
            port: app_context.config.port,
        }
    }

    /// Resolve a set of tasks, routing each one locally or to a remote pod
    /// based on consistent hashing. The caller doesn't need to know how
    /// routing works — it just submits tasks and gets results.
    pub(crate) async fn resolve_tasks(
        &self,
        tasks: Vec<ResolveTask>,
    ) -> Result<HashMap<u64, ResolveTaskResult>, UnhandledError> {
        if self.distributed_headless_host.is_empty() {
            return self.execute_local_tasks(tasks).await;
        }

        let endpoints = self.resolve_endpoints().await?;
        let local_ip = self.local_ip();

        let mut local_tasks = Vec::new();
        let mut remote_tasks: HashMap<String, Vec<ResolveTask>> = HashMap::new();

        for task in tasks {
            match route_task(&task, &endpoints, local_ip) {
                Route::Local(reason) => {
                    metrics::counter!(
                        DISTRIBUTED_TASKS_TOTAL,
                        "task_type" => task.task_type_label(),
                        "route" => reason
                    )
                    .increment(1);
                    local_tasks.push(task);
                }
                Route::Remote(ip) => {
                    metrics::counter!(
                        DISTRIBUTED_TASKS_TOTAL,
                        "task_type" => task.task_type_label(),
                        "route" => "remote"
                    )
                    .increment(1);
                    remote_tasks.entry(ip).or_default().push(task);
                }
            }
        }

        self.execute_task_plan(local_tasks, remote_tasks).await
    }

    pub async fn process_internal_request(
        &self,
        request: ResolveBatchRequest,
    ) -> Result<ResolveBatchResponse, UnhandledError> {
        let mut results = Vec::with_capacity(request.tasks.len());

        for task in request.tasks {
            let task_type = task.task_type_label();
            match self.execute_task_locally(&task).await {
                Ok(result) => {
                    metrics::counter!(
                        INTERNAL_RESOLVE_TASKS_TOTAL,
                        "task_type" => task_type,
                        "outcome" => "success"
                    )
                    .increment(1);
                    results.push(result);
                }
                Err(err) => {
                    metrics::counter!(
                        INTERNAL_RESOLVE_TASKS_TOTAL,
                        "task_type" => task_type,
                        "outcome" => "error"
                    )
                    .increment(1);
                    return Err(err);
                }
            }
        }

        Ok(ResolveBatchResponse { results })
    }

    // -- private transport internals --

    fn local_ip(&self) -> Option<&str> {
        if self.pod_ip.trim().is_empty() {
            None
        } else {
            Some(self.pod_ip.as_str())
        }
    }

    async fn resolve_endpoints(&self) -> Result<Vec<String>, RemoteError> {
        let addrs = tokio::net::lookup_host((self.distributed_headless_host.as_str(), self.port))
            .await
            .map_err(RemoteError::DnsError)?;

        let mut endpoints: Vec<String> = addrs
            .map(|addr| addr.ip().to_string())
            .collect::<std::collections::HashSet<_>>()
            .into_iter()
            .collect();

        if endpoints.is_empty() {
            return Err(RemoteError::NoEndpoints);
        }

        endpoints.sort();
        Ok(endpoints)
    }

    async fn execute_task_plan(
        &self,
        local_tasks: Vec<ResolveTask>,
        remote_tasks: HashMap<String, Vec<ResolveTask>>,
    ) -> Result<HashMap<u64, ResolveTaskResult>, UnhandledError> {
        let mut results = self.execute_local_tasks(local_tasks).await?;

        // Dispatch remote batches concurrently — requests to different pods are independent
        let remote_futures: Vec<_> = remote_tasks
            .into_iter()
            .map(|(destination_ip, tasks)| {
                let ctx = self.clone();
                async move {
                    (
                        destination_ip.clone(),
                        ctx.execute_remote_tasks(&destination_ip, &tasks).await,
                        tasks,
                    )
                }
            })
            .collect();

        let remote_outcomes = futures::future::join_all(remote_futures).await;

        for (destination_ip, outcome, tasks) in remote_outcomes {
            let remote_results = outcome.map_err(|err| {
                warn!(
                    destination = %destination_ip,
                    error = %err,
                    task_count = tasks.len(),
                    "remote resolution failed"
                );
                err
            })?;

            let mut remote_map: HashMap<u64, ResolveTaskResult> = remote_results
                .into_iter()
                .map(|result| (result.task_id(), result))
                .collect();

            for task in tasks {
                let result = remote_map.remove(&task.task_id()).ok_or_else(|| {
                    RemoteError::InvalidResponse(format!(
                        "remote pod {} did not return result for task {}",
                        destination_ip,
                        task.task_id()
                    ))
                })?;
                results.insert(task.task_id(), result);
            }
        }

        Ok(results)
    }

    async fn execute_local_tasks(
        &self,
        tasks: Vec<ResolveTask>,
    ) -> Result<HashMap<u64, ResolveTaskResult>, UnhandledError> {
        let futs: Vec<_> = tasks
            .iter()
            .map(|task| self.execute_task_locally(task))
            .collect();

        let outcomes = futures::future::join_all(futs).await;

        let mut results = HashMap::new();
        for (task, outcome) in tasks.iter().zip(outcomes) {
            results.insert(task.task_id(), outcome?);
        }
        Ok(results)
    }

    async fn execute_remote_tasks(
        &self,
        destination_ip: &str,
        tasks: &[ResolveTask],
    ) -> Result<Vec<ResolveTaskResult>, RemoteError> {
        let started = Instant::now();
        let result = self.send_remote_request(destination_ip, tasks).await;

        metrics::histogram!(
            DISTRIBUTED_REMOTE_REQUEST_DURATION_SECONDS,
            "outcome" => result.as_ref().map_or_else(|e| e.histogram_label(), |_| "success")
        )
        .record(started.elapsed().as_secs_f64());

        result
    }

    async fn send_remote_request(
        &self,
        destination_ip: &str,
        tasks: &[ResolveTask],
    ) -> Result<Vec<ResolveTaskResult>, RemoteError> {
        let url = format!(
            "http://{}:{}/_internal/resolve-batch",
            destination_ip, self.port
        );
        let request = ResolveBatchRequest {
            tasks: tasks.to_vec(),
        };

        let response = tokio::time::timeout(
            Duration::from_millis(self.distributed_remote_timeout_ms),
            self.http_client.post(url).json(&request).send(),
        )
        .await
        .map_err(|_| RemoteError::Timeout)?
        .map_err(RemoteError::RequestFailed)?;

        if response.status() != StatusCode::OK {
            return Err(RemoteError::BadStatus(response.status()));
        }

        response
            .json::<ResolveBatchResponse>()
            .await
            .map(|r| r.results)
            .map_err(RemoteError::InvalidResponseBody)
    }

    async fn execute_task_locally(
        &self,
        task: &ResolveTask,
    ) -> Result<ResolveTaskResult, UnhandledError> {
        let _permit = self.resolution.acquire_symbol_resolution_permit().await?;
        task.execute(&*self.resolution.symbol_resolver).await
    }
}

// -- routing (private) --

enum Route {
    Local(&'static str),
    Remote(String),
}

fn route_task(task: &ResolveTask, endpoints: &[String], local_ip: Option<&str>) -> Route {
    let Some(routing_ref) = task.routing_ref() else {
        return Route::Local("no_ref");
    };

    let destination = endpoint_for_ref(task.team_id(), routing_ref, endpoints);
    if local_ip == Some(destination.as_str()) {
        Route::Local("local")
    } else {
        Route::Remote(destination)
    }
}

fn endpoint_for_ref(team_id: i32, routing_ref: &str, endpoints: &[String]) -> String {
    let key = stable_key(team_id, routing_ref);
    let bucket = jump_consistent_hash(key, endpoints.len() as i32) as usize;
    endpoints[bucket].clone()
}

// Uses SipHash-1-3 with fixed keys for deterministic hashing that is stable
// across Rust toolchain versions. DefaultHasher's output is explicitly not
// guaranteed to be stable.
const SIP_KEY0: u64 = 0x7a31_6f39_5e12_d8b1;
const SIP_KEY1: u64 = 0x4f2a_c891_e5d7_36c0;

fn stable_key(team_id: i32, routing_ref: &str) -> u64 {
    let mut hasher = SipHasher13::new_with_keys(SIP_KEY0, SIP_KEY1);
    team_id.hash(&mut hasher);
    ":".hash(&mut hasher);
    routing_ref.hash(&mut hasher);
    hasher.finish()
}

fn jump_consistent_hash(mut key: u64, num_buckets: i32) -> i32 {
    let mut b: i64 = -1;
    let mut j: i64 = 0;

    while j < num_buckets as i64 {
        b = j;
        key = key.wrapping_mul(2862933555777941757).wrapping_add(1);
        j = (((b + 1) as f64) * ((1_u64 << 31) as f64 / ((key >> 33) + 1) as f64)) as i64;
    }

    b as i32
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn jump_hash_stays_in_bucket_range() {
        for key in [1_u64, 2, 3, 42, 123456789] {
            let bucket = jump_consistent_hash(key, 7);
            assert!((0..7).contains(&bucket));
        }
    }

    #[test]
    fn route_task_remote_without_local_ip() {
        let task = test_task(Some("ref"));
        let endpoints = vec!["10.0.0.1".to_string()];
        let route = route_task(&task, &endpoints, None);
        assert!(matches!(route, Route::Remote(_)));
    }

    #[test]
    fn route_task_local_when_no_routing_ref() {
        let task = test_task(None);
        let endpoints = vec!["10.0.0.1".to_string()];
        let route = route_task(&task, &endpoints, None);
        assert!(matches!(route, Route::Local("no_ref")));
    }

    fn test_task(routing_ref: Option<&str>) -> ResolveTask {
        use crate::distributed::tasks::DartExceptionTask;

        ResolveTask::DartException(DartExceptionTask {
            task_id: 1,
            team_id: 1,
            exception_type: "test".to_string(),
            chunk_id: "chunk".to_string(),
            routing_ref: routing_ref.map(String::from),
        })
    }

    #[test]
    fn stable_key_is_deterministic() {
        let a = stable_key(42, "debug-id-abc");
        let b = stable_key(42, "debug-id-abc");
        assert_eq!(a, b);

        let c = stable_key(42, "debug-id-xyz");
        assert_ne!(a, c);
    }
}
