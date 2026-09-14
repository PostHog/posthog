use super::*;

use std::pin::Pin;
use std::sync::OnceLock;

use common_kafka_consumer::{AssignmentEpoch, Offset as MessageOffset};
use futures::{stream, Stream};
use lifecycle::{ComponentOptions, LifecycleError, Manager, MonitorGuard};
use rdkafka::error::{KafkaError, KafkaResult, RDKafkaErrorCode};
use rdkafka::message::{OwnedMessage, Timestamp};
use tokio::sync::{oneshot, Mutex as AsyncMutex};
use tokio_util::sync::CancellationToken;

use crate::consumer_io::{BatchSubmitter, KafkaInput};
use crate::order_sentinel::SentinelContext;

const TEST_TIMEOUT: Duration = Duration::from_secs(5);
const TOPIC: &str = "test";
type Commit = Vec<(String, i32, i64)>;

enum Input {
    Message(OwnedMessage),
    Revoke(Vec<i32>),
    Assign(Vec<i32>),
    Barrier(oneshot::Sender<()>),
    Error(KafkaError),
    Fatal(RDKafkaErrorCode, String),
}

struct ScriptedKafka {
    context: SentinelContext,
    inputs: AsyncMutex<mpsc::UnboundedReceiver<Input>>,
    commits: mpsc::UnboundedSender<Commit>,
    fatal: OnceLock<(RDKafkaErrorCode, String)>,
}

fn partition_list(partitions: &[i32]) -> TopicPartitionList {
    let mut list = TopicPartitionList::new();
    for partition in partitions {
        list.add_partition(TOPIC, *partition);
    }
    list
}

impl KafkaInput for ScriptedKafka {
    type Message<'a> = OwnedMessage;
    type Stream<'a> = Pin<Box<dyn Stream<Item = KafkaResult<OwnedMessage>> + Send + 'a>>;

    fn stream(&self) -> Self::Stream<'_> {
        Box::pin(stream::unfold(self, |kafka| async move {
            loop {
                let input = kafka.inputs.lock().await.recv().await?;
                match input {
                    Input::Message(message) => return Some((Ok(message), kafka)),
                    Input::Revoke(partitions) => {
                        kafka.context.on_revoke(&partition_list(&partitions));
                    }
                    Input::Assign(partitions) => {
                        kafka.context.on_assign(&partition_list(&partitions));
                    }
                    Input::Barrier(ack) => {
                        let _ = ack.send(());
                    }
                    Input::Error(error) => return Some((Err(error), kafka)),
                    Input::Fatal(code, reason) => {
                        let _ = kafka.fatal.set((code, reason));
                        return Some((Err(KafkaError::MessageConsumption(code)), kafka));
                    }
                }
            }
        }))
    }

    fn context(&self) -> &SentinelContext {
        &self.context
    }

    fn commit(&self, offsets: &TopicPartitionList) -> KafkaResult<()> {
        let mut commit: Commit = offsets
            .elements()
            .iter()
            .map(|element| {
                let rdkafka::Offset::Offset(offset) = element.offset() else {
                    panic!("consumer must commit a concrete next-to-read offset");
                };
                (element.topic().to_string(), element.partition(), offset)
            })
            .collect();
        commit.sort();
        self.commits.send(commit).unwrap();
        Ok(())
    }

    fn fatal_error(&self) -> Option<(RDKafkaErrorCode, String)> {
        self.fatal.get().cloned()
    }

    fn fetch_committed_offsets(&self) -> KafkaResult<Option<Vec<(String, i32, i64)>>> {
        // These tests observe submission of commits, not broker persistence.
        Ok(None)
    }
}

struct Submission {
    accumulator: Accumulator,
    epoch: u64,
}

struct ScriptedBatcher {
    submissions: mpsc::UnboundedSender<Submission>,
    epoch: AssignmentEpoch,
}

impl BatchSubmitter for ScriptedBatcher {
    fn submit(&self, accumulator: Accumulator) -> u64 {
        let epoch = self.epoch.current();
        self.submissions
            .send(Submission { accumulator, epoch })
            .unwrap();
        epoch
    }

    fn purge_revoked(&self, _partitions: &[(String, i32)]) {
        // No scheduler is simulated: tests explicitly choose which work ACKs,
        // including late ACKs racing a purge.
    }

    fn scheduler_kind(&self) -> SchedulerKind {
        SchedulerKind::KeyTable
    }
}

struct Harness {
    inputs: mpsc::UnboundedSender<Input>,
    submissions: mpsc::UnboundedReceiver<Submission>,
    commits: mpsc::UnboundedReceiver<Commit>,
    completions: Option<mpsc::UnboundedSender<GroupCompletion>>,
    errors: mpsc::UnboundedSender<String>,
    shutdown: CancellationToken,
    process: JoinHandle<()>,
    monitor: Option<MonitorGuard>,
}

impl Harness {
    fn new(batch_size: usize, max_in_flight_batches: usize) -> Self {
        let (inputs, input_rx) = mpsc::unbounded_channel();
        let (commits_tx, commits) = mpsc::unbounded_channel();
        let (submissions_tx, submissions) = mpsc::unbounded_channel();
        let (completions, completion_rx) = mpsc::unbounded_channel();
        let (errors, error_rx) = mpsc::unbounded_channel();
        let epoch = AssignmentEpoch::new();
        let mut context = SentinelContext::detached();
        context.set_assignment_epoch(epoch.clone());
        let kafka = ScriptedKafka {
            context,
            inputs: AsyncMutex::new(input_rx),
            commits: commits_tx,
            fatal: OnceLock::new(),
        };
        let batcher = ScriptedBatcher {
            submissions: submissions_tx,
            epoch,
        };
        let mut manager = Manager::builder("consumer-boundary-test")
            .with_trap_signals(false)
            .build();
        let handle = manager.register("consumer", ComponentOptions::new());
        let shutdown = handle.shutdown_token();
        let monitor = manager.monitor_background();
        let consumer = IngestionConsumer::new(
            kafka,
            batcher,
            BatcherOutputs {
                completions: completion_rx,
                errors: error_rx,
            },
            IngestionConsumerOptions {
                batch_size,
                batch_size_bytes: 0,
                batch_timeout: Duration::from_secs(60),
                max_in_flight_batches,
                group_id: "consumer-boundary-test".to_string(),
                worker_urls: Vec::new(),
                debug_recorder: None,
            },
            handle,
        );
        Self {
            inputs,
            submissions,
            commits,
            completions: Some(completions),
            errors,
            shutdown,
            process: tokio::spawn(consumer.process()),
            monitor: Some(monitor),
        }
    }

    fn input(&self, input: Input) {
        self.inputs.send(input).unwrap();
    }

    fn messages(&self, partition: i32, offsets: &[i64]) {
        for offset in offsets {
            self.input(Input::Message(OwnedMessage::new(
                Some(b"payload".to_vec()),
                Some(b"key".to_vec()),
                TOPIC.to_string(),
                Timestamp::CreateTime(0),
                partition,
                *offset,
                None,
            )));
        }
    }

    async fn barrier(&self) {
        let (ack, received) = oneshot::channel();
        self.input(Input::Barrier(ack));
        tokio::time::timeout(TEST_TIMEOUT, received)
            .await
            .expect("consumer must reach the next Kafka input")
            .expect("Kafka input must acknowledge the barrier");
    }

    async fn submission(&mut self) -> Submission {
        tokio::time::timeout(TEST_TIMEOUT, self.submissions.recv())
            .await
            .expect("consumer must submit the collected poll")
            .expect("consumer must not stop before submission")
    }

    fn complete(&self, epoch: u64, partition: i32, offsets: &[i64], accepted: u32) {
        self.completions
            .as_ref()
            .unwrap()
            .send(GroupCompletion {
                partition: Partition(partition),
                assignment_epoch: epoch,
                offsets: offsets.iter().copied().map(MessageOffset).collect(),
                accepted,
            })
            .unwrap();
    }

    async fn commit(&mut self) -> Commit {
        tokio::time::timeout(TEST_TIMEOUT, self.commits.recv())
            .await
            .expect("acknowledged work must reach Kafka commit")
            .expect("consumer must not stop before committing")
    }

    async fn finish(mut self) -> (Vec<Commit>, Result<(), LifecycleError>) {
        tokio::time::timeout(TEST_TIMEOUT, &mut self.process)
            .await
            .expect("consumer must drain or fail without hanging")
            .expect("consumer task must not panic");
        let result = tokio::time::timeout(TEST_TIMEOUT, self.monitor.take().unwrap().wait())
            .await
            .expect("lifecycle monitor must terminate with the consumer");
        let mut commits = Vec::new();
        while let Ok(commit) = self.commits.try_recv() {
            commits.push(commit);
        }
        (commits, result)
    }
}

impl Drop for Harness {
    fn drop(&mut self) {
        self.shutdown.cancel();
        self.process.abort();
    }
}

fn committed(partitions: &[(i32, i64)]) -> Commit {
    partitions
        .iter()
        .map(|(partition, offset)| (TOPIC.to_string(), *partition, *offset))
        .collect()
}

#[tokio::test]
async fn later_completed_poll_commits_only_after_the_older_poll_at_next_to_read_frontiers() {
    let mut harness = Harness::new(2, 2);
    harness.messages(0, &[10, 11]);
    let first = harness.submission().await;
    harness.messages(0, &[12, 13]);
    let second = harness.submission().await;

    harness.shutdown.cancel();
    harness.complete(second.epoch, 0, &[12, 13], 2);
    harness.complete(first.epoch, 0, &[10, 11], 2);
    let (commits, result) = harness.finish().await;

    result.unwrap();
    assert_eq!(commits, [committed(&[(0, 12)]), committed(&[(0, 14)])]);
}

#[tokio::test]
async fn one_completion_can_cover_offsets_from_multiple_polls() {
    let mut harness = Harness::new(4, 2);
    harness.messages(0, &[0, 1, 2, 3]);
    let first = harness.submission().await;
    harness.messages(0, &[4, 5, 6, 7]);
    harness.submission().await;

    harness.shutdown.cancel();
    // A key-table run can merge a key's messages across poll boundaries.
    harness.complete(first.epoch, 0, &[2, 3, 4, 5], 4);
    harness.complete(first.epoch, 0, &[0, 1], 2);
    harness.complete(first.epoch, 0, &[6, 7], 2);
    let (commits, result) = harness.finish().await;

    result.unwrap();
    assert_eq!(commits, [committed(&[(0, 4)]), committed(&[(0, 8)])]);
}

#[tokio::test]
async fn under_acceptance_commits_the_accepted_prefix_but_fails_the_tail_poll() {
    let mut harness = Harness::new(2, 2);
    harness.messages(0, &[0, 1]);
    let first = harness.submission().await;
    harness.messages(0, &[2, 3]);
    harness.submission().await;

    harness.shutdown.cancel();
    harness.complete(first.epoch, 0, &[0, 1, 2, 3], 3);
    let (commits, result) = harness.finish().await;

    assert!(matches!(
        result,
        Err(LifecycleError::ComponentFailure { .. })
    ));
    assert_eq!(commits, [committed(&[(0, 2)])]);
}

#[tokio::test]
async fn partial_revoke_preserves_kept_work_and_removes_revoked_completion_credit() {
    let mut harness = Harness::new(4, 2);
    harness.messages(9, &[0, 1, 2, 3]);
    let control = harness.submission().await;
    harness.messages(0, &[0, 1]);
    harness.messages(1, &[10, 11]);
    let mixed = harness.submission().await;

    // FIFO completions followed by the older poll's commit form a positive
    // barrier: partition 1 has already received credit when it is revoked.
    harness.complete(mixed.epoch, 1, &[10], 1);
    harness.complete(control.epoch, 9, &[0, 1, 2, 3], 4);
    assert_eq!(harness.commit().await, committed(&[(9, 4)]));
    harness.barrier().await;
    harness.input(Input::Revoke(vec![1]));
    harness.messages(0, &[2, 3]);
    harness.messages(2, &[20, 21]);
    let next = harness.submission().await;

    harness.shutdown.cancel();
    harness.complete(mixed.epoch, 1, &[11], 1);
    harness.complete(mixed.epoch, 0, &[0, 1], 2);
    harness.complete(next.epoch, 0, &[2, 3], 2);
    harness.complete(next.epoch, 2, &[20, 21], 2);
    let (commits, result) = harness.finish().await;

    result.unwrap();
    assert_eq!(
        commits,
        [committed(&[(0, 2)]), committed(&[(0, 4), (2, 22)])]
    );
}

#[tokio::test]
async fn fully_revoked_poll_does_not_wait_for_an_ack_before_later_work_can_commit() {
    let mut harness = Harness::new(2, 2);
    harness.messages(0, &[0, 1]);
    harness.submission().await;
    harness.input(Input::Revoke(vec![0]));
    harness.messages(2, &[10, 11]);
    let kept = harness.submission().await;

    harness.shutdown.cancel();
    harness.complete(kept.epoch, 2, &[10, 11], 2);
    let (commits, result) = harness.finish().await;

    result.unwrap();
    assert_eq!(commits, [committed(&[(2, 12)])]);
}

#[tokio::test]
async fn historical_revoke_during_collection_allows_the_reassigned_replay_to_commit() {
    let mut harness = Harness::new(2, 1);
    harness.input(Input::Assign(vec![0]));
    harness.messages(0, &[0]);
    // Reaching the next input proves the first delivery was appended to the
    // still-open poll before the real rebalance callbacks reset its ledger.
    harness.barrier().await;
    harness.input(Input::Revoke(vec![0]));
    harness.input(Input::Assign(vec![0]));
    harness.messages(0, &[0]);
    let replay = harness.submission().await;
    let offsets: Vec<_> = replay
        .accumulator
        .into_groups()
        .into_iter()
        .flat_map(|group| group.messages.into_iter().map(|message| message.offset.0))
        .collect();
    assert_eq!(
        offsets,
        [0, 0],
        "both deliveries must share the collected poll"
    );

    // Both deliveries reach the batch boundary, but only the reassigned
    // delivery belongs to the current ledger generation.
    harness.complete(replay.epoch, 0, &[0, 0], 2);
    assert_eq!(harness.commit().await, committed(&[(0, 1)]));
    harness.shutdown.cancel();
    let (commits, result) = harness.finish().await;
    result.unwrap();
    assert!(commits.is_empty());
}

#[tokio::test]
async fn stale_epoch_and_unmatched_completions_cannot_acknowledge_replayed_work() {
    let mut harness = Harness::new(2, 2);
    harness.input(Input::Assign(vec![0]));
    harness.messages(0, &[0, 1]);
    let old = harness.submission().await;
    harness.input(Input::Revoke(vec![0]));
    harness.input(Input::Assign(vec![0]));
    harness.messages(0, &[0, 1]);
    let replay = harness.submission().await;

    harness.shutdown.cancel();
    harness.complete(old.epoch, 0, &[0, 1], 2);
    harness.complete(replay.epoch, 7, &[0, 1], 2);
    harness.complete(replay.epoch, 0, &[50, 51], 2);
    // Closing the completion stream is a deterministic barrier after all
    // invalid ACKs: the consumer must fail, not commit the unacknowledged replay.
    drop(harness.completions.take());
    let (commits, result) = harness.finish().await;

    assert!(matches!(
        result,
        Err(LifecycleError::ComponentFailure { .. })
    ));
    assert!(commits.is_empty());
}

#[tokio::test]
async fn batcher_failure_stops_the_consumer_without_committing_unacknowledged_work() {
    let mut harness = Harness::new(2, 1);
    harness.messages(0, &[0, 1]);
    harness.submission().await;
    harness
        .errors
        .send("worker rejected the batch".to_string())
        .unwrap();
    let (commits, result) = harness.finish().await;

    let Err(LifecycleError::ComponentFailure { reason, .. }) = result else {
        panic!("batcher failure must fail the consumer component");
    };
    assert!(reason.contains("worker rejected the batch"));
    assert!(commits.is_empty());
}

#[tokio::test]
async fn recoverable_kafka_error_flushes_collected_work_and_allows_later_progress() {
    let mut harness = Harness::new(4, 2);
    harness.messages(0, &[10, 11]);
    harness.input(Input::Error(KafkaError::PartitionEOF(0)));
    let partial = harness.submission().await;
    harness.messages(0, &[12, 13, 14, 15]);
    let next = harness.submission().await;

    harness.shutdown.cancel();
    harness.complete(partial.epoch, 0, &[10, 11], 2);
    harness.complete(next.epoch, 0, &[12, 13, 14, 15], 4);
    let (commits, result) = harness.finish().await;

    result.unwrap();
    assert_eq!(commits, [committed(&[(0, 12)]), committed(&[(0, 16)])]);
}

#[tokio::test]
async fn fatal_kafka_error_does_not_submit_or_commit_a_partially_collected_poll() {
    let mut harness = Harness::new(2, 1);
    harness.messages(0, &[0]);
    harness.barrier().await;
    harness.input(Input::Fatal(
        RDKafkaErrorCode::Unknown,
        "Kafka client is fenced".to_string(),
    ));
    tokio::time::timeout(TEST_TIMEOUT, &mut harness.process)
        .await
        .expect("fatal Kafka input must stop collection")
        .expect("consumer task must not panic");
    assert!(harness.submissions.try_recv().is_err());
    // The task was already joined; only the lifecycle result remains to await.
    let result = tokio::time::timeout(TEST_TIMEOUT, harness.monitor.take().unwrap().wait())
        .await
        .expect("lifecycle monitor must terminate");
    let Err(LifecycleError::ComponentFailure { reason, .. }) = result else {
        panic!("fatal Kafka input must fail the consumer component");
    };
    assert!(reason.contains("Kafka client is fenced"));
    assert!(harness.commits.try_recv().is_err());
}
