//! Helpers for executing a typed local stage through the generic remote stage
//! gRPC envelope.
//!
//! The pipeline orchestrator decides which stage to run. This module owns the
//! transport-only concerns: envelope encoding, remote client lookup, unary
//! response collection, and mapping transport failures to retryable per-item failures.

use std::collections::{HashMap, HashSet};
use std::future::Future;
use std::net::SocketAddr;

use cymbal_api::cymbal::v1::{StageBatchResult, StageItemResult};
use cymbal_core::routing::{
    AttemptFailureKind, CapacityAwarePartitioner, EndpointSubBatch, FallbackPolicy,
    PartitionRequest, RoutingKey, UnroutableReason,
};
use cymbal_core::{BatchContext, StagePayload, StageType};
use futures::StreamExt;
use tonic::{Code, Status};

use crate::api::stage_error_to_status;
use crate::codec::{decode_json_payload, encode_json_payload};
use crate::observability::{record_remote_retries, RemoteRetryReason};
use crate::remote::{
    jittered_retry_after_ms, RemoteStageConfig, RemoteStageConnectionManager, RemoteStageItem,
};

const REMOTE_STAGE_SUB_BATCH_DISPATCH_CONCURRENCY: usize = 8;

#[derive(Debug, Clone)]
pub(crate) struct RemoteStageBatch<T> {
    pub items: Vec<T>,
    pub failures: Vec<RemoteStageItemFailure>,
    /// Whether the call completed cleanly, hit the per-call timeout, or had
    /// the upstream request fail before a response was returned. The
    /// orchestrator uses this to label `cymbal_stage_duration_seconds`.
    pub outcome: RemoteStageRunOutcome,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RemoteStageRunOutcome {
    Ok,
    Timeout,
    TransportError,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct RemoteStageItemFailure {
    pub item_id: String,
    pub message: String,
    pub retryable: bool,
    pub retry_after_ms: Option<u64>,
}

/// Borrowed dispatch metadata for [`process_remote_stage`]. Grouped into a
/// struct so the orchestrator entry point stays under the clippy
/// `too_many_arguments` ceiling.
pub(crate) struct RemoteStageCall<'a> {
    pub remote_connections: Option<&'a RemoteStageConnectionManager>,
    pub target_name: &'a str,
    pub stage_id: &'a str,
    pub input_type: StageType,
    pub output_type: StageType,
    pub retryable_on_transient_failure: bool,
}

pub(crate) async fn process_remote_stage<TInput, TOutput>(
    call: RemoteStageCall<'_>,
    context: BatchContext,
    inputs: Vec<TInput>,
) -> Result<RemoteStageBatch<TOutput>, Status>
where
    TInput: RemoteStageInput,
    TOutput: serde::de::DeserializeOwned + StagePayload + RemoteStageOutput,
{
    let RemoteStageCall {
        remote_connections,
        target_name,
        stage_id,
        input_type,
        output_type,
        retryable_on_transient_failure,
    } = call;
    let remote_connections = remote_connections.ok_or_else(|| {
        Status::unavailable("remote stage requested but no remote connection manager is configured")
    })?;
    if inputs.is_empty() {
        return Ok(RemoteStageBatch {
            items: Vec::new(),
            failures: Vec::new(),
            outcome: RemoteStageRunOutcome::Ok,
        });
    }

    tracing::debug!(
        stage_id,
        target = target_name,
        batch_id = %context.batch_id,
        items = inputs.len(),
        "calling remote stage"
    );
    let original_order = inputs
        .iter()
        .enumerate()
        .map(|(index, input)| (input.stage_item_id().to_string(), index))
        .collect::<HashMap<_, _>>();
    let mut pending = inputs
        .into_iter()
        .enumerate()
        .map(|(index, input)| PendingRemoteInput::new(index, input))
        .collect::<Vec<_>>();
    let mut excluded_endpoints = HashSet::new();
    let mut completed_items = Vec::new();
    let mut failures = Vec::new();
    let mut aggregate_outcome = RemoteStageRunOutcome::Ok;

    while !pending.is_empty() {
        let endpoints = remote_connections
            .endpoint_addresses_for_target(target_name)
            .await?;
        let mut capacity = remote_connections
            .endpoint_capacity_snapshot(target_name, stage_id, &endpoints)
            .await;
        for endpoint_capacity in &mut capacity.endpoints {
            if excluded_endpoints.contains(&endpoint_capacity.endpoint) {
                endpoint_capacity.ejected = true;
            }
        }

        let partitioner = CapacityAwarePartitioner::new(pending.len() as u64, pending.len() as u64);
        let policy = remote_connections.routing_policy_for_stage(stage_id);
        let partitioned = {
            let mut rng = rand::thread_rng();
            let extractor = |pending_input: &PendingRemoteInput<TInput>| {
                pending_input.input.routing_key(stage_id)
            };
            partitioner.partition(
                pending,
                PartitionRequest {
                    stage_id,
                    endpoints: &endpoints,
                    capacity: &capacity,
                    policy: &policy,
                    extractor: &extractor,
                },
                &mut rng,
            )
        };
        pending = Vec::new();

        let unroutable_failures = partitioned
            .unroutable
            .into_iter()
            .map(|unroutable| {
                unroutable_failure(
                    target_name,
                    unroutable.item.item,
                    unroutable.reason,
                    retryable_on_transient_failure,
                )
            })
            .collect::<Vec<_>>();
        if !unroutable_failures.is_empty() {
            aggregate_outcome =
                merge_outcome(aggregate_outcome, RemoteStageRunOutcome::TransportError);
            record_fallback_exhausted(
                stage_id,
                target_name,
                Code::ResourceExhausted,
                "remote stage sub-batch routing exhausted",
                unroutable_failures.len(),
            );
            record_synthesized_retries(
                stage_id,
                target_name,
                RemoteRetryReason::TransportError,
                &unroutable_failures,
            );
            failures.extend(unroutable_failures);
        }

        if partitioned.sub_batches.is_empty() {
            continue;
        }

        let dispatch_results =
            futures::stream::iter(partitioned.sub_batches.into_iter().map(|sub_batch| {
                let context = context.clone();
                async move {
                    dispatch_remote_sub_batch::<TInput, TOutput>(
                        RemoteSubBatchDispatchContext {
                            remote_connections,
                            target_name,
                            context,
                            stage_id,
                            input_type,
                            output_type,
                            retryable_on_transient_failure,
                        },
                        sub_batch,
                    )
                    .await
                }
            }))
            .buffer_unordered(REMOTE_STAGE_SUB_BATCH_DISPATCH_CONCURRENCY)
            .collect::<Vec<_>>()
            .await;

        for dispatch_result in dispatch_results {
            match dispatch_result? {
                RemoteSubBatchDispatchResult::Completed {
                    endpoint,
                    is_fallback_attempt,
                    batch,
                } => {
                    record_attempt_outcome(remote_connections, target_name, endpoint, Ok(&batch))
                        .await;
                    if is_fallback_attempt && batch.outcome == RemoteStageRunOutcome::Ok {
                        record_fallback_success(
                            stage_id,
                            target_name,
                            endpoint,
                            batch.items.len() + batch.failures.len(),
                        );
                    }
                    aggregate_outcome = merge_outcome(aggregate_outcome, batch.outcome);
                    completed_items.extend(batch.items);
                    failures.extend(batch.failures);
                }
                RemoteSubBatchDispatchResult::SafeFallback {
                    endpoint,
                    mut items,
                    failure,
                } => {
                    excluded_endpoints.insert(endpoint);
                    for item in &mut items {
                        item.mark_fallback(&failure.status, failure.reason);
                    }
                    pending.extend(items);
                    record_endpoint_failure(
                        remote_connections,
                        target_name,
                        endpoint,
                        failure.endpoint_failure_reason,
                    )
                    .await;
                }
            }
        }
    }

    completed_items.sort_by_key(|item: &TOutput| {
        original_order
            .get(item.stage_item_id())
            .copied()
            .unwrap_or(usize::MAX)
    });
    failures.sort_by_key(|failure| {
        original_order
            .get(&failure.item_id)
            .copied()
            .unwrap_or(usize::MAX)
    });

    Ok(RemoteStageBatch {
        items: completed_items,
        failures,
        outcome: aggregate_outcome,
    })
}

#[derive(Debug)]
struct PendingRemoteInput<TInput> {
    input: TInput,
    fallback_attempts: usize,
    last_fallback_reason: Option<&'static str>,
    last_fallback_code: Option<Code>,
    last_fallback_message: Option<String>,
}

impl<TInput> PendingRemoteInput<TInput> {
    fn new(_original_index: usize, input: TInput) -> Self {
        Self {
            input,
            fallback_attempts: 0,
            last_fallback_reason: None,
            last_fallback_code: None,
            last_fallback_message: None,
        }
    }

    fn mark_fallback(&mut self, status: &Status, reason: &'static str) {
        self.fallback_attempts += 1;
        self.last_fallback_reason = Some(reason);
        self.last_fallback_code = Some(status.code());
        self.last_fallback_message = Some(if should_fallback_pre_call(status) {
            status.message().to_string()
        } else {
            format!(
                "remote stage request failed before response: {}",
                status.message()
            )
        });
    }
}

struct SafeFallbackFailure {
    status: Status,
    reason: &'static str,
    endpoint_failure_reason: &'static str,
}

enum RemoteSubBatchDispatchResult<TInput, TOutput> {
    Completed {
        endpoint: SocketAddr,
        is_fallback_attempt: bool,
        batch: RemoteStageBatch<TOutput>,
    },
    SafeFallback {
        endpoint: SocketAddr,
        items: Vec<PendingRemoteInput<TInput>>,
        failure: SafeFallbackFailure,
    },
}

struct RemoteSubBatchDispatchContext<'a> {
    remote_connections: &'a RemoteStageConnectionManager,
    target_name: &'a str,
    context: BatchContext,
    stage_id: &'a str,
    input_type: StageType,
    output_type: StageType,
    retryable_on_transient_failure: bool,
}

async fn dispatch_remote_sub_batch<TInput, TOutput>(
    dispatch_context: RemoteSubBatchDispatchContext<'_>,
    sub_batch: EndpointSubBatch<SocketAddr, PendingRemoteInput<TInput>>,
) -> Result<RemoteSubBatchDispatchResult<TInput, TOutput>, Status>
where
    TInput: RemoteStageInput,
    TOutput: serde::de::DeserializeOwned + StagePayload + RemoteStageOutput,
{
    let RemoteSubBatchDispatchContext {
        remote_connections,
        target_name,
        context,
        stage_id,
        input_type,
        output_type,
        retryable_on_transient_failure,
    } = dispatch_context;
    let endpoint = sub_batch.endpoint;
    let pending_items = sub_batch
        .items
        .into_iter()
        .map(|indexed_item| indexed_item.item)
        .collect::<Vec<_>>();
    let input_ids = pending_items
        .iter()
        .map(|pending| pending.input.stage_item_id().to_string())
        .collect::<Vec<_>>();
    let remote_items = pending_items
        .iter()
        .map(|pending| remote_stage_item(pending.input.stage_item_id(), input_type, &pending.input))
        .collect::<Result<Vec<_>, _>>()?;
    let is_fallback_attempt = pending_items
        .iter()
        .any(|pending| pending.fallback_attempts > 0);

    record_primary_endpoint(stage_id, target_name, endpoint, remote_items.len());
    if is_fallback_attempt {
        let reason = pending_items
            .iter()
            .find_map(|pending| pending.last_fallback_reason)
            .unwrap_or("sub_batch_retry");
        let code = pending_items
            .iter()
            .find_map(|pending| pending.last_fallback_code);
        record_fallback_attempt(
            stage_id,
            target_name,
            endpoint,
            reason,
            code,
            remote_items.len(),
        );
    }

    let config = RemoteStageConfig::new(String::new(), stage_id, input_type, output_type);
    let mut client = match remote_connections
        .client_for_endpoint(target_name, config, endpoint)
        .await
    {
        Ok(client) => client,
        Err(status) if should_fallback_pre_call(&status) => {
            return Ok(RemoteSubBatchDispatchResult::SafeFallback {
                endpoint,
                items: pending_items,
                failure: SafeFallbackFailure {
                    status,
                    reason: "pre_call_unavailable_sub_batch",
                    endpoint_failure_reason: "circuit_open",
                },
            });
        }
        Err(status) => return Err(status),
    };

    match run_remote_stage_attempt::<TOutput>(
        RemoteStageAttemptContext {
            remote_connections,
            endpoint,
            context,
            input_ids,
            output_type,
            retryable_on_transient_failure,
            stage_id,
            target_name,
            stage_timeout: remote_connections.options().stage_timeout,
        },
        &mut client,
        remote_items,
    )
    .await?
    {
        RemoteStageAttemptResult::Completed(batch) => Ok(RemoteSubBatchDispatchResult::Completed {
            endpoint,
            is_fallback_attempt,
            batch,
        }),
        RemoteStageAttemptResult::Fallback { status } => {
            Ok(RemoteSubBatchDispatchResult::SafeFallback {
                endpoint,
                items: pending_items,
                failure: SafeFallbackFailure {
                    status,
                    reason: "resource_exhausted_sub_batch",
                    endpoint_failure_reason: "resource_exhausted",
                },
            })
        }
    }
}

fn unroutable_failure<TInput>(
    target_name: &str,
    pending: PendingRemoteInput<TInput>,
    reason: UnroutableReason,
    retryable: bool,
) -> RemoteStageItemFailure
where
    TInput: RemoteStageInput,
{
    let message = if let Some(message) = pending.last_fallback_message {
        message
    } else {
        match reason {
            UnroutableReason::NoEndpoints => {
                format!("remote stage target {target_name} has no available endpoints")
            }
            UnroutableReason::NoCandidates => format!(
                "remote stage target {target_name} has no available endpoint candidates for item"
            ),
            UnroutableReason::OverCapacity => {
                format!("remote stage target {target_name} has no endpoint capacity for item")
            }
        }
    };
    let item_id = pending.input.stage_item_id().to_string();
    RemoteStageItemFailure {
        retry_after_ms: retryable.then(|| jittered_retry_after_ms(&item_id, &message)),
        item_id,
        message,
        retryable,
    }
}

fn merge_outcome(
    current: RemoteStageRunOutcome,
    next: RemoteStageRunOutcome,
) -> RemoteStageRunOutcome {
    match (current, next) {
        (RemoteStageRunOutcome::TransportError, _) | (_, RemoteStageRunOutcome::TransportError) => {
            RemoteStageRunOutcome::TransportError
        }
        (RemoteStageRunOutcome::Timeout, _) | (_, RemoteStageRunOutcome::Timeout) => {
            RemoteStageRunOutcome::Timeout
        }
        (RemoteStageRunOutcome::Ok, RemoteStageRunOutcome::Ok) => RemoteStageRunOutcome::Ok,
    }
}

enum RemoteStageAttemptResult<T> {
    Completed(RemoteStageBatch<T>),
    Fallback { status: Status },
}

struct RemoteStageAttemptContext<'a> {
    remote_connections: &'a RemoteStageConnectionManager,
    endpoint: SocketAddr,
    context: BatchContext,
    input_ids: Vec<String>,
    output_type: StageType,
    retryable_on_transient_failure: bool,
    stage_id: &'a str,
    target_name: &'a str,
    stage_timeout: Option<std::time::Duration>,
}

async fn run_remote_stage_attempt<TOutput>(
    attempt_context: RemoteStageAttemptContext<'_>,
    client: &mut crate::remote::RemoteStageClient,
    items: Vec<RemoteStageItem>,
) -> Result<RemoteStageAttemptResult<TOutput>, Status>
where
    TOutput: serde::de::DeserializeOwned + StagePayload + RemoteStageOutput,
{
    let RemoteStageAttemptContext {
        remote_connections,
        endpoint,
        context,
        input_ids,
        output_type,
        retryable_on_transient_failure,
        stage_id,
        target_name,
        stage_timeout,
    } = attempt_context;
    let timeout_input_ids = input_ids.clone();
    let attempt = async {
        match client.process_items(context, items).await {
            Ok(output) => {
                if let Some(load) = output.load.clone() {
                    remote_connections
                        .record_endpoint_load(target_name, endpoint, stage_id, load)
                        .await;
                }
                collect_remote_stage_items::<TOutput>(
                    output,
                    output_type.to_string(),
                    input_ids,
                    retryable_on_transient_failure,
                    stage_id,
                    target_name,
                )
                .await
                .map(RemoteStageAttemptResult::Completed)
            }
            Err(status) if should_fallback_after_response(&status) => {
                remote_connections
                    .record_endpoint_status_load(target_name, endpoint, stage_id, &status)
                    .await;
                Ok(RemoteStageAttemptResult::Fallback { status })
            }
            Err(status) => {
                remote_connections
                    .record_endpoint_status_load(target_name, endpoint, stage_id, &status)
                    .await;
                let failures = failures_for_item_ids(
                    input_ids,
                    format!(
                        "remote stage request failed before response: {}",
                        status.message()
                    ),
                    retryable_on_transient_failure,
                );
                record_synthesized_retries(
                    stage_id,
                    target_name,
                    RemoteRetryReason::TransportError,
                    &failures,
                );
                Ok(RemoteStageAttemptResult::Completed(RemoteStageBatch {
                    items: Vec::new(),
                    failures,
                    outcome: RemoteStageRunOutcome::TransportError,
                }))
            }
        }
    };

    match stage_timeout {
        Some(stage_timeout) => {
            tracing::debug!(
                stage_id,
                target = target_name,
                ?stage_timeout,
                "applying remote stage timeout"
            );
            timeout_remote_stage(
                attempt,
                stage_timeout,
                stage_id,
                target_name,
                timeout_input_ids,
                retryable_on_transient_failure,
            )
            .await
        }
        None => attempt.await,
    }
}

fn should_fallback_pre_call(status: &Status) -> bool {
    status.code() == Code::Unavailable
        && status.message().starts_with("remote stage circuit open")
        && safe_remote_fallback_policy()
            .decide(AttemptFailureKind::PreCallEjected, 0)
            .should_try_next_candidate()
}

fn should_fallback_after_response(status: &Status) -> bool {
    status.code() == Code::ResourceExhausted
        && safe_remote_fallback_policy()
            .decide(AttemptFailureKind::PreWorkResourceExhausted, 0)
            .should_try_next_candidate()
}

fn safe_remote_fallback_policy() -> FallbackPolicy {
    FallbackPolicy::pre_work_only()
}

async fn record_endpoint_failure(
    remote_connections: &RemoteStageConnectionManager,
    target_name: &str,
    endpoint: SocketAddr,
    reason: &'static str,
) {
    remote_connections
        .record_failure(target_name, endpoint, reason)
        .await;
}

async fn record_attempt_outcome<T>(
    remote_connections: &RemoteStageConnectionManager,
    target_name: &str,
    endpoint: SocketAddr,
    result: Result<&RemoteStageBatch<T>, &Status>,
) {
    match result {
        Ok(batch) => match batch.outcome {
            RemoteStageRunOutcome::Ok if batch.failures.is_empty() => {
                remote_connections
                    .record_success(target_name, endpoint)
                    .await;
            }
            RemoteStageRunOutcome::Ok => {
                remote_connections
                    .record_failure(target_name, endpoint, "remote_item_error")
                    .await;
            }
            RemoteStageRunOutcome::Timeout => {
                remote_connections
                    .record_failure(target_name, endpoint, "timeout")
                    .await;
            }
            RemoteStageRunOutcome::TransportError => {
                remote_connections
                    .record_failure(target_name, endpoint, "transport_error")
                    .await;
            }
        },
        Err(_) => {
            remote_connections
                .record_failure(target_name, endpoint, "status")
                .await;
        }
    }
}

fn record_primary_endpoint(
    stage_id: &str,
    target_name: &str,
    endpoint: SocketAddr,
    item_count: usize,
) {
    let endpoint_label = endpoint.to_string();
    metrics::counter!(
        "cymbal_remote_stage_primary_endpoint_total",
        "stage" => stage_id.to_string(),
        "target" => target_name.to_string(),
        "endpoint" => endpoint_label.clone(),
    )
    .increment(1);
    tracing::debug!(
        stage_id,
        target = target_name,
        endpoint = %endpoint_label,
        items = item_count,
        "selected primary remote stage endpoint"
    );
}

fn record_fallback_attempt(
    stage_id: &str,
    target_name: &str,
    endpoint: SocketAddr,
    reason: &'static str,
    code: Option<Code>,
    item_count: usize,
) {
    let endpoint_label = endpoint.to_string();
    let code_label = code.map_or("none".to_string(), |code| format!("{code:?}"));
    metrics::counter!(
        "cymbal_remote_stage_fallback_attempts_total",
        "stage" => stage_id.to_string(),
        "target" => target_name.to_string(),
        "endpoint" => endpoint_label.clone(),
        "reason" => reason,
        "code" => code_label.clone(),
    )
    .increment(1);
    metrics::counter!(
        "cymbal_remote_stage_fallback_items_total",
        "stage" => stage_id.to_string(),
        "target" => target_name.to_string(),
        "endpoint" => endpoint_label.clone(),
        "reason" => reason,
        "code" => code_label.clone(),
    )
    .increment(item_count as u64);
    tracing::warn!(
        stage_id,
        target = target_name,
        endpoint = %endpoint_label,
        reason,
        code = %code_label,
        items = item_count,
        "trying remote stage fallback endpoint"
    );
}

fn record_fallback_success(
    stage_id: &str,
    target_name: &str,
    endpoint: SocketAddr,
    item_count: usize,
) {
    let endpoint_label = endpoint.to_string();
    metrics::counter!(
        "cymbal_remote_stage_fallback_success_total",
        "stage" => stage_id.to_string(),
        "target" => target_name.to_string(),
        "endpoint" => endpoint_label.clone(),
    )
    .increment(1);
    tracing::info!(
        stage_id,
        target = target_name,
        endpoint = %endpoint_label,
        items = item_count,
        "remote stage fallback succeeded"
    );
}

fn record_fallback_exhausted(
    stage_id: &str,
    target_name: &str,
    code: Code,
    reason: &str,
    item_count: usize,
) {
    let code_label = format!("{code:?}");
    metrics::counter!(
        "cymbal_remote_stage_fallback_exhausted_total",
        "stage" => stage_id.to_string(),
        "target" => target_name.to_string(),
        "code" => code_label.clone(),
    )
    .increment(1);
    metrics::counter!(
        "cymbal_remote_stage_fallback_exhausted_items_total",
        "stage" => stage_id.to_string(),
        "target" => target_name.to_string(),
        "code" => code_label.clone(),
    )
    .increment(item_count as u64);
    tracing::warn!(
        stage_id,
        target = target_name,
        code = %code_label,
        reason,
        items = item_count,
        "remote stage fallback exhausted"
    );
}

fn record_synthesized_retries(
    stage_id: &str,
    target_name: &str,
    reason: RemoteRetryReason,
    failures: &[RemoteStageItemFailure],
) {
    let retryable = failures.iter().filter(|failure| failure.retryable).count();
    record_remote_retries(stage_id, target_name, reason, retryable);
}

pub(crate) trait RemoteStageInput: serde::Serialize {
    fn stage_item_id(&self) -> &str;

    fn routing_key(&self, _stage_id: &str) -> RoutingKey {
        RoutingKey::new(self.stage_item_id().to_string())
    }
}

pub(crate) trait RemoteStageOutput {
    fn stage_item_id(&self) -> &str;
}

fn remote_stage_item<T>(
    item_id: &str,
    item_type: StageType,
    value: &T,
) -> Result<RemoteStageItem, Status>
where
    T: serde::Serialize,
{
    let payload = encode_json_payload(value).map_err(stage_error_to_status)?;
    Ok(RemoteStageItem::new(item_id, item_type, payload))
}

async fn collect_remote_stage_items<T>(
    output: StageBatchResult,
    expected_type: String,
    input_ids: Vec<String>,
    retryable_on_transient_failure: bool,
    stage_id: &str,
    target_name: &str,
) -> Result<RemoteStageBatch<T>, Status>
where
    T: serde::de::DeserializeOwned + RemoteStageOutput,
{
    let mut unresolved = input_ids.into_iter().collect::<HashSet<_>>();
    let mut items = Vec::new();
    let mut failures = Vec::new();
    let mut remote_item_retries = 0usize;

    for result in output.results {
        let item = decode_remote_stage_result::<T>(result, &expected_type)?;
        unresolved.remove(item.stage_item_id());
        items.push(item);
    }

    for error in output.errors {
        unresolved.remove(&error.item_id);
        if error.retryable {
            remote_item_retries += 1;
        }
        failures.push(RemoteStageItemFailure {
            item_id: error.item_id,
            message: error.message,
            retryable: error.retryable,
            retry_after_ms: None,
        });
    }

    if !unresolved.is_empty() {
        let omitted_failures = failures_for_item_ids(
            unresolved.into_iter().collect(),
            "remote stage response omitted item".to_string(),
            retryable_on_transient_failure,
        );
        remote_item_retries += omitted_failures
            .iter()
            .filter(|failure| failure.retryable)
            .count();
        failures.extend(omitted_failures);
    }

    record_remote_retries(
        stage_id,
        target_name,
        RemoteRetryReason::RemoteItemError,
        remote_item_retries,
    );

    tracing::debug!(
        decoded_items = items.len(),
        failures = failures.len(),
        "collected remote stage response"
    );
    Ok(RemoteStageBatch {
        items,
        failures,
        outcome: RemoteStageRunOutcome::Ok,
    })
}

fn decode_remote_stage_result<T>(item: StageItemResult, expected_type: &str) -> Result<T, Status>
where
    T: serde::de::DeserializeOwned,
{
    if item.r#type != expected_type {
        return Err(Status::internal(format!(
            "remote stage result {} has type {}, expected {}",
            item.item_id, item.r#type, expected_type
        )));
    }

    decode_json_payload(&item.payload).map_err(stage_error_to_status)
}

fn failures_for_item_ids(
    item_ids: Vec<String>,
    message: String,
    retryable: bool,
) -> Vec<RemoteStageItemFailure> {
    item_ids
        .into_iter()
        .map(|item_id| RemoteStageItemFailure {
            retry_after_ms: retryable.then(|| jittered_retry_after_ms(&item_id, &message)),
            item_id,
            message: message.clone(),
            retryable,
        })
        .collect()
}

async fn timeout_remote_stage<T, F>(
    future: F,
    stage_timeout: std::time::Duration,
    stage_id: &str,
    target_name: &str,
    input_ids: Vec<String>,
    retryable_on_transient_failure: bool,
) -> Result<RemoteStageAttemptResult<T>, Status>
where
    F: Future<Output = Result<RemoteStageAttemptResult<T>, Status>>,
{
    match tokio::time::timeout(stage_timeout, future).await {
        Ok(result) => result,
        Err(_) => {
            let failures = failures_for_item_ids(
                input_ids,
                format!("remote stage {stage_id} timed out"),
                retryable_on_transient_failure,
            );
            record_synthesized_retries(
                stage_id,
                target_name,
                RemoteRetryReason::Timeout,
                &failures,
            );
            Ok(RemoteStageAttemptResult::Completed(RemoteStageBatch {
                items: Vec::new(),
                failures,
                outcome: RemoteStageRunOutcome::Timeout,
            }))
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

    use cymbal_api::cymbal::v1::cymbal_stage_runtime_server::{
        CymbalStageRuntime, CymbalStageRuntimeServer,
    };
    use cymbal_api::cymbal::v1::{StageBatch, StageItemResult, StageLoad};
    use cymbal_core::{BatchContext, Metadata, StagePayload};
    use cymbal_domain::{EventOutcome, EventResult, InputEvent};
    use tokio::net::TcpListener;
    use tokio_stream::wrappers::TcpListenerStream;
    use tonic::transport::Server;
    use tonic::{Request, Response};

    use super::*;
    use crate::remote::{
        RemoteStageConnectionManager, RemoteStageConnectionOptions, RemoteStageTarget,
    };
    use cymbal_core::routing::{RemoteRoutingConfig, RoutingPolicy};

    #[derive(Debug, Clone)]
    struct FailingStageService {
        calls: Arc<AtomicUsize>,
    }

    #[derive(Debug, Clone)]
    struct StatusStageService {
        calls: Arc<AtomicUsize>,
        code: Code,
    }

    #[derive(Debug, Clone)]
    struct SuccessfulStageService {
        calls: Arc<AtomicUsize>,
    }

    #[derive(Debug, Clone)]
    struct LoadReportingStageService {
        calls: Arc<AtomicUsize>,
        load: StageLoad,
    }

    #[derive(Debug, Clone)]
    enum RecordingStageBehavior {
        Success,
        Status(Code),
        Sleep(Duration),
    }

    #[derive(Debug, Clone)]
    struct RecordingStageService {
        calls: Arc<AtomicUsize>,
        batches: Arc<Mutex<Vec<Vec<String>>>>,
        behavior: RecordingStageBehavior,
    }

    #[tonic::async_trait]
    impl CymbalStageRuntime for FailingStageService {
        async fn process_stage(
            &self,
            _request: Request<StageBatch>,
        ) -> Result<Response<StageBatchResult>, Status> {
            self.calls.fetch_add(1, Ordering::AcqRel);
            Err(Status::unavailable("remote stage unavailable"))
        }
    }

    #[tonic::async_trait]
    impl CymbalStageRuntime for StatusStageService {
        async fn process_stage(
            &self,
            _request: Request<StageBatch>,
        ) -> Result<Response<StageBatchResult>, Status> {
            self.calls.fetch_add(1, Ordering::AcqRel);
            Err(Status::new(self.code, "configured test status"))
        }
    }

    #[tonic::async_trait]
    impl CymbalStageRuntime for SuccessfulStageService {
        async fn process_stage(
            &self,
            request: Request<StageBatch>,
        ) -> Result<Response<StageBatchResult>, Status> {
            self.calls.fetch_add(1, Ordering::AcqRel);
            Ok(Response::new(StageBatchResult {
                results: event_result_items(request.into_inner()),
                errors: Vec::new(),
                load: None,
            }))
        }
    }

    #[tonic::async_trait]
    impl CymbalStageRuntime for LoadReportingStageService {
        async fn process_stage(
            &self,
            request: Request<StageBatch>,
        ) -> Result<Response<StageBatchResult>, Status> {
            self.calls.fetch_add(1, Ordering::AcqRel);
            Ok(Response::new(StageBatchResult {
                results: event_result_items(request.into_inner()),
                errors: Vec::new(),
                load: Some(self.load.clone()),
            }))
        }
    }

    #[tonic::async_trait]
    impl CymbalStageRuntime for RecordingStageService {
        async fn process_stage(
            &self,
            request: Request<StageBatch>,
        ) -> Result<Response<StageBatchResult>, Status> {
            self.calls.fetch_add(1, Ordering::AcqRel);
            let batch = request.into_inner();
            let item_ids = batch
                .items
                .iter()
                .map(|item| item.item_id.clone())
                .collect::<Vec<_>>();
            self.batches.lock().unwrap().push(item_ids);

            match self.behavior {
                RecordingStageBehavior::Success => Ok(Response::new(StageBatchResult {
                    results: event_result_items(batch),
                    errors: Vec::new(),
                    load: None,
                })),
                RecordingStageBehavior::Status(code) => {
                    Err(Status::new(code, "configured test status"))
                }
                RecordingStageBehavior::Sleep(duration) => {
                    tokio::time::sleep(duration).await;
                    Ok(Response::new(StageBatchResult {
                        results: event_result_items(batch),
                        errors: Vec::new(),
                        load: None,
                    }))
                }
            }
        }
    }

    fn event_result_items(batch: StageBatch) -> Vec<StageItemResult> {
        batch
            .items
            .into_iter()
            .map(|item| StageItemResult {
                item_id: item.item_id.clone(),
                r#type: EventResult::TYPE.to_string(),
                payload: serde_json::to_vec(&EventResult {
                    event_id: item.item_id,
                    outcome: EventOutcome::Next {
                        properties: None,
                        metadata: Metadata::new(),
                    },
                })
                .unwrap(),
            })
            .collect()
    }

    async fn start_failing_stage_server(calls: Arc<AtomicUsize>) -> std::net::SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let service = FailingStageService { calls };

        tokio::spawn(async move {
            Server::builder()
                .add_service(CymbalStageRuntimeServer::new(service))
                .serve_with_incoming(TcpListenerStream::new(listener))
                .await
                .unwrap();
        });

        addr
    }

    async fn start_status_stage_server(
        calls: Arc<AtomicUsize>,
        code: Code,
    ) -> std::net::SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let service = StatusStageService { calls, code };

        tokio::spawn(async move {
            Server::builder()
                .add_service(CymbalStageRuntimeServer::new(service))
                .serve_with_incoming(TcpListenerStream::new(listener))
                .await
                .unwrap();
        });

        addr
    }

    async fn start_successful_stage_server(calls: Arc<AtomicUsize>) -> std::net::SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let service = SuccessfulStageService { calls };

        tokio::spawn(async move {
            Server::builder()
                .add_service(CymbalStageRuntimeServer::new(service))
                .serve_with_incoming(TcpListenerStream::new(listener))
                .await
                .unwrap();
        });

        addr
    }

    async fn start_load_reporting_stage_server(
        calls: Arc<AtomicUsize>,
        load: StageLoad,
    ) -> std::net::SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let service = LoadReportingStageService { calls, load };

        tokio::spawn(async move {
            Server::builder()
                .add_service(CymbalStageRuntimeServer::new(service))
                .serve_with_incoming(TcpListenerStream::new(listener))
                .await
                .unwrap();
        });

        addr
    }

    async fn start_recording_stage_server(
        calls: Arc<AtomicUsize>,
        batches: Arc<Mutex<Vec<Vec<String>>>>,
        behavior: RecordingStageBehavior,
    ) -> std::net::SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let service = RecordingStageService {
            calls,
            batches,
            behavior,
        };

        tokio::spawn(async move {
            Server::builder()
                .add_service(CymbalStageRuntimeServer::new(service))
                .serve_with_incoming(TcpListenerStream::new(listener))
                .await
                .unwrap();
        });

        addr
    }

    fn context() -> BatchContext {
        BatchContext {
            batch_id: "batch-1".to_string(),
            metadata: Metadata::new(),
        }
    }

    fn input_event(event_id: &str) -> InputEvent {
        input_event_with_team(event_id, 2)
    }

    fn input_event_with_team(event_id: &str, team_id: i64) -> InputEvent {
        InputEvent {
            event_id: event_id.to_string(),
            team_id,
            properties: Default::default(),
        }
    }

    async fn team_id_that_routes_first(
        manager: &RemoteStageConnectionManager,
        target_name: &str,
        primary: std::net::SocketAddr,
    ) -> i64 {
        for team_id in 1..500 {
            let candidates = manager
                .candidate_endpoints(
                    target_name,
                    "resolution:v1",
                    &RoutingKey::team_id(team_id),
                    &RoutingPolicy::affinity_first(),
                )
                .await
                .unwrap();
            if candidates.first() == Some(&primary) {
                return team_id;
            }
        }

        panic!("could not find a routing key for primary endpoint {primary}");
    }

    fn recorded_batches(batches: &Arc<Mutex<Vec<Vec<String>>>>) -> Vec<Vec<String>> {
        batches.lock().unwrap().clone()
    }

    async fn record_endpoint_item_capacity(
        manager: &RemoteStageConnectionManager,
        target_name: &str,
        endpoint: std::net::SocketAddr,
        current: u64,
        max: u64,
    ) {
        manager
            .record_endpoint_load(
                target_name,
                endpoint,
                "resolution:v1",
                StageLoad {
                    current_in_flight_items: current,
                    max_in_flight_items: max,
                    ..Default::default()
                },
            )
            .await;
    }

    #[tokio::test]
    async fn event_level_affinity_sends_one_input_batch_to_different_pods() {
        let first_calls = Arc::new(AtomicUsize::new(0));
        let second_calls = Arc::new(AtomicUsize::new(0));
        let first_batches = Arc::new(Mutex::new(Vec::new()));
        let second_batches = Arc::new(Mutex::new(Vec::new()));
        let first_addr = start_recording_stage_server(
            first_calls.clone(),
            first_batches.clone(),
            RecordingStageBehavior::Success,
        )
        .await;
        let second_addr = start_recording_stage_server(
            second_calls.clone(),
            second_batches.clone(),
            RecordingStageBehavior::Success,
        )
        .await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", first_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", second_addr.port()),
            ])
            .await
            .unwrap();
        let first_team = team_id_that_routes_first(&manager, "resolution", first_addr).await;
        let second_team = team_id_that_routes_first(&manager, "resolution", second_addr).await;

        let batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![
                input_event_with_team("event-first", first_team),
                input_event_with_team("event-second", second_team),
            ],
        )
        .await
        .unwrap();

        assert_eq!(batch.outcome, RemoteStageRunOutcome::Ok);
        assert!(batch.failures.is_empty());
        assert_eq!(recorded_batches(&first_batches), vec![vec!["event-first"]]);
        assert_eq!(
            recorded_batches(&second_batches),
            vec![vec!["event-second"]]
        );
    }

    #[tokio::test]
    async fn two_pods_increase_aggregate_accepted_event_capacity() {
        let first_calls = Arc::new(AtomicUsize::new(0));
        let second_calls = Arc::new(AtomicUsize::new(0));
        let first_batches = Arc::new(Mutex::new(Vec::new()));
        let second_batches = Arc::new(Mutex::new(Vec::new()));
        let first_addr = start_recording_stage_server(
            first_calls.clone(),
            first_batches.clone(),
            RecordingStageBehavior::Success,
        )
        .await;
        let second_addr = start_recording_stage_server(
            second_calls.clone(),
            second_batches.clone(),
            RecordingStageBehavior::Success,
        )
        .await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", first_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", second_addr.port()),
            ])
            .await
            .unwrap();
        record_endpoint_item_capacity(&manager, "resolution", first_addr, 0, 2).await;
        record_endpoint_item_capacity(&manager, "resolution", second_addr, 0, 2).await;
        let team_id = team_id_that_routes_first(&manager, "resolution", first_addr).await;

        let batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![
                input_event_with_team("event-1", team_id),
                input_event_with_team("event-2", team_id),
                input_event_with_team("event-3", team_id),
                input_event_with_team("event-4", team_id),
            ],
        )
        .await
        .unwrap();

        assert_eq!(batch.outcome, RemoteStageRunOutcome::Ok);
        assert!(batch.failures.is_empty());
        assert_eq!(batch.items.len(), 4);
        assert_eq!(
            recorded_batches(&first_batches),
            vec![vec!["event-1", "event-2"]]
        );
        assert_eq!(
            recorded_batches(&second_batches),
            vec![vec!["event-3", "event-4"]]
        );
    }

    #[tokio::test]
    async fn affinity_primary_capacity_overflow_uses_fallback_pod() {
        let primary_calls = Arc::new(AtomicUsize::new(0));
        let fallback_calls = Arc::new(AtomicUsize::new(0));
        let primary_batches = Arc::new(Mutex::new(Vec::new()));
        let fallback_batches = Arc::new(Mutex::new(Vec::new()));
        let primary_addr = start_recording_stage_server(
            primary_calls.clone(),
            primary_batches.clone(),
            RecordingStageBehavior::Success,
        )
        .await;
        let fallback_addr = start_recording_stage_server(
            fallback_calls.clone(),
            fallback_batches.clone(),
            RecordingStageBehavior::Success,
        )
        .await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", primary_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", fallback_addr.port()),
            ])
            .await
            .unwrap();
        record_endpoint_item_capacity(&manager, "resolution", primary_addr, 1, 2).await;
        record_endpoint_item_capacity(&manager, "resolution", fallback_addr, 0, 10).await;
        let team_id = team_id_that_routes_first(&manager, "resolution", primary_addr).await;

        let batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![
                input_event_with_team("event-1", team_id),
                input_event_with_team("event-2", team_id),
                input_event_with_team("event-3", team_id),
            ],
        )
        .await
        .unwrap();

        assert_eq!(batch.outcome, RemoteStageRunOutcome::Ok);
        assert!(batch.failures.is_empty());
        assert_eq!(recorded_batches(&primary_batches), vec![vec!["event-1"]]);
        assert_eq!(
            recorded_batches(&fallback_batches),
            vec![vec!["event-2", "event-3"]]
        );
    }

    #[tokio::test]
    async fn resource_exhausted_retries_only_rejected_sub_batch_items() {
        let exhausted_calls = Arc::new(AtomicUsize::new(0));
        let fallback_calls = Arc::new(AtomicUsize::new(0));
        let exhausted_batches = Arc::new(Mutex::new(Vec::new()));
        let fallback_batches = Arc::new(Mutex::new(Vec::new()));
        let exhausted_addr = start_recording_stage_server(
            exhausted_calls.clone(),
            exhausted_batches.clone(),
            RecordingStageBehavior::Status(Code::ResourceExhausted),
        )
        .await;
        let fallback_addr = start_recording_stage_server(
            fallback_calls.clone(),
            fallback_batches.clone(),
            RecordingStageBehavior::Success,
        )
        .await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", exhausted_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", fallback_addr.port()),
            ])
            .await
            .unwrap();
        record_endpoint_item_capacity(&manager, "resolution", exhausted_addr, 0, 2).await;
        record_endpoint_item_capacity(&manager, "resolution", fallback_addr, 0, 2).await;
        let team_id = team_id_that_routes_first(&manager, "resolution", exhausted_addr).await;

        let batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![
                input_event_with_team("event-1", team_id),
                input_event_with_team("event-2", team_id),
                input_event_with_team("event-3", team_id),
                input_event_with_team("event-4", team_id),
            ],
        )
        .await
        .unwrap();

        assert_eq!(batch.outcome, RemoteStageRunOutcome::Ok);
        assert!(batch.failures.is_empty());
        assert_eq!(
            recorded_batches(&exhausted_batches),
            vec![vec!["event-1", "event-2"]]
        );
        assert_eq!(
            recorded_batches(&fallback_batches),
            vec![vec!["event-3", "event-4"], vec!["event-1", "event-2"]]
        );
    }

    #[tokio::test]
    async fn strict_affinity_overflow_is_unroutable_instead_of_fallback() {
        let primary_calls = Arc::new(AtomicUsize::new(0));
        let fallback_calls = Arc::new(AtomicUsize::new(0));
        let primary_batches = Arc::new(Mutex::new(Vec::new()));
        let fallback_batches = Arc::new(Mutex::new(Vec::new()));
        let primary_addr = start_recording_stage_server(
            primary_calls.clone(),
            primary_batches.clone(),
            RecordingStageBehavior::Success,
        )
        .await;
        let fallback_addr = start_recording_stage_server(
            fallback_calls.clone(),
            fallback_batches.clone(),
            RecordingStageBehavior::Success,
        )
        .await;
        let manager = RemoteStageConnectionManager::with_options_and_routing(
            RemoteStageConnectionOptions::default(),
            RemoteRoutingConfig::new(RoutingPolicy::strict_affinity()),
        );
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", primary_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", fallback_addr.port()),
            ])
            .await
            .unwrap();
        record_endpoint_item_capacity(&manager, "resolution", primary_addr, 0, 1).await;
        record_endpoint_item_capacity(&manager, "resolution", fallback_addr, 0, 10).await;
        let team_id = team_id_that_routes_first(&manager, "resolution", primary_addr).await;

        let batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![
                input_event_with_team("event-1", team_id),
                input_event_with_team("event-2", team_id),
                input_event_with_team("event-3", team_id),
            ],
        )
        .await
        .unwrap();

        assert_eq!(batch.outcome, RemoteStageRunOutcome::TransportError);
        assert_eq!(batch.items.len(), 1);
        assert_eq!(batch.failures.len(), 2);
        assert!(batch.failures.iter().all(|failure| failure.retryable));
        assert_eq!(recorded_batches(&primary_batches), vec![vec!["event-1"]]);
        assert!(recorded_batches(&fallback_batches).is_empty());
        assert_eq!(fallback_calls.load(Ordering::Acquire), 0);
    }

    #[tokio::test]
    async fn unsafe_timeout_does_not_fallback_to_next_endpoint() {
        let slow_calls = Arc::new(AtomicUsize::new(0));
        let fallback_calls = Arc::new(AtomicUsize::new(0));
        let slow_batches = Arc::new(Mutex::new(Vec::new()));
        let fallback_batches = Arc::new(Mutex::new(Vec::new()));
        let slow_addr = start_recording_stage_server(
            slow_calls.clone(),
            slow_batches.clone(),
            RecordingStageBehavior::Sleep(Duration::from_millis(100)),
        )
        .await;
        let fallback_addr = start_recording_stage_server(
            fallback_calls.clone(),
            fallback_batches.clone(),
            RecordingStageBehavior::Success,
        )
        .await;
        let options = RemoteStageConnectionOptions {
            stage_timeout: Some(Duration::from_millis(10)),
            ..Default::default()
        };
        let manager = RemoteStageConnectionManager::with_options(options);
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", slow_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", fallback_addr.port()),
            ])
            .await
            .unwrap();
        let team_id = team_id_that_routes_first(&manager, "resolution", slow_addr).await;

        let batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![input_event_with_team("event-1", team_id)],
        )
        .await
        .unwrap();

        assert_eq!(batch.outcome, RemoteStageRunOutcome::Timeout);
        assert_eq!(batch.failures.len(), 1);
        assert!(batch.failures[0].message.contains("timed out"));
        assert_eq!(slow_calls.load(Ordering::Acquire), 1);
        assert_eq!(fallback_calls.load(Ordering::Acquire), 0);
        assert!(recorded_batches(&fallback_batches).is_empty());
    }

    #[tokio::test]
    async fn remote_stage_errors_open_circuit_and_retry_with_backoff() {
        let calls = Arc::new(AtomicUsize::new(0));
        let addr = start_failing_stage_server(calls.clone()).await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_target(&RemoteStageTarget::new(
                "resolution",
                "127.0.0.1",
                addr.port(),
            ))
            .await
            .unwrap();

        for index in 0..5 {
            let batch = process_remote_stage::<InputEvent, EventResult>(
                RemoteStageCall {
                    remote_connections: Some(&manager),
                    target_name: "resolution",
                    stage_id: "resolution:v1",
                    input_type: InputEvent::TYPE,
                    output_type: EventResult::TYPE,
                    retryable_on_transient_failure: true,
                },
                context(),
                vec![input_event(&format!("event-{index}"))],
            )
            .await
            .unwrap();

            assert_eq!(batch.outcome, RemoteStageRunOutcome::TransportError);
            assert_eq!(batch.failures.len(), 1);
            assert!(batch.failures[0].retryable);
            assert!(batch.failures[0].retry_after_ms.is_some());
        }

        assert_eq!(calls.load(Ordering::Acquire), 5);

        let batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![input_event("after-open")],
        )
        .await
        .unwrap();

        assert_eq!(calls.load(Ordering::Acquire), 5);
        assert_eq!(batch.outcome, RemoteStageRunOutcome::TransportError);
        assert_eq!(batch.failures.len(), 1);
        assert!(batch.failures[0].message.contains("circuit open"));
        assert!(batch.failures[0].retry_after_ms.is_some());
    }

    #[tokio::test]
    async fn resource_exhausted_primary_falls_back_to_next_endpoint() {
        let exhausted_calls = Arc::new(AtomicUsize::new(0));
        let success_calls = Arc::new(AtomicUsize::new(0));
        let exhausted_addr =
            start_status_stage_server(exhausted_calls.clone(), Code::ResourceExhausted).await;
        let success_addr = start_successful_stage_server(success_calls.clone()).await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", exhausted_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", success_addr.port()),
            ])
            .await
            .unwrap();
        let team_id = team_id_that_routes_first(&manager, "resolution", exhausted_addr).await;

        let batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![
                input_event_with_team("event-1", team_id),
                input_event_with_team("event-2", team_id),
                input_event_with_team("event-3", team_id),
            ],
        )
        .await
        .unwrap();

        assert_eq!(exhausted_calls.load(Ordering::Acquire), 1);
        assert_eq!(success_calls.load(Ordering::Acquire), 1);
        assert_eq!(batch.outcome, RemoteStageRunOutcome::Ok);
        assert!(batch.failures.is_empty());
        assert_eq!(
            batch
                .items
                .iter()
                .map(|item| item.event_id.as_str())
                .collect::<Vec<_>>(),
            vec!["event-1", "event-2", "event-3"]
        );
    }

    #[tokio::test]
    async fn pre_call_circuit_open_primary_falls_back_to_next_endpoint() {
        let primary_calls = Arc::new(AtomicUsize::new(0));
        let fallback_calls = Arc::new(AtomicUsize::new(0));
        let primary_addr = start_successful_stage_server(primary_calls.clone()).await;
        let fallback_addr = start_successful_stage_server(fallback_calls.clone()).await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", primary_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", fallback_addr.port()),
            ])
            .await
            .unwrap();
        let team_id = team_id_that_routes_first(&manager, "resolution", primary_addr).await;
        for _ in 0..5 {
            manager
                .record_failure("resolution", primary_addr, "test_circuit_open")
                .await;
        }

        let batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![input_event_with_team("event-1", team_id)],
        )
        .await
        .unwrap();

        assert_eq!(primary_calls.load(Ordering::Acquire), 0);
        assert_eq!(fallback_calls.load(Ordering::Acquire), 1);
        assert_eq!(batch.outcome, RemoteStageRunOutcome::Ok);
        assert!(batch.failures.is_empty());
        assert_eq!(batch.items.len(), 1);
        assert_eq!(batch.items[0].event_id, "event-1");
    }

    #[tokio::test]
    async fn observed_saturated_load_demotes_primary_on_next_call() {
        let primary_calls = Arc::new(AtomicUsize::new(0));
        let fallback_calls = Arc::new(AtomicUsize::new(0));
        let primary_addr = start_load_reporting_stage_server(
            primary_calls.clone(),
            StageLoad {
                current_in_flight_stage_batches: 8,
                max_in_flight_stage_batches: 8,
                overloaded: true,
                ..Default::default()
            },
        )
        .await;
        let fallback_addr = start_successful_stage_server(fallback_calls.clone()).await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", primary_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", fallback_addr.port()),
            ])
            .await
            .unwrap();
        let team_id = team_id_that_routes_first(&manager, "resolution", primary_addr).await;

        let first_batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![input_event_with_team("event-1", team_id)],
        )
        .await
        .unwrap();
        assert_eq!(first_batch.outcome, RemoteStageRunOutcome::Ok);
        assert_eq!(primary_calls.load(Ordering::Acquire), 1);

        let second_batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![input_event_with_team("event-2", team_id)],
        )
        .await
        .unwrap();

        assert_eq!(second_batch.outcome, RemoteStageRunOutcome::Ok);
        assert_eq!(primary_calls.load(Ordering::Acquire), 1);
        assert_eq!(fallback_calls.load(Ordering::Acquire), 1);
    }

    #[tokio::test]
    async fn unavailable_after_request_does_not_fallback() {
        let unavailable_calls = Arc::new(AtomicUsize::new(0));
        let success_calls = Arc::new(AtomicUsize::new(0));
        let unavailable_addr =
            start_status_stage_server(unavailable_calls.clone(), Code::Unavailable).await;
        let success_addr = start_successful_stage_server(success_calls.clone()).await;
        let manager = RemoteStageConnectionManager::new();
        manager
            .refresh_targets(&[
                RemoteStageTarget::new("resolution", "127.0.0.1", unavailable_addr.port()),
                RemoteStageTarget::new("resolution", "127.0.0.1", success_addr.port()),
            ])
            .await
            .unwrap();
        let team_id = team_id_that_routes_first(&manager, "resolution", unavailable_addr).await;

        let batch = process_remote_stage::<InputEvent, EventResult>(
            RemoteStageCall {
                remote_connections: Some(&manager),
                target_name: "resolution",
                stage_id: "resolution:v1",
                input_type: InputEvent::TYPE,
                output_type: EventResult::TYPE,
                retryable_on_transient_failure: true,
            },
            context(),
            vec![input_event_with_team("event-1", team_id)],
        )
        .await
        .unwrap();

        assert_eq!(unavailable_calls.load(Ordering::Acquire), 1);
        assert_eq!(success_calls.load(Ordering::Acquire), 0);
        assert_eq!(batch.outcome, RemoteStageRunOutcome::TransportError);
        assert_eq!(batch.failures.len(), 1);
        assert!(batch.failures[0]
            .message
            .contains("remote stage request failed before response"));
        assert!(batch.failures[0].retryable);
    }
}
