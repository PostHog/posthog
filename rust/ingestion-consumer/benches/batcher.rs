//! Throughput of the batcher task's hot path: the state machine plus the
//! per-action work the driver does around it (worker pool snapshot, order
//! sentinel, worker health, completion counters, observer load), with the
//! Prometheus recorder installed. Only the network send is left out. Workers
//! answer every request after each poll.
//!
//! Each scenario runs for about one second of measured time, as many polls as
//! that takes. Generating the polls is not measured.
//!
//! cargo bench -p ingestion-consumer --bench batcher

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use ingestion_consumer::batcher::in_flight::RequestId;
use ingestion_consumer::batcher::key_queues::KeyRun;
use ingestion_consumer::batcher::packer::{PackTargets, Packer};
use ingestion_consumer::batcher::retry_policy::RetryPolicy;
use ingestion_consumer::batcher::state_machine::{BatcherStateMachine, Effects};
use ingestion_consumer::batcher::worker_assigner::WorkerAssigner;
use ingestion_consumer::batcher::worker_pool::{WorkerPool, WorkerPoolSource};
use ingestion_consumer::order_sentinel::{KeyOrderSentinel, SendKind};
use ingestion_consumer::routing::{Router, RoutingStrategy};
use ingestion_consumer::types::SerializedKafkaMessage;
use ingestion_consumer::worker_registry::{WorkerRegistry, WorkerRegistryConfig};
use metrics::counter;
use metrics_exporter_prometheus::PrometheusBuilder;
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};

const MEASURE: Duration = Duration::from_secs(1);
const WARMUP: Duration = Duration::from_millis(200);

const WORKERS: usize = 16;
const REQUESTS_PER_WORKER: usize = 4;
const POLL_MESSAGES: usize = 1_000;
const PARTITIONS: i32 = 64;
const HOT_KEYS: usize = 2_000;
const COLD_KEYS: usize = 200_000;
/// Share of messages from the hot keys, in percent.
const HOT_SHARE: u32 = 80;
const VALUE_BYTES: usize = 300;
const PACK_EVENTS: usize = 500;
const RETRY_DELAY: Duration = Duration::from_millis(5);
/// Virtual time between polls.
const POLL_INTERVAL: Duration = Duration::from_millis(1);

struct Scenario {
    name: &'static str,
    /// Every n-th response returns the last message of its first key; 0 never.
    partial_every: usize,
}

const SCENARIOS: &[Scenario] = &[
    Scenario {
        name: "all accepted",
        partial_every: 0,
    },
    Scenario {
        name: "every 10th response partial",
        partial_every: 10,
    },
];

struct Pending {
    request: RequestId,
    message_count: usize,
    returned: Option<SerializedKafkaMessage>,
}

/// The driver's per-action work around the state machine, minus the send.
struct Harness {
    state: Option<BatcherStateMachine>,
    pool_source: WorkerPoolSource,
    registry: Arc<WorkerRegistry>,
    sentinel: KeyOrderSentinel,
    in_flight: Vec<Pending>,
    wakeup: Option<Instant>,
    responses: usize,
    partial_every: usize,
}

impl Harness {
    fn new(partial_every: usize, now: Instant) -> Self {
        let urls: Vec<String> = (0..WORKERS)
            .map(|n| format!("http://10.0.0.{n}:6738"))
            .collect();
        let registry = Arc::new(WorkerRegistry::new(&urls, registry_config()));
        let pool_source = WorkerPoolSource::new(Arc::clone(&registry), RoutingStrategy::BinPack);
        let packer = Packer::new(PackTargets {
            events: PACK_EVENTS,
            bytes: 0,
            latency_budget: Duration::ZERO,
        });
        let assigner =
            WorkerAssigner::new(Router::new(RoutingStrategy::BinPack), REQUESTS_PER_WORKER)
                .expect("valid cap");
        let retry = RetryPolicy::uniform(RETRY_DELAY).expect("valid retry delay");
        let state = BatcherStateMachine::new(packer, assigner, retry, Duration::from_secs(60), now)
            .expect("valid stall timeout");
        Self {
            state: Some(state),
            pool_source,
            registry,
            sentinel: KeyOrderSentinel::new(),
            in_flight: Vec::new(),
            wakeup: None,
            responses: 0,
            partial_every,
        }
    }

    fn act(
        &mut self,
        action: impl FnOnce(BatcherStateMachine, &WorkerPool) -> (BatcherStateMachine, Effects),
    ) {
        let pool = self.pool_source.pool();
        let state = self.state.take().expect("state present");
        let (state, effects) = action(state, &pool);
        self.perform(&state, effects);
        self.state = Some(state);
    }

    fn perform(&mut self, state: &BatcherStateMachine, effects: Effects) {
        let Effects {
            sends,
            completions,
            key_acks,
            evicted_keys,
            worker_outcomes,
            idle_workers: _,
            busy_workers: _,
            fatal,
            next_wakeup,
        } = effects;
        assert!(fatal.is_none(), "batcher failed: {fatal:?}");
        for ack in &key_acks {
            self.sentinel.note_acked(&ack.routing_key, ack.max_offset);
        }
        for key in &evicted_keys {
            self.sentinel.evict(key);
        }
        for send in sends {
            let kind = if send.class.replay {
                SendKind::Resend
            } else {
                SendKind::Fresh
            };
            self.responses += 1;
            let returned = (self.partial_every > 0 && self.responses % self.partial_every == 0)
                .then(|| send.runs[0].messages.last().cloned())
                .flatten();
            let mut messages = Vec::new();
            for run in send.runs {
                self.sentinel
                    .note_sent(&run.routing_key, &run.messages, kind);
                messages.extend(run.messages);
            }
            self.in_flight.push(Pending {
                request: send.request,
                message_count: messages.len(),
                returned,
            });
            drop(messages);
        }
        for outcome in worker_outcomes {
            self.registry.record_outcome(&outcome.worker, outcome.fault);
        }
        for completion in completions {
            counter!("ingestion_consumer_group_completions_total").increment(1);
            counter!("ingestion_consumer_group_completion_accepted_messages_total")
                .increment(completion.accepted as u64);
        }
        self.wakeup = next_wakeup;
        std::hint::black_box((state.pending_messages(), state.in_flight_messages()));
    }

    /// One poll: submit it, answer every request in flight, and fire any due
    /// wakeup.
    fn cycle(&mut self, runs: Vec<KeyRun>, now: Instant) {
        self.act(|state, pool| state.on_groups(now, pool, 0, runs));
        while !self.in_flight.is_empty() {
            for pending in std::mem::take(&mut self.in_flight) {
                let (accepted, returned) = match pending.returned {
                    Some(message) => (pending.message_count as u32 - 1, vec![message]),
                    None => (pending.message_count as u32, Vec::new()),
                };
                self.act(|state, pool| {
                    state.on_request_succeeded(now, pool, pending.request, accepted, returned)
                });
            }
        }
        if self.wakeup.is_some_and(|at| at <= now) {
            self.act(|state, pool| state.on_wakeup(now, pool));
        }
    }
}

fn registry_config() -> WorkerRegistryConfig {
    WorkerRegistryConfig {
        probe_interval: Duration::from_secs(1),
        dead_declaration: Duration::from_secs(10),
        passive_window: Duration::from_secs(60),
        passive_error_threshold: 0.5,
        passive_min_samples: 1_000,
        degraded_hold: Duration::from_secs(5),
        min_state_duration: Duration::from_secs(1),
        probe_failure_threshold: 2,
        drain_timeout: Duration::from_secs(30),
    }
}

/// One poll's key runs, as the consumer loop builds them: messages of one key
/// sit on one partition, in offset order.
struct PollSource {
    rng: StdRng,
    next_offset: HashMap<i32, i64>,
    value: String,
}

impl PollSource {
    fn new() -> Self {
        Self {
            rng: StdRng::seed_from_u64(7),
            next_offset: HashMap::new(),
            value: "v".repeat(VALUE_BYTES),
        }
    }

    fn next(&mut self) -> Vec<KeyRun> {
        let mut runs: Vec<KeyRun> = Vec::new();
        let mut index_by_key: HashMap<usize, usize> = HashMap::new();
        for _ in 0..POLL_MESSAGES {
            let key = if self.rng.gen_range(0..100) < HOT_SHARE {
                self.rng.gen_range(0..HOT_KEYS)
            } else {
                HOT_KEYS + self.rng.gen_range(0..COLD_KEYS)
            };
            let partition = (key % PARTITIONS as usize) as i32;
            let offset = self.next_offset.entry(partition).or_insert(0);
            let message = SerializedKafkaMessage {
                topic: "events".to_string(),
                partition,
                offset: *offset,
                timestamp: 0,
                key: Some(format!("key-{key}")),
                value: Some(self.value.clone()),
                headers: HashMap::new(),
            };
            *offset += 1;
            match index_by_key.get(&key) {
                Some(&index) => runs[index].messages.push(message),
                None => {
                    index_by_key.insert(key, runs.len());
                    runs.push(KeyRun {
                        routing_key: format!("key-{key}"),
                        messages: vec![message],
                    });
                }
            }
        }
        runs
    }
}

fn run(scenario: &Scenario) {
    let mut clock = Instant::now();
    let mut harness = Harness::new(scenario.partial_every, clock);
    let mut source = PollSource::new();

    let mut measure = |budget: Duration| -> (Duration, usize, usize) {
        let mut measured = Duration::ZERO;
        let mut polls = 0;
        while measured < budget {
            let runs = source.next();
            clock += POLL_INTERVAL;
            let start = Instant::now();
            harness.cycle(runs, clock);
            measured += start.elapsed();
            polls += 1;
        }
        (measured, polls, polls * POLL_MESSAGES)
    };

    measure(WARMUP);
    let (measured, polls, messages) = measure(MEASURE);
    let per_second = messages as f64 / measured.as_secs_f64();
    println!(
        "{:<28} {:>10.0} msg/s  {:>7.0} ns/msg  ({polls} polls in {:.2?})",
        scenario.name,
        per_second,
        measured.as_nanos() as f64 / messages as f64,
        measured,
    );
}

fn main() {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("install the Prometheus recorder");
    println!(
        "{WORKERS} workers x {REQUESTS_PER_WORKER} requests, {POLL_MESSAGES}-message polls, \
         {HOT_KEYS} hot + {COLD_KEYS} cold keys, pack target {PACK_EVENTS}"
    );
    for scenario in SCENARIOS {
        run(scenario);
    }
}
