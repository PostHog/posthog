//! Reads the compared topics with one consumer of the comparator's own group. The comparator
//! creates no producer, so it cannot write to any topic.

use std::time::{Duration, Instant};

use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::error::KafkaError;

use crate::service::kafka_source::to_kafka_message;

use super::{Comparator, Side, Stream};

#[derive(Debug, Clone)]
pub struct TopicPlan {
    pub topic: String,
    pub side: Side,
    pub stream: Stream,
}

pub fn subscribe(consumer: &StreamConsumer, plan: &[TopicPlan]) -> anyhow::Result<()> {
    let topics: Vec<&str> = plan.iter().map(|p| p.topic.as_str()).collect();
    consumer.subscribe(&topics)?;
    Ok(())
}

/// Feeds the comparator until `stop` resolves, or until no message arrived for `idle` when one
/// is given. Sweeps once a second.
pub async fn run_compare(
    consumer: &StreamConsumer,
    plan: &[TopicPlan],
    comparator: &mut Comparator,
    idle: Option<Duration>,
    stop: impl std::future::Future<Output = ()>,
) -> anyhow::Result<()> {
    tokio::pin!(stop);
    let mut last_message = Instant::now();
    let mut seen_any = false;
    let mut last_report = Instant::now();
    loop {
        let recv = tokio::time::timeout(Duration::from_secs(1), consumer.recv());
        let received = tokio::select! {
            _ = &mut stop => return Ok(()),
            r = recv => r,
        };
        let now = Instant::now();
        match received {
            Err(_) => comparator.sweep(now),
            Ok(Err(KafkaError::PartitionEOF(_))) => {}
            Ok(Err(e)) => tracing::warn!(error = %e, "comparator consume error"),
            Ok(Ok(m)) => {
                let message = to_kafka_message(&m);
                if let Some(p) = plan.iter().find(|p| p.topic == message.topic) {
                    comparator.ingest(p.side, p.stream, &message, now);
                }
                last_message = now;
                seen_any = true;
            }
        }
        if now.duration_since(last_report) > Duration::from_secs(60) {
            let r = comparator.report();
            tracing::info!(
                matched = r.matched,
                mismatched = r.mismatched,
                node_only = r.node_only,
                rust_only = r.rust_only,
                warmup_unmatched = r.warmup_unmatched,
                pending = comparator.pending(),
                "shadow comparison"
            );
            last_report = now;
        }
        if let Some(idle) = idle {
            if seen_any && now.duration_since(last_message) > idle {
                return Ok(());
            }
        }
    }
}
