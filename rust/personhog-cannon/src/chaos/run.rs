use anyhow::{bail, Result};
use owo_colors::OwoColorize;
use rand::{Rng, SeedableRng};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Semaphore;

use personhog_proto::personhog::types::v1::ConsistencyLevel;

use crate::cli::ChaosRunArgs;
use crate::client::CannonClient;
use crate::report::print_report;
use crate::state::PersonState;
use crate::stats::StatsCollector;

use super::etcd::EtcdState;
use super::k8s;

pub async fn run(client: CannonClient, args: ChaosRunArgs) -> Result<()> {
    let etcd = EtcdState::connect(&args.etcd_endpoints, &args.etcd_prefix).await?;

    println!("{}", "=== initial coordination state ===".bold());
    print_brief_status(&etcd).await?;

    let person_ids = resolve_person_ids(&client, &args).await?;
    if person_ids.is_empty() {
        bail!("no persons found — provide --person-ids or --discover-distinct-ids");
    }
    println!(
        "Targeting {} persons for team {}",
        person_ids.len().bold(),
        args.team_id
    );

    let mut schedule: Vec<ScheduledEvent> = Vec::new();

    if let Some(kill_after) = args.kill_after {
        schedule.push(ScheduledEvent {
            at: kill_after,
            action: ChaosAction::KillLeader,
        });
    }

    if let Some(scale_up_after) = args.scale_up_after {
        schedule.push(ScheduledEvent {
            at: scale_up_after,
            action: ChaosAction::ScaleUp,
        });
    }

    if let Some(shutdown_after) = args.shutdown_after {
        let pod_name = args.shutdown_pod_name.clone();
        schedule.push(ScheduledEvent {
            at: shutdown_after,
            action: ChaosAction::ShutdownLeader { pod_name },
        });
    }

    schedule.sort_by_key(|e| e.at);

    if schedule.is_empty() {
        println!(
            "  {} no disruptions scheduled — running a plain blast",
            "WARN".yellow()
        );
    } else {
        println!("  Disruption schedule:");
        for event in &schedule {
            println!(
                "    {:>6}: {}",
                humantime::format_duration(event.at),
                event.action.describe()
            );
        }
    }
    println!();

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
        let team_id = args.team_id;

        handles.push(tokio::spawn(async move {
            let mut counter: u64 = 0;
            let mut rng = rand::rngs::StdRng::from_entropy();

            while Instant::now() < deadline {
                let _permit = sem.acquire().await.unwrap();
                let idx = rng.gen_range(0..person_ids.len());
                let person_id = person_ids[idx];
                counter += 1;

                let key = format!("cannon_{worker_id}_{counter}");
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
                    Err(_) => {
                        collector.writes.record_failure();
                    }
                }
            }
        }));
    }

    let namespace = args.namespace.clone();
    let statefulset_name = args.statefulset_name.clone();
    let label = args.label.clone();
    let etcd_for_chaos = EtcdState::connect(&args.etcd_endpoints, &args.etcd_prefix).await?;
    let chaos_handle = tokio::spawn(async move {
        let start = Instant::now();
        for event in schedule {
            let wait = event.at.saturating_sub(start.elapsed());
            if !wait.is_zero() {
                tokio::time::sleep(wait).await;
            }
            if Instant::now() >= deadline {
                break;
            }

            println!();
            println!(
                "  {} [t={:.1}s] {}",
                "CHAOS".red().bold(),
                start.elapsed().as_secs_f64(),
                event.action.describe()
            );

            if let Err(e) = execute_action(
                &event.action,
                &namespace,
                &statefulset_name,
                &label,
                &etcd_for_chaos,
            )
            .await
            {
                println!("    {} {e}", "ERR".red());
            }
        }
    });

    for handle in handles {
        drop(handle.await);
    }
    chaos_handle.abort();

    println!();
    println!("Waiting for coordination to stabilize...");
    match etcd.wait_for_stable(Duration::from_secs(60)).await {
        Ok(()) => println!("  {} coordination stable", "OK".green()),
        Err(e) => println!("  {} {e}", "WARN".yellow()),
    }

    println!();
    println!("{}", "=== post-chaos coordination state ===".bold());
    print_brief_status(&etcd).await?;

    println!("Verifying reads with STRONG consistency...");
    let mut violations = Vec::new();
    let tracked_ids = state.person_ids().await;

    for person_id in tracked_ids {
        let start = Instant::now();
        match client
            .get_person(args.team_id, person_id, ConsistencyLevel::Strong)
            .await
        {
            Ok(Some(person)) => {
                collector.reads.record_success(start.elapsed());
                let props: serde_json::Value = if person.properties.is_empty() {
                    serde_json::json!({})
                } else {
                    serde_json::from_slice(&person.properties)?
                };
                let mut v = state.verify(person_id, &props).await;
                violations.append(&mut v);
            }
            Ok(None) => {
                collector.reads.record_failure();
            }
            Err(_) => {
                collector.reads.record_failure();
            }
        }
    }

    print_report(
        "chaos run",
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

struct ScheduledEvent {
    at: Duration,
    action: ChaosAction,
}

enum ChaosAction {
    KillLeader,
    ScaleUp,
    ShutdownLeader { pod_name: Option<String> },
}

impl ChaosAction {
    fn describe(&self) -> String {
        match self {
            ChaosAction::KillLeader => "force-delete leader pod + lease revoke".to_string(),
            ChaosAction::ScaleUp => "scale up StatefulSet (+1 replica)".to_string(),
            ChaosAction::ShutdownLeader { pod_name } => {
                let target = pod_name.as_deref().unwrap_or("(first found)");
                format!("graceful delete: {target}")
            }
        }
    }
}

async fn execute_action(
    action: &ChaosAction,
    namespace: &str,
    statefulset_name: &str,
    label: &str,
    etcd: &EtcdState,
) -> Result<()> {
    match action {
        ChaosAction::KillLeader => {
            let pods = k8s::list_leader_pods(namespace, label).await?;
            let target = pods
                .iter()
                .find(|p| p.ready)
                .or(pods.first())
                .map(|p| p.name.clone());

            if let Some(pod_name) = &target {
                println!("    Revoking lease for {pod_name}...");
                if let Err(e) = etcd.revoke_pod_lease(pod_name).await {
                    println!("    {} lease revoke: {e}", "WARN".yellow());
                } else {
                    println!("    {} lease revoked", "OK".green());
                }

                println!("    Force-deleting pod {pod_name}...");
                k8s::force_delete_pod(namespace, pod_name).await?;
                println!("    {} pod deleted", "OK".green());
            } else {
                println!("    {} no leader pods found", "WARN".yellow());
            }
            Ok(())
        }
        ChaosAction::ScaleUp => {
            let current = k8s::get_statefulset_replicas(namespace, statefulset_name).await?;
            let target = current + 1;
            println!("    Scaling {statefulset_name} from {current} to {target}...");
            k8s::scale_statefulset(namespace, statefulset_name, target).await?;
            println!("    {} scale issued", "OK".green());

            let new_pod = format!("{statefulset_name}-{}", target - 1);
            println!("    Waiting for {new_pod} to become Ready...");
            match k8s::wait_for_pod_ready(namespace, &new_pod, 120).await {
                Ok(()) => println!("    {} {new_pod} is Ready", "OK".green()),
                Err(e) => println!("    {} {e}", "WARN".yellow()),
            }
            Ok(())
        }
        ChaosAction::ShutdownLeader { pod_name } => {
            let target = match pod_name {
                Some(name) => name.clone(),
                None => {
                    let pods = k8s::list_leader_pods(namespace, label).await?;
                    pods.first()
                        .map(|p| p.name.clone())
                        .unwrap_or_else(|| format!("{statefulset_name}-0"))
                }
            };
            println!("    Gracefully deleting pod {target}...");
            k8s::delete_pod(namespace, &target).await?;
            println!("    {} delete issued", "OK".green());
            Ok(())
        }
    }
}

async fn resolve_person_ids(client: &CannonClient, args: &ChaosRunArgs) -> Result<Vec<i64>> {
    let mut ids = args.person_ids.clone();

    if !args.discover_distinct_ids.is_empty() {
        let results = client
            .discover_by_distinct_ids(args.team_id, args.discover_distinct_ids.clone())
            .await?;
        for r in results {
            if let Some(person) = r.person {
                if !ids.contains(&person.id) {
                    ids.push(person.id);
                }
            }
        }
    }

    Ok(ids)
}

async fn print_brief_status(etcd: &EtcdState) -> Result<()> {
    let pods = etcd.list_pods().await?;
    let assignments = etcd.list_assignments().await?;
    let handoffs = etcd.list_handoffs().await?;

    let pod_names: Vec<&str> = pods.iter().map(|p| p.pod_name.as_str()).collect();
    println!("  Pods: {:?}", pod_names);
    println!("  Assignments: {} partitions assigned", assignments.len());
    if !handoffs.is_empty() {
        println!("  Handoffs: {} active", handoffs.len());
    }

    Ok(())
}
