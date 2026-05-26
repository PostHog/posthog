//! Generic ordered emission primitives for incremental pipeline runners.
//!
//! This module owns the framework-level sink trait and the ordered emitter
//! used to enforce input-order delivery on top of an arbitrary sink without
//! depending on any specific item type. Domain pipelines (e.g. the exception
//! pipeline) pin `T` to their own per-item outcome type and pass an extractor
//! that maps each item back to its input ID.
//!
//! Concerns that explicitly do not belong here: stage execution, streaming
//! orchestration, or domain-specific result shapes. Those live in
//! [`crate::executor`] and the per-domain pipeline crates.

use std::collections::HashMap;

use async_trait::async_trait;

use crate::StageError;

/// Minimal identity contract for items emitted by generic pipeline helpers.
///
/// The identity must match one of the canonical input IDs supplied to
/// [`OrderedEmitter`]. Product crates implement this for their own terminal
/// item types so callers can use [`OrderedEmitter::for_identified`] without
/// repeating a closure at each call site.
pub trait IdentifiedItem {
    fn item_id(&self) -> &str;
}

/// Streaming sink for ordered per-item outcomes.
///
/// Implementations should apply backpressure in `emit`; the gRPC service uses
/// a bounded response channel so a slow client pauses pipeline progress
/// instead of accumulating an unbounded response buffer.
#[async_trait]
pub trait Sink<T>: Send
where
    T: Send + 'static,
{
    async fn emit(&mut self, item: T) -> Result<(), StageError>;
}

#[async_trait]
impl<T, U> Sink<T> for &mut U
where
    T: Send + 'static,
    U: Sink<T> + Send + ?Sized,
{
    async fn emit(&mut self, item: T) -> Result<(), StageError> {
        (**self).emit(item).await
    }
}

/// Whether items may be emitted as soon as they are produced or must be
/// reordered to match the original input order.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EmissionOrder {
    /// Preserve the order of the original input IDs.
    InputOrder,
    /// Emit each item immediately, in whatever order it arrived.
    CompletionOrder,
}

/// Ordered emitter that buffers out-of-order items and flushes the contiguous
/// input-order prefix to a downstream [`Sink`].
///
/// The emitter is generic over the item type `T`, the underlying sink `S`,
/// and an ID extractor `F` that returns each item's input ID. The IDs are
/// supplied at construction time as the canonical input ordering; every
/// emitted item must carry an ID that exists in that list, and each ID may
/// be emitted at most once.
///
/// `finish` validates that every input ID has been emitted and that no
/// items remain buffered. Callers that do not need ordering can use
/// [`EmissionOrder::CompletionOrder`] to bypass buffering while still
/// validating duplicate/unknown/missing-ID invariants on `finish`.
pub struct OrderedEmitter<T, S, F>
where
    T: Send + 'static,
    S: Sink<T>,
    F: Fn(&T) -> &str + Send,
{
    input_ids: Vec<String>,
    input_index_by_id: HashMap<String, usize>,
    next_ordered_index: usize,
    buffered: HashMap<usize, T>,
    seen_ids: HashMap<String, ()>,
    order: EmissionOrder,
    id_fn: F,
    sink: S,
}

impl<T, S, F> OrderedEmitter<T, S, F>
where
    T: Send + 'static,
    S: Sink<T>,
    F: Fn(&T) -> &str + Send,
{
    pub fn new(input_ids: Vec<String>, order: EmissionOrder, id_fn: F, sink: S) -> Self {
        let input_index_by_id = input_ids
            .iter()
            .enumerate()
            .map(|(index, id)| (id.clone(), index))
            .collect();
        Self {
            input_ids,
            input_index_by_id,
            next_ordered_index: 0,
            buffered: HashMap::new(),
            seen_ids: HashMap::new(),
            order,
            id_fn,
            sink,
        }
    }

    pub async fn emit_many<I>(&mut self, items: I) -> Result<(), StageError>
    where
        I: IntoIterator<Item = T>,
    {
        for item in items {
            self.emit(item).await?;
        }
        Ok(())
    }

    pub async fn emit(&mut self, item: T) -> Result<(), StageError> {
        let id = (self.id_fn)(&item).to_string();
        if self.seen_ids.insert(id.clone(), ()).is_some() {
            return Err(StageError::Internal(
                "ordered emitter received duplicate item id".to_string(),
            ));
        }
        let Some(index) = self.input_index_by_id.get(&id).copied() else {
            return Err(StageError::Internal(
                "ordered emitter received item with unknown id".to_string(),
            ));
        };

        match self.order {
            EmissionOrder::CompletionOrder => self.sink.emit(item).await,
            EmissionOrder::InputOrder => {
                self.buffered.insert(index, item);
                self.flush_ordered_prefix().await
            }
        }
    }

    async fn flush_ordered_prefix(&mut self) -> Result<(), StageError> {
        while let Some(item) = self.buffered.remove(&self.next_ordered_index) {
            self.next_ordered_index += 1;
            self.sink.emit(item).await?;
        }
        Ok(())
    }

    pub fn finish(self) -> Result<(), StageError> {
        if self.seen_ids.len() != self.input_ids.len() {
            for id in self.input_ids {
                if !self.seen_ids.contains_key(&id) {
                    return Err(StageError::Internal(format!(
                        "ordered emitter received no item for id {id}"
                    )));
                }
            }
        }
        if !self.buffered.is_empty() {
            return Err(StageError::Internal(
                "ordered emitter buffered out-of-order items that could not be emitted".to_string(),
            ));
        }
        Ok(())
    }
}

impl<T, S> OrderedEmitter<T, S, fn(&T) -> &str>
where
    T: IdentifiedItem + Send + 'static,
    S: Sink<T>,
{
    pub fn for_identified(input_ids: Vec<String>, order: EmissionOrder, sink: S) -> Self {
        fn item_id<T: IdentifiedItem>(item: &T) -> &str {
            item.item_id()
        }

        Self::new(input_ids, order, item_id::<T>, sink)
    }
}

#[cfg(test)]
mod tests {
    use std::sync::{Arc, Mutex};

    use super::*;

    #[derive(Clone, Debug, PartialEq, Eq)]
    struct Item {
        id: String,
        payload: u32,
    }

    impl IdentifiedItem for Item {
        fn item_id(&self) -> &str {
            self.id.as_str()
        }
    }

    fn item(id: &str, payload: u32) -> Item {
        Item {
            id: id.to_string(),
            payload,
        }
    }

    #[derive(Default, Clone)]
    struct RecordingSink {
        emitted: Arc<Mutex<Vec<Item>>>,
    }

    impl RecordingSink {
        fn ids(&self) -> Vec<String> {
            self.emitted
                .lock()
                .unwrap()
                .iter()
                .map(|item| item.id.clone())
                .collect()
        }
    }

    #[async_trait]
    impl Sink<Item> for RecordingSink {
        async fn emit(&mut self, item: Item) -> Result<(), StageError> {
            self.emitted.lock().unwrap().push(item);
            Ok(())
        }
    }

    fn id_fn(item: &Item) -> &str {
        item.id.as_str()
    }

    #[tokio::test]
    async fn input_order_buffers_late_arrivals_until_prefix_completes() {
        let sink = RecordingSink::default();
        let mut emitter = OrderedEmitter::new(
            vec!["a".to_string(), "b".to_string(), "c".to_string()],
            EmissionOrder::InputOrder,
            id_fn,
            sink.clone(),
        );

        emitter.emit(item("c", 3)).await.unwrap();
        assert!(sink.ids().is_empty(), "no contiguous prefix yet");
        emitter.emit(item("a", 1)).await.unwrap();
        assert_eq!(sink.ids(), vec!["a"], "prefix flushes through a");
        emitter.emit(item("b", 2)).await.unwrap();
        assert_eq!(
            sink.ids(),
            vec!["a", "b", "c"],
            "remaining items flush in input order"
        );
        emitter.finish().unwrap();
    }

    #[tokio::test]
    async fn completion_order_emits_immediately() {
        let sink = RecordingSink::default();
        let mut emitter = OrderedEmitter::new(
            vec!["a".to_string(), "b".to_string(), "c".to_string()],
            EmissionOrder::CompletionOrder,
            id_fn,
            sink.clone(),
        );

        emitter.emit(item("c", 3)).await.unwrap();
        emitter.emit(item("a", 1)).await.unwrap();
        emitter.emit(item("b", 2)).await.unwrap();
        assert_eq!(sink.ids(), vec!["c", "a", "b"]);
        emitter.finish().unwrap();
    }

    #[tokio::test]
    async fn for_identified_uses_item_identity() {
        let sink = RecordingSink::default();
        let mut emitter = OrderedEmitter::for_identified(
            vec!["a".to_string(), "b".to_string(), "c".to_string()],
            EmissionOrder::InputOrder,
            sink.clone(),
        );

        emitter.emit(item("c", 3)).await.unwrap();
        emitter.emit(item("a", 1)).await.unwrap();
        emitter.emit(item("b", 2)).await.unwrap();

        assert_eq!(sink.ids(), vec!["a", "b", "c"]);
        emitter.finish().unwrap();
    }

    #[tokio::test]
    async fn duplicate_ids_fail_emit() {
        let sink = RecordingSink::default();
        let mut emitter = OrderedEmitter::new(
            vec!["a".to_string()],
            EmissionOrder::CompletionOrder,
            id_fn,
            sink,
        );
        emitter.emit(item("a", 1)).await.unwrap();
        let err = emitter.emit(item("a", 2)).await.unwrap_err();
        assert!(matches!(err, StageError::Internal(_)));
    }

    #[tokio::test]
    async fn unknown_ids_fail_emit() {
        let sink = RecordingSink::default();
        let mut emitter = OrderedEmitter::new(
            vec!["a".to_string()],
            EmissionOrder::InputOrder,
            id_fn,
            sink,
        );
        let err = emitter.emit(item("zzz", 0)).await.unwrap_err();
        assert!(matches!(err, StageError::Internal(_)));
    }

    #[tokio::test]
    async fn finish_errors_when_some_ids_missing() {
        let sink = RecordingSink::default();
        let mut emitter = OrderedEmitter::new(
            vec!["a".to_string(), "b".to_string()],
            EmissionOrder::CompletionOrder,
            id_fn,
            sink,
        );
        emitter.emit(item("a", 1)).await.unwrap();
        let err = emitter.finish().unwrap_err();
        assert!(matches!(err, StageError::Internal(_)));
    }

    #[tokio::test]
    async fn emit_many_routes_each_item_through_emit() {
        let sink = RecordingSink::default();
        let mut emitter = OrderedEmitter::new(
            vec!["a".to_string(), "b".to_string(), "c".to_string()],
            EmissionOrder::InputOrder,
            id_fn,
            sink.clone(),
        );
        emitter
            .emit_many(vec![item("b", 2), item("a", 1), item("c", 3)])
            .await
            .unwrap();
        assert_eq!(sink.ids(), vec!["a", "b", "c"]);
        emitter.finish().unwrap();
    }
}
