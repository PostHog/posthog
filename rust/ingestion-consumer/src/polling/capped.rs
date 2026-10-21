use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use common_kafka_consumer::{GroupCompletion, Offset, TopicPartition};
use lifecycle::Handle;
use metrics::{counter, gauge};
use tokio::sync::mpsc;
use tokio::time::Interval;
use tracing::{info, warn};

use super::poll::{debug_partition_offsets, InFlightPoll, PartitionDeliveries};
use super::{Collector, FetchingPartitions, LoopParts, RevokedPartition, Step};
use crate::debug_recorder::{record_if, DebugEventKind, DebugRecorder};
use crate::settlement::Settlement;

/// Collects a poll, submits it, and admits up to `max_in_flight_polls`
/// polls. When the cap is full it waits on the oldest poll, and applies
/// completions only while it waits.
pub(crate) struct CappedPolling {
    collector: Collector,
    completions: mpsc::UnboundedReceiver<GroupCompletion>,
    errors: mpsc::UnboundedReceiver<String>,
    settlement: Arc<dyn Settlement>,
    fetching: Arc<FetchingPartitions>,
    revoked_partitions: Arc<Mutex<Vec<RevokedPartition>>>,
    handle: Handle,
    commit_tick: Duration,
    group_id: String,
    debug_recorder: Option<Arc<DebugRecorder>>,
    max_in_flight_polls: usize,
    in_flight_polls: VecDeque<InFlightPoll>,
    accepting_new_batches: bool,
    /// Set while the loop waits on the oldest poll.
    heartbeat: Option<Interval>,
}

impl CappedPolling {
    pub(crate) fn new(parts: LoopParts, max_in_flight_polls: usize) -> Self {
        let LoopParts {
            collector,
            completions,
            errors,
            settlement,
            fetching,
            revoked_partitions,
            handle,
            commit_tick,
            group_id,
            debug_recorder,
        } = parts;
        Self {
            collector,
            completions,
            errors,
            settlement,
            fetching,
            revoked_partitions,
            handle,
            commit_tick,
            group_id,
            debug_recorder,
            max_in_flight_polls: max_in_flight_polls.max(1),
            in_flight_polls: VecDeque::new(),
            accepting_new_batches: true,
            heartbeat: None,
        }
    }

    pub(crate) async fn next(&mut self) -> Step {
        loop {
            if self.heartbeat.is_none() {
                if !self.accepting_new_batches && self.in_flight_polls.is_empty() {
                    return Step::Stop;
                }
                if let Some(step) = self.collect().await {
                    return step;
                }
                if self.heartbeat.is_none() {
                    continue;
                }
            }
            if let Some(step) = self.wait_on_oldest_poll().await {
                return step;
            }
        }
    }

    pub(crate) fn submitted(&mut self, poll: InFlightPoll) {
        self.in_flight_polls.push_back(poll);
        if self.in_flight_polls.len() >= self.max_in_flight_polls {
            self.start_waiting();
        }
    }

    /// Returns `None` when the loop must collect again or wait on the oldest
    /// poll; `heartbeat` tells which.
    async fn collect(&mut self) -> Option<Step> {
        self.drop_revoked_polls();
        // Consumer-level concurrency: how many Kafka batches are being
        // processed in parallel, bounded by `max_in_flight_polls`.
        gauge!("ingestion_consumer_in_flight_batches").set(self.in_flight_polls.len() as f64);

        // Not beside `collect_batch`: a tick there would drop a collection
        // in progress.
        if let Some(commit) = self.settlement.take_due(Instant::now()) {
            return Some(Step::Commit(commit));
        }

        let collect = self.accepting_new_batches
            && self.in_flight_polls.len() < self.max_in_flight_polls
            // Paused partitions fill no poll, so a collection would wait out the batch
            // timeout before the completions whose commits resume them.
            && (self.in_flight_polls.is_empty() || !self.fetching.all_paused());
        if collect {
            let collected = tokio::select! {
                _ = self.handle.shutdown_recv() => None,
                result = self.collector.collect_batch() => Some(result),
            };
            match collected {
                None => {
                    info!(
                        in_flight = self.in_flight_polls.len(),
                        "Shutdown signal received, draining in-flight batches"
                    );
                    self.accepting_new_batches = false;
                    self.start_waiting();
                    return Some(Step::BeginShutdown);
                }
                Some(Err(err)) => return Some(Step::Fail(err)),
                Some(Ok(collected)) if collected.accumulator.message_count() == 0 => {
                    self.handle.report_healthy();
                    if self.in_flight_polls.is_empty() {
                        return None;
                    }
                }
                Some(Ok(collected)) => return Some(Step::Submit(collected)),
            }
        }
        self.start_waiting();
        None
    }

    /// Wait for completions to cover the oldest in-flight poll, then retire
    /// it. Completions for newer polls are credited while waiting. Returns
    /// `None` when the loop must collect again.
    async fn wait_on_oldest_poll(&mut self) -> Option<Step> {
        loop {
            // A rebalance can drop the front poll (its partitions were
            // revoked and its purged messages will never complete), so
            // re-resolve it every pass instead of waiting on it forever.
            self.drop_revoked_polls();
            let Some(front) = self.in_flight_polls.front() else {
                self.stop_waiting();
                return None;
            };
            if front.is_complete() {
                return self.retire_oldest_poll();
            }
            let heartbeat = self.heartbeat.as_mut().expect("the loop is waiting");
            let woke = tokio::select! {
                completion = self.completions.recv() => Woke::Completion(completion),
                failure = self.errors.recv() => Woke::Error(failure),
                _ = heartbeat.tick() => Woke::Heartbeat,
            };
            match woke {
                Woke::Completion(Some(completion)) => {
                    let settlement = &self.settlement;
                    if let Err(err) = apply_completion(
                        &mut self.in_flight_polls,
                        &completion,
                        |tp, generation, run| settlement.settle_run(tp, generation, run),
                    ) {
                        return Some(Step::Fail(err));
                    }
                    if let Some(commit) = self.settlement.take_due(Instant::now()) {
                        // A resumed partition can fill a poll, so collect instead of waiting here.
                        if !commit.resume.is_empty() {
                            self.stop_waiting();
                        }
                        return Some(Step::Commit(commit));
                    }
                }
                Woke::Completion(None) => {
                    return Some(Step::Fail(anyhow::anyhow!(
                        "batcher completion channel closed"
                    )))
                }
                Woke::Error(Some(message)) => return Some(Step::Fail(anyhow::anyhow!(message))),
                Woke::Error(None) => {
                    return Some(Step::Fail(anyhow::anyhow!("batcher error channel closed")))
                }
                Woke::Heartbeat => {
                    self.handle.report_healthy();
                    let collectable = self.in_flight_polls.len() < self.max_in_flight_polls
                        && !self.fetching.all_paused();
                    match self.settlement.take_due(Instant::now()) {
                        Some(commit) => {
                            if !commit.resume.is_empty() || collectable {
                                self.stop_waiting();
                            }
                            return Some(Step::Commit(commit));
                        }
                        None if collectable => {
                            self.stop_waiting();
                            return None;
                        }
                        None => {}
                    }
                }
            }
        }
    }

    fn retire_oldest_poll(&mut self) -> Option<Step> {
        self.stop_waiting();
        let poll = match pop_committable(&mut self.in_flight_polls) {
            Ok(poll) => poll,
            Err(err) => return Some(Step::Fail(err)),
        };
        if let Err(err) = self.settlement.settle_poll(&poll.charged_slices()) {
            return Some(Step::Fail(err));
        }
        emit_latest_processed_timestamp_metrics(&poll.partitions, &self.group_id);
        record_if(&self.debug_recorder, || DebugEventKind::PollCompleted {
            batch_id: poll.poll_id.clone(),
            accepted: poll.accepted,
            duration_ms: poll.dispatched_at.elapsed().as_millis() as u64,
            partitions: debug_partition_offsets(&poll.partitions),
        });

        counter!("ingestion_consumer_messages_processed_total").increment(poll.accepted as u64);
        counter!("ingestion_consumer_batches_processed_total").increment(1);
        self.handle.report_healthy();

        self.settlement.take_due(Instant::now()).map(Step::Commit)
    }

    fn start_waiting(&mut self) {
        self.heartbeat = Some(tokio::time::interval_at(
            tokio::time::Instant::now() + self.commit_tick,
            self.commit_tick,
        ));
    }

    fn stop_waiting(&mut self) {
        self.heartbeat = None;
    }

    /// Drop in-flight polls holding a revoked partition. The key table
    /// purges those partitions' queued messages, so such a poll can never be
    /// covered; its offsets stay uncommitted and replay under the new
    /// assignment, and its late completions are discarded as stale.
    fn drop_revoked_polls(&mut self) {
        let revoked: Vec<RevokedPartition> =
            std::mem::take(&mut *self.revoked_partitions.lock().unwrap());
        if revoked.is_empty() {
            return;
        }
        let stripped = strip_revoked_partitions(&mut self.in_flight_polls, &revoked);
        if stripped > 0 {
            counter!("ingestion_consumer_polls_dropped_on_revoke_total").increment(stripped);
            info!(
                stripped,
                "Removed revoked partitions' messages from in-flight polls"
            );
        }
    }
}

enum Woke {
    Completion(Option<GroupCompletion>),
    Error(Option<String>),
    Heartbeat,
}

/// Remove revoked partitions from in-flight polls, and remove polls left
/// empty. Only slices from before that partition's revoke generation go: a
/// poll's kept or newly reassigned slices retain their counts and settle their
/// ledger charges at commit, so the frontier never crosses a hole.
fn strip_revoked_partitions(
    in_flight_polls: &mut VecDeque<InFlightPoll>,
    revoked: &[RevokedPartition],
) -> u64 {
    let mut stripped: u64 = 0;
    for poll in in_flight_polls.iter_mut() {
        let mut removed_delivered = 0u32;
        let mut removed_covered = 0u32;
        let mut removed_accepted = 0u32;
        poll.partitions.retain(|topic_partition, deliveries| {
            if revoked.iter().any(|revoked| {
                revoked.topic_partition == *topic_partition
                    && deliveries.generation < revoked.generation
            }) {
                removed_delivered += deliveries.delivered;
                removed_covered += deliveries.covered;
                removed_accepted += deliveries.accepted;
                false
            } else {
                true
            }
        });
        if removed_delivered > 0 {
            stripped += u64::from(removed_delivered);
            poll.message_count = poll.message_count.saturating_sub(removed_delivered);
            poll.covered = poll.covered.saturating_sub(removed_covered);
            poll.accepted = poll.accepted.saturating_sub(removed_accepted);
        }
    }
    in_flight_polls.retain(|poll| poll.message_count > 0);
    stripped
}

/// Credit each of a completion's offsets to the poll that contains it: the
/// one collected under the same assignment epoch whose span holds the offset.
/// Within one epoch, poll spans are disjoint per partition, so at most one
/// poll matches per offset. A key-table run merges messages from several
/// polls into one send, so one completion can span polls; crediting per
/// offset keeps every poll's count exact. Acceptance credits the leading
/// offsets, so a worker that under-reports shorts the tail poll's accepted
/// check, matching [`send_group_completions`]'s split across groups. An
/// offset that matches no poll (its partition was revoked and reassigned
/// while the group was out, or its poll is gone) is discarded; a completion
/// with any discarded offset counts as stale once.
///
/// [`send_group_completions`]: crate::batcher
fn apply_completion(
    in_flight: &mut VecDeque<InFlightPoll>,
    completion: &GroupCompletion,
    mut settle: impl FnMut(&TopicPartition, u64, &[Offset]) -> anyhow::Result<()>,
) -> anyhow::Result<()> {
    let fully_accepted = completion.accepted as usize == completion.offsets.len();
    let mut accepted = completion.accepted;
    let mut unmatched: u64 = 0;
    let mut remaining = completion.offsets.as_slice();
    'runs: while let Some(first) = remaining.first() {
        for poll in in_flight
            .iter_mut()
            .filter(|poll| poll.assignment_epoch == completion.assignment_epoch)
        {
            for (topic_partition, deliveries) in poll.partitions.iter_mut() {
                let span = deliveries.span;
                if topic_partition.partition != completion.partition.0
                    || first.0 < span.first
                    || span.last < first.0
                {
                    continue;
                }
                let run_len = remaining
                    .iter()
                    .take_while(|offset| span.first <= offset.0 && offset.0 <= span.last)
                    .count();
                let (run, rest) = remaining.split_at(run_len);
                let run_accepted = accepted.min(run_len as u32);
                accepted -= run_accepted;
                poll.covered += run_len as u32;
                poll.accepted += run_accepted;
                deliveries.covered += run_len as u32;
                deliveries.accepted += run_accepted;
                let settleable = deliveries.credit_run(run);
                if fully_accepted && !settleable.is_empty() {
                    settle(topic_partition, deliveries.generation, &settleable)?;
                }
                remaining = rest;
                continue 'runs;
            }
        }
        unmatched += 1;
        remaining = &remaining[1..];
    }
    if unmatched > 0 {
        counter!("ingestion_consumer_stale_group_completions_total").increment(1);
        warn!(
            partition = %completion.partition,
            unmatched,
            epoch = completion.assignment_epoch,
            "Discarding completion offsets that match no in-flight poll"
        );
    }
    Ok(())
}

/// Pops the front poll for its commit. A complete poll commits only when
/// workers accepted all of it and a completion covered every charged offset.
fn pop_committable(in_flight: &mut VecDeque<InFlightPoll>) -> anyhow::Result<InFlightPoll> {
    let poll = in_flight.pop_front().expect("front is present");
    if poll.accepted < poll.message_count {
        anyhow::bail!(
            "accepted {}/{} messages — not committing offsets",
            poll.accepted,
            poll.message_count
        );
    }
    if let Some((topic_partition, offset)) = poll.uncredited_charge() {
        counter!("ingestion_consumer_commit_violations_total", "kind" => "uncredited").increment(1);
        anyhow::bail!(
            "offset {} of {}/{} has no completion — not committing offsets",
            offset.0,
            topic_partition.topic,
            topic_partition.partition
        );
    }
    Ok(poll)
}

fn emit_latest_processed_timestamp_metrics(
    partitions: &HashMap<TopicPartition, PartitionDeliveries>,
    group_id: &str,
) {
    // Same name as the Node.js consumer's gauge, so one dashboard reads both.
    for (topic_partition, partition) in partitions {
        gauge!(
            "latest_processed_timestamp_ms",
            "topic" => topic_partition.topic.clone(),
            "partition" => topic_partition.partition.to_string(),
            "groupId" => group_id.to_string()
        )
        .set(partition.latest_kafka_ts as f64);
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;
    use std::time::Duration;

    use common_kafka_consumer::{Charge, Offset as MessageOffset, Partition, TopicOffsetLedger};

    use super::*;
    use crate::order_sentinel::OffsetSpan;
    use crate::partition_budget::BudgetLimits;
    use crate::polling::poll::Delivery;
    use crate::settlement::{charge_offsets, GroupSettlement};

    fn poll(epoch: u64, partition: i32, first: i64, last: i64, count: u32) -> InFlightPoll {
        let mut partitions = HashMap::new();
        partitions.insert(
            TopicPartition::new("test", partition),
            PartitionDeliveries {
                span: OffsetSpan { first, last },
                generation: 0,
                generations_version_seen: 0,
                charges: (first..=last)
                    .map(|offset| (MessageOffset(offset), Charge::ZERO))
                    .collect(),
                latest_kafka_ts: 0,
                max_lag_ms: None,
                delivered: count,
                covered: 0,
                accepted: 0,
                credited: HashSet::default(),
            },
        );
        InFlightPoll {
            poll_id: format!("poll-{epoch}-{partition}-{first}"),
            assignment_epoch: epoch,
            partitions,
            message_count: count,
            covered: 0,
            accepted: 0,
            dispatched_at: Instant::now(),
        }
    }

    fn completion(epoch: u64, partition: i32, offsets: &[i64], accepted: u32) -> GroupCompletion {
        GroupCompletion {
            partition: Partition(partition),
            assignment_epoch: epoch,
            offsets: offsets.iter().map(|o| MessageOffset(*o)).collect(),
            accepted,
        }
    }

    fn credit(in_flight: &mut VecDeque<InFlightPoll>, completion: GroupCompletion) {
        apply_completion(in_flight, &completion, |_, _, _| Ok(())).unwrap();
    }

    fn regained_poll(charged: i64, span_last: i64, delivered: u32) -> InFlightPoll {
        let mut poll = poll(1, 0, charged, charged, delivered);
        let deliveries = poll
            .partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap();
        deliveries.span.last = span_last;
        deliveries.generation = 2;
        poll
    }

    #[test]
    fn an_accepted_completion_settles_one_run_per_poll() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);
        in_flight[1]
            .partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap()
            .generation = 1;
        let mut runs = Vec::new();

        apply_completion(
            &mut in_flight,
            &completion(1, 0, &[2, 3, 4, 5], 4),
            |topic_partition, generation, offsets| {
                runs.push((topic_partition.partition, generation, offsets.to_vec()));
                Ok(())
            },
        )
        .unwrap();

        assert_eq!(
            runs,
            vec![
                (0, 0, vec![MessageOffset(2), MessageOffset(3)]),
                (0, 1, vec![MessageOffset(4), MessageOffset(5)]),
            ],
            "each run carries its own poll's generation"
        );
    }

    #[test]
    fn a_completion_spanning_two_polls_commits_once_the_prefix_is_whole() {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement =
            GroupSettlement::new(Arc::clone(&ledger), Duration::ZERO, BudgetLimits::unset());
        let partition = TopicPartition::new("test", 0);
        charge_offsets(&ledger, &partition, 0, &[0, 1, 2, 3, 4, 5, 6, 7]);
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);
        let mut settle = |topic_partition: &TopicPartition, generation: u64, offsets: &[Offset]| {
            settlement.settle_run(topic_partition, generation, offsets)
        };

        apply_completion(
            &mut in_flight,
            &completion(1, 0, &[2, 3, 4, 5], 4),
            &mut settle,
        )
        .unwrap();
        assert!(
            settlement.take_due(Instant::now()).is_none(),
            "offsets 0 and 1 are still in flight"
        );

        apply_completion(
            &mut in_flight,
            &completion(1, 0, &[0, 1, 6, 7], 4),
            &mut settle,
        )
        .unwrap();
        assert_eq!(
            settlement
                .take_due(Instant::now())
                .map(|commit| commit.offsets),
            Some(HashMap::from([(partition, MessageOffset(8))]))
        );
    }

    #[test]
    fn a_short_accepted_completion_settles_nothing() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4)]);
        let mut runs = 0;

        apply_completion(&mut in_flight, &completion(1, 0, &[0, 1], 1), |_, _, _| {
            runs += 1;
            Ok(())
        })
        .unwrap();

        assert_eq!(runs, 0, "the ledger must not commit past a dropped message");
        assert_eq!(in_flight[0].covered, 2);
        assert_eq!(in_flight[0].accepted, 1);
    }

    #[test]
    fn a_regained_poll_settles_each_charged_offset_once() {
        // Offsets 8..10, a regain, then offset 8 again: four deliveries, one charge.
        let mut in_flight = VecDeque::from([regained_poll(8, 10, 4)]);
        let mut runs = Vec::new();
        let mut settle = |_: &TopicPartition, generation: u64, offsets: &[Offset]| {
            runs.push((generation, offsets.to_vec()));
            Ok(())
        };

        apply_completion(
            &mut in_flight,
            &completion(1, 0, &[8, 9, 10], 3),
            &mut settle,
        )
        .unwrap();
        apply_completion(&mut in_flight, &completion(1, 0, &[8], 1), &mut settle).unwrap();

        assert_eq!(
            runs,
            vec![(2, vec![MessageOffset(8)])],
            "neither the uncharged old offsets nor the redelivered one reach the ledger"
        );
        assert!(in_flight[0].is_complete());
        assert!(pop_committable(&mut in_flight).is_ok());
    }

    #[test]
    fn apply_completion_spanning_two_polls_credits_each() {
        // A key-table run merges messages from consecutive polls into one
        // send, so its completion spans both spans.
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

        credit(&mut in_flight, completion(1, 0, &[2, 3, 4, 5], 4));

        assert_eq!(in_flight[0].covered, 2);
        assert_eq!(in_flight[0].accepted, 2);
        assert_eq!(in_flight[1].covered, 2);
        assert_eq!(in_flight[1].accepted, 2);
    }

    #[test]
    fn apply_completion_under_report_shorts_the_tail_poll() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

        credit(&mut in_flight, completion(1, 0, &[2, 3, 4, 5], 3));

        assert_eq!(in_flight[0].accepted, 2, "leading offsets are accepted");
        assert_eq!(
            in_flight[1].accepted, 1,
            "the tail poll fails its accepted check"
        );
        assert_eq!(in_flight[1].covered, 2);
    }

    #[test]
    fn a_complete_poll_with_a_charged_offset_no_completion_covered_is_not_committable() {
        let mut in_flight = VecDeque::from([poll(1, 0, 10, 12, 3)]);

        credit(&mut in_flight, completion(1, 0, &[10, 12, 12], 3));

        assert!(in_flight[0].is_complete());
        let error = pop_committable(&mut in_flight)
            .err()
            .expect("offset 11 has no completion");
        assert!(error.to_string().contains("offset 11 "), "{error}");
    }

    #[test]
    fn a_poll_whose_deliveries_span_an_offset_gap_commits() {
        // A compacted or transactional topic skips offsets, so a span can far
        // exceed the poll's message count.
        let mut gapped = poll(1, 0, 0, 0, 2);
        let deliveries = gapped
            .partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap();
        deliveries.span.last = i64::MAX;
        deliveries
            .charges
            .push((MessageOffset(i64::MAX), Charge::ZERO));
        let mut in_flight = VecDeque::from([gapped]);

        credit(&mut in_flight, completion(1, 0, &[0, i64::MAX], 2));

        assert!(in_flight[0].is_complete());
        assert!(pop_committable(&mut in_flight).is_ok());
    }

    #[test]
    fn strip_revoked_partitions_keeps_the_other_partitions_slices() {
        // A cooperative rebalance revokes one partition of a two-partition
        // poll. The kept partition's slice must stay accounted, or its
        // ledger charges never settle and its commits freeze at the hole.
        let mut two = poll(1, 0, 0, 1, 4);
        two.partitions.insert(
            TopicPartition::new("test", 1),
            PartitionDeliveries {
                span: OffsetSpan {
                    first: 10,
                    last: 11,
                },
                generation: 0,
                generations_version_seen: 0,
                charges: Vec::new(),
                latest_kafka_ts: 0,
                max_lag_ms: None,
                delivered: 2,
                covered: 0,
                accepted: 0,
                credited: HashSet::default(),
            },
        );
        two.partitions
            .get_mut(&TopicPartition::new("test", 0))
            .unwrap()
            .delivered = 2;
        let mut in_flight = VecDeque::from([two]);
        // Partition 1 already had one message covered before the revoke.
        credit(&mut in_flight, completion(1, 1, &[10], 1));

        let stripped = strip_revoked_partitions(
            &mut in_flight,
            &[RevokedPartition {
                topic_partition: TopicPartition::new("test", 1),
                generation: 1,
            }],
        );

        assert_eq!(stripped, 2);
        assert_eq!(in_flight[0].message_count, 2);
        assert_eq!(in_flight[0].covered, 0, "the revoked slice's credit goes");
        assert!(!in_flight[0].is_complete());

        // The kept partition completes the poll; a late completion for the
        // revoked partition is discarded, not credited.
        credit(&mut in_flight, completion(1, 1, &[11], 1));
        assert_eq!(in_flight[0].covered, 0);
        credit(&mut in_flight, completion(1, 0, &[0, 1], 2));
        assert!(in_flight[0].is_complete());
        assert_eq!(in_flight[0].accepted, 2);
        assert!(pop_committable(&mut in_flight).is_ok());
    }

    #[test]
    fn strip_revoked_partitions_removes_an_emptied_poll() {
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 2, 0, 3, 4)]);

        let stripped = strip_revoked_partitions(
            &mut in_flight,
            &[RevokedPartition {
                topic_partition: TopicPartition::new("test", 0),
                generation: 1,
            }],
        );

        assert_eq!(stripped, 4);
        assert_eq!(in_flight.len(), 1);
        assert_eq!(in_flight[0].message_count, 4);
    }

    #[test]
    fn historical_revoke_keeps_a_reassigned_poll_and_its_ledger_slice() {
        let topic_partition = TopicPartition::new("test", 0);
        let ledger = TopicOffsetLedger::new();
        let delivery = Delivery {
            offset: 10,
            charge: Charge {
                events: 1,
                bytes: 1,
            },
            kafka_ts: 0,
            lag_ms: None,
        };

        // This collection saw offset 10 immediately before a revoke, then
        // saw its replay after the partition was assigned again. Only the
        // current generation is charged, while the poll still covers both
        // deliveries that the batcher will complete.
        let mut reassigned_deliveries = PartitionDeliveries::new(
            ledger.generation(&topic_partition),
            ledger.generations_version(),
            &delivery,
        );
        ledger.forget_partitions([("test", 0)]);
        ledger.forget_partitions([("test", 0)]);
        reassigned_deliveries.record(
            ledger.generations_version(),
            || ledger.generation(&topic_partition),
            &delivery,
        );
        assert_eq!(reassigned_deliveries.generation, 2);
        assert_eq!(reassigned_deliveries.delivered, 2);
        assert_eq!(reassigned_deliveries.charges.len(), 1);
        ledger
            .charge(
                &topic_partition,
                reassigned_deliveries.generation,
                reassigned_deliveries.charges.iter().copied(),
            )
            .unwrap();

        // The queued revoke notification belongs to generation 0. It must
        // remove genuine old in-flight work, but not this poll collected and
        // charged under the later reassignment.
        let old_poll = poll(0, 0, 1, 1, 1);
        let reassigned_poll = InFlightPoll {
            poll_id: "reassigned".to_string(),
            assignment_epoch: 1,
            partitions: HashMap::from([(topic_partition.clone(), reassigned_deliveries)]),
            message_count: 2,
            covered: 0,
            accepted: 0,
            dispatched_at: Instant::now(),
        };
        let mut in_flight = VecDeque::from([old_poll, reassigned_poll]);

        let stripped = strip_revoked_partitions(
            &mut in_flight,
            &[RevokedPartition {
                topic_partition: topic_partition.clone(),
                generation: 1,
            }],
        );

        assert_eq!(stripped, 1, "only the old assignment is stripped");
        assert_eq!(in_flight.len(), 1);
        assert_eq!(in_flight[0].poll_id, "reassigned");

        credit(&mut in_flight, completion(1, 0, &[10, 10], 2));
        assert!(in_flight[0].is_complete());
        let reassigned = pop_committable(&mut in_flight)
            .expect("an offset credited twice still counts as credited");
        let retained = reassigned.partitions.get(&topic_partition).unwrap();
        ledger
            .settle(
                &topic_partition,
                retained.generation,
                retained.charges.iter().map(|(offset, _)| *offset),
            )
            .unwrap();
        assert_eq!(
            ledger
                .take_frontier(&topic_partition)
                .map(|taken| taken.offset),
            Some(Offset(11))
        );

        // With the retained replay slice settled, the next accepted offset
        // advances normally instead of remaining stuck behind offset 10.
        ledger
            .charge(
                &topic_partition,
                retained.generation,
                [(Offset(11), delivery.charge)],
            )
            .unwrap();
        ledger
            .settle(&topic_partition, retained.generation, [Offset(11)])
            .unwrap();
        assert_eq!(
            ledger
                .take_frontier(&topic_partition)
                .map(|taken| taken.offset),
            Some(Offset(12))
        );
        assert_eq!(ledger.held(&topic_partition).offsets, 0);
    }

    #[test]
    fn apply_completion_requires_a_matching_epoch() {
        // The same offsets exist in two polls when a partition was revoked,
        // reassigned, and replayed. The epoch keeps each incarnation's
        // completions in its own poll.
        let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(2, 0, 0, 3, 4)]);

        credit(&mut in_flight, completion(2, 0, &[0, 1, 2, 3], 4));

        assert_eq!(in_flight[0].covered, 0);
        assert_eq!(in_flight[1].covered, 4);
    }

    #[test]
    fn a_covered_head_is_popped_before_a_redelivered_offset_is_matched() {
        let ledger = Arc::new(TopicOffsetLedger::new());
        let settlement =
            GroupSettlement::new(Arc::clone(&ledger), Duration::ZERO, BudgetLimits::unset());
        let partition = TopicPartition::new("test", 0);
        ledger.forget_partitions([("test", 0)]);
        charge_offsets(&ledger, &partition, 1, &[0, 1]);
        let mut settle = |topic_partition: &TopicPartition, generation: u64, offsets: &[Offset]| {
            settlement.settle_run(topic_partition, generation, offsets)
        };

        // Both polls carry the same offsets: a regain during collection.
        let mut old = poll(3, 0, 0, 1, 2);
        old.poll_id = "old".into();
        let mut replay = poll(3, 0, 0, 1, 2);
        replay.poll_id = "replay".into();
        replay.partitions.get_mut(&partition).unwrap().generation = 1;
        let mut in_flight = VecDeque::from([old, replay]);
        let event = completion(3, 0, &[0, 1], 2);

        apply_completion(&mut in_flight, &event, &mut settle).unwrap();
        assert_eq!(in_flight[0].poll_id, "old");
        assert!(in_flight[0].is_complete());
        assert!(
            settlement.take_due(Instant::now()).is_none(),
            "the old generation's settle is stale"
        );
        in_flight.pop_front();

        apply_completion(&mut in_flight, &event, &mut settle).unwrap();
        assert_eq!(in_flight[0].poll_id, "replay");
        assert!(in_flight[0].is_complete());
        assert_eq!(
            settlement
                .take_due(Instant::now())
                .map(|commit| commit.offsets),
            Some(HashMap::from([(partition, MessageOffset(2))]))
        );
    }
}
