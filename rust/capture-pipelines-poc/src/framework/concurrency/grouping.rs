//! `concurrently_per_group`: group by key, run groups concurrently, items in-order.

use super::processor::AsyncProcessor;
use crate::framework::result::StepResult;
use futures::stream::{self, StreamExt};
use std::collections::HashMap;
use std::hash::Hash;

/// Group the chunk by `key_of`, process **groups concurrently** (bounded by
/// `max_groups`), and within each group process items **strictly in input order**.
/// This is Node's `concurrentlyPerGroup` — the priority combinator for keyed work
/// (per-`token:distinct_id` limiting, per-session replay).
///
/// Unlike Node, which emits in group-completion order, results are reassembled
/// **positionally**: verdict `i` corresponds to input `i`. Within-group ordering and
/// cross-group concurrency are identical to Node.
///
/// `max_groups` is clamped to at least 1; pass the group count for "unbounded".
pub async fn concurrently_per_group<K, F, P>(
    max_groups: usize,
    key_of: F,
    processor: &P,
    items: Vec<P::In>,
) -> Vec<StepResult<P::Out, P::Outputs>>
where
    F: Fn(&P::In) -> K,
    K: Eq + Hash + Clone,
    P: AsyncProcessor,
{
    let total = items.len();

    // Route into per-key queues, remembering original positions and first-seen order.
    let mut first_seen: Vec<K> = Vec::new();
    let mut groups: HashMap<K, Vec<(usize, P::In)>> = HashMap::new();
    for (idx, item) in items.into_iter().enumerate() {
        let key = key_of(&item);
        if !groups.contains_key(&key) {
            first_seen.push(key.clone());
        }
        groups.entry(key).or_default().push((idx, item));
    }

    let group_lists: Vec<Vec<(usize, P::In)>> = first_seen
        .into_iter()
        .map(|k| groups.remove(&k).expect("key was just inserted"))
        .collect();

    // Each group is one future that processes its items sequentially, in order.
    // `buffer_unordered` runs up to `max_groups` group-futures concurrently.
    #[allow(clippy::type_complexity)] // indexed per-group results, an internal intermediate
    let processed: Vec<Vec<(usize, StepResult<P::Out, P::Outputs>)>> = stream::iter(group_lists)
        .map(|group| async move {
            let mut out = Vec::with_capacity(group.len());
            for (idx, item) in group {
                out.push((idx, processor.process(item).await));
            }
            out
        })
        .buffer_unordered(max_groups.max(1))
        .collect()
        .await;

    // Reassemble positionally: verdict i -> input i.
    let mut slots: Vec<Option<StepResult<P::Out, P::Outputs>>> = (0..total).map(|_| None).collect();
    for group_out in processed {
        for (idx, verdict) in group_out {
            slots[idx] = Some(verdict);
        }
    }
    slots
        .into_iter()
        .map(|v| v.expect("every position filled exactly once"))
        .collect()
}
