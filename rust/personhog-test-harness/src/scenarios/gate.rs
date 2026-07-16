use std::collections::HashMap;
use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use sqlx::postgres::PgPool;
use sqlx::Row;

use crate::cli::GateArgs;
use crate::client::HarnessClient;
use crate::report::{print_report, ConsistencyViolation};
use crate::scenarios::{blast, consistency};
use crate::seed;
use crate::stack::{Stack, StackConfig};
use crate::state::{verify_properties, ExpectedPerson, PersonState};
use crate::stats::StatsCollector;

/// How long to wait for the writer to drain acked writes into Postgres
/// before declaring them lost.
const QUIESCE_DEADLINE: Duration = Duration::from_secs(60);

/// A chaos disruption scheduled relative to the start of the traffic phase.
enum ChaosEvent {
    Kill { fast: bool },
    Shutdown,
    ScaleUp,
    Restart,
    ZombieStop,
    ZombieResume,
    WriterCrash,
    WriterPause,
    WriterResume,
    RouterKill { fast: bool },
    RouterShutdown,
}

impl fmt::Display for ChaosEvent {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ChaosEvent::Kill { fast: true } => write!(f, "kill (fast lease revoke)"),
            ChaosEvent::Kill { fast: false } => write!(f, "kill (lease TTL expiry)"),
            ChaosEvent::Shutdown => write!(f, "graceful shutdown"),
            ChaosEvent::ScaleUp => write!(f, "scale up"),
            ChaosEvent::Restart => write!(f, "leader crash-restart"),
            ChaosEvent::ZombieStop => write!(f, "zombie stop (SIGSTOP + lease revoke)"),
            ChaosEvent::ZombieResume => write!(f, "zombie resume (SIGCONT)"),
            ChaosEvent::WriterCrash => write!(f, "writer crash-restart"),
            ChaosEvent::WriterPause => write!(f, "writer pause (lag injection)"),
            ChaosEvent::WriterResume => write!(f, "writer resume"),
            ChaosEvent::RouterKill { fast: true } => write!(f, "coordinator router kill"),
            ChaosEvent::RouterKill { fast: false } => {
                write!(f, "coordinator router crash (lease TTL expiry)")
            }
            ChaosEvent::RouterShutdown => write!(f, "coordinator router graceful shutdown"),
        }
    }
}

fn chaos_timeline(args: &GateArgs) -> Vec<(Duration, ChaosEvent)> {
    let mut events = Vec::new();
    if let Some(after) = args.kill_after {
        events.push((
            after,
            ChaosEvent::Kill {
                fast: args.kill_fast,
            },
        ));
    }
    if let Some(after) = args.shutdown_after {
        events.push((after, ChaosEvent::Shutdown));
    }
    if let Some(after) = args.scale_up_after {
        events.push((after, ChaosEvent::ScaleUp));
    }
    if let Some(after) = args.restart_after {
        events.push((after, ChaosEvent::Restart));
    }
    if let Some(after) = args.zombie_after {
        events.push((after, ChaosEvent::ZombieStop));
        events.push((after + args.zombie_duration, ChaosEvent::ZombieResume));
    }
    if let Some(after) = args.writer_crash_after {
        events.push((after, ChaosEvent::WriterCrash));
    }
    if let Some(after) = args.writer_pause_after {
        events.push((after, ChaosEvent::WriterPause));
        events.push((after + args.writer_pause_duration, ChaosEvent::WriterResume));
    }
    if let Some(after) = args.router_kill_after {
        events.push((
            after,
            ChaosEvent::RouterKill {
                fast: args.router_kill_fast,
            },
        ));
    }
    if let Some(after) = args.router_shutdown_after {
        events.push((after, ChaosEvent::RouterShutdown));
    }
    events.sort_by_key(|(after, _)| *after);
    events
}

/// The workspace target directory for the profile this harness was built
/// with, derived from the crate's location at compile time. The runtime
/// executable path is deliberately not consulted — its output is
/// attacker-influenceable — and the harness only ever runs sibling
/// binaries produced by the same cargo build; `--bin-dir` overrides for
/// anything else.
fn default_bin_dir() -> PathBuf {
    let profile = if cfg!(debug_assertions) {
        "debug"
    } else {
        "release"
    };
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../target")
        .join(profile)
}

/// The full e2e correctness gate: bring up an isolated stack (or target a
/// running one), seed persons, drive update traffic through the router —
/// optionally disrupting the stack mid-traffic — then assert every acked
/// write is visible via strong reads AND lands in Postgres with the acked
/// version. Exits non-zero on any violation, so it can gate CI.
pub async fn run(args: GateArgs) -> Result<()> {
    seed::validate_table_name(&args.pg_target_table)?;
    let chaos = chaos_timeline(&args);
    if args.external_router_url.is_some() && (!chaos.is_empty() || args.kill_handoff_target) {
        bail!("chaos flags require a spawned stack; they cannot target --external-router-url");
    }
    if (args.router_kill_after.is_some() || args.router_shutdown_after.is_some())
        && args.routers < 2
    {
        bail!("--router-kill-after requires --routers >= 2 (traffic targets the last router)");
    }
    if args.kill_handoff_target && args.shutdown_after.is_none() && args.scale_up_after.is_none() {
        bail!("--kill-handoff-target needs a handoff-creating event (--shutdown-after or --scale-up-after)");
    }

    let mut stack = match &args.external_router_url {
        Some(_) => None,
        None => {
            let bin_dir = args.bin_dir.clone().unwrap_or_else(default_bin_dir);
            Some(
                Stack::up(StackConfig {
                    bin_dir,
                    leaders: args.leaders,
                    routers: args.routers,
                    partitions: args.partitions,
                    kafka_hosts: args.kafka_hosts.clone(),
                    etcd_endpoints: args.etcd_endpoints.clone(),
                    persons_db_url: args.persons_db_url.clone(),
                    writer_flush_interval_ms: 1000,
                    pg_target_table: args.pg_target_table.clone(),
                    cache_memory_capacity: args.cache_capacity,
                    leader_lease_ttl: args.leader_lease_ttl,
                })
                .await?,
            )
        }
    };

    let router_url = match (&args.external_router_url, &stack) {
        (Some(url), _) => url.clone(),
        (None, Some(stack)) => stack.router_url.clone(),
        (None, None) => unreachable!(),
    };
    let client = HarnessClient::connect(&router_url).await?;

    let pool = PgPool::connect(&args.persons_db_url)
        .await
        .context("connecting to persons DB")?;

    // A crashed prior run may have left rows behind; the team id belongs to
    // the harness, so start from a clean slate.
    seed::cleanup_team(&pool, args.team_id).await?;
    let person_ids = Arc::new(seed::seed_persons(&pool, args.team_id, args.persons).await?);
    println!(
        "Seeded {} persons for team {}",
        person_ids.len(),
        args.team_id
    );

    println!(
        "Driving traffic for {} with concurrency {}...",
        humantime::format_duration(args.duration),
        args.concurrency
    );
    let collector = Arc::new(StatsCollector::new());
    let state = PersonState::new();
    let traffic = {
        let client = client.clone();
        let person_ids = person_ids.clone();
        let collector = collector.clone();
        let state = state.clone();
        let (team_id, duration, concurrency) = (args.team_id, args.duration, args.concurrency);
        tokio::spawn(async move {
            blast::run_traffic(
                &client,
                team_id,
                person_ids,
                duration,
                concurrency,
                "harness_gate_",
                &collector,
                &state,
            )
            .await
        })
    };

    // Read-your-write probers run for the same window as the traffic, so
    // recency is asserted through whatever chaos fires below.
    let probers = {
        let client = client.clone();
        let person_ids = person_ids.clone();
        let collector = collector.clone();
        let state = state.clone();
        let (team_id, duration, prober_count) = (args.team_id, args.duration, args.probers);
        tokio::spawn(async move {
            consistency::run_probers(
                &client,
                team_id,
                person_ids,
                prober_count,
                duration,
                &collector,
                &state,
            )
            .await
        })
    };

    // Fire scheduled disruptions while traffic flows. Failures aren't
    // journaled, so the invariant is untouched: whatever the leader acked
    // through the disruption must still be visible afterwards.
    let traffic_start = Instant::now();
    let mut handoff_kill_armed = args.kill_handoff_target;
    for (after, event) in chaos {
        let stack = stack.as_mut().expect("chaos requires a spawned stack");
        tokio::time::sleep_until((traffic_start + after).into()).await;
        let creates_handoff = matches!(event, ChaosEvent::Shutdown | ChaosEvent::ScaleUp);
        let pod = match event {
            ChaosEvent::Kill { fast } => Some(stack.kill_leader(fast).await?),
            ChaosEvent::Shutdown => Some(stack.shutdown_leader().await?),
            ChaosEvent::ScaleUp => Some(stack.spawn_leader()?),
            ChaosEvent::Restart => Some(stack.restart_leader().await?),
            ChaosEvent::ZombieStop => Some(stack.stop_zombie().await?),
            ChaosEvent::ZombieResume => Some(stack.resume_zombie()?),
            ChaosEvent::WriterCrash => {
                stack.crash_restart_writer().await?;
                None
            }
            ChaosEvent::WriterPause => {
                stack.pause_writer()?;
                None
            }
            ChaosEvent::WriterResume => {
                stack.resume_writer()?;
                None
            }
            ChaosEvent::RouterKill { fast } => Some(stack.kill_coordinator_router(fast).await?),
            ChaosEvent::RouterShutdown => Some(stack.shutdown_coordinator_router().await?),
        };
        println!(
            "Chaos at {:.1}s: {event} → pod {} | {}",
            traffic_start.elapsed().as_secs_f64(),
            pod.as_deref().unwrap_or("-"),
            stack.coordination_report().await,
        );

        // Immediately after the first handoff-creating event, optionally
        // hunt the resulting handoff and kill its target mid-flight.
        if handoff_kill_armed && creates_handoff {
            handoff_kill_armed = false;
            match stack.kill_handoff_target(Duration::from_secs(15)).await? {
                Some(victim) => println!(
                    "Chaos at {:.1}s: killed handoff target → pod {victim} | {}",
                    traffic_start.elapsed().as_secs_f64(),
                    stack.coordination_report().await,
                ),
                None => println!("No in-flight handoff observed; handoff-target kill skipped"),
            }
        }
    }

    traffic.await.context("traffic task panicked")??;
    let prober_violations = probers.await.context("prober task panicked")??;

    // Verification asserts data visibility on a converged topology, not
    // recovery speed: chaos legitimately leaves handoffs to re-drive, and
    // the protocol's convergence is bounded (worst known case ~40s via the
    // drained pod's lifecycle timeout). An already-settled run waits zero
    // time; a run that cannot converge fails here with the stuck state.
    if let Some(stack) = stack.as_mut() {
        let settled = stack
            .wait_converged(Duration::from_secs(90))
            .await
            .context("coordination must converge before verification")?;
        println!(
            "Post-traffic coordination settled in {:.1}s: {}",
            settled.as_secs_f64(),
            stack.coordination_report().await
        );
    }

    println!("Verifying strong reads...");
    let mut violations = prober_violations;
    violations.extend(state.take_anomalies().await);
    violations.extend(blast::verify_strong(&client, &collector, &state, args.team_id).await?);

    println!("Waiting for the writer to drain, then verifying Postgres...");
    let journal = state.snapshot().await;
    violations.extend(verify_postgres(&pool, &args.pg_target_table, args.team_id, &journal).await?);

    print_report(
        "gate",
        &collector,
        args.team_id,
        person_ids.len(),
        &violations,
    );

    if !args.keep_data {
        let persons = seed::cleanup_team(&pool, args.team_id).await?;
        if args.pg_target_table != "posthog_person" {
            seed::cleanup_target_table(&pool, &args.pg_target_table, args.team_id).await?;
        }
        println!("Cleaned up {persons} persons");
    }

    if let Some(stack) = stack {
        if args.keep_stack {
            println!(
                "Stack left running (logs at {}); services die with this process",
                stack.log_dir.display()
            );
            // Hold the stack (and its kill-on-drop children) until the user
            // interrupts, since child processes die with the harness.
            tokio::signal::ctrl_c().await?;
            stack.down().await?;
        } else {
            stack.down().await?;
        }
    }

    if !violations.is_empty() {
        bail!("{} consistency violations detected", violations.len());
    }
    // The invariant is "acked implies visible", which zero acks satisfy
    // vacuously — a stack that failed every write must not pass the gate.
    if collector.writes.snapshot().successes == 0 {
        bail!("no writes were acked; the gate asserted nothing");
    }
    println!("Gate passed: every acked write visible in strong reads and Postgres");
    Ok(())
}

/// Poll Postgres until every journaled person row contains all acked
/// property writes at the acked version, or the quiesce deadline passes.
/// Returns the outstanding violations (empty = converged).
async fn verify_postgres(
    pool: &PgPool,
    table: &str,
    team_id: i64,
    journal: &HashMap<i64, ExpectedPerson>,
) -> Result<Vec<ConsistencyViolation>> {
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;
    let person_ids: Vec<i64> = journal.keys().copied().collect();
    if person_ids.is_empty() {
        return Ok(Vec::new());
    }

    let query = format!(
        "SELECT id, properties::text AS properties, version \
         FROM {table} WHERE team_id = $1 AND id = ANY($2)"
    );
    let deadline = Instant::now() + QUIESCE_DEADLINE;
    loop {
        let rows = sqlx::query(&query)
            .bind(team)
            .bind(&person_ids)
            .fetch_all(pool)
            .await
            .context("reading persons from Postgres")?;

        let mut by_id: HashMap<i64, (serde_json::Value, i64)> = HashMap::new();
        for row in rows {
            let id: i64 = row.get("id");
            let properties: Option<String> = row.get("properties");
            let version: Option<i64> = row.get("version");
            let props = properties
                .as_deref()
                .map(serde_json::from_str)
                .transpose()
                .context("parsing properties JSON")?
                .unwrap_or_else(|| serde_json::json!({}));
            by_id.insert(id, (props, version.unwrap_or(0)));
        }

        let mut violations = Vec::new();
        for (person_id, expected) in journal {
            match by_id.get(person_id) {
                Some((props, version)) => {
                    violations.extend(verify_properties(
                        *person_id,
                        &expected.written_properties,
                        props,
                    ));
                    // The highest acked version is a floor, not an exact
                    // target: a write that produced its record but lost the
                    // response (a drain, a client timeout) is unacked yet
                    // still applied, legitimately leaving the row above the
                    // floor. Below it, an acked write never reached
                    // Postgres.
                    if *version < expected.last_version {
                        violations.push(ConsistencyViolation {
                            person_id: *person_id,
                            key: "__version".to_string(),
                            expected: serde_json::json!(format!(">= {}", expected.last_version)),
                            actual: serde_json::json!(version),
                        });
                    }
                }
                None => {
                    violations.push(ConsistencyViolation {
                        person_id: *person_id,
                        key: "__row".to_string(),
                        expected: serde_json::json!("present"),
                        actual: serde_json::Value::Null,
                    });
                }
            }
        }

        if violations.is_empty() {
            return Ok(violations);
        }
        if Instant::now() > deadline {
            tracing::error!(
                outstanding = violations.len(),
                "Postgres did not converge within {QUIESCE_DEADLINE:?}"
            );
            return Ok(violations);
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

#[cfg(test)]
mod tests {
    use clap::Parser;

    use super::*;
    use crate::cli::{Cli, Command};

    fn gate_args(extra: &[&str]) -> GateArgs {
        let mut argv = vec!["personhog-test-harness", "gate"];
        argv.extend_from_slice(extra);
        match Cli::try_parse_from(argv)
            .expect("gate args must parse")
            .command
        {
            Command::Gate(args) => *args,
            _ => unreachable!("gate subcommand parses to Gate"),
        }
    }

    #[test]
    fn chaos_timeline_is_empty_without_flags() {
        assert!(chaos_timeline(&gate_args(&[])).is_empty());
    }

    /// Events must fire in offset order regardless of flag order, and the
    /// paired disruptions (zombie, writer pause) must schedule their
    /// resume at start + duration — a mis-built timeline silently runs a
    /// different scenario than the flags describe.
    #[test]
    fn chaos_timeline_sorts_events_and_pairs_stop_with_resume() {
        let args = gate_args(&[
            "--kill-after",
            "10s",
            "--shutdown-after",
            "5s",
            "--zombie-after",
            "7s",
            "--zombie-duration",
            "3s",
            "--writer-pause-after",
            "2s",
            "--writer-pause-duration",
            "1s",
        ]);
        let rendered: Vec<(u64, String)> = chaos_timeline(&args)
            .iter()
            .map(|(after, event)| (after.as_secs(), event.to_string()))
            .collect();
        let expected: Vec<(u64, String)> = [
            (2, "writer pause (lag injection)"),
            (3, "writer resume"),
            (5, "graceful shutdown"),
            (7, "zombie stop (SIGSTOP + lease revoke)"),
            (10, "kill (fast lease revoke)"),
            (10, "zombie resume (SIGCONT)"),
        ]
        .into_iter()
        .map(|(after, event)| (after, event.to_string()))
        .collect();
        assert_eq!(rendered, expected);
    }
}
