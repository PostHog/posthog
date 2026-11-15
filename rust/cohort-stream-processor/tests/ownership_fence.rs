//! The ownership fence against a **real** Kafka broker: commit stamps round-trip on every input
//! group, a pod of another split waits until the split is consistent, and the run-time audit stops
//! a pod when another split commits one of its partitions.
//!
//! `#[ignore]`d by default: the fence reads Kafka commit metadata, which the in-process
//! `MockCluster` does not keep. Run against a local stack with:
//!
//! ```sh
//! cargo test -p cohort-stream-processor --test ownership_fence -- --ignored
//! ```

// Writes commits as an older build, an offset reset or another split would, outside the stamp.
#![allow(clippy::disallowed_methods)]

use std::collections::{BTreeSet, HashMap};
use std::num::NonZeroU16;
use std::sync::Arc;
use std::time::Duration;

use cohort_stream_processor::config::Config;
use cohort_stream_processor::partitions::{
    AdmittedSplit, Committed, FenceBlock, FenceError, InputGroups, OwnershipAudit,
    PartitionOwnership, PositionsError, ResumeOffset, SplitClaim, Stamp, StoreSource,
};
use cohort_stream_processor::store::durability::PodOrdinal;
use cohort_stream_processor::sweep::Sweeper;
use envconfig::Envconfig;
use lifecycle::{ComponentOptions, LifecycleError, Manager};
use rdkafka::admin::{AdminClient, AdminOptions, NewTopic, TopicReplication};
use rdkafka::client::DefaultClientContext;
use rdkafka::consumer::{BaseConsumer, CommitMode, Consumer};
use rdkafka::{ClientConfig, Offset, TopicPartitionList};
use uuid::Uuid;

const PARTITIONS: u16 = 4;

fn bootstrap_servers() -> String {
    std::env::var("KAFKA_HOSTS").unwrap_or_else(|_| "localhost:9092".to_string())
}

fn split(pods: u16, ordinal: u16) -> PartitionOwnership {
    PartitionOwnership::new(
        NonZeroU16::new(pods).unwrap(),
        PodOrdinal::from(ordinal),
        PARTITIONS,
    )
    .unwrap()
}

fn claim(pods: u16, ordinal: u16, reshard_from: Option<u16>) -> SplitClaim {
    SplitClaim::new(split(pods, ordinal), reshard_from.and_then(NonZeroU16::new)).unwrap()
}

/// The test's own events, merges and transfers topics, each read through its own group.
struct Inputs {
    events: String,
    merges: String,
    transfers: String,
    group: String,
}

impl Inputs {
    async fn create() -> Self {
        let suffix = Uuid::new_v4();
        let inputs = Self {
            events: format!("cohort_stream_events_fence_{suffix}"),
            merges: format!("person_merge_events_fence_{suffix}"),
            transfers: format!("cohort_merge_state_transfer_fence_{suffix}"),
            group: format!("cohort-stream-processor-fence-{suffix}"),
        };
        let admin = admin();
        let topics: Vec<NewTopic<'_>> = inputs
            .names()
            .iter()
            .map(|name| NewTopic::new(name, i32::from(PARTITIONS), TopicReplication::Fixed(1)))
            .collect();
        for result in admin
            .create_topics(&topics, &admin_options())
            .await
            .expect("create_topics")
        {
            result.expect("create a test topic");
        }
        inputs
    }

    fn names(&self) -> [&str; 3] {
        [&self.events, &self.merges, &self.transfers]
    }

    fn merges_group(&self) -> String {
        format!("{}-merges", self.group)
    }

    fn groups(&self) -> Arc<InputGroups> {
        let mut config = Config::init_from_hashmap(&HashMap::new()).expect("default config");
        config.kafka_hosts = bootstrap_servers();
        config.cohort_stream_events_topic = self.events.clone();
        config.kafka_consumer_group = self.group.clone();
        config.person_merge_events_topic = self.merges.clone();
        config.kafka_merge_consumer_group = self.merges_group();
        config.cohort_merge_state_transfer_topic = self.transfers.clone();
        config.kafka_merge_apply_consumer_group = format!("{}-transfers", self.group);
        Arc::new(InputGroups::new(&config))
    }

    async fn delete(&self) {
        let _result = admin().delete_topics(&self.names(), &admin_options()).await;
    }
}

fn admin() -> AdminClient<DefaultClientContext> {
    ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .create()
        .expect("create admin client")
}

fn admin_options() -> AdminOptions {
    AdminOptions::new().operation_timeout(Some(Duration::from_secs(10)))
}

fn committer(group: &str) -> BaseConsumer {
    ClientConfig::new()
        .set("bootstrap.servers", bootstrap_servers())
        .set("group.id", group)
        .create()
        .expect("create committer")
}

/// Commits `offset` on `partition` for `group` with `metadata`, as a build from before stamps
/// (empty), an offset reset (empty) or another split would.
fn commit_as(group: &str, topic: &str, partition: i32, offset: i64, metadata: &str) {
    let mut list = TopicPartitionList::new();
    let mut elem = list.add_partition(topic, partition);
    elem.set_offset(Offset::Offset(offset)).unwrap();
    elem.set_metadata(metadata);
    committer(group)
        .commit(&list, CommitMode::Sync)
        .expect("commit");
}

fn every_partition() -> BTreeSet<u16> {
    (0..PARTITIONS).collect()
}

/// The broker keeps a commit's metadata, on every group: the claim stamps each owned partition at
/// its commit, or at the low watermark where the group never committed, and reads every stamp back.
/// A commit from a build before stamps reads back unstamped and admits. A claim admitted before
/// another split claimed refuses to commit over that split's stamps. If the broker stops keeping
/// metadata, this test fails first.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn commit_stamps_round_trip_on_every_group() {
    let inputs = Inputs::create().await;
    let groups = inputs.groups();
    commit_as(&inputs.group, &inputs.events, 1, 5, "");

    let before = groups.ledger(&every_partition()).unwrap();
    let events = before.inputs().next().unwrap();
    assert_eq!(
        events.commits()[&1],
        Committed::At {
            offset: ResumeOffset::try_from(5).unwrap(),
            stamp: Stamp::Unstamped,
        },
    );
    assert_eq!(events.commits()[&0], Committed::Never);

    let admitted = AdmittedSplit::try_admit(claim(1, 0, None), &groups)
        .expect("a commit without a stamp admits");
    assert_eq!(admitted.source(), StoreSource::Own);
    let stale =
        AdmittedSplit::try_admit(claim(2, 0, None), &groups).expect("nothing is stamped yet");
    admitted
        .claim(&groups)
        .expect("the claim reads its stamps back");
    assert!(
        stale.claim(&groups).is_err(),
        "a stale admission must not claim over another split's stamps",
    );

    let after = groups.ledger(&every_partition()).unwrap();
    let ours = Stamp::Split(split(1, 0));
    for input in after.inputs() {
        for (&partition, committed) in input.commits() {
            let resumes = if input.topic().as_str() == inputs.events && partition == 1 {
                5
            } else {
                0
            };
            assert_eq!(
                *committed,
                Committed::At {
                    offset: ResumeOffset::try_from(resumes).unwrap(),
                    stamp: ours.clone(),
                },
                "{} partition {partition}",
                input.topic(),
            );
        }
    }
    assert_eq!(after.inputs().count(), 3, "the claim stamps every group");

    inputs.delete().await;
}

/// A pod of a new split waits while the old split's stamps say its pods may still run. Without a
/// reshard marker it never admits. With one, it waits until its parent restarts under the new split,
/// then takes the partitions over, and after its own claim it keeps what it took over.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn a_pod_of_another_split_waits_until_the_split_is_consistent() {
    let inputs = Inputs::create().await;
    let groups = inputs.groups();
    let admit = |claim| AdmittedSplit::try_admit(claim, &groups);
    admit(claim(1, 0, None))
        .unwrap()
        .claim(&groups)
        .expect("the single pod claims every partition");

    assert!(matches!(
        admit(claim(2, 1, None)),
        Err(FenceError::Blocked(FenceBlock::ForeignSplit { found, .. })) if found == split(1, 0)
    ));
    assert!(matches!(
        admit(claim(2, 1, Some(1))),
        Err(FenceError::Blocked(FenceBlock::ParentRunning { parent })) if parent == split(1, 0)
    ));

    let parent = admit(claim(2, 0, Some(1))).expect("the parent admits over its own stamps");
    assert_eq!(parent.source(), StoreSource::Own);
    parent.claim(&groups).unwrap();

    let child = admit(claim(2, 1, Some(1))).expect("the parent restarted under the new split");
    assert_eq!(
        child.source(),
        StoreSource::TakeOver {
            parent: split(1, 0)
        }
    );
    child.claim(&groups).unwrap();
    assert_eq!(
        admit(claim(2, 1, Some(1))).unwrap().source(),
        StoreSource::Own,
        "a child that restarts after its claim finished its takeover",
    );

    inputs.delete().await;
}

/// The audit lets a commit without a stamp pass, as an operator's offset reset writes one, and stops
/// the pod when another split commits one of its partitions. It also revokes the pod's commits, so
/// the final commits of the stop cannot cover the foreign stamp, and the next boot holds. A
/// checkpoint then refuses that position.
#[tokio::test]
#[ignore = "requires a running Kafka broker (KAFKA_HOSTS); run with --ignored against a local stack"]
async fn the_audit_stops_a_pod_whose_partition_another_split_commits() {
    let inputs = Inputs::create().await;
    let groups = inputs.groups();
    let claimed = AdmittedSplit::try_admit(claim(1, 0, None), &groups)
        .unwrap()
        .claim(&groups)
        .unwrap();

    let audit_once = |name: &str| {
        let mut manager = Manager::builder(name).with_trap_signals(false).build();
        let handle = manager.register(
            "consumer",
            ComponentOptions::new().with_graceful_shutdown(Duration::from_secs(5)),
        );
        let monitor = manager.monitor_background();
        let audit = OwnershipAudit::new(groups.clone(), claimed.clone(), handle.clone());
        async move {
            audit.run_once().await;
            handle.work_completed();
            handle.request_shutdown();
            monitor.wait().await
        }
    };

    commit_as(&inputs.group, &inputs.events, 0, 3, "");
    audit_once("audit-reset")
        .await
        .expect("an unstamped commit passes");

    commit_as(
        &inputs.merges_group(),
        &inputs.merges,
        3,
        0,
        "cohort-split/1:2:1:4",
    );
    let stopped = audit_once("audit-foreign").await;
    assert!(
        matches!(stopped, Err(LifecycleError::ComponentFailure { ref reason, .. }) if reason.contains("another split")),
        "{stopped:?}",
    );
    let final_commit = claimed
        .stamp()
        .list(&inputs.merges, [(3, 1)])
        .unwrap()
        .commit(&committer(&inputs.merges_group()), CommitMode::Sync);
    assert!(final_commit.is_err(), "the audit revokes the pod's commits");
    assert!(
        AdmittedSplit::try_admit(claim(1, 0, None), &groups).is_err(),
        "the next boot holds in the fence",
    );
    let captured = groups.owned_positions(&claimed, &every_partition());
    assert!(
        matches!(captured, Err(PositionsError::Foreign { partition: 3, .. })),
        "a checkpoint takes no position another split committed: {captured:?}",
    );

    inputs.delete().await;
}
