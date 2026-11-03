mod common;

use std::sync::{Arc, Mutex};

use common::items;
use ingestion_framework::{
    chunk_step, drop, new_chunk_pipeline, ok, ChunkPipelineUnwrapper, SideEffect,
};

#[tokio::test]
async fn feed_then_next_drives_the_pipeline_until_it_returns_null() {
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk(chunk_step("doubleStep", |events: Vec<i64>| async move {
            Ok(events.into_iter().map(|e| ok(e * 2)).collect())
        }))
        .build();
    pipeline.feed(items([1, 2, 3]));
    let mut values = Vec::new();
    while let Some(results) = pipeline.next().await.unwrap() {
        values.extend(results.into_iter().filter_map(|r| r.result.into_value()));
    }
    assert_eq!(values, [2, 4, 6]);
    assert!(pipeline.next().await.unwrap().is_none());
}

#[tokio::test]
async fn chunk_pipeline_unwrapper_returns_plain_values_and_drops_non_ok_results() {
    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk(chunk_step("filterStep", |events: Vec<i64>| async move {
            Ok(events
                .into_iter()
                .map(|e| {
                    if e % 2 == 0 {
                        drop("even filtered")
                    } else {
                        ok(e)
                    }
                })
                .collect())
        }))
        .build();
    let unwrapper = ChunkPipelineUnwrapper::new(pipeline);
    unwrapper.feed(items([1, 2, 3]));
    let mut values = Vec::new();
    while let Some(chunk) = unwrapper.next().await.unwrap() {
        values.extend(chunk);
    }
    assert_eq!(values, [1, 3]);
}

#[derive(Clone, Default)]
struct Capture(Arc<Mutex<Vec<String>>>);

impl<S: tracing::Subscriber> tracing_subscriber::Layer<S> for Capture {
    fn on_event(
        &self,
        event: &tracing::Event<'_>,
        _ctx: tracing_subscriber::layer::Context<'_, S>,
    ) {
        struct V<'a>(&'a mut String);
        impl tracing::field::Visit for V<'_> {
            fn record_debug(&mut self, _f: &tracing::field::Field, value: &dyn std::fmt::Debug) {
                self.0.push_str(&format!("{value:?}"));
            }
        }
        let mut s = String::new();
        event.record(&mut V(&mut s));
        self.0.lock().unwrap().push(s);
    }
}

#[tokio::test]
async fn chunk_pipeline_unwrapper_warns_about_unhandled_side_effects() {
    use tracing_subscriber::layer::SubscriberExt;
    let capture = Capture::default();
    let subscriber = tracing_subscriber::registry().with(capture.clone());
    let _guard = tracing::subscriber::set_default(subscriber);

    let pipeline = new_chunk_pipeline::<i64, ()>()
        .pipe_chunk(chunk_step(
            "stepWithSideEffect",
            |events: Vec<i64>| async move {
                Ok(events
                    .into_iter()
                    .map(|e| ok(e).with_side_effect(SideEffect::resolved()))
                    .collect())
            },
        ))
        .build();
    let unwrapper = ChunkPipelineUnwrapper::new(pipeline);
    unwrapper.feed(items([1]));
    unwrapper.next().await.unwrap();
    assert!(capture
        .0
        .lock()
        .unwrap()
        .iter()
        .any(|m| m.contains("remaining side effects")));
}
