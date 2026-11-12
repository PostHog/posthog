//! librdkafka reports the result of a manual commit only when the commit is
//! synchronous, and it does not retry a rejected one. So every commit here is
//! synchronous, and a rejected offset goes out again in the next round.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use common_kafka_consumer::{Offset, TopicPartition};
use metrics::{counter, gauge};
use rdkafka::consumer::{CommitMode, Consumer, StreamConsumer};
use rdkafka::error::{KafkaError, RDKafkaErrorCode};
use rdkafka::TopicPartitionList;
use tokio::sync::Notify;
use tokio::task::JoinHandle;
use tracing::warn;

use crate::rebalance::RebalanceContext;

pub(crate) trait CommitClient: Send + Sync + 'static {
    fn commit_sync(&self, offsets: &HashMap<TopicPartition, Offset>) -> Result<(), KafkaError>;
}

impl CommitClient for StreamConsumer<RebalanceContext> {
    fn commit_sync(&self, offsets: &HashMap<TopicPartition, Offset>) -> Result<(), KafkaError> {
        let mut tpl = TopicPartitionList::new();
        for (topic_partition, next_to_read) in offsets {
            tpl.add_partition_offset(
                &topic_partition.topic,
                topic_partition.partition,
                rdkafka::Offset::Offset(next_to_read.0),
            )?;
        }
        self.commit(&tpl, CommitMode::Sync)
    }
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum CommitError {
    #[error(transparent)]
    Kafka(#[from] KafkaError),
    #[error("the commit task failed: {0}")]
    Task(#[from] tokio::task::JoinError),
}

impl CommitError {
    /// Group membership, the coordinator, partition metadata and the network
    /// recover on their own.
    /// Any other error fails again for the same offsets.
    fn is_retriable(&self) -> bool {
        let Self::Kafka(KafkaError::ConsumerCommit(code)) = self else {
            return false;
        };
        matches!(
            code,
            RDKafkaErrorCode::StaleMemberEpoch
                | RDKafkaErrorCode::FencedMemberEpoch
                | RDKafkaErrorCode::UnknownMemberId
                | RDKafkaErrorCode::IllegalGeneration
                | RDKafkaErrorCode::RebalanceInProgress
                | RDKafkaErrorCode::UnknownTopicOrPartition
                | RDKafkaErrorCode::NotCoordinator
                | RDKafkaErrorCode::CoordinatorNotAvailable
                | RDKafkaErrorCode::CoordinatorLoadInProgress
                | RDKafkaErrorCode::WaitingForCoordinator
                | RDKafkaErrorCode::BrokerTransportFailure
                | RDKafkaErrorCode::NetworkException
                | RDKafkaErrorCode::RequestTimedOut
                | RDKafkaErrorCode::OperationTimedOut
        )
    }

    fn kind(&self) -> &'static str {
        match self {
            Self::Kafka(KafkaError::ConsumerCommit(code)) => match code {
                RDKafkaErrorCode::StaleMemberEpoch => "stale_member_epoch",
                RDKafkaErrorCode::FencedMemberEpoch => "fenced_member_epoch",
                RDKafkaErrorCode::UnknownMemberId => "unknown_member_id",
                RDKafkaErrorCode::IllegalGeneration => "illegal_generation",
                RDKafkaErrorCode::RebalanceInProgress => "rebalance_in_progress",
                RDKafkaErrorCode::UnknownTopicOrPartition => "unknown_topic_or_partition",
                RDKafkaErrorCode::NotCoordinator
                | RDKafkaErrorCode::CoordinatorNotAvailable
                | RDKafkaErrorCode::CoordinatorLoadInProgress
                | RDKafkaErrorCode::WaitingForCoordinator => "coordinator",
                RDKafkaErrorCode::BrokerTransportFailure | RDKafkaErrorCode::NetworkException => {
                    "network"
                }
                RDKafkaErrorCode::RequestTimedOut | RDKafkaErrorCode::OperationTimedOut => {
                    "timeout"
                }
                _ => "other",
            },
            Self::Kafka(_) => "client",
            Self::Task(_) => "task",
        }
    }
}

pub(crate) struct Committer {
    shared: Arc<Shared>,
    task: JoinHandle<()>,
}

#[derive(Default)]
struct Shared {
    state: Mutex<State>,
    queued: Notify,
    round_done: Notify,
    stopped: Notify,
}

#[derive(Default)]
struct State {
    queued: HashMap<TopicPartition, Offset>,
    in_flight: HashMap<TopicPartition, Offset>,
    stopped: bool,
    stop_reason: Option<CommitError>,
}

enum Round {
    Committed,
    Retry,
    Stop,
}

impl State {
    fn pending(&self, topic_partition: &TopicPartition) -> bool {
        self.queued.contains_key(topic_partition) || self.in_flight.contains_key(topic_partition)
    }
}

impl Committer {
    /// `retry_wait` follows a failed commit. librdkafka sends a heartbeat
    /// early after a `STALE_MEMBER_EPOCH`, and its answer carries the new epoch.
    pub(crate) fn start<C: CommitClient>(client: Arc<C>, retry_wait: Duration) -> Self {
        let shared = Arc::new(Shared::default());
        let task = tokio::spawn(run(Arc::clone(&shared), client, retry_wait));
        Self { shared, task }
    }

    pub(crate) fn submit(&self, offsets: &HashMap<TopicPartition, Offset>) {
        let mut state = self.shared.state();
        for (topic_partition, offset) in offsets {
            state.queued.insert(topic_partition.clone(), *offset);
        }
        drop(state);
        self.shared.queued.notify_one();
    }

    /// A commit in flight for these partitions still lands, but a rejected one
    /// is not sent again.
    pub(crate) fn forget(&self, topic_partitions: &[TopicPartition]) {
        let mut state = self.shared.state();
        for topic_partition in topic_partitions {
            state.queued.remove(topic_partition);
            state.in_flight.remove(topic_partition);
        }
        drop(state);
        self.shared.round_done.notify_waiters();
    }

    /// False when `timeout` passes first or the committer stopped.
    pub(crate) async fn flush(
        &self,
        topic_partitions: &[TopicPartition],
        timeout: Duration,
    ) -> bool {
        self.wait_until(timeout, |state| {
            !topic_partitions
                .iter()
                .any(|topic_partition| state.pending(topic_partition))
        })
        .await
    }

    /// Call before the client closes. The close bumps the member epoch, and the
    /// broker rejects every commit that arrives after it, retries included.
    pub(crate) async fn flush_all(&self, timeout: Duration) -> bool {
        self.wait_until(timeout, |state| {
            state.queued.is_empty() && state.in_flight.is_empty()
        })
        .await
    }

    pub(crate) async fn stopped(&self) -> CommitError {
        loop {
            let stopped = self.shared.stopped.notified();
            tokio::pin!(stopped);
            stopped.as_mut().enable();
            if let Some(err) = self.shared.state().stop_reason.take() {
                return err;
            }
            stopped.await;
        }
    }

    async fn wait_until(&self, timeout: Duration, done: impl Fn(&State) -> bool) -> bool {
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            let round_done = self.shared.round_done.notified();
            tokio::pin!(round_done);
            round_done.as_mut().enable();
            {
                let state = self.shared.state();
                if state.stopped {
                    return false;
                }
                if done(&state) {
                    return true;
                }
            }
            if tokio::time::timeout_at(deadline, round_done).await.is_err() {
                return false;
            }
        }
    }
}

impl Drop for Committer {
    fn drop(&mut self) {
        self.task.abort();
    }
}

impl Shared {
    fn state(&self) -> MutexGuard<'_, State> {
        self.state.lock().unwrap()
    }

    fn start_round(&self) -> Option<HashMap<TopicPartition, Offset>> {
        let mut state = self.state();
        if state.queued.is_empty() {
            return None;
        }
        state.in_flight = std::mem::take(&mut state.queued);
        Some(state.in_flight.clone())
    }

    fn finish_round(&self, result: Result<(), CommitError>) -> Round {
        let mut state = self.state();
        let sent = std::mem::take(&mut state.in_flight);
        let round = match result {
            Ok(()) => {
                for (topic_partition, offset) in &sent {
                    record_committed(topic_partition, *offset);
                }
                Round::Committed
            }
            Err(err) => {
                counter!("ingestion_consumer_commit_failures_total", "kind" => err.kind())
                    .increment(1);
                warn!(error = %err, "Offset commit failed");
                if err.is_retriable() {
                    for (topic_partition, offset) in sent {
                        state.queued.entry(topic_partition).or_insert(offset);
                    }
                    Round::Retry
                } else {
                    state.stopped = true;
                    state.stop_reason = Some(err);
                    Round::Stop
                }
            }
        };
        drop(state);
        self.round_done.notify_waiters();
        if matches!(round, Round::Stop) {
            self.stopped.notify_waiters();
        }
        round
    }
}

async fn run<C: CommitClient>(shared: Arc<Shared>, client: Arc<C>, retry_wait: Duration) {
    loop {
        let Some(offsets) = shared.start_round() else {
            shared.queued.notified().await;
            continue;
        };
        let commit_client = Arc::clone(&client);
        let result =
            match tokio::task::spawn_blocking(move || commit_client.commit_sync(&offsets)).await {
                Ok(committed) => committed.map_err(CommitError::from),
                Err(join_error) => Err(CommitError::from(join_error)),
            };
        match shared.finish_round(result) {
            Round::Committed => {}
            Round::Retry => tokio::time::sleep(retry_wait).await,
            Round::Stop => return,
        }
    }
}

fn record_committed(topic_partition: &TopicPartition, next_to_read: Offset) {
    gauge!(
        "ingestion_consumer_committed_offset",
        "topic" => topic_partition.topic.clone(),
        "partition" => topic_partition.partition.to_string(),
    )
    .set(next_to_read.0 as f64);
}

#[cfg(test)]
mod tests {
    use std::collections::VecDeque;
    use std::sync::mpsc;

    use tokio::sync::mpsc::{unbounded_channel, UnboundedReceiver, UnboundedSender};

    use super::*;

    const RETRY_WAIT: Duration = Duration::from_millis(1);
    const FLUSH: Duration = Duration::from_secs(5);

    enum Reply {
        Accept,
        Fail(KafkaError),
        Hold(mpsc::Receiver<Reply>),
    }

    fn stale_member_epoch() -> Reply {
        Reply::Fail(KafkaError::ConsumerCommit(
            RDKafkaErrorCode::StaleMemberEpoch,
        ))
    }

    struct FakeClient {
        replies: Mutex<VecDeque<Reply>>,
        reject_once_replies_run_out: bool,
        calls: Mutex<Vec<HashMap<TopicPartition, Offset>>>,
        started: UnboundedSender<()>,
    }

    impl CommitClient for FakeClient {
        fn commit_sync(&self, offsets: &HashMap<TopicPartition, Offset>) -> Result<(), KafkaError> {
            self.calls.lock().unwrap().push(offsets.clone());
            let _ = self.started.send(());
            let mut reply = self.replies.lock().unwrap().pop_front().unwrap_or(
                if self.reject_once_replies_run_out {
                    stale_member_epoch()
                } else {
                    Reply::Accept
                },
            );
            while let Reply::Hold(release) = reply {
                reply = release.recv().expect("the test releases a held commit");
            }
            match reply {
                Reply::Accept => Ok(()),
                Reply::Fail(error) => Err(error),
                Reply::Hold(_) => unreachable!(),
            }
        }
    }

    struct Fixture {
        committer: Committer,
        client: Arc<FakeClient>,
        started: UnboundedReceiver<()>,
    }

    impl Fixture {
        fn with_replies(replies: Vec<Reply>) -> Self {
            Self::start(replies, false)
        }

        fn rejecting_every_commit() -> Self {
            Self::start(vec![], true)
        }

        fn start(replies: Vec<Reply>, reject_once_replies_run_out: bool) -> Self {
            let (started_tx, started) = unbounded_channel();
            let client = Arc::new(FakeClient {
                replies: Mutex::new(replies.into()),
                reject_once_replies_run_out,
                calls: Mutex::new(Vec::new()),
                started: started_tx,
            });
            let committer = Committer::start(Arc::clone(&client), RETRY_WAIT);
            Self {
                committer,
                client,
                started,
            }
        }

        fn holding_the_first_commit(rest: Vec<Reply>) -> (Self, mpsc::Sender<Reply>) {
            let (release, held) = mpsc::channel();
            let mut replies = vec![Reply::Hold(held)];
            replies.extend(rest);
            (Self::with_replies(replies), release)
        }

        async fn wait_for_a_commit_to_start(&mut self) {
            self.started.recv().await.expect("the client is alive");
        }

        fn calls(&self) -> Vec<HashMap<TopicPartition, Offset>> {
            self.client.calls.lock().unwrap().clone()
        }
    }

    fn p(partition: i32) -> TopicPartition {
        TopicPartition::new("events", partition)
    }

    fn offsets(entries: &[(i32, i64)]) -> HashMap<TopicPartition, Offset> {
        entries
            .iter()
            .map(|&(partition, offset)| (p(partition), Offset(offset)))
            .collect()
    }

    #[tokio::test]
    async fn a_submitted_offset_is_committed_and_the_flush_returns() {
        let fixture = Fixture::with_replies(vec![]);
        fixture.committer.submit(&offsets(&[(0, 1), (1, 2)]));

        assert!(fixture.committer.flush_all(FLUSH).await);
        assert_eq!(fixture.calls(), vec![offsets(&[(0, 1), (1, 2)])]);
    }

    #[tokio::test]
    async fn offsets_queued_during_a_commit_go_out_together_in_the_next_one() {
        let (mut fixture, release) = Fixture::holding_the_first_commit(vec![]);
        fixture.committer.submit(&offsets(&[(0, 1)]));
        fixture.wait_for_a_commit_to_start().await;

        fixture.committer.submit(&offsets(&[(0, 2)]));
        fixture.committer.submit(&offsets(&[(1, 5)]));
        fixture.committer.submit(&offsets(&[(0, 3)]));
        release.send(Reply::Accept).unwrap();

        assert!(fixture.committer.flush_all(FLUSH).await);
        assert_eq!(
            fixture.calls(),
            vec![offsets(&[(0, 1)]), offsets(&[(0, 3), (1, 5)])]
        );
    }

    #[rstest::rstest]
    #[case::stale_member_epoch(RDKafkaErrorCode::StaleMemberEpoch)]
    #[case::unknown_topic_or_partition(RDKafkaErrorCode::UnknownTopicOrPartition)]
    #[tokio::test]
    async fn a_rejected_offset_goes_out_again_unless_a_newer_one_replaced_it(
        #[case] code: RDKafkaErrorCode,
    ) {
        let (mut fixture, release) = Fixture::holding_the_first_commit(vec![]);
        fixture.committer.submit(&offsets(&[(0, 1), (1, 1)]));
        fixture.wait_for_a_commit_to_start().await;

        fixture.committer.submit(&offsets(&[(0, 2)]));
        release
            .send(Reply::Fail(KafkaError::ConsumerCommit(code)))
            .unwrap();

        assert!(fixture.committer.flush_all(FLUSH).await);
        assert_eq!(
            fixture.calls(),
            vec![offsets(&[(0, 1), (1, 1)]), offsets(&[(0, 2), (1, 1)])]
        );
    }

    #[tokio::test]
    async fn a_flush_times_out_while_the_broker_keeps_rejecting() {
        let fixture = Fixture::rejecting_every_commit();
        fixture.committer.submit(&offsets(&[(0, 1)]));

        assert!(!fixture.committer.flush_all(Duration::from_millis(50)).await);
        let calls = fixture.calls();
        assert!(calls.len() > 1, "the committer keeps retrying");
        assert!(calls.iter().all(|call| *call == offsets(&[(0, 1)])));
    }

    #[tokio::test]
    async fn a_flush_waits_only_for_its_own_partitions() {
        let (mut fixture, release) = Fixture::holding_the_first_commit(vec![]);
        fixture.committer.submit(&offsets(&[(0, 1)]));
        fixture.wait_for_a_commit_to_start().await;

        assert!(fixture.committer.flush(&[p(1)], FLUSH).await);
        assert!(
            !fixture
                .committer
                .flush(&[p(0)], Duration::from_millis(20))
                .await
        );
        release.send(Reply::Accept).unwrap();
        assert!(fixture.committer.flush(&[p(0)], FLUSH).await);
    }

    #[rstest::rstest]
    #[case::client_error(KafkaError::SetPartitionOffset(RDKafkaErrorCode::InvalidArgument))]
    #[case::permanent_broker_error(KafkaError::ConsumerCommit(
        RDKafkaErrorCode::GroupAuthorizationFailed
    ))]
    #[tokio::test]
    async fn an_error_retrying_cannot_fix_stops_the_committer(#[case] error: KafkaError) {
        let fixture = Fixture::with_replies(vec![Reply::Fail(error.clone())]);
        fixture.committer.submit(&offsets(&[(0, 1)]));

        let stop_reason = tokio::time::timeout(FLUSH, fixture.committer.stopped())
            .await
            .expect("the committer stops");
        assert!(matches!(stop_reason, CommitError::Kafka(err) if err == error));
        assert!(!fixture.committer.flush(&[p(0)], FLUSH).await);
        assert!(!fixture.committer.flush_all(FLUSH).await);
        fixture.committer.submit(&offsets(&[(0, 2)]));
        assert!(!fixture.committer.flush_all(FLUSH).await);
        assert_eq!(fixture.calls(), vec![offsets(&[(0, 1)])]);
    }

    struct ForgetCase {
        in_flight_reply: Reply,
        calls: Vec<HashMap<TopicPartition, Offset>>,
    }

    #[rstest::rstest]
    #[case::in_flight_commit_accepted(ForgetCase {
        in_flight_reply: Reply::Accept,
        calls: vec![offsets(&[(0, 1), (1, 1)])],
    })]
    #[case::in_flight_commit_rejected(ForgetCase {
        in_flight_reply: stale_member_epoch(),
        calls: vec![offsets(&[(0, 1), (1, 1)]), offsets(&[(1, 1)])],
    })]
    #[tokio::test]
    async fn a_forgotten_partition_gets_no_further_commits(#[case] case: ForgetCase) {
        let (mut fixture, release) = Fixture::holding_the_first_commit(vec![]);
        fixture.committer.submit(&offsets(&[(0, 1), (1, 1)]));
        fixture.wait_for_a_commit_to_start().await;

        fixture.committer.submit(&offsets(&[(0, 2)]));
        fixture.committer.forget(&[p(0)]);
        release.send(case.in_flight_reply).unwrap();

        assert!(fixture.committer.flush_all(FLUSH).await);
        assert_eq!(fixture.calls(), case.calls);
    }
}
