use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Result};
use metrics::{counter, histogram};
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

pub async fn run(args: BlastArgs) -> Result<()> {
    let client = HarnessClient::connect(&args.router_url).await?;
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
        &args.property_prefix,
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
    property_prefix: &str,
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
        let prefix = property_prefix.to_string();
        let stop = stop.clone();

        handles.push(tokio::spawn(async move {
            let mut counter: u64 = 0;
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
                counter += 1;

                let key = format!("{prefix}{worker_id}_{counter}");
                let value = Uuid::new_v4().to_string();
                let props = json!({ &key: &value });

                let start = Instant::now();
                match client
                    .update_properties(team_id, person_id, props, json!({}), vec![])
                    .await
                {
                    Ok(resp) => {
                        collector.writes.record_success(start.elapsed());
                        counter!("personhog_traffic_writes_total", "outcome" => "ok").increment(1);
                        histogram!("personhog_traffic_write_seconds")
                            .record(start.elapsed().as_secs_f64());
                        let mut written = HashMap::new();
                        written.insert(key, serde_json::Value::String(value));
                        match resp.person {
                            Some(person) => {
                                state.record_write(person_id, person.version, written).await
                            }
                            None => state.record_ack_anomaly(person_id, written).await,
                        }
                    }
                    Err(e) => {
                        collector.writes.record_failure();
                        counter!("personhog_traffic_writes_total", "outcome" => "failed")
                            .increment(1);
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
                all_violations.push(ConsistencyViolation {
                    person_id,
                    key: "__missing_person".to_string(),
                    expected: json!("person with acked writes exists"),
                    actual: Value::Null,
                });
            }
            Err(e) => {
                collector.reads.record_failure();
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
}
