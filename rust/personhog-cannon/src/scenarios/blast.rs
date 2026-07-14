use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Result};
use personhog_proto::personhog::types::v1::ConsistencyLevel;
use rand::{Rng, SeedableRng};

use crate::cli::BlastArgs;
use crate::client::CannonClient;
use crate::report::{print_report, ConsistencyViolation};
use crate::state::PersonState;
use crate::stats::StatsCollector;

pub async fn run(args: BlastArgs) -> Result<()> {
    let client = CannonClient::connect(&args.router_url).await?;
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
        &args.property_prefix,
        &collector,
        &state,
    )
    .await?;

    let mut violations = Vec::new();
    if args.verify {
        println!("Verifying reads with STRONG consistency...");
        violations = verify_strong(&client, &collector, &state, args.team_id).await?;
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
#[allow(clippy::too_many_arguments)]
pub async fn run_traffic(
    client: &CannonClient,
    team_id: i64,
    person_ids: Arc<Vec<i64>>,
    duration: Duration,
    concurrency: usize,
    property_prefix: &str,
    collector: &Arc<StatsCollector>,
    state: &PersonState,
) -> Result<()> {
    let deadline = Instant::now() + duration;

    let mut handles = Vec::new();
    for worker_id in 0..concurrency {
        let client = client.clone();
        let collector = collector.clone();
        let state = state.clone();
        let person_ids = person_ids.clone();
        let prefix = property_prefix.to_string();

        handles.push(tokio::spawn(async move {
            let mut counter: u64 = 0;
            let mut rng = rand::rngs::StdRng::from_entropy();

            while Instant::now() < deadline {
                let person_id = person_ids[rng.gen_range(0..person_ids.len())];
                counter += 1;

                let key = format!("{prefix}{worker_id}_{counter}");
                let value = uuid::Uuid::new_v4().to_string();
                let props = serde_json::json!({ &key: &value });

                let start = Instant::now();
                match client
                    .update_properties(team_id, person_id, props, serde_json::json!({}), vec![])
                    .await
                {
                    Ok(resp) => {
                        collector.writes.record_success(start.elapsed());
                        if let Some(person) = resp.person {
                            let mut written = HashMap::new();
                            written.insert(key, serde_json::Value::String(value));
                            state.record_write(person_id, person.version, written).await;
                        }
                    }
                    Err(e) => {
                        collector.writes.record_failure();
                        tracing::warn!(person_id, error = %e, "write failed");
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

/// Read every journaled person back with STRONG consistency and check that
/// all acked writes are visible.
pub async fn verify_strong(
    client: &CannonClient,
    collector: &StatsCollector,
    state: &PersonState,
    team_id: i64,
) -> Result<Vec<ConsistencyViolation>> {
    let person_ids = state.person_ids().await;
    let mut all_violations = Vec::new();

    for person_id in person_ids {
        let start = Instant::now();
        match client
            .get_person(team_id, person_id, ConsistencyLevel::Strong)
            .await
        {
            Ok(Some(person)) => {
                collector.reads.record_success(start.elapsed());
                let props: serde_json::Value = if person.properties.is_empty() {
                    serde_json::json!({})
                } else {
                    serde_json::from_slice(&person.properties)?
                };
                let mut violations = state.verify(person_id, &props).await;
                all_violations.append(&mut violations);
            }
            Ok(None) => {
                collector.reads.record_failure();
                tracing::warn!(person_id, "person not found during verification");
            }
            Err(e) => {
                collector.reads.record_failure();
                tracing::warn!(person_id, error = %e, "read failed during verification");
            }
        }
    }

    Ok(all_violations)
}
