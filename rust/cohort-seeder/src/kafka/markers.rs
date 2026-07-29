//! Tails the membership-change topic for `reconcile_complete` markers — the completion *authority*.
//!
//! An assign-only consumer with a unique throwaway group id: it never subscribes and never commits, so
//! it participates in no rebalance and leaves no durable offset. It watches every membership partition
//! from explicit start offsets (the high watermarks captured at dispatch), with `auto.offset.reset=
//! error` so a start below the log's low watermark surfaces as [`WatchError::Truncated`] instead of
//! silently jumping. The topic is high-volume and person-keyed; markers are the rare key that contains
//! `':'` (`"{team}:{cohort}:{run}"`), so that byte probe rejects membership rows before any JSON parse.
//! Non-marker messages still advance the partition's next-read offset. rdkafka types stay confined
//! here — the watcher yields typed [`WatchItem`]s.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use common_kafka::config::KafkaConfig;
use futures::stream::{self, StreamExt, TryStreamExt};
use metrics::counter;
use rdkafka::consumer::{Consumer, StreamConsumer};
use rdkafka::error::KafkaError;
use rdkafka::message::Message;
use rdkafka::{ClientConfig, Offset, TopicPartitionList};

use crate::domain::{
    MarkerPartition, MembershipPartition, NextOffset, ObservedMarker, ReconcileCompleteMarker,
    WatchPositions,
};
use crate::observability::metrics::RECONCILE_MARKER_PARSE_FAILURES;

/// In-flight watermark fetches during a seek, matching the group-lag scanner's bound.
const WATERMARK_CONCURRENCY: usize = 16;

/// One record read from the membership topic: where the watcher now sits on that partition, and the
/// marker it carried (if any). Non-marker rows carry `marker: None` but still advance `next_offset`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WatchItem {
    pub partition: MembershipPartition,
    pub next_offset: NextOffset,
    pub marker: Option<ObservedMarker>,
}

/// An assign-only consumer over the membership topic. Holds an rdkafka `StreamConsumer` behind an
/// `Arc` so the (infrequent, blocking) watermark check can run on the blocking pool while `recv` keeps
/// borrowing it. The app-level `MarkerStream` seam wraps it so the watch task can be tested with a fake.
pub struct MarkerWatcher {
    consumer: Arc<StreamConsumer>,
    topic: String,
    watermark_timeout: Duration,
}

impl MarkerWatcher {
    /// Create the consumer without assigning any partitions. The first [`Self::seek_to`] seeks it to
    /// the watched runs' start offsets.
    pub fn new(
        kafka: &KafkaConfig,
        topic: String,
        group_id: &str,
        watermark_timeout: Duration,
    ) -> Result<Self, WatchError> {
        let consumer: Arc<StreamConsumer> = Arc::new(
            build_config(kafka, group_id)
                .create()
                .map_err(WatchError::Consumer)?,
        );
        Ok(Self {
            consumer,
            topic,
            watermark_timeout,
        })
    }

    /// Re-assign the consumer to read from `start` on every named partition. Unconditional — the app's
    /// watch state decides *when* a seek is needed (a run was added or re-dispatched); re-reading is
    /// safe because bit folds and position advances are idempotent. Each start offset is checked
    /// against the log's low watermark first, so a start below retention surfaces as
    /// [`WatchError::Truncated`] rather than a silent reset. The blocking watermark calls run on the
    /// blocking pool.
    pub async fn seek_to(&mut self, start: &WatchPositions) -> Result<(), WatchError> {
        let lows = self.low_watermarks(start).await?;
        let tpl = build_assignment(&self.topic, start, &lows)?;
        self.consumer.assign(&tpl).map_err(WatchError::Assign)?;
        // Records queued under the previous assignment can still be sitting in librdkafka's fetch
        // queue here. They are discarded rather than delivered: `assign` bumps each partition's
        // fetch version, and the client drops messages tagged with a stale version. The watch state
        // relies on that — a leaked pre-seek record would advance coverage past markers the rewound
        // run never read.
        Ok(())
    }

    /// Fetch every watched partition's low watermark, one blocking call each, bounded-concurrent
    /// like `ingestion-control-plane`'s group-lag scan. Each call can block for the full watermark
    /// timeout, and a seek covers all 64 membership partitions, so serializing them against an
    /// unresponsive broker overruns the watch task's liveness deadline.
    async fn low_watermarks(
        &self,
        start: &WatchPositions,
    ) -> Result<HashMap<MembershipPartition, i64>, WatchError> {
        let partitions: Vec<MembershipPartition> = start.iter().map(|(p, _)| p).collect();
        stream::iter(partitions)
            .map(|partition| {
                let consumer = Arc::clone(&self.consumer);
                let topic = self.topic.clone();
                let timeout = self.watermark_timeout;
                async move {
                    tokio::task::spawn_blocking(move || {
                        consumer
                            .fetch_watermarks(&topic, partition.get(), timeout)
                            .map(|(low, _high)| (partition, low))
                            .map_err(|source| WatchError::Watermarks {
                                partition: partition.get(),
                                source,
                            })
                    })
                    .await
                    .map_err(WatchError::WatermarkJoin)?
                }
            })
            .buffer_unordered(WATERMARK_CONCURRENCY)
            .try_collect()
            .await
    }

    /// Drop every assigned partition. The consumer stays alive and re-assigns on the next
    /// [`Self::seek_to`].
    pub fn unassign(&self) -> Result<(), WatchError> {
        self.consumer
            .assign(&TopicPartitionList::new())
            .map_err(WatchError::Assign)
    }

    /// Await the next record and classify it. A membership row yields `marker: None`; a keyed record
    /// that fails to parse increments the parse-failure counter and still advances the offset.
    pub async fn next_item(&self) -> Result<WatchItem, WatchError> {
        let message = self.consumer.recv().await.map_err(WatchError::Recv)?;
        let partition = MembershipPartition::new(message.partition());
        let next_offset = NextOffset::from_high_watermark(message.offset() + 1);
        let marker = classify_marker(message.key(), message.payload());
        Ok(WatchItem {
            partition,
            next_offset,
            marker,
        })
    }
}

/// Build the assignment TPL for `start`, rejecting any partition whose start fell out of retention.
/// `start` iterates in partition order, so the truncation reported is the lowest offending partition
/// rather than whichever watermark call happened to return first.
fn build_assignment(
    topic: &str,
    start: &WatchPositions,
    lows: &HashMap<MembershipPartition, i64>,
) -> Result<TopicPartitionList, WatchError> {
    let mut tpl = TopicPartitionList::new();
    for (partition, next) in start.iter() {
        // `lows` covers these same partitions, so the fallback is unreachable.
        let low = lows.get(&partition).copied().unwrap_or(0);
        if next.get() < low {
            return Err(WatchError::Truncated {
                partition: partition.get(),
                requested: next.get(),
                low,
            });
        }
        tpl.add_partition_offset(topic, partition.get(), Offset::Offset(next.get()))
            .map_err(WatchError::Assign)?;
    }
    Ok(tpl)
}

/// Cheap discriminator then parse. Markers are keyed `"{team}:{cohort}:{run}"`; membership rows are
/// keyed by a person UUID (no `':'`), so the byte probe skips the JSON parse for the common case.
fn classify_marker(key: Option<&[u8]>, payload: Option<&[u8]>) -> Option<ObservedMarker> {
    let key = key?;
    if !key.contains(&b':') {
        return None;
    }
    let Some(payload) = payload else {
        counter!(RECONCILE_MARKER_PARSE_FAILURES).increment(1);
        return None;
    };
    let marker = match serde_json::from_slice::<ReconcileCompleteMarker>(payload) {
        Ok(marker) => marker,
        Err(_) => {
            counter!(RECONCILE_MARKER_PARSE_FAILURES).increment(1);
            return None;
        }
    };
    match MarkerPartition::new(u32::from(marker.partition())) {
        Ok(partition) => Some(ObservedMarker {
            team_id: marker.team_id(),
            cohort_id: marker.cohort_id(),
            partition,
            run_id: marker.run_id(),
        }),
        Err(_) => {
            counter!(RECONCILE_MARKER_PARSE_FAILURES).increment(1);
            None
        }
    }
}

fn build_config(kafka: &KafkaConfig, group_id: &str) -> ClientConfig {
    let mut config = ClientConfig::new();
    config
        .set("bootstrap.servers", &kafka.kafka_hosts)
        .set("group.id", group_id)
        .set("enable.auto.commit", "false")
        .set("enable.auto.offset.store", "false")
        // A start position outside the retained log is a real event (retention outran the watcher);
        // fail loudly rather than silently reset so the run is re-dispatched.
        .set("auto.offset.reset", "error");
    if kafka.kafka_tls {
        config
            .set("security.protocol", "ssl")
            .set("enable.ssl.certificate.verification", "false");
    }
    if !kafka.kafka_client_rack.is_empty() {
        config.set("client.rack", &kafka.kafka_client_rack);
    }
    config
}

#[derive(Debug, thiserror::Error)]
pub enum WatchError {
    #[error("creating the marker-watch consumer")]
    Consumer(#[source] KafkaError),
    #[error("fetching watermarks for membership partition {partition}")]
    Watermarks {
        partition: i32,
        #[source]
        source: KafkaError,
    },
    #[error("joining the membership watermark task")]
    WatermarkJoin(#[source] tokio::task::JoinError),
    #[error(
        "membership partition {partition} start offset {requested} is below the log's low watermark \
         {low}: the topic was truncated past the captured watch position"
    )]
    Truncated {
        partition: i32,
        requested: i64,
        low: i64,
    },
    #[error("assigning the marker-watch partitions")]
    Assign(#[source] KafkaError),
    #[error("receiving from the membership topic")]
    Recv(#[source] KafkaError),
}

#[cfg(test)]
mod tests {
    use super::*;
    use cohort_core::filters::{CohortId, TeamId};
    use cohort_core::seed::RunId;
    use uuid::Uuid;

    fn marker_payload(partition: u16) -> Vec<u8> {
        serde_json::to_vec(&ReconcileCompleteMarker::new(
            TeamId(2),
            CohortId(42),
            partition,
            RunId(Uuid::nil()),
            "2026-05-26 12:34:56.789123".to_string(),
        ))
        .unwrap()
    }

    #[test]
    fn classify_probes_the_key_before_parsing_and_extracts_the_marker() {
        // Person-keyed membership row: no ':' in the key, so no parse attempt, no marker.
        assert!(classify_marker(Some(b"01928aaa-bbbb-cccc"), Some(b"{}")).is_none());

        // A marker key with a valid payload.
        let observed = classify_marker(Some(b"2:42:run"), Some(&marker_payload(7))).unwrap();
        assert_eq!(observed.team_id, TeamId(2));
        assert_eq!(observed.cohort_id, CohortId(42));
        assert_eq!(observed.partition.get(), 7);

        // A key that passes the probe but a payload that is not a marker: dropped, not a marker.
        assert!(classify_marker(Some(b"2:42:run"), Some(b"{\"not\":\"a marker\"}")).is_none());

        // A marker whose partition is outside the bitmap range is corrupt: dropped.
        assert!(classify_marker(Some(b"2:42:run"), Some(&marker_payload(64))).is_none());
    }

    #[test]
    fn a_start_below_the_low_watermark_is_truncation_and_the_boundary_is_not() {
        // A start exactly at the low watermark is the normal case right after a retention sweep.
        // Reporting it as truncated would drop and tombstone every run on the partition.
        let partition = MembershipPartition::new(0);
        let lows = HashMap::from([(partition, 20_i64)]);
        let positions = |offset| {
            let mut positions = WatchPositions::new();
            positions.insert(partition, NextOffset::from_high_watermark(offset));
            positions
        };

        assert!(matches!(
            build_assignment(TOPIC, &positions(5), &lows),
            Err(WatchError::Truncated {
                partition: 0,
                requested: 5,
                low: 20
            })
        ));

        let tpl = build_assignment(TOPIC, &positions(20), &lows).unwrap();
        assert_eq!(
            tpl.find_partition(TOPIC, 0).map(|entry| entry.offset()),
            Some(Offset::Offset(20))
        );
    }

    const TOPIC: &str = "cohort_membership_changed_shadow";
}
