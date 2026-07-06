//! Per-exception reroute layer: submit one logical item to the selected
//! endpoint mux, classify its terminal outcome, and retry/reroute only that
//! item until its shared deadline or retry budget is exhausted.

use std::net::SocketAddr;
use std::time::{Duration, Instant};

use rand::Rng;
use tokio::sync::OwnedSemaphorePermit;
use tracing::warn;

use cymbal_proto::cymbal::resolution::v1::{resolve_outcome, ErrorKind, ResolveOutcome};
use tonic::Status;

use crate::error::UnhandledError;
use crate::metric_consts::{
    REMOTE_RESOLUTION_ERROR_KINDS, REMOTE_RESOLUTION_LATENCY,
    REMOTE_RESOLUTION_OVERLOAD_ESCALATIONS, REMOTE_RESOLUTION_REQUESTS,
    REMOTE_RESOLUTION_REROUTE_DEPTH,
};
use crate::types::Exception;

use crate::stages::resolution::remote::{client::RemoteCallError, mux::ResolveItemSession};

use super::{RemoteResolutionContext, RemoteWorkItem, ResolvedRemoteItem};

pub(super) async fn resolve_work_item(
    ctx: &RemoteResolutionContext,
    work_item: RemoteWorkItem,
    deadline: Instant,
) -> Result<ResolvedRemoteItem, UnhandledError> {
    let max_attempts = ctx.config.max_retries.saturating_add(1);
    let mut excluded_endpoints: Vec<SocketAddr> = Vec::new();
    let mut last_error: Option<String> = None;
    let mut attempts_used = 0u32;
    let mut routing_permit = None;

    for attempt in 0..max_attempts {
        attempts_used = attempt + 1;
        if routing_permit.is_none() {
            routing_permit = Some(acquire_routing_permit(ctx).await?);
        }
        let remaining = remaining_deadline(deadline)?;
        let handle = match ctx
            .pool
            .select_for_key(&work_item.routing_key, &excluded_endpoints)
            .await
        {
            Ok(handle) => handle,
            Err(err) => {
                let reason = match &err {
                    crate::stages::resolution::remote::pool::EndpointPoolError::Empty(reason) => {
                        reason.as_metric_tag()
                    }
                    _ => "unknown",
                };
                metrics::counter!(
                    REMOTE_RESOLUTION_REQUESTS,
                    "outcome" => "pool_empty",
                    "reason" => reason,
                )
                .increment(1);
                last_error = Some(format!("pool unavailable: {err}"));
                if attempt + 1 < max_attempts {
                    sleep_with_deadline(generic_retry_backoff_for(ctx, attempt, None), deadline)
                        .await?;
                }
                continue;
            }
        };

        let endpoint = handle.addr;
        let start = Instant::now();
        let permit = routing_permit
            .take()
            .expect("routing permit must be acquired before selecting an endpoint");
        let session = handle.mux.submit_session(work_item.to_item(remaining));
        let outcome = wait_for_terminal_or_acceptance(session, remaining, permit).await;
        let elapsed_ms = start.elapsed().as_millis() as f64;
        drop(handle);

        let outcomes = match outcome {
            Ok((outcome, permit)) => {
                routing_permit = permit;
                vec![outcome]
            }
            Err((err, permit)) if err.is_retryable() => {
                routing_permit = permit;
                metrics::counter!(
                    REMOTE_RESOLUTION_REQUESTS,
                    "outcome" => "transport_retry",
                    "reason" => err.reason_tag(),
                )
                .increment(1);
                warn!(
                    endpoint = %endpoint,
                    token = work_item.token,
                    attempt,
                    error = %err,
                    reason = err.reason_tag(),
                    "remote resolution transport-level retry for item"
                );
                excluded_endpoints.push(endpoint);
                last_error = Some(err.to_string());
                if attempt + 1 < max_attempts {
                    sleep_with_deadline(generic_retry_backoff_for(ctx, attempt, None), deadline)
                        .await?;
                }
                continue;
            }
            Err((err, _permit)) => {
                metrics::counter!(
                    REMOTE_RESOLUTION_REQUESTS,
                    "outcome" => "terminal",
                    "reason" => err.reason_tag(),
                )
                .increment(1);
                record_reroute_depth("terminal", attempts_used);
                return Err(UnhandledError::Other(format!(
                    "remote resolution failed terminally for item {}: {err}",
                    work_item.token
                )));
            }
        };

        metrics::histogram!(REMOTE_RESOLUTION_LATENCY).record(elapsed_ms);
        let Some(outcome) = single_outcome(work_item.token, outcomes)? else {
            metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "missing_items")
                .increment(1);
            last_error = Some(format!(
                "missing item outcome from {endpoint} for token {}",
                work_item.token
            ));
            if attempt + 1 < max_attempts {
                sleep_with_deadline(generic_retry_backoff_for(ctx, attempt, None), deadline)
                    .await?;
            }
            continue;
        };

        let decision = match classify_outcome(&work_item, outcome) {
            Ok(decision) => decision,
            Err(err) => {
                record_reroute_depth("terminal_item", attempts_used);
                return Err(err);
            }
        };

        match decision {
            ItemDecision::Done(exception) => {
                metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "ok").increment(1);
                record_reroute_depth("ok", attempts_used);
                return Ok(ResolvedRemoteItem {
                    event_slot: work_item.event_slot,
                    exception_slot: work_item.exception_slot,
                    exception,
                });
            }
            ItemDecision::Overloaded(message) => {
                metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "overloaded_item")
                    .increment(1);
                metrics::counter!(REMOTE_RESOLUTION_OVERLOAD_ESCALATIONS).increment(1);
                warn!(
                    endpoint = %endpoint,
                    token = work_item.token,
                    attempt,
                    "remote resolution returned item overload; rerouting with overload policy"
                );
                ctx.pool.eject_overloaded(endpoint).await;
                excluded_endpoints.push(endpoint);
                last_error = Some(format!(
                    "per-item Overloaded outcome from {endpoint}: {message}"
                ));
                if attempt + 1 < max_attempts {
                    sleep_with_deadline(overload_backoff_for(ctx, attempt), deadline).await?;
                }
            }
            ItemDecision::Retry {
                message,
                retry_after,
            } => {
                metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "retryable_item")
                    .increment(1);
                warn!(
                    endpoint = %endpoint,
                    token = work_item.token,
                    attempt,
                    "remote resolution returned item retry; rerouting"
                );
                excluded_endpoints.push(endpoint);
                last_error = Some(format!("per-item Retry outcome from {endpoint}: {message}"));
                if attempt + 1 < max_attempts {
                    sleep_with_deadline(
                        generic_retry_backoff_for(ctx, attempt, retry_after),
                        deadline,
                    )
                    .await?;
                }
            }
        }
    }

    metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "exhausted").increment(1);
    record_reroute_depth("exhausted", attempts_used);
    Err(UnhandledError::Other(format!(
        "remote resolution exhausted retries for item {} ({} attempt(s)): {}",
        work_item.token,
        max_attempts,
        last_error.unwrap_or_else(|| "no recorded cause".to_string()),
    )))
}

async fn wait_for_terminal_or_acceptance(
    mut session: ResolveItemSession,
    deadline: Duration,
    permit: OwnedSemaphorePermit,
) -> Result<
    (ResolveOutcome, Option<OwnedSemaphorePermit>),
    (RemoteCallError, Option<OwnedSemaphorePermit>),
> {
    let mut permit = Some(permit);
    let sleep = tokio::time::sleep(deadline);
    tokio::pin!(sleep);

    loop {
        tokio::select! {
            outcome = session.outcomes.recv() => {
                let Some(outcome) = outcome else {
                    return Err((RemoteCallError::Retryable(Status::unavailable("remote resolution session was dropped")), permit));
                };
                let outcome = match outcome {
                    Ok(outcome) => outcome,
                    Err(err) => return Err((err, permit)),
                };
                if matches!(outcome.result, Some(resolve_outcome::Result::Accepted(_))) {
                    drop(permit.take());
                    continue;
                }
                return Ok((outcome, permit));
            }
            _ = &mut sleep => {
                session.cancel();
                return Err((RemoteCallError::Deadline(deadline), permit));
            }
        }
    }
}

fn single_outcome(
    token: u64,
    outcomes: Vec<ResolveOutcome>,
) -> Result<Option<ResolveOutcome>, UnhandledError> {
    let mut matching = None;
    for outcome in outcomes {
        if outcome.id != token {
            warn!(
                token,
                outcome_id = outcome.id,
                "remote resolution outcome id did not match submitted item; ignoring outcome"
            );
            continue;
        }
        if matching.replace(outcome).is_some() {
            return Err(UnhandledError::Other(format!(
                "remote resolution returned duplicate outcome for item {token}"
            )));
        }
    }
    Ok(matching)
}

#[derive(Debug)]
enum ItemDecision {
    Done(Exception),
    Overloaded(String),
    Retry {
        message: String,
        retry_after: Option<Duration>,
    },
}

fn classify_outcome(
    work_item: &RemoteWorkItem,
    outcome: ResolveOutcome,
) -> Result<ItemDecision, UnhandledError> {
    let Some(result) = outcome.result else {
        return Err(terminal_item_error(
            work_item.token,
            "remote resolution outcome had no result".to_string(),
        ));
    };

    match result {
        resolve_outcome::Result::Done(done) => {
            let exception = serde_json::from_slice::<Exception>(&done.resolved_exception_json)
                .map_err(|err| {
                    terminal_item_error(
                        work_item.token,
                        format!("invalid_done_payload: failed to parse resolved exception: {err}"),
                    )
                })?;
            Ok(ItemDecision::Done(exception))
        }
        resolve_outcome::Result::Retry(retry) => {
            let retry_after = (retry.retry_after_ms > 0)
                .then(|| Duration::from_millis(retry.retry_after_ms as u64));
            Ok(ItemDecision::Retry {
                message: retry.message,
                retry_after,
            })
        }
        resolve_outcome::Result::Error(err) => {
            let kind = ErrorKind::try_from(err.kind).unwrap_or(ErrorKind::Unspecified);
            metrics::counter!(REMOTE_RESOLUTION_ERROR_KINDS, "kind" => kind.metric_label())
                .increment(1);
            match kind {
                ErrorKind::Overloaded => Ok(ItemDecision::Overloaded(err.message)),
                ErrorKind::Poison => Err(terminal_item_error(
                    work_item.token,
                    format!(
                        "remote resolution returned poison item; failing batch under all-or-nothing policy until DLQ plumbing is added: {}",
                        err.message
                    ),
                )),
                ErrorKind::InvalidPayload | ErrorKind::Unhandled => Err(terminal_item_error(
                    work_item.token,
                    format!(
                        "remote resolution returned terminal item error {}: {}",
                        kind.as_str_name(),
                        err.message
                    ),
                )),
                ErrorKind::Unspecified => Err(terminal_item_error(
                    work_item.token,
                    format!(
                        "remote resolution returned unspecified item error: {}",
                        err.message
                    ),
                )),
            }
        }
        resolve_outcome::Result::Accepted(_) => Err(terminal_item_error(
            work_item.token,
            "remote resolution returned accepted without a terminal outcome".to_string(),
        )),
    }
}

fn terminal_item_error(token: u64, message: String) -> UnhandledError {
    metrics::counter!(REMOTE_RESOLUTION_REQUESTS, "outcome" => "items_failed").increment(1);
    UnhandledError::Other(format!(
        "remote resolution item {token} failed terminally; failing batch under all-or-nothing rollout policy ({message})"
    ))
}

async fn acquire_routing_permit(
    ctx: &RemoteResolutionContext,
) -> Result<OwnedSemaphorePermit, UnhandledError> {
    ctx.routing_semaphore
        .clone()
        .acquire_owned()
        .await
        .map_err(|_| {
            UnhandledError::Other("remote resolution routing semaphore closed".to_string())
        })
}

fn remaining_deadline(deadline: Instant) -> Result<Duration, UnhandledError> {
    deadline
        .checked_duration_since(Instant::now())
        .ok_or_else(|| {
            UnhandledError::Other(
                "remote resolution item deadline elapsed before completion".to_string(),
            )
        })
}

async fn sleep_with_deadline(backoff: Duration, deadline: Instant) -> Result<(), UnhandledError> {
    let remaining = remaining_deadline(deadline)?;
    tokio::time::sleep(backoff.min(remaining)).await;
    Ok(())
}

/// Exponential backoff with jitter for the n-th retry (0-indexed). Each step
/// doubles the base, capped at `retry_max_backoff`; up to ~50% random jitter
/// is added so a fleet of cymbal pods doesn't synchronize retries.
fn generic_retry_backoff_for(
    ctx: &RemoteResolutionContext,
    retry_index: u32,
    retry_after: Option<Duration>,
) -> Duration {
    let computed = jittered_backoff(ctx, retry_index);
    retry_after
        .map(|hint| hint.max(computed).min(ctx.config.retry_max_backoff))
        .unwrap_or(computed)
}

fn overload_backoff_for(ctx: &RemoteResolutionContext, retry_index: u32) -> Duration {
    jittered_backoff(ctx, retry_index)
}

fn jittered_backoff(ctx: &RemoteResolutionContext, retry_index: u32) -> Duration {
    let base_ms = ctx.config.retry_backoff.as_millis() as u64;
    let cap_ms = ctx.config.retry_max_backoff.as_millis() as u64;
    let exp = retry_index.min(16);
    let scaled = base_ms.saturating_mul(1u64 << exp).min(cap_ms);
    let jitter = if scaled == 0 {
        0
    } else {
        rand::thread_rng().gen_range(0..=scaled / 2)
    };
    Duration::from_millis(scaled.saturating_add(jitter).min(cap_ms))
}

fn record_reroute_depth(outcome: &'static str, attempts_used: u32) {
    metrics::histogram!(REMOTE_RESOLUTION_REROUTE_DEPTH, "outcome" => outcome)
        .record(attempts_used.saturating_sub(1) as f64);
}

#[cfg(test)]
mod tests {
    use cymbal_proto::cymbal::resolution::v1::{Done, Error, Retry};

    use super::*;

    #[test]
    fn classify_outcome_parses_done_exception() {
        let work_item = work_item(7);
        let outcome = ResolveOutcome {
            id: 7,
            result: Some(resolve_outcome::Result::Done(Done {
                resolved_exception_json: serde_json::to_vec(&exception("Resolved"))
                    .expect("valid exception"),
            })),
        };

        let decision = classify_outcome(&work_item, outcome).expect("done outcome");
        assert!(matches!(decision, ItemDecision::Done(exc) if exc.exception_type == "Resolved"));
    }

    #[test]
    fn classify_outcome_reroutes_overload() {
        let work_item = work_item(7);
        let outcome = error_outcome(ErrorKind::Overloaded, "busy");
        let decision = classify_outcome(&work_item, outcome).expect("overload reroutes");
        assert!(matches!(decision, ItemDecision::Overloaded(message) if message == "busy"));
    }

    #[test]
    fn classify_outcome_reroutes_retry_with_hint() {
        let work_item = work_item(7);
        let outcome = ResolveOutcome {
            id: 7,
            result: Some(resolve_outcome::Result::Retry(Retry {
                code: "transient".to_string(),
                message: "try again".to_string(),
                retry_after_ms: 25,
            })),
        };
        let decision = classify_outcome(&work_item, outcome).expect("retry reroutes");
        assert!(matches!(
            decision,
            ItemDecision::Retry { retry_after: Some(duration), .. } if duration == Duration::from_millis(25)
        ));
    }

    #[test]
    fn classify_outcome_treats_poison_as_terminal_all_or_nothing() {
        let work_item = work_item(7);
        let err = classify_outcome(&work_item, error_outcome(ErrorKind::Poison, "bad symbols"))
            .unwrap_err();
        assert!(err.to_string().contains("DLQ plumbing"));
        assert!(err.to_string().contains("all-or-nothing"));
    }

    #[test]
    fn classify_outcome_treats_invalid_payload_and_unhandled_as_terminal() {
        let work_item = work_item(7);
        for kind in [ErrorKind::InvalidPayload, ErrorKind::Unhandled] {
            let err = classify_outcome(&work_item, error_outcome(kind, "boom")).unwrap_err();
            assert!(err.to_string().contains(kind.as_str_name()));
            assert!(err.to_string().contains("failing batch"));
        }
    }

    #[test]
    fn single_outcome_ignores_unrelated_ids() {
        let outcome = ResolveOutcome {
            id: 10,
            result: None,
        };
        assert!(single_outcome(7, vec![outcome]).unwrap().is_none());
    }

    fn error_outcome(kind: ErrorKind, message: &str) -> ResolveOutcome {
        ResolveOutcome {
            id: 7,
            result: Some(resolve_outcome::Result::Error(Error {
                kind: kind as i32,
                message: message.to_string(),
                details_json: Vec::new(),
            })),
        }
    }

    fn work_item(token: u64) -> RemoteWorkItem {
        RemoteWorkItem {
            token,
            routing_key: "team:1".to_string(),
            event_slot: 0,
            exception_slot: 0,
            item: cymbal_proto::cymbal::resolution::v1::ResolveItem {
                id: token,
                team_id: 1,
                exception_json: Vec::new(),
                metadata: Vec::new(),
                deadline_ms: 0,
            },
        }
    }

    fn exception(exception_type: &str) -> Exception {
        Exception {
            exception_id: None,
            exception_type: exception_type.to_string(),
            exception_message: "boom".to_string(),
            mechanism: None,
            module: None,
            thread_id: None,
            stack: None,
        }
    }
}
