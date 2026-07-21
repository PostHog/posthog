//! Typed redirect outputs and the [`OutputRegistry`] that maps them to topics.
//!
//! A pipeline's redirect targets are an `enum` implementing [`Outputs`]. The registry
//! binds each variant to a topic and a producer, and [`check`](OutputRegistry::check)
//! proves at startup that *every* variant has a topic — the Rust equivalent of Node's
//! `outputs.checkTopics()`. Production goes through a generic [`Produce`] bound, so
//! there is no `Box<dyn Producer>` anywhere; tests use the in-memory [`MemProducer`].

use crate::chain::IntoOutputs;
use crate::result::Outputs;
use std::marker::PhantomData;
use std::sync::Mutex;

/// The demo analytics pipeline's redirect targets.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AnalyticsOutputs {
    /// Hot-key overflow lane.
    Overflow,
    /// Dead-letter topic.
    Dlq,
}

impl Outputs for AnalyticsOutputs {
    const ALL: &'static [Self] = &[AnalyticsOutputs::Overflow, AnalyticsOutputs::Dlq];

    fn name(&self) -> &'static str {
        match self {
            AnalyticsOutputs::Overflow => "overflow",
            AnalyticsOutputs::Dlq => "dlq",
        }
    }
}

// Identity lift, so a chain ending in `AnalyticsOutputs` unifies with itself. (The
// `NoOutputs → O` lift is provided blanket-style in `chain`.)
impl IntoOutputs<AnalyticsOutputs> for AnalyticsOutputs {
    fn into_outputs(self) -> AnalyticsOutputs {
        self
    }
}

/// A produce sink: hand it a topic and payload, it emits. Generic bound — no trait
/// objects.
pub trait Produce {
    /// Produce `payload` to `topic`.
    fn produce(&self, topic: &'static str, payload: Vec<u8>);
}

/// An in-memory producer for tests: records every `(topic, payload)` it receives.
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

    fn topic_for(o: AnalyticsOutputs) -> Option<&'static str> {
        match o {
            AnalyticsOutputs::Overflow => Some("events_overflow"),
            AnalyticsOutputs::Dlq => Some("events_dlq"),
        }
    }

    #[test]
    fn check_passes_when_every_output_has_a_topic() {
        let registry = OutputRegistry::new(topic_for, MemProducer::new());
        assert!(registry.check().is_ok());
    }

    #[test]
    fn check_fails_and_names_the_missing_output() {
        // Overflow deliberately unconfigured.
        fn partial(o: AnalyticsOutputs) -> Option<&'static str> {
            match o {
                AnalyticsOutputs::Overflow => None,
                AnalyticsOutputs::Dlq => Some("events_dlq"),
            }
        }
        let registry = OutputRegistry::new(partial, MemProducer::new());
        assert_eq!(registry.check(), Err(MissingTopic { output: "overflow" }));
    }

    #[test]
    fn emit_records_topic_and_payload() {
        let registry = OutputRegistry::new(topic_for, MemProducer::new());
        registry
            .emit(AnalyticsOutputs::Dlq, b"raw".to_vec())
            .unwrap();
        assert_eq!(registry.producer().topics(), vec!["events_dlq"]);
    }
}
