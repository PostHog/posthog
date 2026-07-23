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

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use rand::{Rng, SeedableRng};
use sqlx::postgres::PgPool;

use crate::cli::TrafficArgs;
use crate::client::HarnessClient;
use crate::scenarios::{blast, consistency};
use crate::seed;
use crate::state::PersonState;
use crate::stats::StatsCollector;
use crate::traffic_metrics;
use crate::verify::verify_postgres;

/// The environment marker that must be present (and equal to "dev") for
/// the traffic mode to start. The mode seeds and deletes persons on its
/// team ids, so it must be structurally unable to run against prod.
pub const ENV_GUARD_VAR: &str = "PERSONHOG_TRAFFIC_ENV";

pub async fn run(args: TrafficArgs) -> Result<()> {
    check_env_guard(std::env::var(ENV_GUARD_VAR).ok().as_deref())?;
    if args.rate_min <= 0.0 || args.rate_max < args.rate_min {
        bail!(
            "invalid rate range: {}..{} (need 0 < min <= max)",
            args.rate_min,
            args.rate_max
        );
    }
    seed::validate_table_name(&args.pg_target_table)?;

    traffic_metrics::spawn_server(args.metrics_port)?;
    metrics::gauge!("personhog_traffic_enabled").set(if args.enabled { 1.0 } else { 0.0 });
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

    // A crashed prior run leaves rows behind; both teams belong to the
    // harness, so boot from a clean slate.
    for team in [args.team_id, args.hostile_team_id] {
        seed::cleanup_team(&pool, team).await?;
        if args.pg_target_table != "posthog_person" {
            seed::cleanup_target_table(&pool, &args.pg_target_table, team).await?;
        }
    }

    // Hostile targets live for the process lifetime: their documents stay
    // small (fixed keys, no journal growth) and their outcomes are only
    // observed, never verified.
    let hostile_ids = if args.hostile_rate > 0.0 {
        Arc::new(seed::seed_persons(&pool, args.hostile_team_id, 4).await?)
    } else {
        Arc::new(Vec::new())
    };

    // A signal task flips the flag; the epoch loop exits at the next epoch
    // boundary so the final epoch is still verified and cleaned up.
    let shutdown = Arc::new(AtomicBool::new(false));
    {
        let shutdown = shutdown.clone();
        tokio::spawn(async move {
            shutdown_signal().await;
            tracing::info!("shutdown signal received; finishing the current epoch");
            shutdown.store(true, Ordering::SeqCst);
        });
    }

    let mut rng = rand::rngs::StdRng::from_entropy();
    let mut epoch: u64 = 0;
    loop {
        epoch += 1;
        let rate = rng.gen_range(args.rate_min..=args.rate_max);
        metrics::counter!("personhog_traffic_epochs_total").increment(1);
        metrics::gauge!("personhog_traffic_epoch_target_rps").set(rate);
        tracing::info!(epoch, rate = format!("{rate:.0}"), "epoch starting");

        let person_ids = Arc::new(seed::seed_persons(&pool, args.team_id, args.pool_size).await?);
        let collector = Arc::new(StatsCollector::new());
        let state = PersonState::new();

        let traffic = {
            let client = client.clone();
            let person_ids = person_ids.clone();
            let collector = collector.clone();
            let state = state.clone();
            let (team_id, duration, concurrency) = (args.team_id, args.epoch, args.concurrency);
            let prefix = format!("traffic_e{epoch}_");
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
        let hostile = {
            let client = client.clone();
            let hostile_ids = hostile_ids.clone();
            let (team_id, duration, rate) = (args.hostile_team_id, args.epoch, args.hostile_rate);
            tokio::spawn(
                async move { run_hostile(&client, team_id, hostile_ids, duration, rate).await },
            )
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
        metrics::gauge!("personhog_traffic_last_epoch_completed_timestamp_seconds").set(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
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

        // Rotate the pool. Rows for this epoch's persons are deleted from
        // both the seed table and the writer's target table.
        seed::cleanup_team(&pool, args.team_id).await?;
        if args.pg_target_table != "posthog_person" {
            seed::cleanup_target_table(&pool, &args.pg_target_table, args.team_id).await?;
        }

        if shutdown.load(Ordering::SeqCst) {
            tracing::info!("cleaning up and exiting");
            for team in [args.team_id, args.hostile_team_id] {
                seed::cleanup_team(&pool, team).await?;
                if args.pg_target_table != "posthog_person" {
                    seed::cleanup_target_table(&pool, &args.pg_target_table, team).await?;
                }
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
) {
    if person_ids.is_empty() || rate_per_sec <= 0.0 {
        return;
    }
    let deadline = Instant::now() + duration;
    let mut interval = tokio::time::interval(Duration::from_secs_f64(1.0 / rate_per_sec));
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    let mut rng = rand::rngs::StdRng::from_entropy();
    let mut counter: u64 = 0;

    while Instant::now() < deadline {
        interval.tick().await;
        counter += 1;
        let person_id = person_ids[rng.gen_range(0..person_ids.len())];
        let (payload_kind, props) = hostile_payload(counter);

        let outcome = match client
            .update_properties(team_id, person_id, props, serde_json::json!({}), vec![])
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
        metrics::counter!(
            "personhog_traffic_hostile_total",
            "payload" => payload_kind,
            "outcome" => outcome
        )
        .increment(1);
    }
}

/// Rotates through the hostile payload shapes. The `unset` cycle keeps the
/// hostile documents from growing without bound across epochs.
fn hostile_payload(counter: u64) -> (&'static str, serde_json::Value) {
    match counter % 4 {
        0 => (
            "nul",
            serde_json::json!({ "hostile_nul": format!("x\u{0000}y_{counter}") }),
        ),
        1 => (
            "oversized_trimmable",
            serde_json::json!({ "hostile_blob": "x".repeat(700_000) }),
        ),
        2 => (
            "oversized_protected",
            serde_json::json!({ "email": "x".repeat(700_000) }),
        ),
        _ => ("reset", serde_json::json!({ "hostile_nul": "clean" })),
    }
}

fn check_env_guard(value: Option<&str>) -> Result<()> {
    match value {
        Some("dev") => Ok(()),
        Some(other) => bail!(
            "{ENV_GUARD_VAR}={other:?} — the traffic mode only runs where {ENV_GUARD_VAR}=dev; \
             it seeds and deletes person rows and must never target prod"
        ),
        None => bail!(
            "{ENV_GUARD_VAR} is not set — the traffic mode only runs where {ENV_GUARD_VAR}=dev; \
             it seeds and deletes person rows and must never target prod"
        ),
    }
}

/// Resolves when SIGTERM (Kubernetes) or ctrl-c arrives.
async fn shutdown_signal() {
    let ctrl_c = tokio::signal::ctrl_c();
    #[cfg(unix)]
    {
        let mut sigterm = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("installing SIGTERM handler");
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
    fn env_guard_only_accepts_dev() {
        assert!(check_env_guard(Some("dev")).is_ok());
        assert!(check_env_guard(Some("prod-us")).is_err());
        assert!(check_env_guard(Some("")).is_err());
        assert!(check_env_guard(None).is_err());
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
