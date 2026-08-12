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
use assignment_coordination::store::{EtcdStore, StoreConfig};
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

    let team_id = args.team_id;
    let hostile_team_id = args.hostile_team_id;
    // Instances share the team pair; disjointness comes from the boot
    // nonce in every distinct id, so verification (id-scoped) and the
    // janitor (age-guarded) never cross instances.
    let nonce = format!("{:08x}", rand::random::<u32>());
    tracing::info!(%nonce, team_id, hostile_team_id, "instance identity");

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
        // Nonce'd ids: a restart must insert fresh hostile rows, not
        // revive the previous boot's tombstones, and a sibling instance
        // must never resolve onto this one's rows.
        let distinct_ids: Vec<String> =
            (0..4).map(|i| format!("bed-hostile-{nonce}-{i}")).collect();
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
    // roll the stack permanently, so a Postgres advisory lock elects
    // exactly one killer and the rest stay candidates.
    gauge!("personhog_traffic_chaos_enabled").set(0.0);
    if args.chaos_enabled {
        let args = args.clone();
        let shutdown = shutdown.clone();
        tokio::spawn(async move {
            chaos_singleton(&args, shutdown).await;
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

        // Fresh ids every epoch, nonce'd per instance: each create
        // inserts a new row rather than reviving a tombstone, and
        // sibling instances on the shared team never resolve onto each
        // other's rows.
        let distinct_ids: Vec<String> = (0..args.pool_size)
            .map(|i| format!("bed-{nonce}-e{epoch}-p{i}"))
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
/// The lease TTL bounding both sides of the chaos election: a dead
/// holder's claim expires within this window, and a live holder demotes
/// on its first unconfirmed keepalive, well inside it.
const CHAOS_LEASE_TTL: Duration = Duration::from_secs(30);
const CHAOS_KEEPALIVE_TICK: Duration = Duration::from_secs(10);
const CHAOS_KEEPALIVE_TIMEOUT: Duration = Duration::from_secs(5);
// The demotion bound. Anchor at S, the send instant of the last
// confirmed keepalive: etcd expires the key no earlier than S + TTL,
// while the holder's next round starts within timeout + tick of S and
// concludes (send and read each bounded by the timeout) within another
// 2 * timeout. So the holder is demoted before the key can expire and
// admit a successor, and two concurrent chaos runners are impossible.
const _: () = assert!(
    CHAOS_KEEPALIVE_TICK.as_secs() + 3 * CHAOS_KEEPALIVE_TIMEOUT.as_secs()
        < CHAOS_LEASE_TTL.as_secs()
);

/// Lease-backed chaos election on the coordination etcd. The winner
/// claims `{prefix}chaos_leader` under a lease it keeps alive; losers
/// retry on a slow cadence. Without etcd endpoints there is nothing to
/// elect against, so a single instance is assumed and chaos runs
/// directly.
async fn chaos_singleton(args: &TrafficArgs, shutdown: Arc<AtomicBool>) {
    const RETRY: Duration = Duration::from_secs(30);

    let Some(endpoints) = args.chaos_etcd_endpoints.clone() else {
        tracing::warn!("chaos enabled without etcd endpoints; running unelected");
        gauge!("personhog_traffic_chaos_enabled").set(1.0);
        chaos::run(chaos_config(args), shutdown).await;
        return;
    };

    while !shutdown.load(Ordering::SeqCst) {
        if let Err(error) = campaign(args, &endpoints, &shutdown).await {
            tracing::warn!(%error, "chaos election attempt failed; retrying");
        }
        tokio::time::sleep(RETRY).await;
    }
}

/// One election attempt: claim the leader key, and while the claim
/// holds, run chaos. Returns after losing the campaign, demoting, or
/// shutdown; the caller paces the next attempt.
async fn campaign(args: &TrafficArgs, endpoints: &str, shutdown: &Arc<AtomicBool>) -> Result<()> {
    let store = EtcdStore::connect(StoreConfig {
        endpoints: endpoints.split(',').map(String::from).collect(),
        prefix: args.chaos_etcd_prefix.clone(),
    })
    .await
    .context("connecting to etcd for the chaos election")?;
    let key = format!("{}chaos_leader", store.prefix());

    let lease_id = store.grant_lease(CHAOS_LEASE_TTL.as_secs() as i64).await?;
    if !store
        .put_if_absent(&key, b"held".to_vec(), lease_id)
        .await?
    {
        store.revoke_lease(lease_id).await.ok();
        return Ok(());
    }

    gauge!("personhog_traffic_chaos_enabled").set(1.0);
    tracing::info!("chaos leadership claimed; this instance runs chaos");
    let result = hold_and_run(args, &store, lease_id, shutdown).await;
    gauge!("personhog_traffic_chaos_enabled").set(0.0);
    // Free the key immediately on a clean exit so a successor need not
    // wait out the TTL. Best-effort: expiry covers an unreachable etcd.
    store.revoke_lease(lease_id).await.ok();
    result
}

/// Runs chaos while keepalives confirm the lease, demoting on the
/// first doubt: a send or read failure, a timeout, or a keepalive
/// answered with TTL 0 (etcd already expired the lease). Doubt is
/// cheap because the failure direction is one-sided — the key outlives
/// the hold until revoke or expiry, so a spurious demotion costs a
/// short chaos gap, never a second runner. Chaos's own etcd bounce
/// lands here too: the holder demotes and re-campaigns once the
/// cluster settles.
async fn hold_and_run(
    args: &TrafficArgs,
    store: &EtcdStore,
    lease_id: i64,
    shutdown: &Arc<AtomicBool>,
) -> Result<()> {
    let chaos = chaos::run(chaos_config(args), shutdown.clone());
    tokio::pin!(chaos);
    let (mut keeper, mut stream) = store.keep_alive(lease_id).await?;
    let mut tick = tokio::time::interval(CHAOS_KEEPALIVE_TICK);
    tick.set_missed_tick_behavior(MissedTickBehavior::Skip);
    loop {
        tokio::select! {
            _ = &mut chaos => return Ok(()),
            _ = tick.tick() => {
                let confirmed = async {
                    tokio::time::timeout(CHAOS_KEEPALIVE_TIMEOUT, keeper.keep_alive())
                        .await
                        .ok()?
                        .ok()?;
                    let resp = tokio::time::timeout(CHAOS_KEEPALIVE_TIMEOUT, stream.message())
                        .await
                        .ok()?
                        .ok()??;
                    (resp.ttl() > 0).then_some(())
                }
                .await;
                if confirmed.is_none() {
                    tracing::warn!("chaos lease unconfirmed; demoting");
                    return Ok(());
                }
            }
        }
    }
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

    /// Needs the CI gate's etcd; run explicitly with `--ignored`.
    #[tokio::test]
    #[ignore = "needs a local etcd"]
    async fn chaos_claim_is_exclusive_and_freed_by_lease_revoke() {
        let endpoints =
            std::env::var("ETCD_ENDPOINTS").unwrap_or_else(|_| "http://localhost:2379".to_string());
        let store = EtcdStore::connect(StoreConfig {
            endpoints: endpoints.split(',').map(String::from).collect(),
            prefix: "/personhog-harness-test/".to_string(),
        })
        .await
        .unwrap();
        // A per-run key: a crashed prior run's claim lives only as long
        // as its lease, but a fresh key avoids waiting that out.
        let key = format!("{}chaos_leader_{}", store.prefix(), Uuid::new_v4());

        let holder = store.grant_lease(30).await.unwrap();
        let contender = store.grant_lease(30).await.unwrap();
        assert!(store
            .put_if_absent(&key, b"a".to_vec(), holder)
            .await
            .unwrap());
        assert!(!store
            .put_if_absent(&key, b"b".to_vec(), contender)
            .await
            .unwrap());

        // Revoking the holder's lease deletes the key with it, freeing
        // the claim immediately.
        store.revoke_lease(holder).await.unwrap();
        assert!(store
            .put_if_absent(&key, b"b".to_vec(), contender)
            .await
            .unwrap());
        store.revoke_lease(contender).await.unwrap();
    }

    #[test]
    fn vacuous_or_panicking_configurations_are_rejected() {
        let valid = TrafficArgs {
            chaos_etcd_namespace: None,
            router_url: "http://localhost:1".to_string(),
            identity_url: "http://localhost:2".to_string(),
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
