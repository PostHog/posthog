use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use common_kafka_consumer::{Charge, GroupCompletion, Offset, TopicPartition};
use lifecycle::Handle;
use metrics::{counter, gauge};
use tokio::sync::mpsc;
use tokio::time::{Interval, MissedTickBehavior};
use tracing::{info, warn};

use super::poll::{debug_partition_offsets, InFlightPoll, PartitionDeliveries, PollBuilder};
use super::{Collector, LoopParts, RevokedPartition, Step};
use crate::charge_limit::ChargeLimit;
use crate::debug_recorder::{record_if, DebugEventKind, DebugRecorder, PartitionOffset};
use crate::settlement::Settlement;

/// Reads Kafka while it applies completions and commits. A poll is submitted
/// once it is full or its batch timeout passes, and nothing waits on it after
/// that: the partition budget and the in-flight limit bound admission.
pub(crate) struct ContinuousPolling {
    collector: Collector,
    completions: mpsc::UnboundedReceiver<GroupCompletion>,
    errors: mpsc::UnboundedReceiver<String>,
    settlement: Arc<dyn Settlement>,
    revoked_partitions: Arc<Mutex<Vec<RevokedPartition>>>,
    handle: Handle,
    commit_tick: Interval,
    in_flight: InFlight,
    limits: ChargeLimit,
    at_limit: bool,
    poll: Option<PollInProgress>,
    accepting_new_batches: bool,
}

struct PollInProgress {
    builder: PollBuilder,
    /// The batch timeout runs from the poll's first message.
    deadline: tokio::time::Instant,
}

enum Woke {
    Shutdown,
    Completion(Option<GroupCompletion>),
    Error(Option<String>),
    Tick,
    Deadline,
    Received,
    Failed(anyhow::Error),
}

impl ContinuousPolling {
    pub(crate) fn new(parts: LoopParts, limits: ChargeLimit) -> Self {
        let LoopParts {
            collector,
            completions,
            errors,
            settlement,
            fetching: _,
            revoked_partitions,
            handle,
            commit_tick,
            group_id,
            debug_recorder,
        } = parts;
        let mut commit_tick = tokio::time::interval(commit_tick);
        commit_tick.set_missed_tick_behavior(MissedTickBehavior::Delay);
        Self {
            collector,
            completions,
            errors,
            settlement,
            revoked_partitions,
            handle,
            commit_tick,
            in_flight: InFlight::new(group_id, debug_recorder),
            limits,
            at_limit: false,
            poll: None,
            accepting_new_batches: true,
        }
    }

    pub(crate) async fn next(&mut self) -> Step {
        loop {
            if self.poll.is_some() && self.revokes_pending() {
                // A revoke may have come in while this poll was built, so it
                // goes in flight first, where the revoke can strip it.
                if let Some(step) = self.take_poll() {
                    return step;
                }
            }
            self.drop_revoked_slices();
            let held = self.in_flight.held();
            gauge!("ingestion_consumer_in_flight_events").set(held.events as f64);
            gauge!("ingestion_consumer_in_flight_bytes").set(held.bytes as f64);
            if !self.accepting_new_batches && self.in_flight.is_empty() {
                return Step::Stop;
            }
            if self
                .poll
                .as_ref()
                .is_some_and(|poll| poll.deadline <= tokio::time::Instant::now())
            {
                if let Some(step) = self.take_poll() {
                    return step;
                }
            }

            let reading = self.accepting_new_batches && !self.reached_limit(self.pending());
            let deadline = self.poll.as_ref().map(|poll| poll.deadline);
            let batch_timeout = self.collector.batch_timeout();
            let woke = tokio::select! {
                _ = self.handle.shutdown_recv(), if self.accepting_new_batches => Woke::Shutdown,
                completion = self.completions.recv() => Woke::Completion(completion),
                failure = self.errors.recv() => Woke::Error(failure),
                _ = self.commit_tick.tick() => Woke::Tick,
                _ = tokio::time::sleep_until(deadline.unwrap_or_else(tokio::time::Instant::now)),
                    if deadline.is_some() => Woke::Deadline,
                received = self.collector.receive(), if reading => match received {
                    Ok(Some(message)) => {
                        let poll = self.poll.get_or_insert_with(|| PollInProgress {
                            builder: PollBuilder::new(),
                            deadline: tokio::time::Instant::now() + batch_timeout,
                        });
                        self.collector.add(&mut poll.builder, &message);
                        Woke::Received
                    }
                    Ok(None) => Woke::Received,
                    Err(err) => Woke::Failed(err),
                },
            };

            match woke {
                Woke::Shutdown => {
                    info!(
                        in_flight_events = held.events,
                        "Shutdown signal received, draining in-flight events"
                    );
                    self.accepting_new_batches = false;
                    // Its messages are not charged yet, so they replay from the last commit.
                    self.poll = None;
                    return Step::BeginShutdown;
                }
                Woke::Completion(Some(completion)) => {
                    let settlement = &self.settlement;
                    let processed = match self.in_flight.apply(
                        &completion,
                        |topic_partition, generation, run| {
                            settlement.settle_run(topic_partition, generation, run)
                        },
                    ) {
                        Ok(processed) => processed,
                        Err(err) => return Step::Fail(err),
                    };
                    counter!("ingestion_consumer_messages_processed_total").increment(processed);
                    if let Some(commit) = self.settlement.take_due(Instant::now()) {
                        return Step::Commit(commit);
                    }
                }
                Woke::Completion(None) => {
                    return Step::Fail(anyhow::anyhow!("batcher completion channel closed"))
                }
                Woke::Error(Some(message)) => return Step::Fail(anyhow::anyhow!(message)),
                Woke::Error(None) => {
                    return Step::Fail(anyhow::anyhow!("batcher error channel closed"))
                }
                Woke::Tick => {
                    self.handle.report_healthy();
                    if let Some(commit) = self.settlement.take_due(Instant::now()) {
                        return Step::Commit(commit);
                    }
                }
                Woke::Deadline => {
                    if let Some(step) = self.take_poll() {
                        return step;
                    }
                }
                Woke::Received => {
                    let full = self
                        .poll
                        .as_ref()
                        .is_some_and(|poll| self.collector.is_full(&poll.builder));
                    if full || self.limits.reached(self.pending()) {
                        if let Some(step) = self.take_poll() {
                            return step;
                        }
                    }
                }
                Woke::Failed(err) => return Step::Fail(err),
            }
        }
    }

    pub(crate) fn submitted(&mut self, poll: InFlightPoll) {
        self.in_flight.submitted(poll);
    }

    fn take_poll(&mut self) -> Option<Step> {
        let poll = self.poll.take()?;
        (poll.builder.message_count() > 0).then(|| Step::Submit(poll.builder.finish()))
    }

    /// The in-flight charge plus the poll in progress, whose messages the
    /// process holds too.
    fn pending(&self) -> Charge {
        let building = self
            .poll
            .as_ref()
            .map_or(Charge::ZERO, |poll| poll.builder.charge());
        self.in_flight.held() + building
    }

    fn reached_limit(&mut self, pending: Charge) -> bool {
        let at_limit = self.limits.reached(pending);
        if at_limit && !self.at_limit {
            counter!("ingestion_consumer_in_flight_limit_reached_total").increment(1);
        }
        self.at_limit = at_limit;
        at_limit
    }

    fn revokes_pending(&self) -> bool {
        !self.revoked_partitions.lock().unwrap().is_empty()
    }

    /// The batcher purges a revoked partition's messages, so their slices
    /// never complete.
    fn drop_revoked_slices(&mut self) {
        let revoked: Vec<RevokedPartition> =
            std::mem::take(&mut *self.revoked_partitions.lock().unwrap());
        if revoked.is_empty() {
            return;
        }
        let stripped = self.in_flight.drop_revoked(&revoked);
        if stripped > 0 {
            counter!("ingestion_consumer_polls_dropped_on_revoke_total").increment(stripped);
            info!(stripped, "Removed revoked partitions' in-flight messages");
        }
    }
}

/// One partition's share of a submitted poll.
struct Slice {
    poll: u64,
    assignment_epoch: u64,
    deliveries: PartitionDeliveries,
    bytes: u64,
}

impl Slice {
    fn uncovered(&self) -> u32 {
        self.deliveries
            .delivered
            .saturating_sub(self.deliveries.covered)
    }
}

/// The messages submitted and not yet completed, per partition, in submit
/// order.
struct InFlight {
    partitions: HashMap<TopicPartition, VecDeque<Slice>>,
    held: Charge,
    latest_processed_ms: HashMap<TopicPartition, i64>,
    group_id: String,
    next_poll: u64,
    /// Kept only with a debug recorder, whose UI marks a poll done on its
    /// `PollCompleted` event.
    polls: HashMap<u64, PollProgress>,
    debug_recorder: Option<Arc<DebugRecorder>>,
}

struct PollProgress {
    poll_id: String,
    slices: usize,
    completed_slices: usize,
    accepted: u32,
    dispatched_at: Instant,
    partitions: Vec<PartitionOffset>,
}

impl InFlight {
    fn new(group_id: String, debug_recorder: Option<Arc<DebugRecorder>>) -> Self {
        Self {
            partitions: HashMap::new(),
            held: Charge::ZERO,
            latest_processed_ms: HashMap::new(),
            group_id,
            next_poll: 0,
            polls: HashMap::new(),
            debug_recorder,
        }
    }

    fn is_empty(&self) -> bool {
        self.partitions.is_empty()
    }

    /// A completion releases its events. A slice's bytes release when
    /// completions cover the whole slice, so the byte figure is never low.
    fn held(&self) -> Charge {
        self.held
    }

    fn submitted(&mut self, poll: InFlightPoll) {
        let seq = self.next_poll;
        self.next_poll += 1;
        if self.debug_recorder.is_some() {
            self.polls.insert(
                seq,
                PollProgress {
                    poll_id: poll.poll_id.clone(),
                    slices: poll.partitions.len(),
                    completed_slices: 0,
                    accepted: 0,
                    dispatched_at: poll.dispatched_at,
                    partitions: debug_partition_offsets(&poll.partitions),
                },
            );
        }
        for (topic_partition, deliveries) in poll.partitions {
            let bytes = deliveries
                .charges
                .iter()
                .map(|(_, charge)| charge.bytes)
                .sum();
            self.held.events += u64::from(deliveries.delivered);
            self.held.bytes += bytes;
            self.partitions
                .entry(topic_partition)
                .or_default()
                .push_back(Slice {
                    poll: seq,
                    assignment_epoch: poll.assignment_epoch,
                    deliveries,
                    bytes,
                });
        }
    }

    /// Credit each run of a completion's offsets to the oldest slice with the
    /// completion's epoch whose span holds the run, and settle the charged
    /// offsets under that slice's generation. An offset with no slice is
    /// stale: its partition was revoked while the group was out. Returns the
    /// offsets that matched a slice.
    fn apply(
        &mut self,
        completion: &GroupCompletion,
        mut settle: impl FnMut(&TopicPartition, u64, &[Offset]) -> anyhow::Result<()>,
    ) -> anyhow::Result<u64> {
        if (completion.accepted as usize) < completion.offsets.len() {
            anyhow::bail!(
                "accepted {}/{} messages — not committing offsets",
                completion.accepted,
                completion.offsets.len()
            );
        }
        let mut unmatched: u64 = 0;
        let mut remaining = completion.offsets.as_slice();
        while let Some(first) = remaining.first() {
            let found = self
                .partitions
                .iter_mut()
                .filter(|(topic_partition, _)| topic_partition.partition == completion.partition.0)
                .find_map(|(topic_partition, slices)| {
                    let index = slices.iter().position(|slice| {
                        let span = slice.deliveries.span;
                        slice.assignment_epoch == completion.assignment_epoch
                            && span.first <= first.0
                            && first.0 <= span.last
                    })?;
                    Some((topic_partition, slices, index))
                });
            let Some((topic_partition, slices, index)) = found else {
                unmatched += 1;
                remaining = &remaining[1..];
                continue;
            };
            let slice = &mut slices[index];
            let span = slice.deliveries.span;
            let run_len = remaining
                .iter()
                .take_while(|offset| span.first <= offset.0 && offset.0 <= span.last)
                .count();
            let (run, rest) = remaining.split_at(run_len);
            self.held.events -= u64::from(slice.uncovered().min(run_len as u32));
            slice.deliveries.covered += run_len as u32;
            slice.deliveries.accepted += run_len as u32;
            let settleable = slice.deliveries.credit_run(run);
            if !settleable.is_empty() {
                settle(topic_partition, slice.deliveries.generation, &settleable)?;
            }
            let mut finished = None;
            if slice.uncovered() == 0 {
                let slice = slices.remove(index).expect("the index is in range");
                finished = Some((slice.poll, slice.deliveries.accepted));
                self.held.bytes -= slice.bytes;
                let latest = self
                    .latest_processed_ms
                    .entry(topic_partition.clone())
                    .or_insert(i64::MIN);
                if slice.deliveries.latest_kafka_ts > *latest {
                    *latest = slice.deliveries.latest_kafka_ts;
                    // Same name as the Node.js consumer's gauge, so one dashboard reads both.
                    gauge!(
                        "latest_processed_timestamp_ms",
                        "topic" => topic_partition.topic.clone(),
                        "partition" => topic_partition.partition.to_string(),
                        "groupId" => self.group_id.clone()
                    )
                    .set(*latest as f64);
                }
                if slices.is_empty() {
                    let topic_partition = topic_partition.clone();
                    self.partitions.remove(&topic_partition);
                }
            }
            if let Some((poll, accepted)) = finished {
                self.slice_finished(poll, Some(accepted));
            }
            remaining = rest;
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
        Ok(completion.offsets.len() as u64 - unmatched)
    }

    /// Drop the slices collected before each partition's revoke generation.
    /// A slice collected after a later reassignment stays. Returns the
    /// messages dropped.
    fn drop_revoked(&mut self, revoked: &[RevokedPartition]) -> u64 {
        let mut stripped: u64 = 0;
        let mut dropped_polls = Vec::new();
        for revoked in revoked {
            let Some(slices) = self.partitions.get_mut(&revoked.topic_partition) else {
                continue;
            };
            slices.retain(|slice| {
                if slice.deliveries.generation >= revoked.generation {
                    return true;
                }
                stripped += u64::from(slice.deliveries.delivered);
                self.held.events -= u64::from(slice.uncovered());
                self.held.bytes -= slice.bytes;
                dropped_polls.push(slice.poll);
                false
            });
            if slices.is_empty() {
                self.partitions.remove(&revoked.topic_partition);
            }
        }
        for poll in dropped_polls {
            self.slice_finished(poll, None);
        }
        stripped
    }

    /// A poll completes when its last slice is covered or revoked, as long as
    /// one slice was covered: a poll the revoke emptied completes nothing.
    fn slice_finished(&mut self, poll: u64, accepted: Option<u32>) {
        let Some(progress) = self.polls.get_mut(&poll) else {
            return;
        };
        progress.slices -= 1;
        if let Some(accepted) = accepted {
            progress.completed_slices += 1;
            progress.accepted += accepted;
        }
        if progress.slices > 0 {
            return;
        }
        let progress = self.polls.remove(&poll).expect("the poll is tracked");
        if progress.completed_slices == 0 {
            return;
        }
        record_if(&self.debug_recorder, || DebugEventKind::PollCompleted {
            batch_id: progress.poll_id,
            accepted: progress.accepted,
            duration_ms: progress.dispatched_at.elapsed().as_millis() as u64,
            partitions: progress.partitions,
        });
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use common_kafka_consumer::{Offset as MessageOffset, Partition};

    use super::*;
    use crate::order_sentinel::OffsetSpan;

    fn p(partition: i32) -> TopicPartition {
        TopicPartition::new("events", partition)
    }

    fn poll(epoch: u64, partition: i32, generation: u64, first: i64, last: i64) -> InFlightPoll {
        let deliveries = PartitionDeliveries {
            span: OffsetSpan { first, last },
            generation,
            generations_version_seen: 0,
            charges: (first..=last)
                .map(|offset| {
                    (
                        MessageOffset(offset),
                        Charge {
                            events: 1,
                            bytes: 10,
                        },
                    )
                })
                .collect(),
            latest_kafka_ts: last,
            max_lag_ms: None,
            delivered: (last - first + 1) as u32,
            covered: 0,
            accepted: 0,
            credited: HashSet::default(),
        };
        InFlightPoll {
            poll_id: format!("poll-{epoch}-{partition}-{first}"),
            assignment_epoch: epoch,
            partitions: HashMap::from([(p(partition), deliveries)]),
            message_count: (last - first + 1) as u32,
            covered: 0,
            accepted: 0,
            dispatched_at: std::time::Instant::now(),
        }
    }

    fn completion(epoch: u64, partition: i32, offsets: &[i64]) -> GroupCompletion {
        GroupCompletion {
            partition: Partition(partition),
            assignment_epoch: epoch,
            offsets: offsets
                .iter()
                .map(|&offset| MessageOffset(offset))
                .collect(),
            accepted: offsets.len() as u32,
        }
    }

    fn charge(events: u64, bytes: u64) -> Charge {
        Charge { events, bytes }
    }

    fn settled_runs(
        in_flight: &mut InFlight,
        completion: &GroupCompletion,
    ) -> Vec<(i32, u64, Vec<i64>)> {
        let mut runs = Vec::new();
        in_flight
            .apply(completion, |topic_partition, generation, offsets| {
                runs.push((
                    topic_partition.partition,
                    generation,
                    offsets.iter().map(|offset| offset.0).collect(),
                ));
                Ok(())
            })
            .unwrap();
        runs
    }

    #[test]
    fn a_completion_releases_its_events_and_a_covered_slice_its_bytes() {
        let mut in_flight = InFlight::new("test".into(), None);
        in_flight.submitted(poll(1, 0, 0, 0, 3));
        assert_eq!(in_flight.held(), charge(4, 40));

        assert_eq!(
            settled_runs(&mut in_flight, &completion(1, 0, &[0, 1])),
            vec![(0, 0, vec![0, 1])]
        );
        assert_eq!(
            in_flight.held(),
            charge(2, 40),
            "the slice is not covered yet"
        );

        settled_runs(&mut in_flight, &completion(1, 0, &[2, 3]));
        assert_eq!(in_flight.held(), Charge::ZERO);
        assert!(in_flight.is_empty());
    }

    #[test]
    fn a_completion_spanning_two_polls_settles_each_under_its_generation() {
        let mut in_flight = InFlight::new("test".into(), None);
        in_flight.submitted(poll(1, 0, 0, 0, 3));
        in_flight.submitted(poll(1, 0, 1, 4, 7));

        assert_eq!(
            settled_runs(&mut in_flight, &completion(1, 0, &[2, 3, 4, 5])),
            vec![(0, 0, vec![2, 3]), (0, 1, vec![4, 5])]
        );
        assert_eq!(in_flight.held(), charge(4, 80));
    }

    #[test]
    fn a_completion_from_another_epoch_settles_nothing() {
        let mut in_flight = InFlight::new("test".into(), None);
        in_flight.submitted(poll(2, 0, 1, 0, 3));

        let processed = in_flight
            .apply(&completion(1, 0, &[0, 1, 2, 3]), |_, _, _| {
                panic!("a stale completion settles nothing")
            })
            .unwrap();
        assert_eq!(processed, 0);
        assert_eq!(in_flight.held(), charge(4, 40));
    }

    #[test]
    fn a_redelivered_offset_settles_against_the_replay_once_the_old_slice_is_covered() {
        let mut in_flight = InFlight::new("test".into(), None);
        in_flight.submitted(poll(3, 0, 0, 0, 1));
        in_flight.submitted(poll(3, 0, 1, 0, 1));

        assert_eq!(
            settled_runs(&mut in_flight, &completion(3, 0, &[0, 1])),
            vec![(0, 0, vec![0, 1])]
        );
        assert_eq!(
            settled_runs(&mut in_flight, &completion(3, 0, &[0, 1])),
            vec![(0, 1, vec![0, 1])]
        );
        assert!(in_flight.is_empty());
    }

    #[test]
    fn a_completion_a_worker_did_not_accept_in_full_is_an_error() {
        let mut in_flight = InFlight::new("test".into(), None);
        in_flight.submitted(poll(1, 0, 0, 0, 3));
        let mut short = completion(1, 0, &[0, 1]);
        short.accepted = 1;

        let error = in_flight
            .apply(&short, |_, _, _| Ok(()))
            .expect_err("a dropped message must not commit");
        assert!(error.to_string().contains("accepted 1/2"), "{error}");
    }

    #[test]
    fn a_revoke_drops_only_the_older_generations_slices_and_releases_them() {
        let mut in_flight = InFlight::new("test".into(), None);
        in_flight.submitted(poll(1, 0, 0, 0, 3));
        in_flight.submitted(poll(1, 1, 0, 10, 11));
        in_flight.submitted(poll(2, 0, 1, 0, 1));
        settled_runs(&mut in_flight, &completion(1, 0, &[0]));

        let stripped = in_flight.drop_revoked(&[RevokedPartition {
            topic_partition: p(0),
            generation: 1,
        }]);

        assert_eq!(stripped, 4);
        assert_eq!(
            in_flight.held(),
            charge(4, 40),
            "partition 1 and the reassigned slice stay"
        );
        assert!(
            settled_runs(&mut in_flight, &completion(1, 0, &[1, 2, 3])).is_empty(),
            "a late completion for the revoked slice is stale"
        );
        assert_eq!(
            settled_runs(&mut in_flight, &completion(2, 0, &[0, 1])),
            vec![(0, 1, vec![0, 1])]
        );
    }

    fn completed_polls(recorder: &DebugRecorder) -> Vec<(String, u32)> {
        recorder
            .backlog()
            .into_iter()
            .filter_map(|event| match event.kind {
                DebugEventKind::PollCompleted {
                    batch_id, accepted, ..
                } => Some((batch_id, accepted)),
                _ => None,
            })
            .collect()
    }

    fn two_partition_poll() -> InFlightPoll {
        let mut both = poll(1, 0, 0, 0, 1);
        both.partitions.extend(poll(1, 1, 0, 10, 11).partitions);
        both
    }

    #[test]
    fn a_poll_completes_for_the_debug_ui_once_its_last_slice_is_covered() {
        let recorder = DebugRecorder::new(100, std::time::Duration::from_secs(60));
        let mut in_flight = InFlight::new("test".into(), Some(Arc::clone(&recorder)));
        in_flight.submitted(two_partition_poll());

        settled_runs(&mut in_flight, &completion(1, 0, &[0, 1]));
        assert!(
            completed_polls(&recorder).is_empty(),
            "partition 1 is still in flight"
        );

        settled_runs(&mut in_flight, &completion(1, 1, &[10, 11]));
        assert_eq!(
            completed_polls(&recorder),
            vec![("poll-1-0-0".to_string(), 4)]
        );
    }

    #[test]
    fn a_revoked_slice_ends_its_poll_without_counting_as_accepted() {
        let recorder = DebugRecorder::new(100, std::time::Duration::from_secs(60));
        let mut in_flight = InFlight::new("test".into(), Some(Arc::clone(&recorder)));
        in_flight.submitted(two_partition_poll());
        in_flight.submitted(poll(1, 2, 0, 20, 21));

        settled_runs(&mut in_flight, &completion(1, 0, &[0, 1]));
        in_flight.drop_revoked(&[
            RevokedPartition {
                topic_partition: p(1),
                generation: 1,
            },
            RevokedPartition {
                topic_partition: p(2),
                generation: 1,
            },
        ]);

        assert_eq!(
            completed_polls(&recorder),
            vec![("poll-1-0-0".to_string(), 2)],
            "the poll the revoke emptied completes nothing"
        );
    }
}
