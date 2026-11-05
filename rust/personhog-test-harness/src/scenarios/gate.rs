use std::collections::{HashMap, HashSet};
use std::fmt;
use std::path::{Path, PathBuf};
use std::sync::atomic::AtomicBool;
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use sqlx::postgres::PgPool;

use personhog_coordination::types::MigrationPhase;
use personhog_proto::personhog::identity::v1::GetOrCreatePersonEntry;

use crate::cli::{GateArgs, DEFAULT_KEYS_PER_PERSON};
use crate::client::{HarnessClient, IdentityClient};
use crate::pool::TargetPool;
use crate::publish;
use crate::report::{print_report, ConsistencyViolation};
use crate::scenarios::merge::{self, MergeLane, WideRole};
use crate::scenarios::{blast, consistency};
use crate::seed;
use crate::stack::{MigrationChaos, PublishConfig, Stack, StackConfig, StallAt};
use crate::state::PersonState;
use crate::stats::StatsCollector;
use crate::verify::verify_postgres;

/// The property set on every person the identity service creates. The
/// merge lane expects it on every survivor.
pub const SEED_KEY: &str = "harness_seed";

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
    FencePersons,
    ReleaseFences,
    PublisherCrash,
    IdentityCrash,
    Migrate,
    MigrateAgain,
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
            ChaosEvent::FencePersons => write!(f, "fence persons (lifecycle delete op)"),
            ChaosEvent::ReleaseFences => write!(f, "release fences (aborted)"),
            ChaosEvent::RouterShutdown => write!(f, "coordinator router graceful shutdown"),
            ChaosEvent::PublisherCrash => write!(f, "publisher crash-restart"),
            ChaosEvent::IdentityCrash => write!(f, "identity crash-restart"),
            ChaosEvent::Migrate => write!(f, "changelog migration"),
            ChaosEvent::MigrateAgain => write!(f, "second changelog migration"),
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
    if let Some(after) = args.migrate_after {
        events.push((after, ChaosEvent::Migrate));
    }
    if let Some(after) = args.migrate_again_after {
        events.push((after, ChaosEvent::MigrateAgain));
    }
    if let Some(after) = args.fence_after {
        events.push((after, ChaosEvent::FencePersons));
        events.push((
            args.fence_release_after
                .expect("validated: --fence-after requires --fence-release-after"),
            ChaosEvent::ReleaseFences,
        ));
    }
    if let Some(after) = args.publisher_crash_after {
        events.push((after, ChaosEvent::PublisherCrash));
    }
    if let Some(after) = args.identity_crash_after {
        events.push((after, ChaosEvent::IdentityCrash));
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
pub(crate) fn default_bin_dir() -> PathBuf {
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
    // Fence events act through the router client, so they are the one kind
    // of chaos an external stack can host.
    let needs_stack_chaos = chaos
        .iter()
        .any(|(_, event)| !matches!(event, ChaosEvent::FencePersons | ChaosEvent::ReleaseFences));
    if args.external_router_url.is_some() && (needs_stack_chaos || args.kill_handoff_target) {
        bail!("chaos flags require a spawned stack; they cannot target --external-router-url");
    }
    if args.external_router_url.is_some() && !args.leader_env.is_empty() {
        bail!("--leader-env requires a spawned stack; it cannot target --external-router-url");
    }
    // Merges need distinct ids. Only the identity create path provides
    // them.
    let create_via_identity =
        args.create_via_identity || args.merge_concurrency > 0 || args.publish;
    if create_via_identity
        && args.external_router_url.is_some()
        && args.external_identity_url.is_none()
    {
        bail!("--create-via-identity (or --merge-concurrency) with --external-router-url needs --external-identity-url");
    }
    if args.merge_concurrency > 0 && args.persons < 2 {
        bail!("--merge-concurrency needs at least 2 persons to pair");
    }
    if args.merge_rate.is_some_and(|rate| rate <= 0.0) {
        bail!("--merge-rate must be positive; omit it to run the merge workers flat out");
    }
    if args.merge_sources == 0 {
        bail!("--merge-sources must be at least 1");
    }
    if args.merge_wide_persons > 0 && args.merge_concurrency == 0 {
        bail!("--merge-wide-persons needs --merge-concurrency");
    }
    let wide_role = WideRole::parse(&args.merge_wide_role)
        .ok_or_else(|| anyhow::anyhow!("unknown --merge-wide-role {:?}", args.merge_wide_role))?;
    // The spawned identity derives its whole table set (person, distinct id,
    // hash-key overrides) from --pg-target-table, so any known table set
    // works; Stack::up rejects person tables without a known companion set.
    if (args.router_kill_after.is_some() || args.router_shutdown_after.is_some())
        && args.routers < 3
    {
        bail!(
            "coordinator chaos requires --routers >= 3: traffic targets the last router, \
             which never campaigns, so two routers leave no standby to win the failover \
             election"
        );
    }
    if args.kill_handoff_target && args.shutdown_after.is_none() && args.scale_up_after.is_none() {
        bail!("--kill-handoff-target needs a handoff-creating event (--shutdown-after or --scale-up-after)");
    }
    match (args.fence_after, args.fence_release_after) {
        (Some(fence), Some(release)) if release <= fence => {
            bail!("--fence-release-after must be after --fence-after");
        }
        (Some(_), None) | (None, Some(_)) => {
            bail!("--fence-after and --fence-release-after must be given together");
        }
        _ => {}
    }
    if args.fence_after.is_some() && args.fence_count == 0 {
        bail!("--fence-count must be at least 1 with --fence-after");
    }
    if args.migrate_after.is_some() && args.migrate_to_partitions.is_none_or(|n| n == 0) {
        bail!("--migrate-after needs --migrate-to-partitions >= 1");
    }
    if args.migrate_again_after.is_some() && args.migrate_again_to_partitions.is_none_or(|n| n == 0)
    {
        bail!("--migrate-again-after needs --migrate-again-to-partitions >= 1");
    }
    if args.migrate_kill_coordinator && args.routers < 3 {
        bail!("--migrate-kill-coordinator requires --routers >= 3");
    }
    if args.migrate_kill_leader && args.migrate_kill_leader_at_sealing {
        bail!("--migrate-kill-leader and --migrate-kill-leader-at-sealing are exclusive");
    }
    let mut router_env = args.router_env.clone();
    if let Some(ms) = args.migrate_slow_coordinator_ms {
        router_env.push(("COORDINATOR_MIGRATION_DEBOUNCE_MS".into(), ms.to_string()));
    }
    if args.migrate_stall_leader {
        router_env.push((
            "COORDINATOR_MIGRATION_PRE_FLIP_DEADLINE_SECS".into(),
            "5".into(),
        ));
    }
    if args.publish && args.external_router_url.is_some() {
        bail!("--publish requires a spawned stack; it cannot target --external-router-url");
    }
    if args.publish && args.publishers == 0 {
        bail!("--publishers must be at least 1 with --publish");
    }
    if args.publish && args.publish_rows_per_pass <= 0 {
        bail!("--publish-rows-per-pass must be positive");
    }
    if args.publisher_crash_after.is_some() && !args.publish {
        bail!("--publisher-crash-after needs --publish");
    }
    if args.identity_crash_after.is_some() && !create_via_identity {
        bail!(
            "--identity-crash-after needs the identity path (--create-via-identity, \
             --merge-concurrency or --publish)"
        );
    }

    let pool = PgPool::connect(&args.persons_db_url)
        .await
        .context("connecting to persons DB")?;
    let outbox_table = seed::publish_outbox_table_for(&args.pg_target_table);
    let (lifecycle_op, lifecycle_op_person) = seed::lifecycle_tables_for(&args.pg_target_table);

    // A crashed prior run may have left rows behind; the team id belongs to
    // the harness, so start from a clean slate before anything spawns.
    // Lifecycle ops included: a leftover mark would make this run's
    // takeover scan install a stale fence for this team. Outbox rows too:
    // the publishers would drain a previous run's rows onto this run's
    // topics.
    seed::cleanup_team(&pool, &args.pg_target_table, args.team_id).await?;
    sqlx::query(&format!("DELETE FROM {lifecycle_op} WHERE team_id = $1"))
        .bind(args.team_id as i32)
        .execute(&pool)
        .await
        .context("cleaning lifecycle ops")?;
    if args.publish {
        sqlx::query(&format!("DELETE FROM {outbox_table} WHERE team_id = $1"))
            .bind(args.team_id as i32)
            .execute(&pool)
            .await
            .context("cleaning the publish outbox")?;
        // The publishers claim every team's rows, so another team's pending
        // rows would drain onto this run's topics and vanish with them.
        let foreign_pending =
            publish::pending_outbox_rows(&pool, outbox_table, Some(args.team_id as i32)).await?;
        if foreign_pending > 0 {
            bail!(
                "{foreign_pending} pending outbox rows belong to other teams and the harness \
                 publishers would drain them onto this run's topics; clear {outbox_table} or \
                 use a dedicated persons database for --publish"
            );
        }
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
                    extra_leader_env: args.leader_env.clone(),
                    extra_router_env: router_env,
                    recovery_pool_size: args.recovery_pool_size,
                    leader_lease_ttl: args.leader_lease_ttl,
                    spawn_identity: create_via_identity,
                    publish: args.publish.then_some(PublishConfig {
                        publishers: args.publishers,
                        rows_per_pass: args.publish_rows_per_pass,
                    }),
                    monitor: None,
                })
                .await?,
            )
        }
    };

    let outcome = run_gate(
        GateContext {
            args: &args,
            pool: &pool,
            outbox_table,
            lifecycle_op,
            lifecycle_op_person,
            create_via_identity,
        },
        &mut stack,
        wide_role,
        chaos,
    )
    .await;

    // Teardown runs whatever the gate found, so a failed verification does
    // not leave the per-run topics behind. Only a passing run honors
    // --keep-stack.
    if let Some(stack) = stack {
        match &outcome {
            Ok(_) if args.keep_stack => {
                println!(
                    "Stack left running (logs at {}); services die with this process",
                    stack.log_dir.display()
                );
                // Hold the stack (and its kill-on-drop children) until the user
                // interrupts, since child processes die with the harness.
                tokio::signal::ctrl_c().await?;
                stack.down().await?;
            }
            Ok(_) => stack.down().await?,
            Err(_) => {
                if let Err(e) = stack.down().await {
                    tracing::warn!(error = %e, "stack teardown failed after the gate failed");
                }
            }
        }
    }

    let run = outcome?;
    if !run.violations.is_empty() {
        bail!("{} consistency violations detected", run.violations.len());
    }
    // The invariant is "acked implies visible", which zero acks satisfy
    // vacuously — a stack that failed every write must not pass the gate.
    if run.acked_writes == 0 {
        bail!("no writes were acked; the gate asserted nothing");
    }
    println!("Gate passed: every acked write visible in strong reads and Postgres");
    Ok(())
}

struct GateContext<'a> {
    args: &'a GateArgs,
    pool: &'a PgPool,
    outbox_table: &'static str,
    lifecycle_op: &'static str,
    lifecycle_op_person: &'static str,
    create_via_identity: bool,
}

struct GateRun {
    violations: Vec<ConsistencyViolation>,
    acked_writes: u64,
}

/// Everything between stack bring-up and teardown: seed, traffic, chaos,
/// verification, the delete leg and the data cleanup. Apart from `run` so
/// the stack comes down whatever this returns.
async fn run_gate(
    ctx: GateContext<'_>,
    stack: &mut Option<Stack>,
    wide_role: WideRole,
    chaos: Vec<(Duration, ChaosEvent)>,
) -> Result<GateRun> {
    let GateContext {
        args,
        pool,
        outbox_table,
        lifecycle_op,
        lifecycle_op_person,
        create_via_identity,
    } = ctx;
    let router_url = match (&args.external_router_url, &*stack) {
        (Some(url), _) => url.clone(),
        (None, Some(stack)) => stack.router_url.clone(),
        (None, None) => unreachable!(),
    };
    let client = HarnessClient::connect(&router_url).await?;
    let publish_topics = stack
        .as_ref()
        .and_then(|stack| stack.publish_topics().cloned());

    let state = PersonState::new();
    // A spawned stack always uses its own identity service — the gate's
    // assertions target that stack, so an external identity service pointed
    // elsewhere would only produce confusing failures.
    let identity_url = match (&args.external_identity_url, &*stack) {
        _ if !create_via_identity => None,
        (_, Some(stack)) => stack.identity_url.clone(),
        (Some(url), None) => Some(url.clone()),
        (None, None) => unreachable!("validated above"),
    };
    let mut distinct_ids: HashMap<i64, String> = HashMap::new();
    let person_ids = match &identity_url {
        Some(url) => {
            let created =
                create_persons_via_identity(url, args.team_id, args.persons, &state).await?;
            println!(
                "Created {} persons via identity for team {}",
                created.len(),
                args.team_id
            );
            let ids = created.iter().map(|(id, _)| *id).collect();
            distinct_ids.extend(created);
            ids
        }
        None => {
            let ids =
                seed::seed_persons(pool, &args.pg_target_table, args.team_id, args.persons).await?;
            println!("Seeded {} persons for team {}", ids.len(), args.team_id);
            ids
        }
    };
    let mut person_ids = person_ids;
    let mut wide_persons = Vec::new();
    if let (Some(url), true) = (&identity_url, args.merge_wide_persons > 0) {
        let created = create_wide_persons_via_identity(
            url,
            args.team_id,
            args.merge_wide_persons,
            args.merge_wide_distinct_ids,
            &state,
        )
        .await?;
        println!(
            "Created {} wide persons with {} extra distinct ids each",
            created.len(),
            args.merge_wide_distinct_ids
        );
        wide_persons.extend(created.iter().map(|(id, _)| *id));
        person_ids.extend(created.iter().map(|(id, _)| *id));
        distinct_ids.extend(created);
    }
    let created_count = person_ids.len();
    let person_ids = Arc::new(TargetPool::new(person_ids));
    let distinct_ids = Arc::new(distinct_ids);

    println!(
        "Driving traffic for {} with concurrency {}...",
        humantime::format_duration(args.duration),
        args.concurrency
    );
    let collector = Arc::new(StatsCollector::new());
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
                None,
                &blast::PropertyPlan::new(
                    "harness_gate_".to_string(),
                    DEFAULT_KEYS_PER_PERSON,
                    concurrency,
                ),
                &collector,
                &state,
                Arc::new(AtomicBool::new(false)),
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
                Arc::new(AtomicBool::new(false)),
            )
            .await
        })
    };

    let merges = identity_url
        .as_ref()
        .filter(|_| args.merge_concurrency > 0)
        .map(|url| {
            let url = url.clone();
            let router = client.clone();
            let person_ids = person_ids.clone();
            let distinct_ids = distinct_ids.clone();
            let collector = collector.clone();
            let state = state.clone();
            let lane = MergeLane {
                team_id: args.team_id,
                concurrency: args.merge_concurrency,
                rate_per_sec: args.merge_rate,
                sources_per_call: args.merge_sources,
                allow_identified_sources: args.merge_identified_sources,
                // A survivor collects the distinct ids of every merged
                // source. This limit covers the whole pool, so no source
                // trips the move guard.
                move_limit: i64::from(args.persons)
                    + i64::from(args.merge_wide_persons)
                        * (i64::from(args.merge_wide_distinct_ids) + 1)
                    + 1,
                wide_persons: wide_persons.clone(),
                wide_role,
            };
            let duration = args.duration;
            println!(
                "Merging with {} workers{}, {} source(s) per call...",
                args.merge_concurrency,
                args.merge_rate
                    .map(|rate| format!(" at {rate} merges/s"))
                    .unwrap_or_default(),
                args.merge_sources
            );
            tokio::spawn(async move {
                let identity = IdentityClient::connect(&url).await?;
                merge::run_merges(
                    &identity,
                    &router,
                    lane,
                    person_ids,
                    distinct_ids,
                    duration,
                    &collector,
                    &state,
                    Arc::new(AtomicBool::new(false)),
                )
                .await
            })
        });

    // Fire scheduled disruptions while traffic flows. Failures aren't
    // journaled, so the invariant is untouched: whatever the leader acked
    // through the disruption must still be visible afterwards.
    let traffic_start = Instant::now();
    let mut handoff_kill_armed = args.kill_handoff_target;
    // Fenced persons and their shared op id, filled by FencePersons and
    // drained by ReleaseFences.
    let fence_op = uuid::Uuid::new_v4();
    let mut fenced_persons: Vec<i64> = Vec::new();
    for (after, event) in chaos {
        tokio::time::sleep_until((traffic_start + after).into()).await;
        // The fence events act through the router like any client; they
        // need no spawned stack.
        match event {
            ChaosEvent::FencePersons => {
                // The durable fence record is the mark, written before any
                // seal — a leader taking partition ownership mid-window
                // rebuilds its fences from these rows. Fencing without them
                // would not survive a restart (the harness acts as the
                // saga's mark step here).
                sqlx::query(&format!(
                    "INSERT INTO {lifecycle_op} (op_id, op_type, team_id, step, request) \
                     VALUES ($1, 'delete', $2, 'started', '{{}}'::jsonb)"
                ))
                .bind(fence_op)
                .bind(args.team_id as i32)
                .execute(pool)
                .await
                .context("inserting fence op row")?;
                for &person_id in person_ids.snapshot().iter().take(args.fence_count) {
                    sqlx::query(&format!(
                        "INSERT INTO {lifecycle_op_person} \
                         (op_id, team_id, person_id, person_uuid, role, status) \
                         VALUES ($1, $2, $3, gen_random_uuid(), 'victim', 'marked')"
                    ))
                    .bind(fence_op)
                    .bind(args.team_id as i32)
                    .bind(person_id)
                    .execute(pool)
                    .await
                    .context("inserting fence mark")?;
                }
                for &person_id in person_ids.snapshot().iter().take(args.fence_count) {
                    match client
                        .fence_person(args.team_id, person_id, &fence_op)
                        .await
                    {
                        Ok(response) => {
                            let sealed = response
                                .sealed
                                .map(|person| person.version)
                                .unwrap_or_default();
                            state.open_fence(person_id, sealed).await;
                            fenced_persons.push(person_id);
                        }
                        // Chaos may legitimately fail the call (a partition
                        // mid-handoff); an unfenced person just isn't
                        // asserted on.
                        Err(e) => tracing::warn!(person_id, error = %e, "fence failed; skipping"),
                    }
                }
                println!(
                    "Chaos at {:.1}s: {event} → {} of {} fenced (op {fence_op})",
                    traffic_start.elapsed().as_secs_f64(),
                    fenced_persons.len(),
                    args.fence_count,
                );
                continue;
            }
            ChaosEvent::ReleaseFences => {
                let mut released = 0usize;
                for person_id in fenced_persons.drain(..) {
                    // Close the window before releasing so a write racing
                    // the release ack cannot be flagged as a phantom
                    // violation.
                    state.close_fence(person_id).await;
                    match client
                        .release_fence_aborted(args.team_id, person_id, &fence_op)
                        .await
                    {
                        Ok(()) => released += 1,
                        Err(e) => {
                            tracing::warn!(person_id, error = %e, "release failed; person stays fenced")
                        }
                    }
                }
                // The op is over: settle it so the marks leave the live
                // set (an aborted op's marks must not fence anyone after
                // release).
                sqlx::query(&format!(
                    "UPDATE {lifecycle_op_person} SET status = 'skipped_conflict' WHERE op_id = $1"
                ))
                .bind(fence_op)
                .execute(pool)
                .await
                .context("settling fence marks")?;
                sqlx::query(&format!(
                    "UPDATE {lifecycle_op} SET step = 'aborted', completed_at = now() WHERE op_id = $1"
                ))
                .bind(fence_op)
                .execute(pool)
                .await
                .context("completing fence op")?;
                println!(
                    "Chaos at {:.1}s: {event} → {released} released",
                    traffic_start.elapsed().as_secs_f64(),
                );
                continue;
            }
            _ => {}
        }
        let stack = stack.as_mut().expect("chaos requires a spawned stack");
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
            ChaosEvent::PublisherCrash => {
                stack.crash_restart_publisher().await?;
                None
            }
            ChaosEvent::IdentityCrash => {
                stack.crash_restart_identity().await?;
                None
            }
            ChaosEvent::Migrate | ChaosEvent::MigrateAgain => {
                let chaos = match event {
                    ChaosEvent::Migrate => MigrationChaos {
                        to_partitions: args
                            .migrate_to_partitions
                            .expect("validated: --migrate-after needs --migrate-to-partitions"),
                        kill_coordinator: args.migrate_kill_coordinator,
                        kill_leader_at: if args.migrate_kill_leader {
                            Some(MigrationPhase::Resuming)
                        } else if args.migrate_kill_leader_at_sealing {
                            Some(MigrationPhase::Sealing)
                        } else {
                            None
                        },
                        restart_leader: args.migrate_restart_leader,
                        stall: if args.migrate_stall_leader {
                            Some(StallAt::BeforeStart)
                        } else if args.migrate_stall_leader_at_sealing {
                            Some(StallAt::Sealing)
                        } else {
                            None
                        },
                        pause_writer: args
                            .migrate_pause_writer
                            .then_some(args.writer_pause_duration),
                    },
                    // The second migration runs clean; the first carries the chaos.
                    _ => MigrationChaos {
                        to_partitions: args.migrate_again_to_partitions.expect(
                            "validated: --migrate-again-after needs --migrate-again-to-partitions",
                        ),
                        kill_coordinator: false,
                        kill_leader_at: None,
                        restart_leader: false,
                        stall: None,
                        pause_writer: None,
                    },
                };
                let took = stack.migrate(chaos).await?;
                println!(
                    "Chaos at {:.1}s: migration ended in {:.1}s",
                    traffic_start.elapsed().as_secs_f64(),
                    took.as_secs_f64()
                );
                None
            }
            ChaosEvent::FencePersons | ChaosEvent::ReleaseFences => {
                unreachable!("fence events are dispatched before the stack match")
            }
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
    let mut prober_violations = probers.await.context("prober task panicked")??;
    if let Some(stack) = stack.as_mut() {
        stack.retire_drained().await?;
    }
    let mut unresolved_merges = Vec::new();
    if let Some(merges) = merges {
        let result = merges.await.context("merge task panicked")??;
        prober_violations.extend(result.violations);
        unresolved_merges = result.unresolved;
    }

    // Verification asserts data visibility on a converged topology, not
    // recovery speed: chaos legitimately leaves handoffs to re-drive. The
    // slowest legitimate recoveries can serialize: a leader kill with
    // --kill-fast false is blind until the leader lease expires (30s
    // default), and a concurrent slow router crash appends the election
    // TTL + campaign retry + registration TTL chain (~16s) — so the
    // deadline stretches with the configured leader TTL plus that chain
    // with margin, floored at 30s. A regression toward the old
    // multi-tens-of-seconds wedges still fails loudly. An already-settled
    // run waits zero time; a run that cannot converge fails here with the
    // stuck state.
    if let Some(stack) = stack.as_mut() {
        let convergence_deadline =
            Duration::from_secs(30).max(Duration::from_secs(args.leader_lease_ttl as u64 + 30));
        let settled = stack
            .wait_converged(convergence_deadline)
            .await
            .context("coordination must converge before verification")?;
        println!(
            "Post-traffic coordination settled in {:.1}s: {}",
            settled.as_secs_f64(),
            stack.coordination_report().await
        );
    }

    // Merges that lost every response settle from their op records
    // first. The sweeper re-drives an abandoned op only after its 15s
    // lease lapses, which is why the deadline is long.
    let mut violations = prober_violations;
    violations.extend(
        merge::settle_unresolved(
            pool,
            &args.pg_target_table,
            &state,
            unresolved_merges,
            Duration::from_secs(90),
        )
        .await?,
    );

    println!("Verifying strong reads...");
    violations.extend(state.take_anomalies().await);
    violations.extend(blast::verify_strong(&client, &collector, &state, args.team_id).await?);

    println!("Waiting for the writer to drain, then verifying Postgres...");
    let merged_ids = state.merged_source_ids().await;
    let journal = state.snapshot().await;
    let merged = state.snapshot_merged().await;
    violations.extend(
        verify_postgres(pool, &args.pg_target_table, args.team_id, &journal, &merged).await?,
    );

    // The publish plane: once the outbox has drained, the topics must hold
    // the Postgres mappings and the journaled merges. This pass compares
    // the live mappings; the delete leg below turns them into tombstones,
    // which the second pass compares.
    let mut publish_expected = None;
    if let Some(topics) = &publish_topics {
        println!("Waiting for the publish outbox to drain, then verifying Kafka...");
        let (drained_in, outbox_violations) =
            publish::wait_outbox_drained(pool, outbox_table, args.team_id, publish::DRAIN_DEADLINE)
                .await?;
        println!("  Outbox drained in {:.1}s", drained_in.as_secs_f64());
        // A publisher that died mid-drain is hidden by its replica.
        if let Some(stack) = stack.as_mut() {
            stack.check_alive()?;
        }
        violations.extend(outbox_violations);
        let expected =
            publish::expected_mappings(pool, &args.pg_target_table, args.team_id).await?;
        let publish::PublishedMappings {
            rows,
            conflicts,
            foreign_rows,
        } = publish::read_published_mappings(&args.kafka_hosts, &topics.distinct_ids, args.team_id)
            .await?;
        violations.extend(conflicts);
        violations.extend(publish::verify_published_mappings(&expected, &rows));
        let uncertain = state.merge_uncertain_ids().await;
        let expected_merges = publish::expected_merges(
            pool,
            &args.pg_target_table,
            args.team_id,
            &merged,
            &uncertain,
        )
        .await?;
        let published_merges =
            publish::read_published_merges(&args.kafka_hosts, &topics.merge_events, args.team_id)
                .await?;
        violations.extend(publish::verify_published_merges(
            &expected_merges,
            &published_merges,
        ));
        println!(
            "  {} mappings and {} merge events for {} pairs read back from Kafka ({foreign_rows} rows and {} events of other teams skipped)",
            rows.len(),
            published_merges.events,
            published_merges.pairs.len(),
            published_merges.foreign_events
        );
        publish_expected = Some(expected);
    }

    print_report("gate", &collector, args.team_id, created_count, &violations);
    let mut disputed: HashMap<i64, Vec<String>> = HashMap::new();
    for violation in &violations {
        let keys = disputed.entry(violation.person_id).or_default();
        if !keys.contains(&violation.key) {
            keys.push(violation.key.clone());
        }
    }
    for (person_id, keys) in disputed {
        println!("{}", state.describe(person_id, &keys).await);
    }
    if !merged_ids.is_empty() {
        println!(
            "  Merged {} of {} persons; {} live at the end",
            merged_ids.len(),
            created_count,
            person_ids.len()
        );
        println!();
    }

    // The delete leg of the identity path: persons created through
    // get-or-create leave through the lifecycle saga, and both the
    // outcomes and the saga's idempotence are gate assertions — every
    // created person deletes exactly once, and a second attempt under a
    // fresh op id answers not_found for all of them. A merged source is
    // a tombstone already, so it answers not_found on the first attempt.
    if let Some(url) = &identity_url {
        if !args.keep_data {
            println!("Deleting persons through the lifecycle saga...");
            let lifecycle = crate::client::LifecycleClient::connect(url).await?;
            let uncertain = state.merge_uncertain_ids().await;
            let mut live: Vec<i64> = distinct_ids.keys().copied().collect();
            live.retain(|id| !merged_ids.contains(id) && !uncertain.contains(id));
            live.sort_unstable();
            verify_lifecycle_delete(&lifecycle, args.team_id, &live, &merged_ids, &uncertain)
                .await?;
            println!("Lifecycle delete verified: all deleted, re-delete answers not_found");
        }
    }

    if let (Some(before), Some(topics), false) =
        (&publish_expected, &publish_topics, args.keep_data)
    {
        println!(
            "Waiting for the publish outbox to drain, then verifying the tombstones on Kafka..."
        );
        let (drained_in, outbox_violations) =
            publish::wait_outbox_drained(pool, outbox_table, args.team_id, publish::DRAIN_DEADLINE)
                .await?;
        println!("  Outbox drained in {:.1}s", drained_in.as_secs_f64());
        if let Some(stack) = stack.as_mut() {
            stack.check_alive()?;
        }
        // Rows parked before the first pass were reported there.
        let reported: HashSet<String> = violations.iter().map(|v| v.key.clone()).collect();
        let mut late: Vec<_> = outbox_violations
            .into_iter()
            .filter(|v| !reported.contains(&v.key))
            .collect();
        let after = publish::expected_mappings(pool, &args.pg_target_table, args.team_id).await?;
        late.extend(publish::verify_tombstoned_in_postgres(before, &after));
        let published =
            publish::read_published_mappings(&args.kafka_hosts, &topics.distinct_ids, args.team_id)
                .await?;
        late.extend(published.conflicts);
        late.extend(publish::verify_published_mappings(&after, &published.rows));
        if late.is_empty() {
            println!(
                "  Every one of {} mappings tombstoned on Kafka at the version Postgres holds",
                before.len()
            );
        } else {
            println!("  {} publish violations after the delete leg:", late.len());
            for violation in late.iter().take(20) {
                println!(
                    "    person {} {}: expected {} actual {}",
                    violation.person_id, violation.key, violation.expected, violation.actual
                );
            }
        }
        violations.extend(late);
    }

    if !args.keep_data {
        let persons = seed::cleanup_team(pool, &args.pg_target_table, args.team_id).await?;
        println!("Cleaned up {persons} persons");
        if args.publish {
            sqlx::query(&format!("DELETE FROM {outbox_table} WHERE team_id = $1"))
                .bind(args.team_id as i32)
                .execute(pool)
                .await
                .context("cleaning the publish outbox")?;
        }
    }

    Ok(GateRun {
        violations,
        acked_writes: collector.writes.snapshot().successes,
    })
}

/// Delete `person_ids` through the lifecycle saga and hold the answers
/// to the gate's standard: every id deleted on the first attempt, every
/// id not_found on a second attempt under a fresh op id (deleting a
/// tombstone is a no-op, never an error, never a false success).
/// `merged_ids` must answer not_found on the first attempt. A `deleted`
/// there means the merge left a living row. `uncertain_ids` had a merge
/// call that never answered, so either answer is accepted.
///
/// A `skipped_conflict` means another lifecycle op still holds the
/// person, usually a merge that chaos interrupted. The delete is retried
/// under fresh op ids until the sweeper settles that op. An op that
/// never settles fails the gate, because nobody can merge or delete
/// that person again.
async fn verify_lifecycle_delete(
    lifecycle: &crate::client::LifecycleClient,
    team_id: i64,
    person_ids: &[i64],
    merged_ids: &[i64],
    uncertain_ids: &[i64],
) -> Result<()> {
    use personhog_proto::personhog::lifecycle::v1::DeletePersonOutcome;

    /// The sweeper claims an abandoned op only after its 15s lease
    /// lapses, then re-drives it. Sized for a few of those in sequence.
    const SETTLE_DEADLINE: Duration = Duration::from_secs(90);

    let mut expected: HashMap<i64, Vec<DeletePersonOutcome>> = HashMap::new();
    for &id in person_ids {
        expected.insert(id, vec![DeletePersonOutcome::Deleted]);
    }
    for &id in merged_ids {
        expected.insert(id, vec![DeletePersonOutcome::NotFound]);
    }
    for &id in uncertain_ids {
        expected.insert(
            id,
            vec![DeletePersonOutcome::Deleted, DeletePersonOutcome::NotFound],
        );
    }
    let mut pending: Vec<i64> = expected.keys().copied().collect();
    pending.sort_unstable();
    let deadline = Instant::now() + SETTLE_DEADLINE;
    while !pending.is_empty() {
        let mut conflicts = Vec::new();
        // The lifecycle service caps batches at 250 person ids.
        for chunk in pending.chunks(200) {
            let op_id = uuid::Uuid::new_v4();
            for (person_id, outcome) in lifecycle
                .delete_persons(team_id, chunk.to_vec(), &op_id)
                .await?
            {
                let accepted = &expected[&person_id];
                if outcome == DeletePersonOutcome::SkippedConflict {
                    conflicts.push(person_id);
                } else if !accepted.contains(&outcome) {
                    bail!(
                        "lifecycle delete: person {person_id} answered {outcome:?}, \
                         expected one of {accepted:?}"
                    );
                }
            }
        }
        if conflicts.is_empty() {
            break;
        }
        if Instant::now() > deadline {
            bail!(
                "lifecycle delete: {} persons still held by another lifecycle op after {:?}: {:?}",
                conflicts.len(),
                SETTLE_DEADLINE,
                &conflicts[..conflicts.len().min(10)]
            );
        }
        println!(
            "  {} persons held by an unsettled lifecycle op; waiting for the sweeper...",
            conflicts.len()
        );
        tokio::time::sleep(Duration::from_secs(3)).await;
        pending = conflicts;
    }

    // A second attempt under a fresh op id must answer not_found for
    // everything. Deleting a tombstone is a no-op, not an error.
    let mut all: Vec<i64> = expected.keys().copied().collect();
    all.sort_unstable();
    for chunk in all.chunks(200) {
        let op_id = uuid::Uuid::new_v4();
        for (person_id, outcome) in lifecycle
            .delete_persons(team_id, chunk.to_vec(), &op_id)
            .await?
        {
            if outcome != DeletePersonOutcome::NotFound {
                bail!(
                    "lifecycle re-delete: person {person_id} answered {outcome:?}, expected NotFound"
                );
            }
        }
    }
    Ok(())
}

/// Create the traffic-target persons through the identity service's batch
/// get-or-create, with one seed property per person, returning each
/// person's id with its distinct id. The create ack covers both planes
/// (stub committed in Postgres, initial properties durable in the
/// changelog), so each ack is journaled like any other write. The
/// end-of-run strong reads and the Postgres check then hold create
/// visibility to the same invariant as update visibility.
async fn create_persons_via_identity(
    identity_url: &str,
    team_id: i64,
    count: u32,
    state: &PersonState,
) -> Result<Vec<(i64, String)>> {
    /// The identity service caps batches at 250 entries by default.
    const CREATE_BATCH_SIZE: u32 = 250;

    let client = IdentityClient::connect(identity_url).await?;
    let mut person_ids = Vec::with_capacity(count as usize);
    let mut start = 0u32;
    while start < count {
        let end = (start + CREATE_BATCH_SIZE).min(count);
        let entries: Vec<GetOrCreatePersonEntry> = (start..end)
            .map(|i| {
                let distinct_id = format!("harness-gate-{team_id}-{i}");
                GetOrCreatePersonEntry {
                    team_id,
                    distinct_id: distinct_id.clone(),
                    extra_distinct_ids: vec![],
                    event_name: "$set".to_string(),
                    set_properties: serde_json::to_vec(
                        &serde_json::json!({ SEED_KEY: distinct_id }),
                    )
                    .expect("seed properties serialize"),
                    set_once_properties: Vec::new(),
                    created_at: 0,
                    is_identified: false,
                }
            })
            .collect();

        for result in client.get_or_create_persons(entries).await? {
            if let Some(error) = &result.error {
                bail!(
                    "identity create failed for distinct id {}: {error}",
                    result.distinct_id
                );
            }
            let person = result
                .person
                .with_context(|| format!("no person for distinct id {}", result.distinct_id))?;
            if !result.created {
                bail!(
                    "distinct id {} already existed; the harness team must start clean",
                    result.distinct_id
                );
            }
            let seed_properties =
                HashMap::from([(SEED_KEY.to_string(), serde_json::json!(result.distinct_id))]);
            state
                .record_write(person.id, person.version, seed_properties)
                .await;
            person_ids.push((person.id, result.distinct_id));
        }
        start = end;
    }
    Ok(person_ids)
}

/// Create persons with `extra_distinct_ids` extra distinct ids each, so
/// a merge makes the flip repoint many mappings.
async fn create_wide_persons_via_identity(
    identity_url: &str,
    team_id: i64,
    count: u32,
    extra_distinct_ids: u32,
    state: &PersonState,
) -> Result<Vec<(i64, String)>> {
    let client = IdentityClient::connect(identity_url).await?;
    let mut persons = Vec::with_capacity(count as usize);
    for i in 0..count {
        let distinct_id = format!("harness-gate-{team_id}-wide{i}");
        let entry = GetOrCreatePersonEntry {
            team_id,
            distinct_id: distinct_id.clone(),
            extra_distinct_ids: (0..extra_distinct_ids)
                .map(|j| format!("{distinct_id}-{j}"))
                .collect(),
            event_name: "$set".to_string(),
            set_properties: serde_json::to_vec(&serde_json::json!({ SEED_KEY: distinct_id }))
                .expect("seed properties serialize"),
            set_once_properties: Vec::new(),
            created_at: 0,
            is_identified: false,
        };
        let mut results = client.get_or_create_persons(vec![entry]).await?;
        let result = results
            .pop()
            .context("identity returned no result for a wide person")?;
        if let Some(error) = &result.error {
            bail!("identity create failed for wide person {distinct_id}: {error}");
        }
        let person = result
            .person
            .with_context(|| format!("no person for wide distinct id {distinct_id}"))?;
        if !result.created {
            bail!("distinct id {distinct_id} already existed; the harness team must start clean");
        }
        state
            .record_write(
                person.id,
                person.version,
                HashMap::from([(SEED_KEY.to_string(), serde_json::json!(result.distinct_id))]),
            )
            .await;
        persons.push((person.id, result.distinct_id));
    }
    Ok(persons)
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
            "--publisher-crash-after",
            "4s",
        ]);
        let rendered: Vec<(u64, String)> = chaos_timeline(&args)
            .iter()
            .map(|(after, event)| (after.as_secs(), event.to_string()))
            .collect();
        let expected: Vec<(u64, String)> = [
            (2, "writer pause (lag injection)"),
            (3, "writer resume"),
            (4, "publisher crash-restart"),
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
