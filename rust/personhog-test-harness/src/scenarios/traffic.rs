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
use metrics::{counter, gauge, histogram};
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
use crate::client::{IdentityClient, LifecycleClient};
use crate::scenarios::chaos::{self, ChaosConfig, TargetKind, TargetSpec};
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

/// How old a leftover row must be before the startup janitor reaps it.
/// Far above any epoch length, so a live sibling pod's pool is never
/// touched; far below forever, so crashed instances' rows don't
/// accumulate.
const STALE_ROW_AGE: Duration = Duration::from_secs(3600);

pub async fn run(args: TrafficArgs) -> Result<()> {
    validate_args(&args)?;

    // Multi-instance beds stride their team pair by ordinal, so N
    // replicas own N disjoint team spaces with one configuration.
    let ordinal = resolve_ordinal(args.instance_ordinal, std::env::var("POD_NAME").ok());
    let team_id = args.team_id + args.team_stride * ordinal;
    let hostile_team_id = args.hostile_team_id + args.team_stride * ordinal;

    traffic_metrics::spawn_server(args.metrics_port)?;
    gauge!("personhog_traffic_instance_ordinal").set(ordinal as f64);
    tracing::info!(ordinal, team_id, hostile_team_id, "instance identity");
    gauge!("personhog_traffic_enabled").set(if args.enabled { 1.0 } else { 0.0 });
    if !args.enabled {
        // Deployed but switched off: stay alive and observable so the
        // absence alarm keeps meaning "dead", never "disabled".
        tracing::info!("traffic disabled by TRAFFIC_ENABLED=false; idling");
        shutdown_signal().await;
        return Ok(());
    }
    let client = HarnessClient::connect(&args.router_url).await?;
    let identity = IdentityClient::connect(&args.identity_url).await?;
    let lifecycle = LifecycleClient::connect(&args.identity_url).await?;
    let pool = PgPool::connect(&args.persons_db_url)
        .await
        .context("connecting to persons DB")?;

    // Refuse to send traffic anywhere the router provably doesn't serve
    // this database. On failure the process exits and the Deployment's
    // restart loop retries — which also rides out startup races where the
    // leader hasn't claimed partitions yet.
    sentinel_round_trip(&client, &pool, &args.pg_target_table, team_id).await?;

    // A crashed prior run leaves rows behind; reap the ones old enough
    // that they cannot belong to a live sibling — a rolling restart
    // briefly runs two bed pods against the same team, each on its own
    // disjoint id pool, and a fresh row is the sibling's business.
    for team in [team_id, hostile_team_id] {
        seed::reap_stale_team_rows(&pool, &args.pg_target_table, team, STALE_ROW_AGE).await?;
    }

    // Hostile targets live for the process lifetime: their documents stay
    // small (fixed keys, no journal growth) and their outcomes are only
    // observed, never verified.
    let hostile_ids = if args.hostile_rate > 0.0 {
        // Boot-unique ids: a restart must insert fresh hostile rows, not
        // revive the previous boot's tombstones.
        let boot = std::process::id();
        let distinct_ids: Vec<String> = (0..4).map(|i| format!("bed-hostile-{boot}-{i}")).collect();
        Arc::new(seed::seed_persons_via_identity(&identity, hostile_team_id, &distinct_ids).await?)
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

    // Chaos is a singleton: N instances compounding kill cadences would
    // roll the stack permanently, so only ordinal 0 runs it.
    let chaos_here = args.chaos_enabled && ordinal == 0;
    if args.chaos_enabled && !chaos_here {
        tracing::info!(ordinal, "chaos enabled but deferred to ordinal 0");
    }
    gauge!("personhog_traffic_chaos_enabled").set(if chaos_here { 1.0 } else { 0.0 });
    if chaos_here {
        // Chaos runs for the process lifetime, independent of epochs:
        // the bed is expected to stay correct while pods die under load.
        let cfg = chaos_config(&args);
        let shutdown = shutdown.clone();
        tokio::spawn(async move {
            chaos::run(cfg, shutdown).await;
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

        // The hostile pool outlives epochs; keep its liveness stamp fresh
        // so a sibling pod's startup janitor never reaps it mid-use.
        seed::refresh_created_at(&pool, &args.pg_target_table, hostile_team_id, &hostile_ids)
            .await?;

        // The per-epoch janitor: crashed-run leftovers and the
        // tombstones lifecycle rotation leaves behind both age into
        // eligibility; without this the table grows one pool per epoch
        // for the life of the deployment.
        for team in [team_id, hostile_team_id] {
            seed::reap_stale_team_rows(&pool, &args.pg_target_table, team, STALE_ROW_AGE).await?;
        }

        // Fresh ids every epoch: each create inserts a new row rather
        // than reviving the previous epoch's tombstone.
        let distinct_ids: Vec<String> = (0..args.pool_size)
            .map(|i| format!("bed-e{epoch}-p{i}"))
            .collect();
        let person_ids =
            Arc::new(seed::seed_persons_via_identity(&identity, team_id, &distinct_ids).await?);
        let collector = Arc::new(StatsCollector::new());
        let state = PersonState::new();

        let traffic = {
            let client = client.clone();
            let person_ids = person_ids.clone();
            let collector = collector.clone();
            let state = state.clone();
            let (team_id, duration, concurrency) = (team_id, args.epoch, args.concurrency);
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
            let (team_id, duration, prober_count) = (team_id, args.epoch, args.probers);
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
            let (team_id, duration, rate) = (hostile_team_id, args.epoch, args.hostile_rate);
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
        violations.extend(blast::verify_strong(&client, &collector, &state, team_id).await?);
        let journal = state.snapshot().await;
        violations.extend(verify_postgres(&pool, &args.pg_target_table, team_id, &journal).await?);
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

        // Rotate the pool through the lifecycle delete saga: the same
        // path production deletes take, exercised every epoch under
        // whatever chaos is running. By id, not by team — a successor
        // pod may already be running its own pool against this team.
        delete_pool(&lifecycle, team_id, &person_ids).await?;

        if shutdown.load(Ordering::SeqCst) {
            tracing::info!("cleaning up and exiting");
            delete_pool(&lifecycle, hostile_team_id, &hostile_ids).await?;
            return Ok(());
        }
    }
}

/// The hostile lane: paced writes carrying payloads a correct stack must
/// handle without corruption — NUL bytes (jsonb-hostile) and oversized
/// values (admission/trim pressure). Outcomes are counted, not verified:
/// what a given stack version does with them legitimately changes as
/// admission hardening lands, so dashboards judge, the harness observes.
/// The three target classes, selected by the label convention the
/// personhog charts follow: `app.kubernetes.io/name` equals the release
/// (and namespace) name, and `component=app` excludes the pgbouncer
/// sidecars sharing the namespace.
/// Explicit ordinal wins; otherwise the trailing integer of a
/// StatefulSet pod name; otherwise 0 (single instance, or a Deployment
/// whose hash suffix is not an ordinal).
fn resolve_ordinal(explicit: Option<i64>, pod_name: Option<String>) -> i64 {
    if let Some(ordinal) = explicit {
        return ordinal;
    }
    pod_name
        .as_deref()
        .and_then(|name| name.rsplit('-').next())
        .and_then(|suffix| suffix.parse::<i64>().ok())
        .unwrap_or(0)
}

/// Delete the epoch's pool through the saga and account for every
/// outcome. `deleted` is the expected answer; `not_found` means someone
/// else already removed the row (a startup janitor's reap, never a
/// second bed — pools are id-disjoint) and is counted, not fatal;
/// `skipped_conflict` means a lifecycle operation is stuck holding a
/// pool person, which the bed exists to surface, so it fails the run.
async fn delete_pool(lifecycle: &LifecycleClient, team_id: i64, person_ids: &[i64]) -> Result<()> {
    use personhog_proto::personhog::lifecycle::v1::DeletePersonOutcome;

    // The lifecycle service caps batches at 250 person ids.
    for chunk in person_ids.chunks(200) {
        let op_id = uuid::Uuid::new_v4();
        let started = std::time::Instant::now();
        let outcomes = lifecycle
            .delete_persons(team_id, chunk.to_vec(), &op_id)
            .await?;
        histogram!("personhog_traffic_pool_delete_duration_ms")
            .record(started.elapsed().as_secs_f64() * 1000.0);
        for (person_id, outcome) in outcomes {
            let label = match outcome {
                DeletePersonOutcome::Deleted => "deleted",
                DeletePersonOutcome::NotFound => "not_found",
                DeletePersonOutcome::SkippedConflict => "skipped_conflict",
                DeletePersonOutcome::Unspecified => "unspecified",
            };
            counter!("personhog_traffic_pool_delete_total", "outcome" => label).increment(1);
            if matches!(
                outcome,
                DeletePersonOutcome::SkippedConflict | DeletePersonOutcome::Unspecified
            ) {
                anyhow::bail!(
                    "pool rotation delete returned {label} for person {person_id} on team {team_id}"
                );
            }
        }
    }
    Ok(())
}

fn chaos_config(args: &TrafficArgs) -> ChaosConfig {
    let target = |kind: TargetKind, namespace: &str| TargetSpec {
        kind,
        namespace: namespace.to_string(),
        selector: format!("app.kubernetes.io/name={namespace},app.kubernetes.io/component=app"),
    };
    ChaosConfig {
        interval_min: args.chaos_interval_min,
        interval_max: args.chaos_interval_max,
        targets: vec![
            target(TargetKind::Leader, &args.chaos_leader_namespace),
            target(TargetKind::Router, &args.chaos_router_namespace),
            target(TargetKind::Writer, &args.chaos_writer_namespace),
        ],
        etcd: args
            .chaos_etcd_endpoints
            .clone()
            .map(|endpoints| (endpoints, args.chaos_etcd_prefix.clone())),
        etcd_target: args.chaos_etcd_namespace.as_ref().map(|ns| TargetSpec {
            kind: TargetKind::Etcd,
            namespace: ns.clone(),
            selector: "app.kubernetes.io/name=etcd".to_string(),
        }),
    }
}

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
    sqlx::query(&format!(
        "DELETE FROM {table} WHERE team_id = $1 AND id = $2"
    ))
    .bind(team)
    .bind(person_id)
    .execute(pool)
    .await
    .context("deleting the sentinel person")?;
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
    fn ordinal_resolution_prefers_explicit_then_pod_name_then_zero() {
        // Explicit wins over everything.
        assert_eq!(resolve_ordinal(Some(7), Some("bed-3".to_string())), 7);
        // A StatefulSet pod name's trailing integer.
        assert_eq!(
            resolve_ordinal(None, Some("personhog-bed-3".to_string())),
            3
        );
        assert_eq!(resolve_ordinal(None, Some("bed-0".to_string())), 0);
        // A Deployment hash suffix is not an ordinal.
        assert_eq!(
            resolve_ordinal(
                None,
                Some("personhog-test-harness-65f9f84b5d-d5mkd".to_string())
            ),
            0
        );
        // No identity at all: single instance.
        assert_eq!(resolve_ordinal(None, None), 0);
    }

    #[test]
    fn vacuous_or_panicking_configurations_are_rejected() {
        let valid = TrafficArgs {
            chaos_etcd_namespace: None,
            router_url: "http://localhost:1".to_string(),
            identity_url: "http://localhost:2".to_string(),
            instance_ordinal: None,
            team_stride: 10,
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
            chaos_enabled: false,
            chaos_interval_min: Duration::from_secs(180),
            chaos_interval_max: Duration::from_secs(600),
            chaos_leader_namespace: "personhog-leader".to_string(),
            chaos_router_namespace: "personhog-router-leader".to_string(),
            chaos_writer_namespace: "personhog-writer".to_string(),
            chaos_etcd_endpoints: None,
            chaos_etcd_prefix: "/personhog/".to_string(),
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
