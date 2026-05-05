use std::collections::HashMap;
use std::fmt;

use futures::stream::FuturesUnordered;
use futures::StreamExt;

use crate::v1::context::Context;
use crate::v1::sinks::event::Event;
use crate::v1::sinks::sink::Sink;
use crate::v1::sinks::types::SinkResult;
use crate::v1::sinks::SinkName;

// ---------------------------------------------------------------------------
// RouterError
// ---------------------------------------------------------------------------

/// Batch-level routing errors. These are caller bugs (requesting a sink that
/// doesn't exist), not per-event concerns.
#[derive(Debug)]
pub enum RouterError {
    SinkNotFound(SinkName),
}

impl fmt::Display for RouterError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::SinkNotFound(name) => write!(f, "sink not found: {name}"),
        }
    }
}

impl std::error::Error for RouterError {}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

/// Routes publish requests to the appropriate [`Sink`] by [`SinkName`].
///
/// Owns the mapping of configured sink names to concrete sink implementations
/// and the default sink for single-write mode.
pub struct Router {
    default: SinkName,
    sinks: HashMap<SinkName, Box<dyn Sink>>,
}

impl Router {
    pub fn new(default: SinkName, sinks: HashMap<SinkName, Box<dyn Sink>>) -> Self {
        Self { default, sinks }
    }

    pub fn default_sink(&self) -> SinkName {
        self.default
    }

    pub fn available_sinks(&self) -> Vec<SinkName> {
        self.sinks.keys().copied().collect()
    }

    /// Publish a batch of events to the named sink.
    pub async fn publish_batch(
        &self,
        sink: SinkName,
        ctx: &Context,
        events: &[&(dyn Event + Send + Sync)],
    ) -> Result<Vec<Box<dyn SinkResult>>, RouterError> {
        let target = self
            .sinks
            .get(&sink)
            .ok_or(RouterError::SinkNotFound(sink))?;
        Ok(target.publish_batch(ctx, events).await)
    }

    /// Convenience wrapper for single-event publish.
    pub async fn publish(
        &self,
        sink: SinkName,
        ctx: &Context,
        event: &(dyn Event + Send + Sync),
    ) -> Result<Option<Box<dyn SinkResult>>, RouterError> {
        let results = self.publish_batch(sink, ctx, &[event]).await?;
        Ok(results.into_iter().next())
    }

    /// Flush all sinks concurrently for graceful shutdown.
    pub async fn flush(&self) -> anyhow::Result<()> {
        let mut futs = FuturesUnordered::new();
        for (name, sink) in &self.sinks {
            let name = *name;
            futs.push(async move { sink.flush().await.map_err(|e| (name, e)) });
        }
        let mut errors: Vec<String> = Vec::new();
        while let Some(result) = futs.next().await {
            if let Err((name, e)) = result {
                errors.push(format!("sink {name}: {e:#}"));
            }
        }
        if errors.is_empty() {
            Ok(())
        } else {
            Err(anyhow::anyhow!("{}", errors.join("; ")))
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::Arc;
    use std::time::Duration;

    use common_types::CapturedEventHeaders;
    use uuid::Uuid;

    use crate::config::CaptureMode;
    use crate::v1::context::Context;
    use crate::v1::sinks::event::Event;
    use crate::v1::sinks::kafka::mock::MockProducer;
    use crate::v1::sinks::kafka::sink::KafkaSink;
    use crate::v1::sinks::sink::Sink;
    use crate::v1::sinks::types::Outcome;
    use crate::v1::sinks::{Config, Destination, SinkName};

    use super::*;

    // -- Test helpers --------------------------------------------------------

    struct FakeEvent {
        parsed_uuid: Uuid,
        publish: bool,
        destination: Destination,
    }

    impl FakeEvent {
        fn ok(_uuid: &str) -> Self {
            Self {
                parsed_uuid: Uuid::new_v4(),
                publish: true,
                destination: Destination::AnalyticsMain,
            }
        }

        fn with_publish(mut self, p: bool) -> Self {
            self.publish = p;
            self
        }
    }

    impl Event for FakeEvent {
        fn uuid(&self) -> Uuid {
            self.parsed_uuid
        }

        fn should_publish(&self) -> bool {
            self.publish
        }
        fn destination(&self) -> &Destination {
            &self.destination
        }
        fn headers(&self, _ctx: &Context) -> CapturedEventHeaders {
            CapturedEventHeaders {
                token: None,
                distinct_id: None,
                session_id: None,
                timestamp: None,
                event: None,
                uuid: None,
                now: None,
                force_disable_person_processing: None,
                historical_migration: None,
                dlq_reason: None,
                dlq_step: None,
                dlq_timestamp: None,
            }
        }
        fn partition_key<'buf>(&self, _ctx: &Context, buf: &'buf mut String) -> Option<&'buf str> {
            use std::fmt::Write;
            let _ = write!(buf, "key:{}", self.uuid());
            Some(buf.as_str())
        }
        fn serialize_into(&self, _ctx: &Context, buf: &mut String) -> anyhow::Result<()> {
            buf.push_str(r#"{"event":"test"}"#);
            Ok(())
        }
    }

    fn build_sink(name: SinkName, handle: lifecycle::Handle) -> Box<dyn Sink> {
        let producer = Arc::new(MockProducer::new(name, handle.clone()));
        let config = Config {
            produce_timeout: Duration::from_secs(30),
            kafka: crate::v1::test_utils::test_kafka_config(),
        };
        Box::new(KafkaSink::new(
            name,
            producer,
            config,
            CaptureMode::Events,
            handle,
        ))
    }

    fn test_router(
        default: SinkName,
        names: &[SinkName],
    ) -> (Router, lifecycle::Handle, lifecycle::MonitorGuard) {
        let mut manager = lifecycle::Manager::builder("test")
            .with_trap_signals(false)
            .with_prestop_check(false)
            .build();
        let handle = manager.register("router_test", lifecycle::ComponentOptions::new());
        handle.report_healthy();
        let monitor = manager.monitor_background();

        let sinks: HashMap<SinkName, Box<dyn Sink>> = names
            .iter()
            .map(|&n| (n, build_sink(n, handle.clone())))
            .collect();
        let router = Router::new(default, sinks);
        (router, handle, monitor)
    }

    fn test_ctx() -> Context {
        let mut ctx = crate::v1::test_utils::test_context();
        ctx.created_at = None;
        ctx
    }

    // -- Tests ---------------------------------------------------------------

    #[test]
    fn default_sink_returns_configured_default() {
        let (router, _handle, _monitor) = test_router(SinkName::Msk, &[SinkName::Msk]);
        assert_eq!(router.default_sink(), SinkName::Msk);
    }

    #[test]
    fn available_sinks_returns_all_configured() {
        let (router, _handle, _monitor) =
            test_router(SinkName::Msk, &[SinkName::Msk, SinkName::Ws]);
        let mut available = router.available_sinks();
        available.sort_by_key(|n| n.as_str());
        assert_eq!(available, vec![SinkName::Msk, SinkName::Ws]);
    }

    #[tokio::test]
    async fn publish_batch_routes_to_correct_sink() {
        let (router, _handle, _monitor) =
            test_router(SinkName::Msk, &[SinkName::Msk, SinkName::Ws]);
        let ctx = test_ctx();
        let event = FakeEvent::ok("evt-1");
        let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

        let results = router
            .publish_batch(SinkName::Msk, &ctx, &events)
            .await
            .unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].outcome(), Outcome::Success);
    }

    #[tokio::test]
    async fn publish_batch_sink_not_found() {
        let (router, _handle, _monitor) = test_router(SinkName::Msk, &[SinkName::Msk]);
        let ctx = test_ctx();
        let event = FakeEvent::ok("evt-1");
        let events: Vec<&(dyn Event + Send + Sync)> = vec![&event];

        match router.publish_batch(SinkName::Ws, &ctx, &events).await {
            Err(RouterError::SinkNotFound(SinkName::Ws)) => {}
            Err(e) => panic!("expected SinkNotFound(Ws), got: {e}"),
            Ok(_) => panic!("expected error, got Ok"),
        }
    }

    #[tokio::test]
    async fn publish_single_event_success() {
        let (router, _handle, _monitor) = test_router(SinkName::Msk, &[SinkName::Msk]);
        let ctx = test_ctx();
        let event = FakeEvent::ok("evt-1");

        let result = router.publish(SinkName::Msk, &ctx, &event).await.unwrap();
        assert!(result.is_some());
        assert_eq!(result.unwrap().outcome(), Outcome::Success);
    }

    #[tokio::test]
    async fn publish_single_non_publishable_returns_none() {
        let (router, _handle, _monitor) = test_router(SinkName::Msk, &[SinkName::Msk]);
        let ctx = test_ctx();
        let event = FakeEvent::ok("evt-1").with_publish(false);

        let result = router.publish(SinkName::Msk, &ctx, &event).await.unwrap();
        assert!(result.is_none());
    }

    #[tokio::test]
    async fn publish_sink_not_found() {
        let (router, _handle, _monitor) = test_router(SinkName::Msk, &[SinkName::Msk]);
        let ctx = test_ctx();
        let event = FakeEvent::ok("evt-1");

        match router.publish(SinkName::Ws, &ctx, &event).await {
            Err(RouterError::SinkNotFound(SinkName::Ws)) => {}
            Err(e) => panic!("expected SinkNotFound(Ws), got: {e}"),
            Ok(_) => panic!("expected error, got Ok"),
        }
    }

    #[tokio::test]
    async fn flush_all_sinks() {
        let (router, _handle, _monitor) =
            test_router(SinkName::Msk, &[SinkName::Msk, SinkName::Ws]);
        assert!(router.flush().await.is_ok());
    }
}
