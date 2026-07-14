use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use sqlx::postgres::PgPool;
use sqlx::Row;

use crate::cli::GateArgs;
use crate::client::CannonClient;
use crate::report::{print_report, ConsistencyViolation};
use crate::scenarios::blast;
use crate::seed;
use crate::stack::{Stack, StackConfig};
use crate::state::{ExpectedPerson, PersonState};
use crate::stats::StatsCollector;

/// How long to wait for the writer to drain acked writes into Postgres
/// before declaring them lost.
const QUIESCE_DEADLINE: Duration = Duration::from_secs(60);

/// The full e2e correctness gate: bring up an isolated stack (or target a
/// running one), seed persons, drive update traffic through the router,
/// then assert every acked write is visible via strong reads AND lands in
/// Postgres with the acked version. Exits non-zero on any violation, so it
/// can gate CI.
pub async fn run(args: GateArgs) -> Result<()> {
    let mut stack = match &args.external_router_url {
        Some(_) => None,
        None => {
            let bin_dir = match &args.bin_dir {
                Some(dir) => dir.clone(),
                None => std::env::current_exe()
                    .context("resolving current executable")?
                    .parent()
                    .context("executable has no parent directory")?
                    .to_path_buf(),
            };
            Some(
                Stack::up(StackConfig {
                    bin_dir,
                    leaders: args.leaders,
                    partitions: args.partitions,
                    kafka_hosts: args.kafka_hosts.clone(),
                    etcd_endpoints: args.etcd_endpoints.clone(),
                    persons_db_url: args.persons_db_url.clone(),
                    writer_flush_interval_ms: 1000,
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
    let client = CannonClient::connect(&router_url).await?;

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
    blast::run_traffic(
        &client,
        args.team_id,
        person_ids.clone(),
        args.duration,
        args.concurrency,
        "cannon_gate_",
        &collector,
        &state,
    )
    .await?;

    if let Some(stack) = stack.as_mut() {
        stack.check_alive()?;
    }

    println!("Verifying strong reads...");
    let mut violations = blast::verify_strong(&client, &collector, &state, args.team_id).await?;

    println!("Waiting for the writer to drain, then verifying Postgres...");
    let journal = state.snapshot().await;
    violations.extend(verify_postgres(&pool, args.team_id, &journal).await?);

    print_report(
        "gate",
        &collector,
        args.team_id,
        person_ids.len(),
        &violations,
    );

    if !args.keep_data {
        let (persons, _) = seed::cleanup_team(&pool, args.team_id).await?;
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
    println!("Gate passed: every acked write visible in strong reads and Postgres");
    Ok(())
}

/// Poll Postgres until every journaled person row contains all acked
/// property writes at the acked version, or the quiesce deadline passes.
/// Returns the outstanding violations (empty = converged).
async fn verify_postgres(
    pool: &PgPool,
    team_id: i64,
    journal: &HashMap<i64, ExpectedPerson>,
) -> Result<Vec<ConsistencyViolation>> {
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;
    let person_ids: Vec<i64> = journal.keys().copied().collect();
    if person_ids.is_empty() {
        return Ok(Vec::new());
    }

    let deadline = Instant::now() + QUIESCE_DEADLINE;
    loop {
        let rows = sqlx::query(
            "SELECT id, properties::text AS properties, version \
             FROM posthog_person WHERE team_id = $1 AND id = ANY($2)",
        )
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
                    violations.extend(crate::state::verify_properties(
                        *person_id,
                        &expected.written_properties,
                        props,
                    ));
                    // The writer applies changelog records in order under a
                    // version guard, so once quiesced the row must sit at
                    // exactly the highest acked version.
                    if *version != expected.last_version {
                        violations.push(ConsistencyViolation {
                            person_id: *person_id,
                            key: "__version".to_string(),
                            expected: serde_json::json!(expected.last_version),
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
