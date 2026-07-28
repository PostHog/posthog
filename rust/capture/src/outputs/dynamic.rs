//! Prototype: dynamic outputs with incremental switchover — test-only.
//!
//! A concept demonstration that the [`Outputs`] abstraction accommodates a
//! coordinator-managed produce surface, per the repartitioning-coordinator
//! design note. Nothing here ships: the module is `cfg(test)` and everything
//! runs in process, but the seams are the real ones —
//!
//! - [`KafkaManagerService`] is the coordinator's client surface, shaped
//!   like an RPC service: subscribers register a channel; the manager pushes
//!   [`Change`]s and awaits an application ack per subscriber (a config push
//!   with a response, which is what a fenced switchover protocol needs).
//! - [`DynamicKafkaOutputs`] implements [`Outputs`]: it preps like any leaf
//!   surface, then realizes each address against *live* routing state — a
//!   map of brokers to transport sinks plus, per address, a current mapping
//!   and an optional in-progress switch (next mapping + the set of logical
//!   partitions already enabled on it).
//!
//! The incremental switch: a [`Change::MappingChanged`] carries the target
//! (broker, topic, partition count) and the enabled partition set. Events
//! whose logical partition (a deterministic hash of the partition key) is
//! enabled publish through the new mapping; the rest stay on the old one.
//! Widening the enabled set partition by partition is the coordinator's
//! drain-and-switch loop; enabling every partition completes the switch and
//! drops the old mapping. Brokers arrive and leave via
//! [`Change::BrokerAdded`] / [`Change::BrokerRemoved`] (the sink for a
//! removed broker is flushed and dropped).

use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex, RwLock};

use async_trait::async_trait;
use tokio::sync::{mpsc, oneshot};

use crate::api::CaptureError;
use crate::outputs::{prepare_batch, Outputs, PrepSpec};
use crate::pipeline::Address;
use crate::sinks::kafka::{KafkaSinkBase, RealizedRecord};
use crate::sinks::producer::{MockKafkaProducer, ProduceRecord};
use crate::sinks::SinkResult;
use crate::v0_request::ProcessedEvent;

pub(crate) type BrokerId = String;

/// One concrete destination for an address: a broker's namespace.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Mapping {
    pub broker: BrokerId,
    pub topic: String,
    pub partition_count: u32,
}

/// The change feed a managed outputs surface subscribes to.
#[derive(Clone, Debug)]
pub(crate) enum Change {
    /// A new broker (cluster) is available; the subscriber builds a sink.
    BrokerAdded { id: BrokerId },
    /// A broker is gone; the subscriber flushes and drops its sink.
    BrokerRemoved { id: BrokerId },
    /// (Re)target an address: the new mapping plus the logical partitions
    /// already enabled on it. A subset starts or advances an incremental
    /// switch; the full set completes it.
    MappingChanged {
        address: Address,
        broker: BrokerId,
        topic: String,
        partition_count: u32,
        enabled_partitions: Vec<u32>,
    },
}

/// In-process stand-in for the coordinator's RPC service. `broadcast`
/// resolves only after every subscriber has applied the change — the acked
/// config push a fenced switchover builds on.
/// A pushed change paired with the application-ack channel.
type AckedChange = (Change, oneshot::Sender<()>);

#[derive(Default)]
pub(crate) struct KafkaManagerService {
    subscribers: Mutex<Vec<mpsc::UnboundedSender<AckedChange>>>,
}

impl KafkaManagerService {
    pub fn new() -> Self {
        Self::default()
    }

    /// Register a subscriber; the returned receiver is the client's end of
    /// the change feed.
    pub fn subscribe(&self) -> mpsc::UnboundedReceiver<AckedChange> {
        let (tx, rx) = mpsc::unbounded_channel();
        self.subscribers.lock().unwrap().push(tx);
        rx
    }

    /// Push a change to every subscriber and await application acks.
    pub async fn broadcast(&self, change: Change) {
        let subscribers = self.subscribers.lock().unwrap().clone();
        for sub in subscribers {
            let (ack_tx, ack_rx) = oneshot::channel();
            sub.send((change.clone(), ack_tx))
                .expect("subscriber task gone");
            ack_rx.await.expect("subscriber dropped ack");
        }
    }
}

/// Per-address routing: the current mapping, plus an in-progress switch.
#[derive(Clone, Debug)]
struct AddressRoute {
    current: Mapping,
    next: Option<(Mapping, HashSet<u32>)>,
}

impl AddressRoute {
    /// Pick the mapping for a partition key: an event whose logical
    /// partition is enabled on the in-progress switch target publishes
    /// there; everything else stays on the current mapping.
    fn select(&self, key: Option<&str>) -> &Mapping {
        if let Some((next, enabled)) = &self.next {
            if enabled.contains(&logical_partition(key, next.partition_count)) {
                return next;
            }
        }
        &self.current
    }
}

/// Deterministic stand-in for the producer's partitioner: the coordinator
/// and the switch decision must agree on the key → partition function, so
/// the prototype pins a trivial one both the output and the tests compute.
/// Keyless events get partition 0 (no per-key ordering contract to fence).
pub(crate) fn logical_partition(key: Option<&str>, partition_count: u32) -> u32 {
    match key {
        Some(key) => key.bytes().map(u32::from).sum::<u32>() % partition_count,
        None => 0,
    }
}

/// Builds a transport sink for a broker the manager announces. Tests inject
/// mock producers per broker through this seam.
type SinkFactory = Box<dyn Fn(&BrokerId) -> KafkaSinkBase<MockKafkaProducer> + Send + Sync>;

#[derive(Default)]
struct RoutingState {
    sinks: HashMap<BrokerId, KafkaSinkBase<MockKafkaProducer>>,
    routes: HashMap<Address, AddressRoute>,
}

/// A coordinator-managed produce surface: just another [`Outputs`]
/// implementation, whose namespace realization reads live state instead of a
/// boot-time table.
pub(crate) struct DynamicKafkaOutputs {
    prep: PrepSpec,
    state: Arc<RwLock<RoutingState>>,
}

impl DynamicKafkaOutputs {
    /// Subscribe to the manager and spawn the applier task. The task owns
    /// the subscription; each change is applied under the write lock, then
    /// acked back to the manager.
    pub fn subscribed(prep: PrepSpec, manager: &KafkaManagerService, factory: SinkFactory) -> Self {
        let state = Arc::new(RwLock::new(RoutingState::default()));
        let mut rx = manager.subscribe();
        let task_state = state.clone();
        tokio::spawn(async move {
            while let Some((change, ack)) = rx.recv().await {
                apply(&task_state, &factory, change);
                let _ = ack.send(());
            }
        });
        Self { prep, state }
    }
}

fn apply(state: &RwLock<RoutingState>, factory: &SinkFactory, change: Change) {
    let mut state = state.write().unwrap();
    match change {
        Change::BrokerAdded { id } => {
            let sink = factory(&id);
            state.sinks.insert(id, sink);
        }
        Change::BrokerRemoved { id } => {
            if let Some(sink) = state.sinks.remove(&id) {
                // Drain what the departing broker's producer still buffers
                // before dropping it — the transport half of the fence.
                sink.flush().expect("flush of removed broker failed");
            }
        }
        Change::MappingChanged {
            address,
            broker,
            topic,
            partition_count,
            enabled_partitions,
        } => {
            let mapping = Mapping {
                broker,
                topic,
                partition_count,
            };
            let fully_enabled = enabled_partitions.len() as u32 == partition_count;
            let enabled: HashSet<u32> = enabled_partitions.into_iter().collect();
            match state.routes.get_mut(&address) {
                None => {
                    // First mapping for this address: current, no switch.
                    state.routes.insert(
                        address,
                        AddressRoute {
                            current: mapping,
                            next: None,
                        },
                    );
                }
                Some(route) if fully_enabled => {
                    // Every partition enabled: the switch is complete and
                    // the old mapping is gone.
                    route.current = mapping;
                    route.next = None;
                }
                Some(route) => {
                    route.next = Some((mapping, enabled));
                }
            }
        }
    }
}

#[async_trait]
impl Outputs for DynamicKafkaOutputs {
    async fn publish(&self, events: Vec<ProcessedEvent>) -> Vec<SinkResult> {
        let uuids: Vec<uuid::Uuid> = events.iter().map(|e| e.event.uuid).collect();
        let prepared = match prepare_batch(&self.prep, events).await {
            Ok(prepared) => prepared,
            Err(err) => {
                return uuids
                    .into_iter()
                    .map(|uuid| SinkResult::err(uuid, err.clone()))
                    .collect()
            }
        };

        // Realize each payload against live routing state, grouping per
        // broker (linear scan — prototype batches are small) while
        // preserving within-broker order.
        let mut results: Vec<SinkResult> = Vec::new();
        let mut per_broker: Vec<(
            BrokerId,
            KafkaSinkBase<MockKafkaProducer>,
            Vec<RealizedRecord>,
        )> = Vec::new();
        {
            let state = self.state.read().unwrap();
            for payload in prepared {
                let Some(route) = state.routes.get(&payload.address) else {
                    results.push(SinkResult::err(
                        payload.uuid,
                        CaptureError::NonRetryableSinkError,
                    ));
                    continue;
                };
                let mapping = route.select(payload.key.as_deref());
                let realized = RealizedRecord {
                    uuid: payload.uuid,
                    record: ProduceRecord {
                        topic: mapping.topic.clone(),
                        key: payload.key,
                        payload: payload.payload,
                        headers: payload.headers,
                    },
                };
                match per_broker
                    .iter_mut()
                    .find(|(id, _, _)| *id == mapping.broker)
                {
                    Some((_, _, records)) => records.push(realized),
                    None => {
                        let Some(sink) = state.sinks.get(&mapping.broker) else {
                            results.push(SinkResult::err(
                                realized.uuid,
                                CaptureError::NonRetryableSinkError,
                            ));
                            continue;
                        };
                        per_broker.push((mapping.broker.clone(), sink.clone(), vec![realized]));
                    }
                }
            }
        }

        for (_, sink, records) in per_broker {
            results.extend(sink.publish(records).await);
        }
        results
    }

    fn flush(&self) -> Result<(), anyhow::Error> {
        let state = self.state.read().unwrap();
        for sink in state.sinks.values() {
            sink.flush()?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::EnvelopeCompression;
    use crate::pipeline::AnalyticsLane;
    use crate::utils::uuid_v7_from_datetime;
    use crate::v0_request::{DataType, ProcessedEventMetadata};
    use common_types::CapturedEvent;

    const ANALYTICS: Address = Address::Analytics(AnalyticsLane::Main);
    const PARTITIONS: u32 = 4;

    fn event(distinct_id: &str) -> ProcessedEvent {
        let timestamp = chrono::Utc::now();
        ProcessedEvent {
            event: CapturedEvent {
                uuid: uuid_v7_from_datetime(timestamp),
                distinct_id: distinct_id.to_string(),
                session_id: None,
                ip: "127.0.0.1".to_string(),
                data: "{}".to_string(),
                now: "2024-01-01T00:00:00Z".to_string(),
                sent_at: None,
                token: "tok".to_string(),
                event: "test_event".to_string(),
                timestamp,
                is_cookieless_mode: false,
                historical_migration: false,
            },
            metadata: ProcessedEventMetadata {
                data_type: DataType::AnalyticsMain,
                session_id: None,
                computed_timestamp: None,
                event_name: "test_event".to_string(),
                force_overflow: false,
                skip_person_processing: false,
                redirect_to_dlq: false,
                redirect_to_topic: None,
                skip_heatmap_processing: false,
                overflow_reason: None,
            },
        }
    }

    /// A batch with distinct partition keys spread over the logical
    /// partition space.
    fn batch() -> Vec<ProcessedEvent> {
        (0..8).map(|i| event(&format!("did-{i}"))).collect()
    }

    /// Shared registry of per-broker mock producers plus the factory the
    /// dynamic outputs builds sinks through when the manager announces a
    /// broker.
    fn producer_registry() -> (
        Arc<Mutex<HashMap<BrokerId, MockKafkaProducer>>>,
        SinkFactory,
    ) {
        let producers: Arc<Mutex<HashMap<BrokerId, MockKafkaProducer>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let factory_producers = producers.clone();
        let factory: SinkFactory = Box::new(move |id: &BrokerId| {
            let producer = factory_producers
                .lock()
                .unwrap()
                .entry(id.clone())
                .or_default()
                .clone();
            KafkaSinkBase::with_producer(producer)
        });
        (producers, factory)
    }

    fn producer(
        producers: &Arc<Mutex<HashMap<BrokerId, MockKafkaProducer>>>,
        id: &str,
    ) -> MockKafkaProducer {
        producers
            .lock()
            .unwrap()
            .get(id)
            .expect("broker known")
            .clone()
    }

    fn clear_all(producers: &Arc<Mutex<HashMap<BrokerId, MockKafkaProducer>>>) {
        for p in producers.lock().unwrap().values() {
            p.clear();
        }
    }

    fn mapping(broker: &str, topic: &str, enabled: Vec<u32>) -> Change {
        Change::MappingChanged {
            address: ANALYTICS,
            broker: broker.to_string(),
            topic: topic.to_string(),
            partition_count: PARTITIONS,
            enabled_partitions: enabled,
        }
    }

    #[tokio::test]
    async fn incremental_topic_switchover_on_one_broker() {
        let manager = KafkaManagerService::new();
        let (producers, factory) = producer_registry();
        let output = DynamicKafkaOutputs::subscribed(
            PrepSpec::new(EnvelopeCompression::None, false),
            &manager,
            factory,
        );

        manager
            .broadcast(Change::BrokerAdded {
                id: "kafka-a".to_string(),
            })
            .await;
        manager
            .broadcast(mapping("kafka-a", "events_v1", (0..PARTITIONS).collect()))
            .await;

        // Steady state: everything lands on events_v1.
        output.publish_folded(batch()).await.unwrap();
        let records = producer(&producers, "kafka-a").get_records();
        assert_eq!(records.len(), 8);
        assert!(records.iter().all(|r| r.topic == "events_v1"));
        clear_all(&producers);

        // Begin the switch: partitions 0 and 1 enabled on events_v2. Only
        // events whose logical partition is enabled move; the rest stay —
        // the incremental, key-deterministic drain-and-switch.
        manager
            .broadcast(mapping("kafka-a", "events_v2", vec![0, 1]))
            .await;
        output.publish_folded(batch()).await.unwrap();
        let records = producer(&producers, "kafka-a").get_records();
        assert_eq!(records.len(), 8);
        let mut moved = 0;
        for record in &records {
            let partition = logical_partition(record.key.as_deref(), PARTITIONS);
            let expected = if [0, 1].contains(&partition) {
                moved += 1;
                "events_v2"
            } else {
                "events_v1"
            };
            assert_eq!(record.topic, expected, "partition {partition}");
        }
        assert!(
            moved > 0 && moved < 8,
            "test keys must straddle the enabled set (moved {moved}/8)"
        );
        clear_all(&producers);

        // Complete the switch: all partitions enabled, old mapping gone.
        manager
            .broadcast(mapping("kafka-a", "events_v2", (0..PARTITIONS).collect()))
            .await;
        output.publish_folded(batch()).await.unwrap();
        let records = producer(&producers, "kafka-a").get_records();
        assert_eq!(records.len(), 8);
        assert!(records.iter().all(|r| r.topic == "events_v2"));
    }

    #[tokio::test]
    async fn incremental_broker_switchover() {
        let manager = KafkaManagerService::new();
        let (producers, factory) = producer_registry();
        let output = DynamicKafkaOutputs::subscribed(
            PrepSpec::new(EnvelopeCompression::None, false),
            &manager,
            factory,
        );

        manager
            .broadcast(Change::BrokerAdded {
                id: "kafka-a".to_string(),
            })
            .await;
        manager
            .broadcast(mapping("kafka-a", "events", (0..PARTITIONS).collect()))
            .await;
        output.publish_folded(batch()).await.unwrap();
        assert_eq!(producer(&producers, "kafka-a").get_records().len(), 8);
        clear_all(&producers);

        // New cluster appears; partitions 0 and 1 cut over to it. Same
        // topic name, different namespace — the mapping carries both.
        manager
            .broadcast(Change::BrokerAdded {
                id: "kafka-b".to_string(),
            })
            .await;
        manager
            .broadcast(mapping("kafka-b", "events", vec![0, 1]))
            .await;
        output.publish_folded(batch()).await.unwrap();
        let on_a = producer(&producers, "kafka-a").get_records();
        let on_b = producer(&producers, "kafka-b").get_records();
        assert_eq!(on_a.len() + on_b.len(), 8, "nothing lost mid-switch");
        assert!(!on_a.is_empty() && !on_b.is_empty());
        for record in &on_b {
            let partition = logical_partition(record.key.as_deref(), PARTITIONS);
            assert!([0, 1].contains(&partition), "only enabled partitions move");
        }
        for record in &on_a {
            let partition = logical_partition(record.key.as_deref(), PARTITIONS);
            assert!(
                ![0, 1].contains(&partition),
                "enabled partitions must not stay"
            );
        }
        clear_all(&producers);

        // Complete the cutover and retire the old cluster.
        manager
            .broadcast(mapping("kafka-b", "events", (0..PARTITIONS).collect()))
            .await;
        manager
            .broadcast(Change::BrokerRemoved {
                id: "kafka-a".to_string(),
            })
            .await;
        output.publish_folded(batch()).await.unwrap();
        assert!(producer(&producers, "kafka-a").get_records().is_empty());
        let on_b = producer(&producers, "kafka-b").get_records();
        assert_eq!(on_b.len(), 8);
        assert!(on_b.iter().all(|r| r.topic == "events"));
    }
}
