//! Deferred effects. Steps and plugins never touch Kafka directly; they emit
//! [`DeferredProduce`] values into an [`EffectQueue`], which the harness drains
//! and executes through the output registry at chunk end (all produce futures
//! joined before the batch completes).

use bytes::Bytes;

/// Reference to a pipeline output. In the POC this is just the resolved topic
/// name; the design's registry-indexed `OutputRef` collapses to this.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OutputRef(pub String);

impl OutputRef {
    pub fn new(topic: impl Into<String>) -> Self {
        OutputRef(topic.into())
    }

    pub fn topic(&self) -> &str {
        &self.0
    }
}

/// A produce deferred until chunk end. Payload/key are `Bytes` (refcounted, no
/// re-serialization); headers are owned key/value pairs.
#[derive(Debug, Clone)]
pub struct DeferredProduce {
    pub topic: OutputRef,
    pub key: Option<Bytes>,
    pub payload: Bytes,
    pub headers: Vec<(String, Vec<u8>)>,
}

/// Holds deferred effects accumulated over one chunk.
#[derive(Debug, Default)]
pub struct EffectQueue {
    produces: Vec<DeferredProduce>,
}

impl EffectQueue {
    pub fn new() -> Self {
        Self::default()
    }

    /// Enqueue a produce to run at chunk end.
    pub fn push_produce(&mut self, produce: DeferredProduce) {
        self.produces.push(produce);
    }

    /// The queued produces (read-only).
    pub fn produces(&self) -> &[DeferredProduce] {
        &self.produces
    }

    pub fn len(&self) -> usize {
        self.produces.len()
    }

    pub fn is_empty(&self) -> bool {
        self.produces.is_empty()
    }

    /// Consume the queue, yielding its produces for execution.
    pub fn into_produces(self) -> Vec<DeferredProduce> {
        self.produces
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn queue_accumulates_and_drains() {
        let mut q = EffectQueue::new();
        assert!(q.is_empty());
        q.push_produce(DeferredProduce {
            topic: OutputRef::new("overflow"),
            key: Some(Bytes::from_static(b"k")),
            payload: Bytes::from_static(b"v"),
            headers: vec![("h".to_string(), b"1".to_vec())],
        });
        assert_eq!(q.len(), 1);
        let drained = q.into_produces();
        assert_eq!(drained.len(), 1);
        assert_eq!(drained[0].topic.topic(), "overflow");
    }
}
