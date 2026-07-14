use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

use anyhow::{bail, Result};
use personhog_proto::personhog::types::v1::ConsistencyLevel;

use crate::cli::ConsistencyArgs;
use crate::client::HarnessClient;
use crate::report::{print_report, ConsistencyViolation};
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
                            collector.reads.record_failure();
                            tracing::warn!(person_id, "person not returned from update");
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
