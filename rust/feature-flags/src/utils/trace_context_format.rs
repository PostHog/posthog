//! JSON log formatting that stamps the active OpenTelemetry trace context onto each record.
//!
//! Production logs reach PostHog by being scraped from stdout, and the collector only fills a
//! record's trace ID from a top-level `trace_id` key. tracing-subscriber's JSON formatter nests
//! event fields under `fields`, so the IDs are spliced in at the top level here instead.

use std::fmt;

use opentelemetry::trace::{SpanId, TraceContextExt, TraceId};
use tracing::{Event, Subscriber};
use tracing_opentelemetry::OtelData;
use tracing_subscriber::fmt::format::Writer;
use tracing_subscriber::fmt::{FmtContext, FormatEvent, FormatFields};
use tracing_subscriber::registry::LookupSpan;

/// Wraps a JSON event formatter and prepends `trace_id` and `span_id` when the event is
/// recorded inside a span known to the OpenTelemetry layer. Events outside such a span are
/// written unchanged.
pub struct WithTraceContext<F>(pub F);

impl<S, N, F> FormatEvent<S, N> for WithTraceContext<F>
where
    S: Subscriber + for<'a> LookupSpan<'a>,
    N: for<'a> FormatFields<'a> + 'static,
    F: FormatEvent<S, N>,
{
    fn format_event(
        &self,
        ctx: &FmtContext<'_, S, N>,
        mut writer: Writer<'_>,
        event: &Event<'_>,
    ) -> fmt::Result {
        let Some((trace_id, span_id)) = current_trace_context(ctx) else {
            return self.0.format_event(ctx, writer, event);
        };

        let mut buf = String::new();
        self.0.format_event(ctx, Writer::new(&mut buf), event)?;
        let Some(rest) = buf.strip_prefix('{') else {
            return writer.write_str(&buf);
        };
        let separator = if rest.starts_with('}') { "" } else { "," };
        write!(
            writer,
            "{{\"trace_id\":\"{trace_id}\",\"span_id\":\"{span_id}\"{separator}{rest}"
        )
    }
}

fn current_trace_context<S, N>(ctx: &FmtContext<'_, S, N>) -> Option<(TraceId, SpanId)>
where
    S: Subscriber + for<'a> LookupSpan<'a>,
    N: for<'a> FormatFields<'a> + 'static,
{
    ctx.event_scope()?.find_map(|span| {
        let extensions = span.extensions();
        let otel_data = extensions.get::<OtelData>()?;
        // Root spans carry their own trace ID; child spans inherit it from the parent context.
        let trace_id = otel_data
            .builder
            .trace_id
            .unwrap_or_else(|| otel_data.parent_cx.span().span_context().trace_id());
        let span_id = otel_data.builder.span_id?;
        (trace_id != TraceId::INVALID).then_some((trace_id, span_id))
    })
}

#[cfg(test)]
mod tests {
    use std::io;
    use std::sync::{Arc, Mutex};

    use opentelemetry::trace::TracerProvider as _;
    use opentelemetry_sdk::trace::TracerProvider;
    use serde_json::Value;
    use tracing_opentelemetry::OpenTelemetryLayer;
    use tracing_subscriber::fmt::MakeWriter;
    use tracing_subscriber::layer::SubscriberExt;

    use super::*;

    #[derive(Clone, Default)]
    struct Buffer(Arc<Mutex<Vec<u8>>>);

    impl io::Write for Buffer {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            self.0.lock().unwrap().extend_from_slice(bytes);
            Ok(bytes.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    impl<'a> MakeWriter<'a> for Buffer {
        type Writer = Buffer;

        fn make_writer(&'a self) -> Self::Writer {
            self.clone()
        }
    }

    fn capture_lines(emit: impl FnOnce()) -> Vec<Value> {
        let buffer = Buffer::default();
        // The SDK tracer only holds a weak reference to its provider and hands out invalid
        // IDs once the provider is dropped, so keep it alive for the whole capture.
        let provider = TracerProvider::builder().build();
        let tracer = provider.tracer("test");
        let subscriber = tracing_subscriber::registry()
            .with(
                tracing_subscriber::fmt::layer()
                    .json()
                    .with_span_list(false)
                    .map_event_format(WithTraceContext)
                    .with_writer(buffer.clone()),
            )
            .with(OpenTelemetryLayer::new(tracer));
        tracing::subscriber::with_default(subscriber, emit);

        let output = String::from_utf8(buffer.0.lock().unwrap().clone()).unwrap();
        output
            .lines()
            .map(|line| serde_json::from_str(line).expect("each line must stay valid JSON"))
            .collect()
    }

    #[test]
    fn stamps_trace_context_inside_a_span() {
        let lines = capture_lines(|| {
            let root = tracing::info_span!("root");
            let _root = root.enter();
            tracing::info!(request_id = "abc", "in root");
            let child = tracing::info_span!("child");
            let _child = child.enter();
            tracing::info!("in child");
        });

        assert_eq!(lines.len(), 2);
        let root_trace_id = lines[0]["trace_id"].as_str().unwrap();
        assert_eq!(root_trace_id.len(), 32);
        assert_ne!(root_trace_id, TraceId::INVALID.to_string());
        assert_eq!(lines[0]["span_id"].as_str().unwrap().len(), 16);
        assert_eq!(lines[0]["fields"]["request_id"], "abc");

        assert_eq!(lines[1]["trace_id"], root_trace_id);
        assert_ne!(lines[1]["span_id"], lines[0]["span_id"]);
    }

    #[test]
    fn leaves_events_outside_a_span_unchanged() {
        let lines = capture_lines(|| tracing::info!("no span"));

        assert_eq!(lines.len(), 1);
        assert!(lines[0].get("trace_id").is_none());
        assert!(lines[0].get("span_id").is_none());
        assert_eq!(lines[0]["fields"]["message"], "no span");
    }
}
