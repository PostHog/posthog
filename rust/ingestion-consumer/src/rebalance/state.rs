use std::time::Duration;

use common_kafka_consumer::TopicPartition;
use rdkafka::consumer::{Consumer, ConsumerContext};
use rdkafka::error::KafkaResult;
use rdkafka::TopicPartitionList;
use tokio::time::Instant;

use crate::batcher::RevokeId;

#[derive(Debug, PartialEq)]
pub(crate) enum Event {
    Assigned(Vec<TopicPartition>),
    Revoked {
        revoke: RevokeId,
        partitions: Vec<TopicPartition>,
        unassign: Unassign,
    },
    Draining {
        revoke: RevokeId,
        partitions: Vec<TopicPartition>,
    },
}

#[derive(Debug, PartialEq)]
pub(crate) struct Unassign {
    partitions: TopicPartitionList,
    cooperative: bool,
}

impl Unassign {
    pub(crate) fn new(partitions: TopicPartitionList, cooperative: bool) -> Self {
        Self {
            partitions,
            cooperative,
        }
    }

    pub(crate) fn apply<C: ConsumerContext>(self, consumer: &impl Consumer<C>) -> KafkaResult<()> {
        if self.cooperative {
            consumer.incremental_unassign(&self.partitions)
        } else {
            consumer.unassign()
        }
    }
}

pub(crate) struct Drain {
    revoke: RevokeId,
    pub(crate) partitions: Vec<TopicPartition>,
    pub(crate) unassign: Unassign,
    pub(crate) started: Instant,
    pub(crate) timeout: Duration,
}

enum Phase {
    Starting,
    Consuming { drain_timeout: Option<Duration> },
    Draining { drain: Drain },
    Stopped,
}

pub(crate) struct RebalanceState {
    phase: Phase,
    events: Vec<Event>,
    revokes: u64,
}

impl Default for RebalanceState {
    fn default() -> Self {
        Self {
            phase: Phase::Starting,
            events: Vec::new(),
            revokes: 0,
        }
    }
}

impl RebalanceState {
    pub(crate) fn on_started(&mut self, drain_timeout: Option<Duration>) {
        if matches!(self.phase, Phase::Starting) {
            self.phase = Phase::Consuming { drain_timeout };
        }
    }

    pub(crate) fn on_assigned(&mut self, partitions: Vec<TopicPartition>) {
        self.queue(Event::Assigned(partitions));
    }

    /// `Some` only before `on_started` or after `on_stopped`, when no loop
    /// runs to apply the unassign.
    pub(crate) fn on_revoked(
        &mut self,
        partitions: Vec<TopicPartition>,
        unassign: Unassign,
        lost: bool,
        now: Instant,
    ) -> Option<Unassign> {
        match self.phase {
            // A lost assignment belongs to another member, so its commit fails.
            Phase::Consuming {
                drain_timeout: Some(timeout),
            } if !lost => {
                let revoke = self.next_revoke();
                self.events.push(Event::Draining {
                    revoke,
                    partitions: partitions.clone(),
                });
                self.phase = Phase::Draining {
                    drain: Drain {
                        revoke,
                        partitions,
                        unassign,
                        started: now,
                        timeout,
                    },
                };
                None
            }
            Phase::Consuming { .. } | Phase::Draining { .. } => {
                let revoke = self.next_revoke();
                self.events.push(Event::Revoked {
                    revoke,
                    partitions,
                    unassign,
                });
                None
            }
            Phase::Starting | Phase::Stopped => Some(unassign),
        }
    }

    fn next_revoke(&mut self) -> RevokeId {
        self.revokes += 1;
        RevokeId(self.revokes)
    }

    pub(crate) fn take_events(&mut self) -> Vec<Event> {
        std::mem::take(&mut self.events)
    }

    pub(crate) fn drain_deadline(&self) -> Option<Instant> {
        match &self.phase {
            Phase::Draining { drain } => Some(drain.started + drain.timeout),
            _ => None,
        }
    }

    pub(crate) fn on_drained(&mut self, revoke: RevokeId) -> Option<Drain> {
        match &self.phase {
            Phase::Draining { drain } if drain.revoke == revoke => self.finish_drain(),
            _ => None,
        }
    }

    pub(crate) fn on_drain_timed_out(&mut self, now: Instant) -> Option<Drain> {
        match self.drain_deadline() {
            Some(deadline) if now >= deadline => self.finish_drain(),
            _ => None,
        }
    }

    pub(crate) fn on_stopped(&mut self) -> Option<Drain> {
        match std::mem::replace(&mut self.phase, Phase::Stopped) {
            Phase::Draining { drain } => Some(drain),
            _ => None,
        }
    }

    pub(crate) fn on_dropped(&mut self) -> Vec<Unassign> {
        let mut unassigns: Vec<Unassign> = self
            .on_stopped()
            .map(|drain| drain.unassign)
            .into_iter()
            .collect();
        unassigns.extend(
            self.take_events()
                .into_iter()
                .filter_map(|event| match event {
                    Event::Revoked { unassign, .. } => Some(unassign),
                    Event::Assigned(_) | Event::Draining { .. } => None,
                }),
        );
        unassigns
    }

    fn finish_drain(&mut self) -> Option<Drain> {
        match std::mem::replace(&mut self.phase, Phase::Stopped) {
            Phase::Draining { drain } => {
                self.phase = Phase::Consuming {
                    drain_timeout: Some(drain.timeout),
                };
                Some(drain)
            }
            phase => {
                self.phase = phase;
                None
            }
        }
    }

    fn queue(&mut self, event: Event) {
        if !matches!(self.phase, Phase::Stopped) {
            self.events.push(event);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TIMEOUT: Duration = Duration::from_secs(10);

    fn p(partition: i32) -> TopicPartition {
        TopicPartition::new("events", partition)
    }

    fn unassign() -> Unassign {
        Unassign::new(TopicPartitionList::new(), true)
    }

    fn consuming() -> RebalanceState {
        let mut state = RebalanceState::default();
        state.on_started(Some(TIMEOUT));
        state
    }

    #[test]
    fn a_revoke_while_consuming_waits_for_its_drain() {
        let mut state = consuming();
        let now = Instant::now();

        assert!(state
            .on_revoked(vec![p(0)], unassign(), false, now)
            .is_none());
        assert_eq!(
            state.take_events(),
            vec![Event::Draining {
                revoke: RevokeId(1),
                partitions: vec![p(0)],
            }]
        );
        assert_eq!(state.drain_deadline(), Some(now + TIMEOUT));
        assert!(
            state.on_drained(RevokeId(2)).is_none(),
            "another revoke's answer"
        );

        let drain = state.on_drained(RevokeId(1)).expect("the drain finishes");
        assert_eq!(drain.partitions, vec![p(0)]);
        assert_eq!(state.drain_deadline(), None);
        assert!(
            state
                .on_revoked(vec![p(1)], unassign(), false, now)
                .is_none(),
            "the next revoke drains too"
        );
    }

    fn without_drains() -> RebalanceState {
        let mut state = RebalanceState::default();
        state.on_started(None);
        state
    }

    fn draining() -> RebalanceState {
        let mut state = consuming();
        state.on_revoked(vec![p(9)], unassign(), false, Instant::now());
        state.take_events();
        state
    }

    fn stopped() -> RebalanceState {
        let mut state = consuming();
        state.on_stopped();
        state
    }

    struct LoopUnassignCase {
        state: fn() -> RebalanceState,
        lost: bool,
        revoke: RevokeId,
    }

    #[rstest::rstest]
    #[case::lost(LoopUnassignCase { state: consuming, lost: true, revoke: RevokeId(1) })]
    #[case::no_drain_timeout(LoopUnassignCase { state: without_drains, lost: false, revoke: RevokeId(1) })]
    #[case::during_a_drain(LoopUnassignCase { state: draining, lost: false, revoke: RevokeId(2) })]
    fn a_revoke_that_does_not_drain_goes_to_the_loop_with_its_unassign(
        #[case] case: LoopUnassignCase,
    ) {
        let mut state = (case.state)();

        assert!(state
            .on_revoked(vec![p(0)], unassign(), case.lost, Instant::now())
            .is_none());
        assert_eq!(
            state.take_events(),
            vec![Event::Revoked {
                revoke: case.revoke,
                partitions: vec![p(0)],
                unassign: unassign(),
            }]
        );
    }

    #[rstest::rstest]
    #[case::before_the_loop_starts(RebalanceState::default)]
    #[case::after_the_loop_stops(stopped)]
    fn without_a_loop_the_callback_applies_the_unassign(#[case] state: fn() -> RebalanceState) {
        let mut state = state();

        assert!(state
            .on_revoked(vec![p(0)], unassign(), false, Instant::now())
            .is_some());
        assert_eq!(state.take_events(), vec![]);
        assert_eq!(state.drain_deadline(), None);
    }

    #[test]
    fn a_timed_out_drain_answered_late_does_not_finish_the_next_drain_of_its_partitions() {
        let mut state = consuming();
        let now = Instant::now();
        state.on_revoked(vec![p(0)], unassign(), false, now);

        assert!(state.on_drain_timed_out(now + TIMEOUT / 2).is_none());
        assert!(state.on_drain_timed_out(now + TIMEOUT).is_some());

        state.on_revoked(vec![p(0)], unassign(), false, now + TIMEOUT);
        assert!(state.on_drained(RevokeId(1)).is_none());
        assert!(state.on_drained(RevokeId(2)).is_some());
    }

    #[test]
    fn stopping_hands_back_the_drain() {
        let mut state = draining();

        let drain = state.on_stopped().expect("the drain in progress");
        assert_eq!(drain.partitions, vec![p(9)]);
    }

    fn revoked_and_never_taken() -> RebalanceState {
        let mut state = without_drains();
        state.on_revoked(vec![p(0)], unassign(), false, Instant::now());
        state
    }

    fn draining_then_revoked_and_never_taken() -> RebalanceState {
        let mut state = draining();
        state.on_revoked(vec![p(0)], unassign(), false, Instant::now());
        state
    }

    struct DroppedCase {
        state: fn() -> RebalanceState,
        unassigns: usize,
    }

    #[rstest::rstest]
    #[case::nothing_pending(DroppedCase { state: consuming, unassigns: 0 })]
    #[case::a_revoke_the_loop_never_took(DroppedCase { state: revoked_and_never_taken, unassigns: 1 })]
    #[case::a_drain_in_progress(DroppedCase { state: draining, unassigns: 1 })]
    #[case::a_drain_and_a_revoke_the_loop_never_took(DroppedCase { state: draining_then_revoked_and_never_taken, unassigns: 2 })]
    #[case::after_the_loop_stopped(DroppedCase { state: stopped, unassigns: 0 })]
    fn a_dropped_loop_hands_back_every_unapplied_unassign(#[case] case: DroppedCase) {
        let mut state = (case.state)();

        assert_eq!(state.on_dropped().len(), case.unassigns);

        assert_eq!(state.take_events(), vec![]);
        assert!(
            state
                .on_revoked(vec![p(1)], unassign(), false, Instant::now())
                .is_some(),
            "stopped: the callback applies the next unassign itself"
        );
    }
}
