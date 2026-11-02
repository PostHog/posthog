//! Reads every partition of the compared topics with one consumer. It assigns the partitions
//! itself instead of joining a group, so each replica sees both sides of every partition. The
//! comparator creates no producer, so it cannot write to any topic.

use std::time::{Duration, Instant};

use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::{Offset, TopicPartitionList};

use crate::service::kafka_source::to_kafka_message;

use super::{Comparator, Side, Stream};

/// The comparator's group ends with this, so it never equals a Node, ClickHouse or shadow group.
pub const COMPARE_GROUP_SUFFIX: &str = "-rust-shadow-compare";

pub fn compare_group_id(raw: &str) -> anyhow::Result<String> {
    let group = raw.trim();
    anyhow::ensure!(
        group.len() > COMPARE_GROUP_SUFFIX.len() && group.ends_with(COMPARE_GROUP_SUFFIX),
        "LOGS_SHADOW_COMPARE_GROUP_ID must end with {COMPARE_GROUP_SUFFIX:?}, got {raw:?}"
    );
    Ok(group.to_string())
}

#[derive(Debug, Clone)]
pub struct TopicPlan {
    pub topic: String,
    pub side: Side,
    pub stream: Stream,
}

/// Assigns every partition of every planned topic from its committed offset. Partitions added
/// later are not read until a restart.
pub fn assign_all_partitions(
    consumer: &StreamConsumer,
    plan: &[TopicPlan],
    timeout: Duration,
) -> anyhow::Result<()> {
    // The all-topics request, because a request that names a topic can create it.
    let metadata = consumer.fetch_metadata(None, timeout)?;
    let mut tpl = TopicPartitionList::new();
    for p in plan {
        let topic = metadata
            .topics()
            .iter()
            .find(|t| t.name() == p.topic && t.error().is_none() && !t.partitions().is_empty())
            .ok_or_else(|| anyhow::anyhow!("compared topic {} does not exist", p.topic))?;
        for partition in topic.partitions() {
            tpl.add_partition_offset(&p.topic, partition.id(), Offset::Stored)?;
        }
    }
    consumer.assign(&tpl)?;
    Ok(())
}

/// Feeds the comparator until `stop` resolves, or until no message arrived for `idle` when one
/// is given. Sweeps once a second. A fatal consumer error ends it with that error.
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
            Ok(Err(e)) if is_fatal(consumer, &e) => {
                return Err(anyhow::anyhow!("comparator consumer failed: {e}"))
            }
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

fn is_fatal(consumer: &StreamConsumer, error: &KafkaError) -> bool {
    matches!(error, KafkaError::MessageConsumptionFatal(_))
        || consumer.client().fatal_error().is_some()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compare_group_must_carry_the_reserved_suffix() {
        assert_eq!(
            compare_group_id(" ingestion-logs-rust-shadow-compare ").unwrap(),
            "ingestion-logs-rust-shadow-compare"
        );
        for bad in [
            "ingestion-logs",
            "ingestion-logs-rust-shadow",
            "group1",
            COMPARE_GROUP_SUFFIX,
        ] {
            assert!(compare_group_id(bad).is_err(), "{bad}");
        }
    }
}
