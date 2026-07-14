use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use personhog_proto::personhog::types::v1::ConsistencyLevel;

use crate::cli::ConsistencyArgs;
use crate::client::HarnessClient;
use crate::report::{print_report, ConsistencyViolation};
use crate::state::PersonState;
use crate::stats::StatsCollector;

pub async fn run(args: ConsistencyArgs) -> Result<()> {
    let client = HarnessClient::connect(&args.router_url).await?;
    let person_ids = Arc::new(args.person_ids.clone());

    println!(
        "Running consistency test: {} persons, {} workers, {} iterations each",
        person_ids.len(),
        args.concurrency,
        args.iterations
    );

    let collector = Arc::new(StatsCollector::new());
    let violations = Arc::new(tokio::sync::Mutex::new(Vec::<ConsistencyViolation>::new()));
    let violation_count = Arc::new(AtomicU64::new(0));

    let mut handles = Vec::new();
    for worker_id in 0..args.concurrency {
        let client = client.clone();
        let collector = collector.clone();
        let violations = violations.clone();
        let violation_count = violation_count.clone();
        let person_ids = person_ids.clone();
        let team_id = args.team_id;
        let iterations = args.iterations;
        let read_delay = args.read_delay;

        handles.push(tokio::spawn(async move {
            for i in 0..iterations {
                let person_id = person_ids[(worker_id + i as usize) % person_ids.len()];
                let marker = uuid::Uuid::new_v4().to_string();
                let key = format!("harness_consistency_{marker}");

                let write_start = Instant::now();
                let write_result = client
                    .update_properties(
                        team_id,
                        person_id,
                        serde_json::json!({ &key: &marker }),
                        serde_json::json!({}),
                        vec![],
                    )
                    .await;

                match write_result {
                    Ok(resp) => {
                        collector.writes.record_success(write_start.elapsed());
                        if resp.person.is_none() {
                            // The response contract is that updates return
                            // the updated person; a bare ack is a violation,
                            // not a skip.
                            violation_count.fetch_add(1, Ordering::Relaxed);
                            let mut v = violations.lock().await;
                            if v.len() < 100 {
                                v.push(ConsistencyViolation {
                                    person_id,
                                    key: "__ack_missing_person".to_string(),
                                    expected: serde_json::json!(
                                        "update response carries the person"
                                    ),
                                    actual: serde_json::Value::Null,
                                });
                            }
                            continue;
                        }
                    }
                    Err(e) => {
                        collector.writes.record_failure();
                        tracing::warn!(person_id, error = %e, "consistency write failed");
                        continue;
                    }
                }

                if !read_delay.is_zero() {
                    tokio::time::sleep(read_delay).await;
                }

                let read_start = Instant::now();
                match client
                    .get_person(team_id, person_id, ConsistencyLevel::Strong)
                    .await
                {
                    Ok(Some(person)) => {
                        collector.reads.record_success(read_start.elapsed());
                        let props: serde_json::Value = if person.properties.is_empty() {
                            serde_json::json!({})
                        } else {
                            match serde_json::from_slice(&person.properties) {
                                Ok(v) => v,
                                Err(e) => {
                                    tracing::warn!(
                                        person_id,
                                        error = %e,
                                        "failed to parse properties"
                                    );
                                    continue;
                                }
                            }
                        };

                        let actual = props.get(&key);
                        let expected = serde_json::Value::String(marker.clone());
                        if actual != Some(&expected) {
                            violation_count.fetch_add(1, Ordering::Relaxed);
                            let mut v = violations.lock().await;
                            if v.len() < 100 {
                                v.push(ConsistencyViolation {
                                    person_id,
                                    key: key.clone(),
                                    expected,
                                    actual: actual.cloned().unwrap_or(serde_json::Value::Null),
                                });
                            }
                        }
                    }
                    Ok(None) => {
                        collector.reads.record_failure();
                        tracing::warn!(person_id, "person not found during read-back");
                    }
                    Err(e) => {
                        collector.reads.record_failure();
                        tracing::warn!(person_id, error = %e, "consistency read failed");
                    }
                }
            }
        }));
    }

    for handle in handles {
        handle.await?;
    }

    let final_violations = violations.lock().await;
    print_report(
        "consistency",
        &collector,
        args.team_id,
        person_ids.len(),
        &final_violations,
    );

    let total_violations = violation_count.load(Ordering::Relaxed);
    if total_violations > 0 {
        bail!("{total_violations} consistency violations detected");
    }
    Ok(())
}

/// Read-your-write probers for the gate: each prober repeatedly writes a
/// unique key and immediately strong-reads it back until the deadline.
/// They run alongside the blast traffic, so recency is asserted *during*
/// chaos windows — a transient staleness window that has healed by the
/// end of the run is invisible to the end-of-run verification but trips a
/// prober on the very next read.
///
/// Probed writes are journaled like any other ack, so the end-of-run
/// checks cover their durability too. The mid-run assertion checks only
/// the prober's own key: concurrent blast acks race the journal, so
/// comparing a live read against the full journal would flag phantom
/// violations. A failed read is likewise not a recency violation — reads
/// legitimately fail while a killed owner's partitions are in limbo, and
/// end-of-run verification owns readability.
pub async fn run_probers(
    client: &HarnessClient,
    team_id: i64,
    person_ids: Arc<Vec<i64>>,
    probers: usize,
    duration: Duration,
    collector: &Arc<StatsCollector>,
    state: &PersonState,
) -> Result<Vec<ConsistencyViolation>> {
    let deadline = Instant::now() + duration;

    let mut handles = Vec::new();
    for worker_id in 0..probers {
        let client = client.clone();
        let collector = collector.clone();
        let state = state.clone();
        let person_ids = person_ids.clone();

        handles.push(tokio::spawn(async move {
            let mut violations = Vec::new();
            let mut iteration: usize = 0;

            while Instant::now() < deadline {
                let person_id = person_ids[(worker_id + iteration) % person_ids.len()];
                iteration += 1;
                let marker = uuid::Uuid::new_v4().to_string();
                let key = format!("harness_probe_{worker_id}_{iteration}");

                let write_start = Instant::now();
                let response = match client
                    .update_properties(
                        team_id,
                        person_id,
                        serde_json::json!({ &key: &marker }),
                        serde_json::json!({}),
                        vec![],
                    )
                    .await
                {
                    Ok(response) => {
                        collector.writes.record_success(write_start.elapsed());
                        response
                    }
                    Err(e) => {
                        collector.writes.record_failure();
                        tracing::warn!(person_id, error = %e, "probe write failed");
                        continue;
                    }
                };
                let mut written = HashMap::new();
                written.insert(key.clone(), serde_json::Value::String(marker.clone()));
                match response.person {
                    Some(person) => {
                        state.record_write(person_id, person.version, written).await;
                    }
                    None => {
                        // Already flagged as a violation by the journal; the
                        // keys still get end-of-run verification.
                        state.record_ack_anomaly(person_id, written).await;
                        continue;
                    }
                }

                let read_start = Instant::now();
                match client
                    .get_person(team_id, person_id, ConsistencyLevel::Strong)
                    .await
                {
                    Ok(Some(person)) => {
                        collector.reads.record_success(read_start.elapsed());
                        let props: serde_json::Value = serde_json::from_slice(&person.properties)
                            .unwrap_or_else(|_| serde_json::json!({}));
                        let expected = serde_json::Value::String(marker);
                        let actual = props.get(&key);
                        if actual != Some(&expected) {
                            violations.push(ConsistencyViolation {
                                person_id,
                                key,
                                expected,
                                actual: actual.cloned().unwrap_or(serde_json::Value::Null),
                            });
                        }
                    }
                    Ok(None) => {
                        // A served read that cannot see a person with an
                        // acked write is a violation, not an availability
                        // blip.
                        collector.reads.record_failure();
                        violations.push(ConsistencyViolation {
                            person_id,
                            key,
                            expected: serde_json::Value::String(marker),
                            actual: serde_json::Value::Null,
                        });
                    }
                    Err(e) => {
                        collector.reads.record_failure();
                        tracing::warn!(person_id, error = %e, "probe read failed");
                    }
                }
            }
            violations
        }));
    }

    let mut all_violations = Vec::new();
    for handle in handles {
        all_violations.extend(handle.await.context("prober task panicked")?);
    }
    Ok(all_violations)
}
