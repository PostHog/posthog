use super::*;
use common_kafka_consumer::Offset as MessageOffset;

fn poll(epoch: u64, partition: i32, first: i64, last: i64, count: u32) -> InFlightPoll {
    let mut partitions = HashMap::new();
    partitions.insert(
        TopicPartition::new("test", partition),
        PartitionDeliveries {
            span: OffsetSpan { first, last },
            generation: 0,
            generations_version_seen: 0,
            charges: Vec::new(),
            latest_kafka_ts: 0,
            max_lag_ms: None,
            delivered: count,
            covered: 0,
            accepted: 0,
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

#[test]
fn apply_completion_credits_the_poll_holding_the_offsets() {
    let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

    apply_completion(&mut in_flight, completion(1, 0, &[4, 6], 2));

    assert_eq!(in_flight[0].covered, 0);
    assert_eq!(in_flight[1].covered, 2);
    assert_eq!(in_flight[1].accepted, 2);
    assert!(!in_flight[1].is_complete());

    apply_completion(&mut in_flight, completion(1, 0, &[5, 7], 2));
    assert!(in_flight[1].is_complete());
}

#[test]
fn apply_completion_spanning_two_polls_credits_each() {
    // A key-table run merges messages from consecutive polls into one
    // send, so its completion spans both spans.
    let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

    apply_completion(&mut in_flight, completion(1, 0, &[2, 3, 4, 5], 4));

    assert_eq!(in_flight[0].covered, 2);
    assert_eq!(in_flight[0].accepted, 2);
    assert_eq!(in_flight[1].covered, 2);
    assert_eq!(in_flight[1].accepted, 2);
}

#[test]
fn apply_completion_under_report_shorts_the_tail_poll() {
    let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 0, 4, 7, 4)]);

    apply_completion(&mut in_flight, completion(1, 0, &[2, 3, 4, 5], 3));

    assert_eq!(in_flight[0].accepted, 2, "leading offsets are accepted");
    assert_eq!(
        in_flight[1].accepted, 1,
        "the tail poll fails its accepted check"
    );
    assert_eq!(in_flight[1].covered, 2);
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
        },
    );
    two.partitions
        .get_mut(&TopicPartition::new("test", 0))
        .unwrap()
        .delivered = 2;
    let mut in_flight = VecDeque::from([two]);
    // Partition 1 already had one message covered before the revoke.
    apply_completion(&mut in_flight, completion(1, 1, &[10], 1));

    let stripped = strip_revoked_partitions(&mut in_flight, &[TopicPartition::new("test", 1)]);

    assert_eq!(stripped, 2);
    assert_eq!(in_flight[0].message_count, 2);
    assert_eq!(in_flight[0].covered, 0, "the revoked slice's credit goes");
    assert!(!in_flight[0].is_complete());

    // The kept partition completes the poll; a late completion for the
    // revoked partition is discarded, not credited.
    apply_completion(&mut in_flight, completion(1, 1, &[11], 1));
    assert_eq!(in_flight[0].covered, 0);
    apply_completion(&mut in_flight, completion(1, 0, &[0, 1], 2));
    assert!(in_flight[0].is_complete());
    assert_eq!(in_flight[0].accepted, 2);
}

#[test]
fn strip_revoked_partitions_removes_an_emptied_poll() {
    let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(1, 2, 0, 3, 4)]);

    let stripped = strip_revoked_partitions(&mut in_flight, &[TopicPartition::new("test", 0)]);

    assert_eq!(stripped, 4);
    assert_eq!(in_flight.len(), 1);
    assert_eq!(in_flight[0].message_count, 4);
}

#[test]
fn apply_completion_requires_a_matching_epoch() {
    // The same offsets exist in two polls when a partition was revoked,
    // reassigned, and replayed. The epoch keeps each incarnation's
    // completions in its own poll.
    let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4), poll(2, 0, 0, 3, 4)]);

    apply_completion(&mut in_flight, completion(2, 0, &[0, 1, 2, 3], 4));

    assert_eq!(in_flight[0].covered, 0);
    assert_eq!(in_flight[1].covered, 4);
}

#[test]
fn apply_completion_discards_a_completion_matching_no_poll() {
    let mut in_flight = VecDeque::from([poll(1, 0, 0, 3, 4)]);

    // Wrong partition, then wrong epoch: neither may be credited.
    apply_completion(&mut in_flight, completion(1, 2, &[1], 1));
    apply_completion(&mut in_flight, completion(9, 0, &[1], 1));

    assert_eq!(in_flight[0].covered, 0);
    assert_eq!(in_flight[0].accepted, 0);
}

#[test]
fn frontier_span_submits_the_frontier_verbatim() {
    let span = OffsetSpan {
        first: 10,
        last: 11,
    };
    assert_eq!(
        frontier_span(&span, Some(Offset(12))),
        Some(OffsetSpan {
            first: 10,
            last: 11
        })
    );
    assert_eq!(
        frontier_span(&span, Some(Offset(11))),
        Some(OffsetSpan {
            first: 10,
            last: 10
        }),
        "a frontier trailing the span wins"
    );
}

#[test]
fn a_partition_without_a_frontier_is_not_committed() {
    let span = OffsetSpan {
        first: 20,
        last: 21,
    };
    assert_eq!(frontier_span(&span, None), None);
}
