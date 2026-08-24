use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Result};
use personhog_proto::personhog::types::v1::ConsistencyLevel;
use rand::{Rng, SeedableRng};
use serde_json::{json, Value};
use tokio::time::{interval, sleep, MissedTickBehavior};
use uuid::Uuid;

use crate::cli::BlastArgs;
use crate::client::HarnessClient;
use crate::report::{print_report, ConsistencyViolation};
use crate::state::PersonState;
use crate::stats::StatsCollector;
use crate::traffic_metrics;

pub async fn run(args: BlastArgs) -> Result<()> {
    let client =
        HarnessClient::connect_with_channels(&args.router_url, args.router_channels).await?;
    let person_ids = Arc::new(args.person_ids.clone());

    println!(
        "Blasting {} persons for {} with concurrency {}...",
        person_ids.len(),
        humantime::format_duration(args.duration),
        args.concurrency
    );

    let collector = Arc::new(StatsCollector::new());
    let state = PersonState::new();
    run_traffic(
        &client,
        args.team_id,
        person_ids.clone(),
        args.duration,
        args.concurrency,
        None,
        &PropertyPlan::new(
            args.property_prefix.clone(),
            args.property_keys_per_person,
            args.concurrency,
        ),
        &collector,
        &state,
        Arc::new(AtomicBool::new(false)),
    )
    .await?;

    let mut violations = state.take_anomalies().await;
    if args.verify {
        println!("Verifying reads with STRONG consistency...");
        violations.extend(verify_strong(&client, &collector, &state, args.team_id).await?);
    }

    print_report(
        "blast",
        &collector,
        args.team_id,
        person_ids.len(),
        &violations,
    );

    if !violations.is_empty() {
        bail!("{} consistency violations detected", violations.len());
    }
    Ok(())
}

/// A fixed set of property keys a traffic lane picks from at random.
///
/// A key per write instead grows the document without limit, and since
/// every update ships the whole person to the changelog, the byte rate
/// then grows quadratically in the writes a person has taken. Worker id
/// stays in the key: two workers sharing one would race, because acks are
/// journaled in arrival order, not application order.
#[derive(Clone)]
pub struct PropertyPlan {
    prefix: String,
    keys_per_worker: u64,
}

impl PropertyPlan {
    /// Splits the budget across workers so document size holds still when
    /// concurrency changes. Every worker needs a key of its own, so the
    /// floor is one each: a budget under the worker count delivers
    /// `concurrency` keys per person, and traffic mode refuses it.
    pub fn new(prefix: String, keys_per_person: u64, concurrency: usize) -> Self {
        let keys_per_worker = (keys_per_person.max(1) / concurrency.max(1) as u64).max(1);
        Self {
            prefix,
            keys_per_worker,
        }
    }

    fn key(&self, worker_id: usize, rng: &mut impl Rng) -> String {
        let slot = rng.gen_range(0..self.keys_per_worker);
        format!("{}{worker_id}_{slot}", self.prefix)
    }
}

/// Drive concurrent property updates against random targets until the
/// duration elapses, journaling every acked write into `state`.
///
/// With `rate_per_sec` set, the workers collectively pace to that target
/// (each worker ticks at rate/concurrency); unset, they run flat out.
/// `stop` ends the run early — shutdown must not wait out the full
/// duration, or Kubernetes kills the process before the caller can verify
/// what was acked. Metric emission is a no-op unless an exporter is
/// installed (only the traffic mode installs one), so instrumenting here
/// is free for the bounded modes.
#[allow(clippy::too_many_arguments)]
pub async fn run_traffic(
    client: &HarnessClient,
    team_id: i64,
    person_ids: Arc<Vec<i64>>,
    duration: Duration,
    concurrency: usize,
    rate_per_sec: Option<f64>,
    property_plan: &PropertyPlan,
    collector: &Arc<StatsCollector>,
    state: &PersonState,
    stop: Arc<AtomicBool>,
) -> Result<()> {
    let deadline = Instant::now() + duration;
    let worker_tick = rate_per_sec.map(|rate| per_worker_tick(rate, concurrency));

    let mut handles = Vec::new();
    for worker_id in 0..concurrency {
        let client = client.clone();
        let collector = collector.clone();
        let state = state.clone();
        let person_ids = person_ids.clone();
        let plan = property_plan.clone();
        let stop = stop.clone();

        handles.push(tokio::spawn(async move {
            let mut rng = rand::rngs::StdRng::from_entropy();
            let mut pacer = worker_tick.map(|tick| {
                let mut ticker = interval(tick);
                ticker.set_missed_tick_behavior(MissedTickBehavior::Delay);
                ticker
            });

            while Instant::now() < deadline && !stop.load(Ordering::Relaxed) {
                if let Some(pacer) = pacer.as_mut() {
                    pacer.tick().await;
                }
                let person_id = person_ids[rng.gen_range(0..person_ids.len())];

                let key = plan.key(worker_id, &mut rng);
                let value = Uuid::new_v4().to_string();
                let props = json!({ &key: &value });

                let start = Instant::now();
                match client
                    .update_properties(team_id, person_id, props, json!({}), vec![])
                    .await
                {
                    Ok(resp) => {
                        collector.writes.record_success(start.elapsed());
                        traffic_metrics::record_write_ok(
                            traffic_metrics::LANE_BLAST,
                            start.elapsed(),
                        );
                        let mut written = HashMap::new();
                        written.insert(key, serde_json::Value::String(value));
                        match resp.person {
                            Some(person) if resp.updated => {
                                state.record_write(person_id, person.version, written).await
                            }
                            // A no-change ack (an at-least-once replay whose
                            // first application landed) echoes the current
                            // version, owned by some other write — assert
                            // the keys, claim no version.
                            Some(_) => state.record_write_no_change(person_id, written).await,
                            None => state.record_ack_anomaly(person_id, written).await,
                        }
                    }
                    Err(e) => {
                        collector.writes.record_failure();
                        traffic_metrics::record_write_failed(traffic_metrics::LANE_BLAST, &e);
                        state.record_write_uncertain(person_id, &key).await;
                        // `{:#}` prints the full anyhow chain — the outer
                        // context alone hides the gRPC status underneath.
                        tracing::warn!(person_id, error = format!("{e:#}"), "write failed");
                    }
                }
            }
        }));
    }

    for handle in handles {
        handle.await?;
    }
    Ok(())
}

/// The tick interval each of `concurrency` workers needs so their
/// combined rate hits `rate_per_sec`. Rates too low to represent tick at
/// most once per hour rather than dividing by zero.
pub fn per_worker_tick(rate_per_sec: f64, concurrency: usize) -> Duration {
    let per_worker = (rate_per_sec / concurrency.max(1) as f64).max(1.0 / 3600.0);
    Duration::from_secs_f64(1.0 / per_worker)
}

/// Read every journaled person back with STRONG consistency and check that
/// all acked writes are visible. A person that cannot be read is a
/// violation, not a skip: NotFound for a person with acked writes means the
/// person is gone, and a read error (retried once, since verification can
/// race a settling handoff) means visibility cannot be asserted at all.
pub async fn verify_strong(
    client: &HarnessClient,
    collector: &StatsCollector,
    state: &PersonState,
    team_id: i64,
) -> Result<Vec<ConsistencyViolation>> {
    let person_ids = state.person_ids().await;
    let mut all_violations = Vec::new();

    for person_id in person_ids {
        let start = Instant::now();
        let mut result = client
            .get_person(team_id, person_id, ConsistencyLevel::Strong)
            .await;
        if result.is_err() {
            sleep(Duration::from_secs(2)).await;
            result = client
                .get_person(team_id, person_id, ConsistencyLevel::Strong)
                .await;
        }

        match result {
            Ok(Some(person)) => {
                collector.reads.record_success(start.elapsed());
                traffic_metrics::record_read_ok(traffic_metrics::LANE_VERIFY, start.elapsed());
                let props: Value = if person.properties.is_empty() {
                    json!({})
                } else {
                    serde_json::from_slice(&person.properties)?
                };
                let mut violations = state.verify(person_id, &props, person.version).await;
                all_violations.append(&mut violations);
            }
            Ok(None) => {
                collector.reads.record_failure();
                traffic_metrics::record_read_failed(traffic_metrics::LANE_VERIFY, "missing");
                all_violations.push(ConsistencyViolation {
                    person_id,
                    key: "__missing_person".to_string(),
                    expected: json!("person with acked writes exists"),
                    actual: Value::Null,
                });
            }
            Err(e) => {
                collector.reads.record_failure();
                traffic_metrics::record_read_failed(
                    traffic_metrics::LANE_VERIFY,
                    traffic_metrics::status_reason(&e),
                );
                all_violations.push(ConsistencyViolation {
                    person_id,
                    key: "__strong_read_failed".to_string(),
                    expected: json!("readable"),
                    actual: json!(e.to_string()),
                });
            }
        }
    }

    Ok(all_violations)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn per_worker_tick_divides_the_rate_across_workers() {
        // 100 wps over 20 workers: each ticks every 200ms.
        assert_eq!(per_worker_tick(100.0, 20), Duration::from_millis(200));
        // One worker carries the whole rate.
        assert_eq!(per_worker_tick(4.0, 1), Duration::from_millis(250));
        // Degenerate inputs stay finite instead of dividing by zero.
        assert!(per_worker_tick(0.0, 10) <= Duration::from_secs(3600));
        assert!(per_worker_tick(10.0, 0) <= Duration::from_secs(1));
    }

    /// The document bound is the whole point: a person may never collect
    /// more distinct keys than the budget, however long the run goes.
    #[test]
    fn workers_never_exceed_their_share_of_the_key_budget() {
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);
        let plan = PropertyPlan::new("p_".to_string(), 64, 8);

        let mut keys = std::collections::HashSet::new();
        for _ in 0..100_000 {
            keys.insert(plan.key(3, &mut rng));
            keys.insert(plan.key(5, &mut rng));
        }

        // 64 across 8 workers is 8 each, and the two workers never collide.
        assert_eq!(keys.len(), 16);
        assert!(keys
            .iter()
            .all(|k| k.starts_with("p_3_") || k.starts_with("p_5_")));
    }

    /// Splitting by concurrency is what keeps the bound stable while the
    /// bed scales workers, so the per-person total must not track it.
    #[test]
    fn the_key_budget_holds_as_concurrency_changes() {
        for concurrency in [1usize, 4, 16, 64] {
            let mut rng = rand::rngs::StdRng::seed_from_u64(11);
            let plan = PropertyPlan::new("p_".to_string(), 64, concurrency);
            let mut distinct = std::collections::HashSet::new();
            for worker_id in 0..concurrency {
                for _ in 0..5_000 {
                    distinct.insert(plan.key(worker_id, &mut rng));
                }
            }
            assert_eq!(distinct.len(), 64, "concurrency={concurrency}");
        }
        // Below the worker count the budget cannot be honoured: each
        // worker still takes one key, so the person collects `concurrency`
        // of them. Traffic mode rejects that configuration outright.
        let mut rng = rand::rngs::StdRng::seed_from_u64(13);
        let plan = PropertyPlan::new("p_".to_string(), 2, 8);
        let mut distinct = std::collections::HashSet::new();
        for worker_id in 0..8 {
            for _ in 0..100 {
                distinct.insert(plan.key(worker_id, &mut rng));
            }
        }
        assert_eq!(distinct.len(), 8);
    }
}
