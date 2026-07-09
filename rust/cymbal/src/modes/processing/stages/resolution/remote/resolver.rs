use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use cymbal_proto::cymbal::resolution::v1::ResolveItem;
use futures::future::join_all;
use tokio::sync::Semaphore;

use crate::{
    error::UnhandledError,
    stages::{
        pipeline::ExceptionEventPipelineItem,
        resolution::{
            exception::ExceptionResolver, frame::FrameResolver, remote::pool::EndpointPool,
            ResolutionStage,
        },
    },
    types::{batch::Batch, exception_properties::ExceptionProperties, Exception, ExceptionList},
};

use super::config::RemoteResolutionConfig;

mod chunk;
mod partition;
mod retry;

use chunk::routing_keys_for_event;
use partition::partition_batch;
use retry::resolve_work_item;

/// Context handed to the remote orchestration layer. Cheap to clone because
/// both the pool handle and config are `Arc`/`Clone`-friendly.
#[derive(Clone)]
pub struct RemoteResolutionContext {
    pub pool: Arc<EndpointPool>,
    pub config: RemoteResolutionConfig,
    pub routing_semaphore: Arc<Semaphore>,
}

impl RemoteResolutionContext {
    pub fn new(pool: Arc<EndpointPool>, config: RemoteResolutionConfig) -> Self {
        let routing_acceptance_concurrency = config.routing_acceptance_concurrency;
        Self {
            pool,
            config,
            routing_semaphore: Arc::new(Semaphore::new(routing_acceptance_concurrency)),
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Top-level pipeline
// ─────────────────────────────────────────────────────────────────────────────

/// Resolve a whole stage batch through the remote pool.
///
/// Flow:
/// 1. Partition the batch into errored / empty-passthrough / local / remote.
/// 2. Resolve local events inline (same path as no-remote mode).
/// 3. Build one logical work item per exception, grouped by routing key for
///    deterministic submission, and let each item reroute independently
///    through the mux.
/// 4. Assemble back into the original batch order.
///
/// Each event passes through exactly one bucket and writes itself into the
/// output exactly once. There is no shared mutation across RPC boundaries.
pub async fn resolve_batch(
    batch: Batch<ExceptionEventPipelineItem>,
    ctx: RemoteResolutionContext,
    local_stage: ResolutionStage,
) -> Result<Batch<ExceptionEventPipelineItem>, UnhandledError> {
    let batch_len = batch.len();
    let partition = partition_batch(batch, ctx.config.sample_rate)?;

    let local_resolved = resolve_local_events(partition.local, local_stage).await?;
    let remote_resolved = resolve_remote_events(&ctx, partition.remote).await?;

    assemble_output(
        batch_len,
        partition.errors,
        partition.empty,
        local_resolved,
        remote_resolved,
    )
}

fn assemble_output(
    batch_len: usize,
    errors: Vec<(usize, ExceptionEventPipelineItem)>,
    empty: Vec<(usize, ExceptionEventPipelineItem)>,
    local: Vec<(usize, ExceptionEventPipelineItem)>,
    remote: Vec<(usize, ExceptionEventPipelineItem)>,
) -> Result<Batch<ExceptionEventPipelineItem>, UnhandledError> {
    let mut output: Vec<Option<ExceptionEventPipelineItem>> =
        (0..batch_len).map(|_| None).collect();
    for (idx, item) in errors.into_iter().chain(empty).chain(local).chain(remote) {
        output[idx] = Some(item);
    }
    let resolved: Vec<ExceptionEventPipelineItem> = output
        .into_iter()
        .enumerate()
        .map(|(idx, slot)| {
            slot.ok_or_else(|| {
                UnhandledError::Other(format!("remote resolution left output slot {idx} unfilled"))
            })
        })
        .collect::<Result<_, _>>()?;
    Ok(Batch::from(resolved))
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared data types: an event, exception work item, and resolved slot
// ─────────────────────────────────────────────────────────────────────────────

/// A sampled-remote event with its wire payloads pre-serialized.
///
/// Owning the serialized bytes alongside the event means each `RemoteEvent`
/// moves through the work-item → RPC → apply pipeline by value. No shared
/// mutable state, no `Option<>` sentinels in the RPC layer, no wire-level
/// batch bookkeeping.
struct RemoteEvent {
    batch_index: usize,
    evt: ExceptionProperties,
    /// One serialized exception per `evt.exception_list` entry, in order.
    exception_jsons: Vec<Vec<u8>>,
    /// Shared across this event's exceptions on the wire. The proto carries
    /// it per-item; this is the per-event source bytes we clone from.
    metadata: Vec<u8>,
}

impl RemoteEvent {
    fn item_count(&self) -> usize {
        self.evt.exception_list.len()
    }
}

struct RemoteEventSlot {
    batch_index: usize,
    evt: ExceptionProperties,
    resolved: Vec<Option<Exception>>,
}

/// One logical exception-level item. `token` is client-side only: the mux may
/// replace it with a per-stream token and restores it before returning.
struct RemoteWorkItem {
    token: u64,
    routing_key: String,
    event_slot: usize,
    exception_slot: usize,
    item: ResolveItem,
}

impl RemoteWorkItem {
    fn to_item(&self, deadline: Duration) -> ResolveItem {
        let mut item = self.item.clone();
        item.id = self.token;
        item.deadline_ms = deadline.as_millis().clamp(1, u32::MAX as u128) as u32;
        item
    }
}

struct ResolvedRemoteItem {
    event_slot: usize,
    exception_slot: usize,
    exception: Exception,
}

// ─────────────────────────────────────────────────────────────────────────────
// Local resolution path (passthrough to the inline stage)
// ─────────────────────────────────────────────────────────────────────────────

async fn resolve_local_events(
    local_events: Vec<(usize, ExceptionProperties)>,
    local_stage: ResolutionStage,
) -> Result<Vec<(usize, ExceptionEventPipelineItem)>, UnhandledError> {
    if local_events.is_empty() {
        return Ok(Vec::new());
    }
    let (indexes, events): (Vec<usize>, Vec<ExceptionProperties>) =
        local_events.into_iter().unzip();
    let batch = Batch::from(events.into_iter().map(Ok).collect::<Vec<_>>())
        .apply_operator(ExceptionResolver, local_stage.clone())
        .await?
        .apply_operator(FrameResolver, local_stage)
        .await?;
    Ok(indexes.into_iter().zip(batch.into_iter()).collect())
}

// ─────────────────────────────────────────────────────────────────────────────
// Remote resolution path: group → flatten → reroute independently → apply
// ─────────────────────────────────────────────────────────────────────────────

async fn resolve_remote_events(
    ctx: &RemoteResolutionContext,
    events: Vec<RemoteEvent>,
) -> Result<Vec<(usize, ExceptionEventPipelineItem)>, UnhandledError> {
    if events.is_empty() {
        return Ok(Vec::new());
    }

    let (mut event_slots, work_items) = build_work_items(events)?;
    let deadline = Instant::now()
        .checked_add(ctx.config.request_deadline)
        .unwrap_or_else(Instant::now);

    let resolved = join_all(
        work_items
            .into_iter()
            .map(|work_item| resolve_work_item(ctx, work_item, deadline)),
    )
    .await;

    for result in resolved {
        let item = result?;
        let Some(event_slot) = event_slots.get_mut(item.event_slot) else {
            return Err(UnhandledError::Other(format!(
                "remote resolution returned invalid event slot {}",
                item.event_slot
            )));
        };
        let Some(slot) = event_slot.resolved.get_mut(item.exception_slot) else {
            return Err(UnhandledError::Other(format!(
                "remote resolution returned invalid exception slot {} for event slot {}",
                item.exception_slot, item.event_slot
            )));
        };
        if slot.replace(item.exception).is_some() {
            return Err(UnhandledError::Other(format!(
                "remote resolution filled event slot {} exception slot {} twice",
                item.event_slot, item.exception_slot
            )));
        }
    }

    event_slots
        .into_iter()
        .map(|mut event| {
            let exceptions = event
                .resolved
                .into_iter()
                .enumerate()
                .map(|(exception_slot, slot)| {
                    slot.ok_or_else(|| {
                        UnhandledError::Other(format!(
                            "remote resolution left event slot {} exception slot {exception_slot} unfilled",
                            event.batch_index
                        ))
                    })
                })
                .collect::<Result<Vec<_>, _>>()?;
            event.evt.exception_list = ExceptionList::from(exceptions);
            Ok((event.batch_index, Ok(event.evt)))
        })
        .collect()
}

fn build_work_items(
    events: Vec<RemoteEvent>,
) -> Result<(Vec<RemoteEventSlot>, Vec<RemoteWorkItem>), UnhandledError> {
    let mut event_slots = Vec::new();
    let mut work_items_by_key: BTreeMap<String, Vec<RemoteWorkItem>> = BTreeMap::new();
    let mut next_token = 1u64;

    for event in events {
        let event_slot = event_slots.len();
        let item_count = event.item_count();
        let team_id = event.evt.team_id;
        let routing_keys = routing_keys_for_event(&event.evt);

        for (exception_slot, exception_json) in event.exception_jsons.iter().cloned().enumerate() {
            let routing_key = routing_keys.get(exception_slot).cloned().ok_or_else(|| {
                UnhandledError::Other(format!(
                    "remote resolution missing routing key for event slot {event_slot} exception slot {exception_slot}",
                ))
            })?;
            let token = next_token;
            next_token = next_token.checked_add(1).ok_or_else(|| {
                UnhandledError::Other("remote resolution work item token overflowed".to_string())
            })?;
            work_items_by_key
                .entry(routing_key.clone())
                .or_default()
                .push(RemoteWorkItem {
                    token,
                    routing_key,
                    event_slot,
                    exception_slot,
                    item: ResolveItem {
                        id: token,
                        team_id,
                        exception_json,
                        metadata: event.metadata.clone(),
                        deadline_ms: 0,
                    },
                });
        }

        event_slots.push(RemoteEventSlot {
            batch_index: event.batch_index,
            evt: event.evt,
            resolved: (0..item_count).map(|_| None).collect(),
        });
    }

    let work_items = work_items_by_key.into_values().flatten().collect();

    Ok((event_slots, work_items))
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use uuid::Uuid;

    use super::*;

    #[test]
    fn build_work_items_assigns_client_tokens_and_slots_without_batch_ids() {
        let events = vec![fake_remote_event(2, 3, 2), fake_remote_event(1, 7, 1)];
        let (event_slots, work_items) = build_work_items(events).expect("build work items");

        assert_eq!(event_slots.len(), 2);
        assert_eq!(work_items.len(), 3);
        let mut tokens = work_items.iter().map(|item| item.token).collect::<Vec<_>>();
        tokens.sort_unstable();
        assert_eq!(tokens, vec![1, 2, 3]);
        assert_eq!(
            work_items
                .iter()
                .map(|item| item.routing_key.as_str())
                .collect::<Vec<_>>(),
            vec!["team:1", "team:2", "team:2"]
        );
        assert_eq!(
            work_items
                .iter()
                .map(|item| (item.event_slot, item.exception_slot))
                .collect::<Vec<_>>(),
            vec![(1, 0), (0, 0), (0, 1)]
        );
        assert!(work_items.iter().all(|item| item.item.deadline_ms == 0));
    }

    #[test]
    fn build_work_items_routes_each_exception_by_symbol_set_ref() {
        let events = vec![fake_remote_event_from_exceptions(
            7,
            3,
            vec![
                json!({
                    "type": "Error",
                    "value": "boom-b",
                    "stacktrace": {
                        "type": "raw",
                        "frames": [{
                            "platform": "web:javascript",
                            "filename": "https://example.com/app-b.js",
                            "function": "minified",
                            "lineno": 1,
                            "colno": 2,
                            "chunk_id": "chunk-b"
                        }]
                    }
                }),
                json!({
                    "type": "Error",
                    "value": "boom-a",
                    "stacktrace": {
                        "type": "raw",
                        "frames": [{
                            "platform": "web:javascript",
                            "filename": "https://example.com/app-a.js",
                            "function": "minified",
                            "lineno": 1,
                            "colno": 2,
                            "chunk_id": "chunk-a"
                        }]
                    }
                }),
            ],
        )];

        let (_event_slots, work_items) = build_work_items(events).expect("build work items");

        assert_eq!(
            work_items
                .iter()
                .map(|item| (item.exception_slot, item.routing_key.as_str()))
                .collect::<Vec<_>>(),
            vec![(1, "team:7:symbol:chunk-a"), (0, "team:7:symbol:chunk-b"),]
        );
    }

    fn fake_remote_event(team_id: i32, batch_index: usize, n_exceptions: usize) -> RemoteEvent {
        fake_remote_event_from_exceptions(
            team_id,
            batch_index,
            (0..n_exceptions)
                .map(|i| {
                    json!({
                        "type": "Error",
                        "value": format!("boom-{i}"),
                    })
                })
                .collect(),
        )
    }

    fn fake_remote_event_from_exceptions(
        team_id: i32,
        batch_index: usize,
        exceptions: Vec<serde_json::Value>,
    ) -> RemoteEvent {
        let mut evt: ExceptionProperties = serde_json::from_value(json!({
            "$exception_list": exceptions,
        }))
        .expect("valid exception properties");
        evt.team_id = team_id;
        evt.uuid = Uuid::from_u128(0xABCD_0000_0000_0000 ^ (batch_index as u128));

        let exception_jsons = evt
            .exception_list
            .iter()
            .map(|exc| serde_json::to_vec(exc).expect("serialize exception"))
            .collect();
        RemoteEvent {
            batch_index,
            evt,
            exception_jsons,
            metadata: Vec::new(),
        }
    }
}
