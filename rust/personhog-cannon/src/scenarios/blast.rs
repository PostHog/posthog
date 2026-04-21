use anyhow::{bail, Result};
use owo_colors::OwoColorize;
use rand::{Rng, SeedableRng};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::Semaphore;

use personhog_proto::personhog::types::v1::ConsistencyLevel;

use crate::cli::BlastArgs;
use crate::client::CannonClient;
use crate::report::{print_report, ConsistencyViolation};
use crate::state::PersonState;
use crate::stats::StatsCollector;

pub async fn run(client: CannonClient, args: BlastArgs) -> Result<()> {
    let person_ids = client
        .resolve_person_ids(args.team_id, &args.person_ids, &args.discover_distinct_ids)
        .await?;
    if person_ids.is_empty() {
        bail!("no persons found — provide --person-ids or --discover-distinct-ids");
    }
    println!(
        "Targeting {} persons for team {}",
        person_ids.len().bold(),
        args.team_id
    );

    let state = PersonState::new();
    let collector = Arc::new(StatsCollector::new());
    let semaphore = Arc::new(Semaphore::new(args.concurrency));
    let person_ids = Arc::new(person_ids);
    let deadline = Instant::now() + args.duration;

    println!(
        "Blasting for {} with concurrency {}...",
        humantime::format_duration(args.duration),
        args.concurrency
    );

    let mut handles = Vec::new();
    for worker_id in 0..args.concurrency {
        let client = client.clone();
        let sem = semaphore.clone();
        let collector = collector.clone();
        let state = state.clone();
        let person_ids = person_ids.clone();
        let prefix = args.property_prefix.clone();
        let team_id = args.team_id;

        handles.push(tokio::spawn(async move {
            let mut counter: u64 = 0;
            let mut rng = rand::rngs::StdRng::from_entropy();

            while Instant::now() < deadline {
                let _permit = sem.acquire().await.unwrap();
                let idx = rng.gen_range(0..person_ids.len());
                let person_id = person_ids[idx];
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

    let mut violations = Vec::new();
    if args.verify {
        println!("Verifying reads with STRONG consistency...");
        violations = verify_reads(&client, &collector, &state, args.team_id).await?;
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

async fn verify_reads(
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
