//! Plugins and observers: the framework core hardcodes no cross-cutting concern
//! (ingestion warnings, TopHog, app metrics). There are two extension shapes.
//!
//! **Sink plugins** — steps *write* into them. A [`Plugin`] contributes a
//! per-chunk sink type (accumulation state) and a `flush` that turns the
//! accumulated data into deferred effects at chunk end. Each pipeline composes
//! its own `Fx` struct from the sinks of the plugins it registers and wires
//! access with a one-line [`HasSink`] impl per sink. Steps never touch
//! `HasSink`; a plugin exposes its API as an extension trait with a blanket impl
//! over `HasSink<ItsSink>`, so the methods appear directly on `fx` and the bound
//! *is* the dependency declaration (see the test module for the full pattern).
//!
//! **Observers** — read-only hooks that watch verdicts and contribute effects at
//! chunk end without any step cooperation. `dyn`-dispatched; not hot-path API.

use metrics::counter;

use crate::effects::EffectQueue;
use crate::metrics_consts::PIPELINE_RESULTS;
use crate::step::VerdictKind;

/// A plugin: a per-chunk sink steps write into, plus a flush that converts the
/// collected data into deferred effects at chunk end.
pub trait Plugin {
    /// The per-chunk accumulation state. `Default` so the harness can create a
    /// fresh one per chunk.
    type Sink: Default + Send;

    /// Turn one chunk's accumulated sink data into deferred effects.
    fn flush(&self, sink: Self::Sink, out: &mut EffectQueue);
}

/// Sink-storage lookup implemented by each pipeline's composed `Fx` struct — one
/// line per sink (a derive macro would generate these once there are 3+
/// pipelines composing 2+ sinks).
pub trait HasSink<S> {
    fn sink(&mut self) -> &mut S;
}

/// Read-only hook over the pipeline. The built-in [`MetricsObserver`] is one;
/// dry-run verdict comparison and TopHog-style aggregation are future ones.
pub trait Observer: Send + Sync {
    /// Called once per terminal verdict, with the deciding step and reason.
    fn on_verdict(&self, step: &'static str, kind: VerdictKind, reason: &'static str);

    /// Called once at chunk end; may contribute deferred effects.
    fn on_chunk_end(&self, out: &mut EffectQueue);
}

/// The framework's own metrics, implemented as a built-in observer — proof the
/// extension point is real. Emits `ingestion_pipeline_results{result,
/// last_step_name, details}`, matching the Node vocabulary.
pub struct MetricsObserver;

impl Observer for MetricsObserver {
    fn on_verdict(&self, step: &'static str, kind: VerdictKind, reason: &'static str) {
        counter!(
            PIPELINE_RESULTS,
            "result" => kind.as_str(),
            "last_step_name" => step,
            "details" => reason,
        )
        .increment(1);
    }

    fn on_chunk_end(&self, _out: &mut EffectQueue) {}
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::effects::{DeferredProduce, OutputRef};
    use crate::result::{NoOutputs, StepError, StepResult};
    use crate::step::{Pipeline, Step};
    use bytes::Bytes;

    // --- a toy plugin demonstrating the sink + capability-trait pattern ---

    // 1. The plugin's per-chunk sink.
    #[derive(Default)]
    struct CounterSink {
        records: Vec<(&'static str, u64)>,
    }

    // 2. The plugin itself: flush turns records into one produce each.
    struct CounterPlugin;
    impl Plugin for CounterPlugin {
        type Sink = CounterSink;
        fn flush(&self, sink: CounterSink, out: &mut EffectQueue) {
            for (name, value) in sink.records {
                out.push_produce(DeferredProduce {
                    topic: OutputRef::new("counters"),
                    key: None,
                    payload: Bytes::from(format!("{name}={value}")),
                    headers: Vec::new(),
                });
            }
        }
    }

    // 3. The capability trait steps bound on, with a blanket impl routing to
    //    storage. Steps call `fx.record(...)` and never see `HasSink`.
    trait CounterEffects {
        fn record(&mut self, name: &'static str, value: u64);
    }
    impl<Fx: HasSink<CounterSink>> CounterEffects for Fx {
        fn record(&mut self, name: &'static str, value: u64) {
            self.sink().records.push((name, value));
        }
    }

    // 4. A pipeline's composed effects struct + the one-line HasSink wiring.
    #[derive(Default)]
    struct ComposedFx {
        counters: CounterSink,
    }
    impl HasSink<CounterSink> for ComposedFx {
        fn sink(&mut self) -> &mut CounterSink {
            &mut self.counters
        }
    }

    // 5. A step declaring the capability as a bound — compiles against any Fx
    //    that holds the sink, and would fail to compile against one that does not.
    struct RecordingStep;
    impl<Fx> Step<u32, Fx> for RecordingStep
    where
        Fx: CounterEffects + Send + Sync,
    {
        type Out = u32;
        type Outputs = NoOutputs;
        fn apply(&self, event: u32, fx: &mut Fx) -> Result<StepResult<u32, NoOutputs>, StepError> {
            fx.record("seen", u64::from(event));
            Ok(StepResult::Continue(event))
        }
        fn name(&self) -> &'static str {
            "recording"
        }
    }

    #[tokio::test]
    async fn step_uses_capability_and_plugin_flushes_once_per_chunk() {
        let pipeline = Pipeline::<u32, u32, ComposedFx, NoOutputs>::builder()
            .step(RecordingStep)
            .build();

        let mut fx = ComposedFx::default();
        let outcome = pipeline.run_chunk(vec![1, 2, 3], &mut fx).await.unwrap();
        assert_eq!(outcome.survivor_count(), 3);

        // The step wrote one record per event into the sink.
        assert_eq!(fx.counters.records.len(), 3);

        // Flush once at chunk end -> one produce per accumulated record.
        let mut queue = EffectQueue::new();
        CounterPlugin.flush(std::mem::take(&mut fx.counters), &mut queue);
        assert_eq!(queue.len(), 3);
        assert_eq!(queue.produces()[0].topic.topic(), "counters");
    }

    #[test]
    fn metrics_observer_emits_pipeline_results() {
        let recorder = metrics_util::debugging::DebuggingRecorder::new();
        let snapshotter = recorder.snapshotter();
        metrics::with_local_recorder(&recorder, || {
            MetricsObserver.on_verdict("deny_events", VerdictKind::Dlq, "event_in_denylist");
        });
        let snapshot = snapshotter.snapshot().into_vec();
        let found = snapshot.iter().any(|(key, _unit, _desc, value)| {
            key.key().name() == PIPELINE_RESULTS
                && matches!(value, metrics_util::debugging::DebugValue::Counter(1))
        });
        assert!(found, "expected {PIPELINE_RESULTS} counter: {snapshot:?}");
    }
}
