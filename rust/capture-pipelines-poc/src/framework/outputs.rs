//! The [`OutputRegistry`] that maps a pipeline's typed outputs to topics + a producer.
//!
//! The output *enum* itself is domain data (see
//! [`AnalyticsOutputs`](crate::pipeline::outputs::AnalyticsOutputs)); this module owns
//! only the generic machinery. The registry binds each variant to a topic and a
//! producer, and [`check`](OutputRegistry::check) proves at startup that *every*
//! variant has a topic — the Rust equivalent of Node's `outputs.checkTopics()`.
//! Production goes through a generic [`Produce`] bound, so there is no
//! `Box<dyn Producer>` anywhere; tests use the in-memory [`MemProducer`].

use crate::framework::result::Outputs;
use std::marker::PhantomData;
use std::sync::Mutex;

/// A produce sink: hand it a topic and payload, it emits. Generic bound — no trait
/// objects.
pub trait Produce {
    /// Produce `payload` to `topic`.
    fn produce(&self, topic: &'static str, payload: Vec<u8>);
}

/// An in-memory producer for tests (test-support, not a real transport): records every
/// `(topic, payload)` it receives.
#[derive(Default)]
pub struct MemProducer {
    sent: Mutex<Vec<(&'static str, Vec<u8>)>>,
}

impl MemProducer {
    /// A fresh empty producer.
    pub fn new() -> Self {
        Self::default()
    }

    /// Everything produced so far, as `(topic, payload)` pairs.
    pub fn sent(&self) -> Vec<(&'static str, Vec<u8>)> {
        self.sent.lock().unwrap().clone()
    }

    /// The topics produced to, in order.
    pub fn topics(&self) -> Vec<&'static str> {
        self.sent.lock().unwrap().iter().map(|(t, _)| *t).collect()
    }
}

impl Produce for MemProducer {
    fn produce(&self, topic: &'static str, payload: Vec<u8>) {
        self.sent.lock().unwrap().push((topic, payload));
    }
}

/// A missing-topic error, naming the output that has no configured topic.
#[derive(Debug, PartialEq, Eq)]
pub struct MissingTopic {
    /// The output variant with no topic.
    pub output: &'static str,
}

impl std::fmt::Display for MissingTopic {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "no topic configured for output `{}`", self.output)
    }
}

impl std::error::Error for MissingTopic {}

/// Maps a pipeline's [`Outputs`] enum to topics and a producer.
///
/// `topic_for` returns `None` for an unconfigured output; [`check`](Self::check)
/// iterates [`Outputs::ALL`] to prove none are missing before the pipeline runs.
pub struct OutputRegistry<O: Outputs, P> {
    topic_for: fn(O) -> Option<&'static str>,
    producer: P,
    _marker: PhantomData<O>,
}

impl<O: Outputs, P: Produce> OutputRegistry<O, P> {
    /// Build a registry from a topic-resolver and a producer.
    pub fn new(topic_for: fn(O) -> Option<&'static str>, producer: P) -> Self {
        OutputRegistry {
            topic_for,
            producer,
            _marker: PhantomData,
        }
    }

    /// Verify every output variant has a configured topic (startup check).
    pub fn check(&self) -> Result<(), MissingTopic> {
        for &output in O::ALL {
            if (self.topic_for)(output).is_none() {
                return Err(MissingTopic {
                    output: output.name(),
                });
            }
        }
        Ok(())
    }

    /// Resolve `output` to its topic and produce `payload` there.
    pub fn emit(&self, output: O, payload: Vec<u8>) -> Result<(), MissingTopic> {
        let topic = (self.topic_for)(output).ok_or(MissingTopic {
            output: output.name(),
        })?;
        self.producer.produce(topic, payload);
        Ok(())
    }

    /// The underlying producer (tests inspect it).
    pub fn producer(&self) -> &P {
        &self.producer
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // A local output set, so this generic module needs no domain enum to test.
    #[derive(Clone, Copy, PartialEq, Eq, Debug)]
    enum TestOut {
        A,
        B,
    }
    impl Outputs for TestOut {
        const ALL: &'static [Self] = &[TestOut::A, TestOut::B];
        fn name(&self) -> &'static str {
            match self {
                TestOut::A => "a",
                TestOut::B => "b",
            }
        }
    }

    fn full(o: TestOut) -> Option<&'static str> {
        match o {
            TestOut::A => Some("topic_a"),
            TestOut::B => Some("topic_b"),
        }
    }

    #[test]
    fn check_passes_when_every_output_has_a_topic() {
        let registry = OutputRegistry::new(full, MemProducer::new());
        assert!(registry.check().is_ok());
    }

    #[test]
    fn check_fails_and_names_the_missing_output() {
        fn partial(o: TestOut) -> Option<&'static str> {
            match o {
                TestOut::A => None,
                TestOut::B => Some("topic_b"),
            }
        }
        let registry = OutputRegistry::new(partial, MemProducer::new());
        assert_eq!(registry.check(), Err(MissingTopic { output: "a" }));
    }

    #[test]
    fn emit_records_topic_and_payload() {
        let registry = OutputRegistry::new(full, MemProducer::new());
        registry.emit(TestOut::B, b"raw".to_vec()).unwrap();
        assert_eq!(registry.producer().topics(), vec!["topic_b"]);
    }
}
