//! Offsets are stored once a batch's task and every earlier one succeeded. A task's timeout runs from its dispatch, as `trackTask` does.

use std::collections::{BTreeMap, VecDeque};
use std::time::Duration;

use async_trait::async_trait;
use futures::future::BoxFuture;
use ingestion_framework::KafkaMessage;
use tokio::task::JoinHandle;
use tokio::time::Instant;

use super::config::ConsumerLoopConfig;

pub type BackgroundTask = BoxFuture<'static, anyhow::Result<()>>;

pub type OffsetsToStore = Vec<(String, i32, i64)>;

#[async_trait]
pub trait BatchSource: Send {
    async fn next_batch(
        &mut self,
        max: usize,
        timeout: Duration,
    ) -> anyhow::Result<Vec<KafkaMessage>>;
    fn epochs(&self, offsets: &OffsetsToStore) -> Vec<u64> {
        vec![0; offsets.len()]
    }
    fn store_offsets(&mut self, offsets: &OffsetsToStore, epochs: &[u64]) -> anyhow::Result<()>;
    fn commit(&mut self) -> anyhow::Result<()>;
}

#[async_trait]
pub trait BatchProcessor: Send + Sync {
    async fn process(&self, messages: Vec<KafkaMessage>) -> anyhow::Result<Option<BackgroundTask>>;
}

#[async_trait]
impl BatchProcessor for crate::pipeline::LogsIngestionConsumer {
    async fn process(&self, messages: Vec<KafkaMessage>) -> anyhow::Result<Option<BackgroundTask>> {
        Ok(self.process_kafka_batch(messages).await?.background_task)
    }
}

pub fn offsets_to_store(messages: &[KafkaMessage]) -> OffsetsToStore {
    let mut highest: BTreeMap<(String, i32), i64> = BTreeMap::new();
    for m in messages {
        let entry = highest
            .entry((m.topic.clone(), m.partition))
            .or_insert(m.offset);
        *entry = (*entry).max(m.offset);
    }
    highest
        .into_iter()
        .map(|((topic, partition), offset)| (topic, partition, offset + 1))
        .collect()
}

struct InFlight {
    task: JoinHandle<anyhow::Result<()>>,
    offsets: OffsetsToStore,
    epochs: Vec<u64>,
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct LoopStats {
    pub batches: u64,
    pub messages: u64,
}

async fn settle(entry: InFlight, source: &mut dyn BatchSource) -> anyhow::Result<()> {
    let result = match entry.task.await {
        Err(join_error) => Err(anyhow::anyhow!("background task panicked: {join_error}")),
        Ok(result) => result,
    };
    if let Err(error) = result {
        tracing::error!(error = %error, "kafka_consumer_background_task_failed");
        metrics::counter!("logs_ingestion_consumer_background_task_failed_total").increment(1);
        return Err(error);
    }
    source.store_offsets(&entry.offsets, &entry.epochs)?;
    Ok(())
}

/// Either way it commits what was stored.
pub async fn run_consumer_loop(
    source: &mut dyn BatchSource,
    processor: &dyn BatchProcessor,
    config: &ConsumerLoopConfig,
    shutdown: impl std::future::Future<Output = ()> + Send,
    on_tick: &(dyn Fn() + Send + Sync),
) -> anyhow::Result<LoopStats> {
    tokio::pin!(shutdown);
    let mut in_flight: VecDeque<InFlight> = VecDeque::new();
    let mut stats = LoopStats::default();
    let mut outcome: anyhow::Result<()> = Ok(());
    let telemetry = &config.telemetry;
    let mut last_poll: Option<Instant> = None;
    loop {
        on_tick();
        while in_flight.front().is_some_and(|f| f.task.is_finished()) {
            let entry = in_flight.pop_front().unwrap();
            if let Err(e) = settle(entry, source).await {
                outcome = Err(e);
                break;
            }
        }
        if outcome.is_err() {
            break;
        }
        let poll_started = Instant::now();
        if let Some(last) = last_poll.replace(poll_started) {
            telemetry.consume_interval(poll_started - last);
        }
        let batch = tokio::select! {
            biased;
            _ = &mut shutdown => break,
            batch = source.next_batch(config.batch_size, config.batch_timeout) => batch,
        };
        let messages = match batch {
            Ok(m) => m,
            Err(e) => {
                outcome = Err(e);
                break;
            }
        };
        telemetry.poll(&messages, config.batch_size);
        if messages.is_empty() {
            continue;
        }
        stats.batches += 1;
        stats.messages += messages.len() as u64;
        let offsets = offsets_to_store(&messages);
        let epochs = source.epochs(&offsets);
        let process_started = Instant::now();
        let task = match processor.process(messages).await {
            Ok(task) => task,
            Err(e) => {
                outcome = Err(e);
                break;
            }
        };
        telemetry.batch_processed(process_started.elapsed());
        let timeout = config.background_task_timeout;
        let task_telemetry = telemetry.clone();
        let task = tokio::spawn(async move {
            let Some(task) = task else { return Ok(()) };
            let task_started = Instant::now();
            let result = match tokio::time::timeout(timeout, task).await {
                Ok(result) => result,
                Err(_) => Err(anyhow::anyhow!(
                    "background_task_timeout_after_{}ms",
                    timeout.as_millis()
                )),
            };
            task_telemetry.background_task_settled(task_started.elapsed());
            result
        });
        in_flight.push_back(InFlight {
            task,
            offsets,
            epochs,
        });
        if in_flight.len() >= config.max_background_tasks {
            let entry = in_flight.pop_front().unwrap();
            let wait_started = Instant::now();
            let settled = settle(entry, source).await;
            telemetry.backpressure_released(wait_started.elapsed());
            if let Err(e) = settled {
                outcome = Err(e);
                break;
            }
        }
    }
    if outcome.is_ok() {
        let drain_started = (!in_flight.is_empty()).then(Instant::now);
        while let Some(entry) = in_flight.pop_front() {
            if let Err(e) = settle(entry, source).await {
                outcome = Err(e);
                break;
            }
        }
        if let Some(started) = drain_started {
            telemetry.shutdown_drained(started.elapsed());
        }
    } else {
        for entry in in_flight {
            entry.task.abort();
        }
    }
    if let Err(error) = source.commit() {
        tracing::error!(error = %error, "final offset commit failed");
    }
    outcome.map(|()| stats)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::service::consumer_telemetry::{
        assert_metric_lines, bucket_bounds, render_metrics_of, ConsumerTelemetry,
    };
    use futures::FutureExt;
    use std::sync::{Arc, Mutex};

    #[derive(Default)]
    struct FakeSource {
        batches: VecDeque<Vec<KafkaMessage>>,
        stored: Arc<Mutex<Vec<OffsetsToStore>>>,
        commits: Arc<Mutex<u32>>,
    }

    #[async_trait]
    impl BatchSource for FakeSource {
        async fn next_batch(
            &mut self,
            _max: usize,
            timeout: Duration,
        ) -> anyhow::Result<Vec<KafkaMessage>> {
            match self.batches.pop_front() {
                Some(b) => Ok(b),
                None => {
                    tokio::time::sleep(timeout).await;
                    Ok(vec![])
                }
            }
        }
        fn store_offsets(
            &mut self,
            offsets: &OffsetsToStore,
            _epochs: &[u64],
        ) -> anyhow::Result<()> {
            self.stored.lock().unwrap().push(offsets.clone());
            Ok(())
        }
        fn commit(&mut self) -> anyhow::Result<()> {
            *self.commits.lock().unwrap() += 1;
            Ok(())
        }
    }

    #[derive(Default)]
    struct FakeProcessor {
        fail_task_at: Vec<i64>,
        fail_batch_at: Vec<i64>,
        hang_task_at: Vec<i64>,
        process_time: Duration,
        task_time: Option<Duration>,
    }

    #[async_trait]
    impl BatchProcessor for FakeProcessor {
        async fn process(
            &self,
            messages: Vec<KafkaMessage>,
        ) -> anyhow::Result<Option<BackgroundTask>> {
            let first = messages[0].offset;
            if self.fail_batch_at.contains(&first) {
                anyhow::bail!("batch failed");
            }
            let fail = self.fail_task_at.contains(&first);
            let hang = self.hang_task_at.contains(&first);
            tokio::time::sleep(self.process_time).await;
            let task_time = self.task_time.unwrap_or(Duration::from_millis(5));
            Ok(Some(
                async move {
                    if hang {
                        futures::future::pending::<()>().await;
                    }
                    tokio::time::sleep(task_time).await;
                    if fail {
                        anyhow::bail!("produce failed")
                    }
                    Ok(())
                }
                .boxed(),
            ))
        }
    }

    fn msg(partition: i32, offset: i64) -> KafkaMessage {
        KafkaMessage {
            topic: "in".into(),
            partition,
            offset,
            ..Default::default()
        }
    }

    fn config(max_background_tasks: usize) -> ConsumerLoopConfig {
        ConsumerLoopConfig {
            batch_size: 10,
            batch_timeout: Duration::from_millis(1),
            max_background_tasks,
            background_task_timeout: Duration::from_secs(5),
            telemetry: ConsumerTelemetry::new("in", "group", "pod-0"),
        }
    }

    async fn run(
        batches: Vec<Vec<KafkaMessage>>,
        processor: FakeProcessor,
        max_background_tasks: usize,
    ) -> (anyhow::Result<LoopStats>, Vec<OffsetsToStore>, u32) {
        let mut source = FakeSource {
            batches: batches.into(),
            ..Default::default()
        };
        let stored = source.stored.clone();
        let commits = source.commits.clone();
        let result = run_consumer_loop(
            &mut source,
            &processor,
            &config(max_background_tasks),
            tokio::time::sleep(Duration::from_millis(200)),
            &|| {},
        )
        .await;
        let stored = stored.lock().unwrap().clone();
        let commits = *commits.lock().unwrap();
        (result, stored, commits)
    }

    fn batches() -> Vec<Vec<KafkaMessage>> {
        vec![
            vec![msg(0, 0), msg(1, 7), msg(0, 1)],
            vec![msg(0, 2)],
            vec![msg(1, 8)],
        ]
    }

    #[tokio::test]
    async fn offsets_are_stored_in_order_after_each_task_succeeds() {
        for max in [1, 3] {
            let processor = FakeProcessor {
                fail_task_at: vec![],
                fail_batch_at: vec![],
                ..Default::default()
            };
            let (result, stored, commits) = run(batches(), processor, max).await;
            assert_eq!(result.unwrap().batches, 3);
            assert_eq!(
                stored,
                vec![
                    vec![("in".into(), 0, 2), ("in".into(), 1, 8)],
                    vec![("in".into(), 0, 3)],
                    vec![("in".into(), 1, 9)],
                ]
            );
            assert_eq!(commits, 1);
        }
    }

    #[tokio::test]
    async fn a_failed_task_stores_nothing_from_it_or_later_batches() {
        for max in [1, 3] {
            let processor = FakeProcessor {
                fail_task_at: vec![2],
                fail_batch_at: vec![],
                ..Default::default()
            };
            let (result, stored, commits) = run(batches(), processor, max).await;
            assert_eq!(result.unwrap_err().to_string(), "produce failed");
            assert_eq!(stored, vec![vec![("in".into(), 0, 2), ("in".into(), 1, 8)]]);
            assert_eq!(commits, 1);
        }
    }

    #[tokio::test]
    async fn a_hung_task_times_out_from_dispatch_when_traffic_stops() {
        let processor = FakeProcessor {
            hang_task_at: vec![2],
            ..Default::default()
        };
        let mut source = FakeSource {
            batches: batches().into(),
            ..Default::default()
        };
        let config = ConsumerLoopConfig {
            background_task_timeout: Duration::from_millis(50),
            ..config(3)
        };
        let result = tokio::time::timeout(
            Duration::from_secs(5),
            run_consumer_loop(
                &mut source,
                &processor,
                &config,
                futures::future::pending(),
                &|| {},
            ),
        )
        .await
        .expect("the loop must end without a shutdown or a full queue");
        assert_eq!(
            result.unwrap_err().to_string(),
            "background_task_timeout_after_50ms"
        );
        assert_eq!(source.stored.lock().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn a_failed_batch_stops_the_loop_before_its_offsets() {
        let processor = FakeProcessor {
            fail_task_at: vec![],
            fail_batch_at: vec![8],
            ..Default::default()
        };
        let (result, stored, _) = run(batches(), processor, 1).await;
        assert_eq!(result.unwrap_err().to_string(), "batch failed");
        assert_eq!(stored.len(), 2);
    }

    fn sized(offset: i64, bytes: usize) -> KafkaMessage {
        KafkaMessage {
            value: Some(bytes::Bytes::from(vec![0; bytes])),
            ..msg(0, offset)
        }
    }

    /// Three batches at 0, 250 and 750 ms, then empty polls of 125 ms from 1000 ms. Each task ends 750 ms after its poll.
    fn metrics_after(shutdown_at: Duration) -> String {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_time()
            .start_paused(true)
            .build()
            .unwrap();
        render_metrics_of(|| {
            runtime.block_on(async {
                let mut source = FakeSource {
                    batches: vec![
                        vec![sized(0, 1024), sized(1, 1024), sized(2, 1024)],
                        vec![sized(3, 512)],
                        vec![msg(0, 4)],
                    ]
                    .into(),
                    ..Default::default()
                };
                let processor = FakeProcessor {
                    process_time: Duration::from_millis(250),
                    task_time: Some(Duration::from_millis(500)),
                    ..Default::default()
                };
                let config = ConsumerLoopConfig {
                    batch_timeout: Duration::from_millis(125),
                    ..config(2)
                };
                run_consumer_loop(
                    &mut source,
                    &processor,
                    &config,
                    tokio::time::sleep(shutdown_at),
                    &|| {},
                )
                .await
                .unwrap();
            })
        })
    }

    #[test]
    fn the_loop_reports_the_metrics_of_the_node_consumer() {
        let labels = r#"topic="in",groupId="group""#;
        let after_an_empty_poll = metrics_after(Duration::from_millis(1200));
        assert_metric_lines(
            &after_an_empty_poll,
            &[
                &format!("kafka_consumer_polls_total{{{labels}}} 4"),
                r#"consumer_batch_utilization{groupId="group"} 0"#,
                "consumer_batch_size_sum 5",
                "consumer_batch_size_count 4",
                r#"consumer_batch_size_bucket{le="3000"} 4"#,
                "consumer_batch_size_kb_sum 3.5",
                r#"consumer_batch_size_kb_bucket{le="204800"} 4"#,
                &format!("kafka_consume_interval_ms_sum{{{labels}}} 1125"),
                &format!("kafka_consume_interval_ms_count{{{labels}}} 4"),
                &format!(r#"kafka_consume_interval_ms_bucket{{{labels},le="60000"}} 4"#),
                &format!("consumed_batch_duration_ms_sum{{{labels}}} 750"),
                &format!("consumed_batch_duration_ms_count{{{labels}}} 3"),
                &format!("consumed_batch_background_duration_ms_sum{{{labels}}} 1.5"),
                &format!("consumed_batch_background_duration_ms_count{{{labels}}} 3"),
                &format!("consumed_batch_backpressure_duration_ms_sum{{{labels}}} 0.25"),
                &format!("consumed_batch_backpressure_duration_ms_count{{{labels}}} 2"),
                &format!(
                    r#"kafka_consumer_drain_duration_ms_sum{{{labels},cause="shutdown"}} 0.3"#
                ),
                &format!(
                    r#"kafka_consumer_drain_duration_ms_bucket{{{labels},cause="shutdown",le="120000"}} 1"#
                ),
            ],
        );
        for histogram in [
            "consumed_batch_duration_ms",
            "consumed_batch_background_duration_ms",
            "consumed_batch_backpressure_duration_ms",
        ] {
            assert_eq!(
                bucket_bounds(&after_an_empty_poll, histogram),
                [
                    "0.005", "0.01", "0.025", "0.05", "0.1", "0.25", "0.5", "1", "2.5", "5", "10",
                    "+Inf"
                ],
                "{histogram}"
            );
        }
        let after_a_batch = metrics_after(Duration::from_millis(1050));
        assert_metric_lines(
            &after_a_batch,
            &[
                &format!("kafka_consumer_polls_total{{{labels}}} 3"),
                r#"consumer_batch_utilization{groupId="group"} 0.1"#,
            ],
        );
    }
}
