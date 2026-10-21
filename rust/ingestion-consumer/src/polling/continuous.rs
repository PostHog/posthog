use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use common_kafka_consumer::{Charge, GroupCompletion, Offset, TopicPartition};
use lifecycle::Handle;
use metrics::{counter, gauge};
use tokio::sync::mpsc;
use tokio::time::{Interval, MissedTickBehavior};
use tracing::{info, warn};

use super::poll::{InFlightPoll, PartitionDeliveries, PollBuilder};
use super::{Collector, LoopParts, RevokedPartition, Step};
use crate::in_flight_limit::InFlightLimits;
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
    limits: InFlightLimits,
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
    pub(crate) fn new(parts: LoopParts, limits: InFlightLimits) -> Self {
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
            debug_recorder: _,
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
            in_flight: InFlight::new(group_id),
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

            let reading = self.accepting_new_batches && !self.reached_limit(held);
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
                    if self
                        .poll
                        .as_ref()
                        .is_some_and(|poll| self.collector.is_full(&poll.builder))
                    {
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

    fn reached_limit(&mut self, held: Charge) -> bool {
        let at_limit = self.limits.reached(held);
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
}

impl InFlight {
    fn new(group_id: String) -> Self {
        Self {
            partitions: HashMap::new(),
            held: Charge::ZERO,
            latest_processed_ms: HashMap::new(),
            group_id,
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
            if slice.uncovered() == 0 {
                let slice = slices.remove(index).expect("the index is in range");
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
                false
            });
            if slices.is_empty() {
                self.partitions.remove(&revoked.topic_partition);
            }
        }
        stripped
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
        let mut in_flight = InFlight::new("test".into());
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
        let mut in_flight = InFlight::new("test".into());
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
        let mut in_flight = InFlight::new("test".into());
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
        let mut in_flight = InFlight::new("test".into());
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
        let mut in_flight = InFlight::new("test".into());
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
        let mut in_flight = InFlight::new("test".into());
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
}
