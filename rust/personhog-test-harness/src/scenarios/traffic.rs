//! Continuous synthetic traffic for the dev deployment.
//!
//! Runs forever in verification epochs: seed a fresh person pool, drive
//! paced blast traffic and read-your-write probers at an epoch-specific
//! rate drawn from a configured range, then close the epoch — verify every
//! acked write against strong reads and Postgres, export violations as
//! metrics, rotate the pool, repeat. Pool rotation is load-bearing: blast
//! journals each write under a unique key, so an unrotated person's
//! document would grow into the admission size ceiling and legitimate
//! trims would read as false violations.
//!
//! Rate variance doubles as the autoscaler driver in dev; violations
//! surface exclusively through metrics and logs (a Deployment restart loop
//! can't fix a consistency bug, so the process does not exit on them). A
//! hostile lane sends NUL-bearing and oversized payloads against a
//! dedicated team, observed as outcome metrics rather than verified — its
//! expected behavior legitimately differs across stack versions as
//! admission hardening lands.
//!
//! Every database operation — seeding, verification, cleanup — touches
//! only the configured target table (the writer's validation table), never
//! posthog_person; a startup sentinel round-trip proves the router serves
//! that same table before any traffic flows. Shutdown cuts the in-flight
//! epoch's load short and runs the normal close-out (verify what was
//! acked, record, clean up) inside the termination grace window.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::{bail, Context, Result};
use metrics::{counter, gauge};
use personhog_proto::personhog::types::v1::ConsistencyLevel;
use rand::{Rng, SeedableRng};
use serde_json::{json, Value};
use sqlx::postgres::PgPool;
#[cfg(unix)]
use tokio::signal::unix::{signal, SignalKind};
use tokio::time::{interval, MissedTickBehavior};
use uuid::Uuid;

use crate::cli::TrafficArgs;
use crate::client::HarnessClient;
use crate::scenarios::{blast, consistency};
use crate::seed;
use crate::state::PersonState;
use crate::stats::StatsCollector;
use crate::traffic_metrics;
use crate::verify::verify_postgres;

/// Reject configurations that cannot produce the advertised coverage.
fn validate_args(args: &TrafficArgs) -> Result<()> {
    if args.rate_min <= 0.0 || args.rate_max < args.rate_min {
        bail!(
            "invalid rate range: {}..{} (need 0 < min <= max)",
            args.rate_min,
            args.rate_max
        );
    }
    if args.pool_size == 0 || args.concurrency == 0 || args.probers == 0 {
        // Zero workers or probers would produce vacuously green epochs —
        // worse than a crash for a verification bed — and an empty pool
        // panics at person selection.
        bail!(
            "pool_size ({}), concurrency ({}), and probers ({}) must all be nonzero",
            args.pool_size,
            args.concurrency,
            args.probers
        );
    }
    seed::validate_table_name(&args.pg_target_table)
}

pub async fn run(args: TrafficArgs) -> Result<()> {
    validate_args(&args)?;

    traffic_metrics::spawn_server(args.metrics_port)?;
    gauge!("personhog_traffic_enabled").set(if args.enabled { 1.0 } else { 0.0 });
    if !args.enabled {
        // Deployed but switched off: stay alive and observable so the
        // absence alarm keeps meaning "dead", never "disabled".
        tracing::info!("traffic disabled by TRAFFIC_ENABLED=false; idling");
        shutdown_signal().await;
        return Ok(());
    }
    let client = HarnessClient::connect(&args.router_url).await?;
    let pool = PgPool::connect(&args.persons_db_url)
        .await
        .context("connecting to persons DB")?;

    // Refuse to send traffic anywhere the router provably doesn't serve
    // this database. On failure the process exits and the Deployment's
    // restart loop retries — which also rides out startup races where the
    // leader hasn't claimed partitions yet.
    sentinel_round_trip(&client, &pool, &args.pg_target_table, args.team_id).await?;

    // A crashed prior run leaves rows behind (including the sentinel row
    // just written); both teams belong to the harness, so boot from a
    // clean slate.
    for team in [args.team_id, args.hostile_team_id] {
        seed::cleanup_team(&pool, &args.pg_target_table, team).await?;
    }

    // Hostile targets live for the process lifetime: their documents stay
    // small (fixed keys, no journal growth) and their outcomes are only
    // observed, never verified.
    let hostile_ids = if args.hostile_rate > 0.0 {
        Arc::new(seed::seed_persons(&pool, &args.pg_target_table, args.hostile_team_id, 4).await?)
    } else {
        Arc::new(Vec::new())
    };

    // A signal task flips the flag; the load tasks observe it and end
    // early, and the epoch close-out below still verifies and cleans up
    // whatever was acked before the process exits.
    let shutdown = Arc::new(AtomicBool::new(false));
    {
        let shutdown = shutdown.clone();
        tokio::spawn(async move {
            shutdown_signal().await;
            tracing::info!(
                "shutdown signal received; cutting the epoch short to verify and clean up"
            );
            shutdown.store(true, Ordering::SeqCst);
        });
    }

    let mut rng = rand::rngs::StdRng::from_entropy();
    let mut epoch: u64 = 0;
    loop {
        epoch += 1;
        let rate = rng.gen_range(args.rate_min..=args.rate_max);
        counter!("personhog_traffic_epochs_total").increment(1);
        gauge!("personhog_traffic_epoch_target_rps").set(rate);
        tracing::info!(epoch, rate = format!("{rate:.0}"), "epoch starting");

        let person_ids = Arc::new(
            seed::seed_persons(&pool, &args.pg_target_table, args.team_id, args.pool_size).await?,
        );
        let collector = Arc::new(StatsCollector::new());
        let state = PersonState::new();

        let traffic = {
            let client = client.clone();
            let person_ids = person_ids.clone();
            let collector = collector.clone();
            let state = state.clone();
            let (team_id, duration, concurrency) = (args.team_id, args.epoch, args.concurrency);
            let prefix = format!("traffic_e{epoch}_");
            let stop = shutdown.clone();
            tokio::spawn(async move {
                blast::run_traffic(
                    &client,
                    team_id,
                    person_ids,
                    duration,
                    concurrency,
                    Some(rate),
                    &prefix,
                    &collector,
                    &state,
                    stop,
                )
                .await
            })
        };
        let probers = {
            let client = client.clone();
            let person_ids = person_ids.clone();
            let collector = collector.clone();
            let state = state.clone();
            let (team_id, duration, prober_count) = (args.team_id, args.epoch, args.probers);
            let stop = shutdown.clone();
            tokio::spawn(async move {
                consistency::run_probers(
                    &client,
                    team_id,
                    person_ids,
                    prober_count,
                    duration,
                    &collector,
                    &state,
                    stop,
                )
                .await
            })
        };
        let hostile = {
            let client = client.clone();
            let hostile_ids = hostile_ids.clone();
            let (team_id, duration, rate) = (args.hostile_team_id, args.epoch, args.hostile_rate);
            let stop = shutdown.clone();
            tokio::spawn(async move {
                run_hostile(&client, team_id, hostile_ids, duration, rate, stop).await
            })
        };

        traffic.await.context("traffic task panicked")??;
        let prober_violations = probers.await.context("prober task panicked")??;
        hostile.await.context("hostile task panicked")?;

        // Close the epoch: everything acked in it must now be visible.
        let mut violations = prober_violations;
        violations.extend(state.take_anomalies().await);
        violations.extend(blast::verify_strong(&client, &collector, &state, args.team_id).await?);
        let journal = state.snapshot().await;
        violations
            .extend(verify_postgres(&pool, &args.pg_target_table, args.team_id, &journal).await?);
        traffic_metrics::record_violations(epoch, &violations);

        let writes = collector.writes.snapshot();
        gauge!("personhog_traffic_last_epoch_completed_timestamp_seconds").set(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64(),
        );
        tracing::info!(
            epoch,
            writes = writes.successes,
            failed = writes.failures,
            violations = violations.len(),
            "epoch closed"
        );

        // Rotate the pool: delete this epoch's persons so the next epoch
        // starts from fresh documents.
        seed::cleanup_team(&pool, &args.pg_target_table, args.team_id).await?;

        if shutdown.load(Ordering::SeqCst) {
            tracing::info!("cleaning up and exiting");
            for team in [args.team_id, args.hostile_team_id] {
                seed::cleanup_team(&pool, &args.pg_target_table, team).await?;
            }
            return Ok(());
        }
    }
}

/// The hostile lane: paced writes carrying payloads a correct stack must
/// handle without corruption — NUL bytes (jsonb-hostile) and oversized
/// values (admission/trim pressure). Outcomes are counted, not verified:
/// what a given stack version does with them legitimately changes as
/// admission hardening lands, so dashboards judge, the harness observes.
async fn run_hostile(
    client: &HarnessClient,
    team_id: i64,
    person_ids: Arc<Vec<i64>>,
    duration: Duration,
    rate_per_sec: f64,
    stop: Arc<AtomicBool>,
) {
    if person_ids.is_empty() || rate_per_sec <= 0.0 {
        return;
    }
    let deadline = Instant::now() + duration;
    let mut ticker = interval(Duration::from_secs_f64(1.0 / rate_per_sec));
    ticker.set_missed_tick_behavior(MissedTickBehavior::Delay);
    let mut rng = rand::rngs::StdRng::from_entropy();
    let mut counter: u64 = 0;

    while Instant::now() < deadline && !stop.load(Ordering::Relaxed) {
        ticker.tick().await;
        counter += 1;
        let person_id = person_ids[rng.gen_range(0..person_ids.len())];
        let (payload_kind, props) = hostile_payload(counter);

        let outcome = match client
            .update_properties(team_id, person_id, props, json!({}), vec![])
            .await
        {
            Ok(_) => "acked",
            Err(e) => {
                let rendered = format!("{e:#}");
                if rendered.contains("size limit") || rendered.contains("InvalidArgument") {
                    "rejected"
                } else {
                    "error"
                }
            }
        };
        counter!(
            "personhog_traffic_hostile_total",
            "payload" => payload_kind,
            "outcome" => outcome
        )
        .increment(1);
    }
}

/// Rotates through the hostile payload shapes. The `unset` cycle keeps the
/// hostile documents from growing without bound across epochs.
fn hostile_payload(counter: u64) -> (&'static str, Value) {
    match counter % 4 {
        0 => (
            "nul",
            json!({ "hostile_nul": format!("x\u{0000}y_{counter}") }),
        ),
        1 => (
            "oversized_trimmable",
            json!({ "hostile_blob": "x".repeat(700_000) }),
        ),
        2 => (
            "oversized_protected",
            json!({ "email": "x".repeat(700_000) }),
        ),
        _ => ("reset", json!({ "hostile_nul": "clean" })),
    }
}

/// Prove the router serves the same database this harness seeds and
/// verifies before any traffic flows: insert one person whose properties
/// carry a freshly minted UUID, strong-read it back through the router,
/// and require an exact match. The router path terminates in the leader's
/// PG fallback, so a router pointed at any other environment cannot
/// return a value that was generated here moments ago. The row is
/// removed by the boot cleanup that follows.
async fn sentinel_round_trip(
    client: &HarnessClient,
    pool: &PgPool,
    table: &str,
    team_id: i64,
) -> Result<()> {
    let marker = Uuid::new_v4().to_string();
    let team: i32 = team_id.try_into().context("team_id out of i32 range")?;
    let person_id: i64 = sqlx::query_scalar(&format!(
        r#"
        INSERT INTO {table} (
            team_id, uuid, properties, properties_last_updated_at,
            properties_last_operation, created_at, version, is_identified
        )
        VALUES ($1, gen_random_uuid(), $2::jsonb, '{{}}'::jsonb, '{{}}'::jsonb, now(), 0, false)
        RETURNING id
        "#
    ))
    .bind(team)
    .bind(json!({ "traffic_sentinel": &marker }).to_string())
    .fetch_one(pool)
    .await
    .context("seeding the sentinel person")?;

    let person = client
        .get_person(team_id, person_id, ConsistencyLevel::Strong)
        .await
        .context("sentinel strong read through the router failed")?
        .with_context(|| {
            format!(
                "sentinel person (team {team_id}, id {person_id}) not found through the \
                 router — the router does not serve the database this harness targets"
            )
        })?;
    let props: Value = serde_json::from_slice(&person.properties).unwrap_or(Value::Null);
    if props["traffic_sentinel"] != json!(marker) {
        bail!(
            "sentinel mismatch: the router returned a person without the freshly minted \
             marker (team {team_id}, id {person_id}) — the router does not serve the \
             database this harness targets"
        );
    }
    tracing::info!("sentinel round-trip verified: router and database agree");
    Ok(())
}

/// Resolves when SIGTERM (Kubernetes) or ctrl-c arrives.
async fn shutdown_signal() {
    let ctrl_c = tokio::signal::ctrl_c();
    #[cfg(unix)]
    {
        let mut sigterm = signal(SignalKind::terminate()).expect("installing SIGTERM handler");
        tokio::select! {
            _ = ctrl_c => {}
            _ = sigterm.recv() => {}
        }
    }
    #[cfg(not(unix))]
    {
        let _ = ctrl_c.await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vacuous_or_panicking_configurations_are_rejected() {
        let valid = TrafficArgs {
            router_url: "http://localhost:1".to_string(),
            enabled: true,
            team_id: 900_101,
            hostile_team_id: 900_102,
            persons_db_url: "postgres://unused".to_string(),
            pg_target_table: "personhog_person_tmp".to_string(),
            pool_size: 200,
            epoch: Duration::from_secs(300),
            rate_min: 50.0,
            rate_max: 500.0,
            concurrency: 20,
            probers: 2,
            hostile_rate: 1.0,
            metrics_port: 9110,
        };
        assert!(validate_args(&valid).is_ok());
        // A disabled hostile lane is legal; zero traffic knobs are not.
        assert!(validate_args(&TrafficArgs {
            hostile_rate: 0.0,
            ..valid.clone()
        })
        .is_ok());
        for broken in [
            TrafficArgs {
                pool_size: 0,
                ..valid.clone()
            },
            TrafficArgs {
                concurrency: 0,
                ..valid.clone()
            },
            TrafficArgs {
                probers: 0,
                ..valid.clone()
            },
            TrafficArgs {
                rate_min: 0.0,
                ..valid.clone()
            },
            TrafficArgs {
                rate_max: 1.0,
                ..valid.clone()
            },
            TrafficArgs {
                pg_target_table: "bad; table".to_string(),
                ..valid.clone()
            },
        ] {
            assert!(validate_args(&broken).is_err());
        }
    }

    #[test]
    fn hostile_payloads_cycle_through_every_shape_and_reset() {
        let kinds: Vec<&str> = (0..8).map(|i| hostile_payload(i).0).collect();
        assert_eq!(
            kinds,
            [
                "nul",
                "oversized_trimmable",
                "oversized_protected",
                "reset",
                "nul",
                "oversized_trimmable",
                "oversized_protected",
                "reset"
            ]
        );
        // The NUL payload really carries a NUL, and the reset payload
        // replaces the same key so hostile documents stay bounded.
        let (_, nul) = hostile_payload(0);
        assert!(nul["hostile_nul"].as_str().unwrap().contains('\u{0000}'));
        let (_, reset) = hostile_payload(3);
        assert!(reset.get("hostile_nul").is_some());
    }
}
