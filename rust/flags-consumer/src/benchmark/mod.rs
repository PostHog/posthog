pub mod collector;
pub mod executor;
pub mod ops;
pub mod pg_sampler;
pub mod plancheck;
pub mod population;
pub mod rates;
pub mod report;
pub mod scheduler;
pub mod schema;
pub mod world;

use std::collections::BTreeMap;
use std::num::NonZeroUsize;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::Context;
use common_database::{get_pool_with_config, PoolConfig};
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use serde::Serialize;
use sqlx::PgPool;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use crate::storage::postgres::PostgresStorage;
use collector::{JsonlSink, PhaseCollector};
use executor::{ExecutorConfig, ExecutorDispatchers, ExecutorIngress, ExecutorRuntime};
use ops::{CompletionOutcome, CompletionRecord, OpClass, OpDescriptor, OperationId, PhaseId};
use pg_sampler::{PgDeltaRecord, PgSampler};
use rates::{standard_phases, BenchmarkProfile, Hook, PhaseSpec, RatePerSecond, RateSpec};
use report::{GateEvaluation, GateThresholds, PhaseResult};
use scheduler::{ArrivalSchedule, BoundedDispatcher, DispatchOutcome, DispatchRecord, PhaseClock};
use world::{
    AssignmentMode, PendingCreationToken, PendingDistinctIdToken, PersonCreationCount, ReadMode,
    ReplayMode, WorldConfig, WorldError, WorldGrowth, WorldMemoryEstimate, WorldState,
};

const DEFAULT_OUTPUT: &str = "tmp/flags-read-store-benchmark.jsonl";
const PG_SAMPLE_INTERVAL: Duration = Duration::from_secs(10);
const GROWTH_PREFLIGHT_HEADROOM: f64 = 1.20;
const WORKLOAD_SEED_MIX: u64 = 0xe703_7ed1_a0b4_28db;

#[derive(Debug, Clone, Serialize, clap::Args)]
pub struct BenchmarkArgs {
    #[arg(long, value_enum, default_value_t = BenchmarkProfile::Smoke)]
    pub profile: BenchmarkProfile,

    #[arg(long, default_value_t = 100_000)]
    pub scale: u64,

    #[arg(long, default_value_t = 100)]
    pub teams: i32,

    #[arg(long)]
    pub duration_secs: Option<u64>,

    #[arg(long, default_value_t = 64)]
    pub partitions: usize,

    #[arg(long, default_value_t = 100)]
    pub person_fillfactor: u8,

    #[arg(long, default_value_t = 100)]
    pub map_fillfactor: u8,

    #[arg(long, default_value_t = 500)]
    pub batch_size: usize,

    #[arg(long, default_value_t = 700)]
    pub prop_bytes: usize,

    #[arg(long, default_value_t = 42)]
    pub seed: u64,

    #[arg(long, default_value = DEFAULT_OUTPUT)]
    pub out: PathBuf,

    #[arg(long)]
    pub skip_populate: bool,

    #[arg(long)]
    pub allow_destructive_reset: bool,

    #[arg(long, default_value_t = 64)]
    pub read_workers: usize,

    #[arg(long, default_value_t = 16)]
    pub merge_workers: usize,

    #[arg(long, default_value_t = 8)]
    pub person_batch_workers: usize,

    #[arg(long, default_value_t = 8)]
    pub distinct_id_batch_workers: usize,

    #[arg(long, default_value_t = 6_144)]
    pub max_world_memory_mib: u64,

    #[arg(long, default_value_t = 5)]
    pub creation_percent: u8,

    #[arg(long, default_value_t = 1)]
    pub stale_replay_percent: u8,

    #[arg(long, default_value_t = 1)]
    pub read_miss_percent: u8,

    #[arg(long, default_value_t = 1)]
    pub whale_merge_percent: u8,

    #[arg(long, default_value_t = 50)]
    pub recent_target_percent: u8,

    #[arg(long, default_value_t = 1.0)]
    pub gate_read_p50_ms: f64,

    #[arg(long, default_value_t = 5.0)]
    pub gate_read_p99_ms: f64,

    #[arg(long, default_value_t = 10.0)]
    pub gate_storm_read_p99_ms: f64,

    #[arg(long, default_value_t = 900)]
    pub gate_recovery_max_secs: u64,

    #[arg(long, default_value_t = 5.0)]
    pub gate_catch_up_headroom: f64,

    #[arg(long, default_value_t = 5.0)]
    pub gate_dispatch_p99_ms: f64,

    #[arg(long, default_value_t = 1.0)]
    pub gate_rate_tolerance_percent: f64,

    #[arg(long, default_value_t = 1.2)]
    pub gate_max_read_drift_ratio: f64,

    #[arg(long, default_value_t = 1.0)]
    pub gate_max_backlog_secs: f64,
}

impl BenchmarkArgs {
    fn validate(&self) -> anyhow::Result<()> {
        anyhow::ensure!(self.scale > 0, "--scale must be greater than zero");
        anyhow::ensure!(self.teams > 0, "--teams must be greater than zero");
        anyhow::ensure!(
            self.skip_populate || self.allow_destructive_reset,
            "schema recreation requires --allow-destructive-reset"
        );
        anyhow::ensure!(
            self.batch_size > 0,
            "--batch-size must be greater than zero"
        );
        anyhow::ensure!(
            self.prop_bytes > 0,
            "--prop-bytes must be greater than zero"
        );
        anyhow::ensure!(
            self.max_world_memory_mib > 0,
            "--max-world-memory-mib must be greater than zero"
        );
        for (name, value) in [
            ("--creation-percent", self.creation_percent),
            ("--stale-replay-percent", self.stale_replay_percent),
            ("--read-miss-percent", self.read_miss_percent),
            ("--whale-merge-percent", self.whale_merge_percent),
            ("--recent-target-percent", self.recent_target_percent),
        ] {
            anyhow::ensure!(value <= 100, "{name} must be between 0 and 100");
        }
        for (name, value) in [
            ("--gate-read-p50-ms", self.gate_read_p50_ms),
            ("--gate-read-p99-ms", self.gate_read_p99_ms),
            ("--gate-storm-read-p99-ms", self.gate_storm_read_p99_ms),
            ("--gate-catch-up-headroom", self.gate_catch_up_headroom),
            ("--gate-dispatch-p99-ms", self.gate_dispatch_p99_ms),
            (
                "--gate-rate-tolerance-percent",
                self.gate_rate_tolerance_percent,
            ),
            (
                "--gate-max-read-drift-ratio",
                self.gate_max_read_drift_ratio,
            ),
            ("--gate-max-backlog-secs", self.gate_max_backlog_secs),
        ] {
            anyhow::ensure!(
                value.is_finite() && value > 0.0,
                "{name} must be finite and positive"
            );
        }
        self.executor_config()?;
        Ok(())
    }

    fn duration_override(&self) -> Option<Duration> {
        self.duration_secs.map(Duration::from_secs)
    }

    fn world_config(&self) -> anyhow::Result<WorldConfig> {
        Ok(WorldConfig {
            seed: self.seed,
            team_count: self.teams,
            initial_person_count: usize::try_from(self.scale).context("--scale exceeds usize")?,
            recent_capacity_per_team: 4_096,
            recent_target_percent: self.recent_target_percent,
            property_bytes: self.prop_bytes,
        })
    }

    fn executor_config(&self) -> anyhow::Result<ExecutorConfig> {
        Ok(ExecutorConfig {
            read_workers: nonzero("--read-workers", self.read_workers)?,
            merge_workers: nonzero("--merge-workers", self.merge_workers)?,
            person_batch_workers: nonzero("--person-batch-workers", self.person_batch_workers)?,
            distinct_id_batch_workers: nonzero(
                "--distinct-id-batch-workers",
                self.distinct_id_batch_workers,
            )?,
            batch_size: nonzero("--batch-size", self.batch_size)?,
            ..ExecutorConfig::default()
        })
    }

    fn gate_thresholds(&self) -> GateThresholds {
        GateThresholds {
            steady_read_p50_ms: self.gate_read_p50_ms,
            steady_read_p99_ms: self.gate_read_p99_ms,
            storm_read_p99_ms: self.gate_storm_read_p99_ms,
            recovery_max_secs: self.gate_recovery_max_secs,
            catch_up_headroom: self.gate_catch_up_headroom,
            dispatch_p99_ms: self.gate_dispatch_p99_ms,
            rate_tolerance_percent: self.gate_rate_tolerance_percent,
            max_read_drift_ratio: self.gate_max_read_drift_ratio,
            max_backlog_secs: self.gate_max_backlog_secs,
        }
    }

    fn world_memory_limit_bytes(&self) -> anyhow::Result<u64> {
        self.max_world_memory_mib
            .checked_mul(1024 * 1024)
            .context("--max-world-memory-mib overflows bytes")
    }
}

fn nonzero(name: &'static str, value: usize) -> anyhow::Result<NonZeroUsize> {
    NonZeroUsize::new(value).with_context(|| format!("{name} must be greater than zero"))
}

#[derive(Debug, Serialize)]
struct RunMetaRecord<'a> {
    record_type: &'static str,
    postgres_version: &'a str,
    settings: &'a [(String, String)],
    args: &'a BenchmarkArgs,
    seed: u64,
    population: Option<population::PopulationSummary>,
    schema: &'a schema::SchemaMetadata,
    initial_world_memory: WorldMemoryEstimate,
    projected_world_memory: WorldMemoryEstimate,
    phases: &'a [PhaseSpec],
    plan_evidence: &'a [plancheck::NamedPlanEvidence],
}

#[derive(Debug, Default)]
struct RuntimeGrowth {
    person_creations: u64,
    distinct_id_assignments: u64,
}

#[derive(Debug, Clone, Copy)]
struct PhaseTimings {
    pre_hook: Duration,
    drain: Duration,
}

impl RuntimeGrowth {
    fn creation(&mut self) {
        self.person_creations = self.person_creations.saturating_add(1);
    }

    fn distinct_id(&mut self) {
        self.distinct_id_assignments = self.distinct_id_assignments.saturating_add(1);
    }

    fn as_world_growth(&self) -> WorldGrowth {
        WorldGrowth::new(
            PersonCreationCount::new(self.person_creations),
            world::DistinctIdAssignmentCount::new(self.distinct_id_assignments),
        )
    }
}

#[derive(Debug, Clone, Copy)]
enum PendingReference {
    Creation(u64),
    DistinctId(PendingDistinctIdToken),
}

#[derive(Debug, Clone, Copy)]
struct PendingCreation {
    token: PendingCreationToken,
    remaining: u8,
}

#[derive(Debug, Default)]
struct ActivationTracker {
    next_creation: u64,
    by_operation: BTreeMap<OperationId, PendingReference>,
    creations: BTreeMap<u64, PendingCreation>,
}

impl ActivationTracker {
    fn register_creation(
        &mut self,
        token: PendingCreationToken,
        person_operation: OperationId,
        distinct_id_operation: OperationId,
    ) -> anyhow::Result<()> {
        let creation_id = self.next_creation;
        self.next_creation = self
            .next_creation
            .checked_add(1)
            .context("pending creation identifier exhausted")?;
        self.creations.insert(
            creation_id,
            PendingCreation {
                token,
                remaining: 2,
            },
        );
        for operation_id in [person_operation, distinct_id_operation] {
            anyhow::ensure!(
                self.by_operation
                    .insert(operation_id, PendingReference::Creation(creation_id))
                    .is_none(),
                "duplicate pending operation {}",
                operation_id.0
            );
        }
        Ok(())
    }

    fn register_distinct_id(
        &mut self,
        operation_id: OperationId,
        token: PendingDistinctIdToken,
    ) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.by_operation
                .insert(operation_id, PendingReference::DistinctId(token))
                .is_none(),
            "duplicate pending operation {}",
            operation_id.0
        );
        Ok(())
    }

    fn record_completion(
        &mut self,
        world: &mut WorldState,
        completion: &CompletionRecord,
    ) -> anyhow::Result<()> {
        if let CompletionOutcome::Error { message } = &completion.outcome {
            anyhow::bail!(
                "{:?} operation {} failed: {message}",
                completion.class,
                completion.operation_id.0
            );
        }
        let Some(reference) = self.by_operation.remove(&completion.operation_id) else {
            return Ok(());
        };
        match reference {
            PendingReference::DistinctId(token) => world.activate_distinct_id(token)?,
            PendingReference::Creation(creation_id) => {
                let pending = self
                    .creations
                    .get_mut(&creation_id)
                    .context("pending creation completion lost its state")?;
                pending.remaining = pending
                    .remaining
                    .checked_sub(1)
                    .context("pending creation completed more than twice")?;
                if pending.remaining == 0 {
                    let pending = self
                        .creations
                        .remove(&creation_id)
                        .context("pending creation disappeared before activation")?;
                    world.activate_creation(pending.token)?;
                }
            }
        }
        Ok(())
    }

    fn record_failed_dispatch(
        &mut self,
        world: &mut WorldState,
        operation_id: OperationId,
        outcome: DispatchOutcome,
    ) -> anyhow::Result<()> {
        let reference = self.by_operation.remove(&operation_id);
        if matches!(outcome, DispatchOutcome::Closed) {
            anyhow::bail!(
                "executor closed while dispatching operation {}",
                operation_id.0
            );
        }
        if let Some(PendingReference::Creation(_)) = reference {
            anyhow::bail!("creation operation {} was shed", operation_id.0);
        }
        if let Some(PendingReference::DistinctId(token)) = reference {
            world.abandon_distinct_id(token)?;
        }
        Ok(())
    }

    fn ensure_empty(&self) -> anyhow::Result<()> {
        anyhow::ensure!(
            self.by_operation.is_empty() && self.creations.is_empty(),
            "phase ended with {} pending activations",
            self.by_operation.len()
        );
        Ok(())
    }
}

/// The read-store handles every phase connects through.
struct StoreHandles<'a> {
    database_url: &'a str,
    pool: &'a PgPool,
    storage: &'a Arc<PostgresStorage>,
}

/// The mutable world plus the knobs that shape generated operations. Lives for the
/// whole run: entity versions must never restart between phases, or merges of
/// untouched entities degenerate into no-ops.
struct WorkloadContext<'a> {
    world: &'a mut WorldState,
    rng: &'a mut StdRng,
    growth: &'a mut RuntimeGrowth,
    world_config: &'a WorldConfig,
    memory_limit: u64,
    args: &'a BenchmarkArgs,
    /// Each phase asserts this is empty before it finishes, so it carries no state
    /// across phases beyond a monotonic creation counter.
    tracker: ActivationTracker,
}

/// The recording surfaces a phase accumulates into and hands to `finish_phase`.
struct PhaseMetrics<'a> {
    collector: PhaseCollector,
    intervals: Vec<collector::IntervalRecord>,
    pg_records: Vec<PgDeltaRecord>,
    pg_receiver: mpsc::Receiver<PgSample>,
    sink: &'a mut JsonlSink,
}

pub async fn run(args: BenchmarkArgs) -> anyhow::Result<()> {
    args.validate()?;
    let phases = standard_phases(args.profile, args.duration_override());
    let world_config = args.world_config()?;
    let initial_world_memory = WorldState::estimate_initial_memory(&world_config)?;
    let projected_growth = projected_growth(&args, &phases)?;
    let projected_world_memory = WorldState::estimate_memory(&world_config, projected_growth)?;
    let memory_limit = args.world_memory_limit_bytes()?;
    anyhow::ensure!(
        projected_world_memory.total_bytes <= memory_limit,
        "projected world state requires {:.1} MiB, above --max-world-memory-mib {}",
        bytes_mib(projected_world_memory.total_bytes),
        args.max_world_memory_mib
    );

    ensure_output_parent(&args.out)?;
    let mut sink = JsonlSink::create(&args.out)
        .with_context(|| format!("create benchmark output {}", args.out.display()))?;
    let database_url = benchmark_database_url()?;
    let executor_config = args.executor_config()?;
    let pool = benchmark_pool(&database_url, &executor_config)?;
    let storage = Arc::new(PostgresStorage::new(pool.clone()));
    storage
        .ping()
        .await
        .context("connect read-store database")?;

    let mut world = WorldState::new(world_config.clone())?;
    world.reserve_person_growth(projected_growth.person_creations)?;
    let (population, schema_source) = if args.skip_populate {
        anyhow::ensure!(
            schema::table_exists(&pool).await?,
            "--skip-populate requires existing flags_person and flags_distinct_id_map tables"
        );
        (None, schema::SchemaSource::Existing)
    } else {
        schema::create_schema(
            &pool,
            args.partitions,
            args.person_fillfactor,
            args.map_fillfactor,
        )
        .await?;
        let population = population::populate_world(
            &pool,
            storage.as_ref(),
            world.population(),
            args.batch_size,
        )
        .await?;
        (Some(population), schema::SchemaSource::Created)
    };
    let schema = schema::inspect_schema(&pool, schema_source).await?;

    let plan_evidence = plancheck::verify_storage_plans(&pool).await?;
    let postgres_version: String = sqlx::query_scalar("SELECT version()")
        .fetch_one(&pool)
        .await
        .context("read PostgreSQL version")?;
    let settings = load_postgres_settings(&pool).await?;
    sink.write(&RunMetaRecord {
        record_type: "run_meta",
        postgres_version: &postgres_version,
        settings: &settings,
        args: &args,
        seed: args.seed,
        population,
        schema: &schema,
        initial_world_memory,
        projected_world_memory,
        phases: &phases,
        plan_evidence: &plan_evidence,
    })?;

    let mut phase_results = Vec::with_capacity(phases.len());
    let mut growth = RuntimeGrowth::default();
    let mut workload_rng = StdRng::seed_from_u64(args.seed ^ WORKLOAD_SEED_MIX);
    let store = StoreHandles {
        database_url: &database_url,
        pool: &pool,
        storage: &storage,
    };
    let mut workload = WorkloadContext {
        world: &mut world,
        rng: &mut workload_rng,
        growth: &mut growth,
        world_config: &world_config,
        memory_limit,
        args: &args,
        tracker: ActivationTracker::default(),
    };
    for (index, phase) in phases.iter().enumerate() {
        let phase_id = PhaseId::new(u64::try_from(index + 1).context("phase ID overflow")?);
        let result = run_phase(
            &store,
            &mut workload,
            phase_id,
            phase,
            executor_config.clone(),
            &mut sink,
        )
        .await
        .with_context(|| format!("run {} phase", phase.name.as_str()))?;
        phase_results.push(result);
    }

    let gates = report::evaluate_gates(&phase_results, args.gate_thresholds());
    #[derive(Serialize)]
    struct GateRecord<'a> {
        record_type: &'static str,
        evaluation: &'a GateEvaluation,
    }
    sink.write(&GateRecord {
        record_type: "gate_evaluation",
        evaluation: &gates,
    })?;
    sink.flush()?;
    report::print_report(
        &postgres_version,
        &settings,
        args.seed,
        &phase_results,
        &gates,
    );
    enforce_gate_result(args.profile, &gates, &args.out)
}

async fn run_phase(
    store: &StoreHandles<'_>,
    workload: &mut WorkloadContext<'_>,
    phase_id: PhaseId,
    phase: &PhaseSpec,
    executor_config: ExecutorConfig,
    sink: &mut JsonlSink,
) -> anyhow::Result<PhaseResult> {
    if phase.name == rates::PhaseName::CatchUp {
        run_catch_up_phase(store, workload, phase_id, phase, executor_config, sink).await
    } else {
        run_open_phase(store, workload, phase_id, phase, executor_config, sink).await
    }
}

async fn run_open_phase(
    store: &StoreHandles<'_>,
    workload: &mut WorkloadContext<'_>,
    phase_id: PhaseId,
    phase: &PhaseSpec,
    executor_config: ExecutorConfig,
    sink: &mut JsonlSink,
) -> anyhow::Result<PhaseResult> {
    let args = workload.args;
    let (pre_hook_duration, pg_records) =
        run_pre_hooks(store, phase_id, &phase.pre_hooks, sink).await?;
    let clock = PhaseClock::start_now(phase_id);
    let (mut ingress, mut runtime) =
        executor::start(Arc::clone(store.storage), clock, executor_config);
    let cancellation = runtime.cancellation_token();
    let rates = adjusted_open_rates(phase, args.creation_percent)?;
    let mut schedule = ArrivalSchedule::new(
        phase_id,
        args.seed ^ phase_id.get().wrapping_mul(WORKLOAD_SEED_MIX),
        &rates,
    )?;
    let duration_nanos = duration_as_nanos(phase.duration);
    let (sampler_cancellation, pg_receiver, sampler_task) =
        spawn_pg_sampler(store.database_url.to_owned(), phase_id);
    let mut metrics = PhaseMetrics {
        collector: PhaseCollector::with_deadline(phase_id, duration_nanos),
        intervals: Vec::new(),
        pg_records,
        pg_receiver,
        sink,
    };

    let load_result = drive_open_load(
        &clock,
        phase.duration,
        &mut schedule,
        &mut ingress,
        &mut runtime,
        workload,
        &mut metrics,
    )
    .await;
    let workload_interval_result = flush_interval(duration_nanos, &mut metrics);
    if load_result.is_err() || workload_interval_result.is_err() {
        cancellation.cancel();
    }
    let drain_started = Instant::now();
    drop(ingress);
    let drain_result = runtime
        .drain(|completion| record_completion(&mut metrics.collector, workload, completion))
        .await;
    let drain_duration = drain_started.elapsed();
    sampler_cancellation.cancel();
    let sampler_result = sampler_task.await.context("join PostgreSQL sampler task");
    let pg_sample_result = drain_pg_samples(&mut metrics);

    load_result?;
    workload_interval_result?;
    sampler_result?;
    pg_sample_result?;
    drain_result?;
    workload.tracker.ensure_empty()?;
    finish_phase(
        phase,
        PhaseTimings {
            pre_hook: pre_hook_duration,
            drain: drain_duration,
        },
        clock,
        metrics,
    )
}

async fn run_catch_up_phase(
    store: &StoreHandles<'_>,
    workload: &mut WorkloadContext<'_>,
    phase_id: PhaseId,
    phase: &PhaseSpec,
    executor_config: ExecutorConfig,
    sink: &mut JsonlSink,
) -> anyhow::Result<PhaseResult> {
    let args = workload.args;
    let (pre_hook_duration, pg_records) =
        run_pre_hooks(store, phase_id, &phase.pre_hooks, sink).await?;
    let clock = PhaseClock::start_now(phase_id);
    let (ingress, mut runtime) = executor::start(Arc::clone(store.storage), clock, executor_config);
    let cancellation = runtime.cancellation_token();
    let ExecutorDispatchers {
        person_upserts,
        distinct_id_assignments,
        merges,
        canonical_reads,
    } = ingress.into_dispatchers();
    let mut canonical_reads = Some(canonical_reads);
    let writer_stop = CancellationToken::new();
    let (request_sender, mut request_receiver) = mpsc::channel(16);
    let (dispatch_sender, mut dispatch_receiver) = mpsc::channel(16);
    let (person_sender, person_receiver) = mpsc::channel(1);
    let (distinct_id_sender, distinct_id_receiver) = mpsc::channel(1);
    let (merge_sender, merge_receiver) = mpsc::channel(1);
    let person_task = spawn_writer_pump(
        OpClass::PersonUpsert,
        person_upserts,
        person_receiver,
        request_sender.clone(),
        dispatch_sender.clone(),
        clock,
        writer_stop.clone(),
    );
    let distinct_id_task = spawn_writer_pump(
        OpClass::DistinctIdAssignment,
        distinct_id_assignments,
        distinct_id_receiver,
        request_sender.clone(),
        dispatch_sender.clone(),
        clock,
        writer_stop.clone(),
    );
    let merge_task = spawn_writer_pump(
        OpClass::Merge,
        merges,
        merge_receiver,
        request_sender.clone(),
        dispatch_sender.clone(),
        clock,
        writer_stop.clone(),
    );
    drop(request_sender);
    drop(dispatch_sender);
    let writer_senders = WriterOperationSenders {
        person: person_sender,
        distinct_id: distinct_id_sender,
        merge: merge_sender,
    };

    let mut read_schedule = ArrivalSchedule::new(
        phase_id,
        args.seed ^ phase_id.get().wrapping_mul(WORKLOAD_SEED_MIX),
        &phase.rates,
    )?;
    let duration_nanos = duration_as_nanos(phase.duration);
    let (sampler_cancellation, pg_receiver, sampler_task) =
        spawn_pg_sampler(store.database_url.to_owned(), phase_id);
    let mut metrics = PhaseMetrics {
        collector: PhaseCollector::with_deadline(phase_id, duration_nanos),
        intervals: Vec::new(),
        pg_records,
        pg_receiver,
        sink,
    };

    let load_result = drive_catch_up_load(
        &clock,
        phase.duration,
        &mut read_schedule,
        canonical_reads
            .as_mut()
            .expect("read dispatcher is present"),
        &writer_senders,
        &mut request_receiver,
        &mut dispatch_receiver,
        &mut runtime,
        workload,
        &mut metrics,
    )
    .await;
    let workload_interval_result = flush_interval(duration_nanos, &mut metrics);
    if load_result.is_err() || workload_interval_result.is_err() {
        cancellation.cancel();
    }
    let drain_started = Instant::now();
    writer_stop.cancel();
    drop(writer_senders);
    drop(request_receiver);

    let pump_result = join_writer_pumps(
        person_task,
        distinct_id_task,
        merge_task,
        &mut dispatch_receiver,
        &mut runtime,
        &mut metrics.collector,
        workload,
    )
    .await;
    let (dispatchers, pump_error) = match pump_result {
        Ok((person_upserts, distinct_id_assignments, merges)) => (
            Some(ExecutorDispatchers {
                person_upserts,
                distinct_id_assignments,
                merges,
                canonical_reads: canonical_reads.take().expect("read dispatcher is present"),
            }),
            None,
        ),
        Err(error) => {
            cancellation.cancel();
            drop(canonical_reads.take());
            (None, Some(error))
        }
    };
    // Releasing every dispatcher is what lets the workers finish; on the pump's error
    // path they are already gone, so this is a no-op there.
    drop(dispatchers);
    let drain_result = runtime
        .drain(|completion| record_completion(&mut metrics.collector, workload, completion))
        .await;
    let drain_duration = drain_started.elapsed();
    sampler_cancellation.cancel();
    let sampler_result = sampler_task.await.context("join PostgreSQL sampler task");
    let pg_sample_result = drain_pg_samples(&mut metrics);

    load_result?;
    workload_interval_result?;
    if let Some(error) = pump_error {
        return Err(error);
    }
    sampler_result?;
    pg_sample_result?;
    drain_result?;
    workload.tracker.ensure_empty()?;
    finish_phase(
        phase,
        PhaseTimings {
            pre_hook: pre_hook_duration,
            drain: drain_duration,
        },
        clock,
        metrics,
    )
}

fn benchmark_database_url() -> anyhow::Result<String> {
    std::env::var("FLAGS_READ_STORE_DATABASE_URL").map_err(|_| {
        anyhow::anyhow!("FLAGS_READ_STORE_DATABASE_URL must be set for benchmark mode")
    })
}

fn benchmark_pool(database_url: &str, config: &ExecutorConfig) -> anyhow::Result<PgPool> {
    let worker_connections = config
        .read_workers
        .get()
        .saturating_add(config.merge_workers.get())
        .saturating_add(config.person_batch_workers.get())
        .saturating_add(config.distinct_id_batch_workers.get());
    let max_connections = u32::try_from(worker_connections.saturating_add(4))
        .context("worker count exceeds PostgreSQL pool limit")?;
    Ok(get_pool_with_config(
        database_url,
        PoolConfig {
            max_connections,
            min_connections: 2,
            acquire_timeout: Duration::from_secs(30),
            ..Default::default()
        },
    )?)
}

fn ensure_output_parent(path: &Path) -> anyhow::Result<()> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("create output directory {}", parent.display()))?;
    }
    Ok(())
}

async fn load_postgres_settings(pool: &PgPool) -> anyhow::Result<Vec<(String, String)>> {
    let mut settings = Vec::new();
    for name in [
        "server_version",
        "max_connections",
        "shared_buffers",
        "work_mem",
        "maintenance_work_mem",
        "effective_cache_size",
        "max_wal_size",
        "checkpoint_timeout",
        "autovacuum",
        "autovacuum_naptime",
        "autovacuum_max_workers",
    ] {
        let value: String = sqlx::query_scalar("SELECT current_setting($1)")
            .bind(name)
            .fetch_one(pool)
            .await
            .with_context(|| format!("read PostgreSQL setting {name}"))?;
        settings.push((name.to_owned(), value));
    }
    Ok(settings)
}

fn adjusted_open_rates(
    phase: &PhaseSpec,
    creation_percent: u8,
) -> anyhow::Result<[RateSpec; OpClass::COUNT]> {
    let mut rates = phase.rates;
    if phase.name == rates::PhaseName::CatchUp || creation_percent == 0 {
        return Ok(rates);
    }
    let creation_rate =
        rates[OpClass::PersonUpsert.index()].target.get() * f64::from(creation_percent) / 100.0;
    let distinct_id = &mut rates[OpClass::DistinctIdAssignment.index()];
    anyhow::ensure!(
        distinct_id.target.get() >= creation_rate,
        "creation rate {creation_rate:.1}/s exceeds distinct ID target {:.1}/s in {}",
        distinct_id.target.get(),
        phase.name.as_str()
    );
    distinct_id.target = RatePerSecond::new(distinct_id.target.get() - creation_rate);
    Ok(rates)
}

fn projected_growth(args: &BenchmarkArgs, phases: &[PhaseSpec]) -> anyhow::Result<WorldGrowth> {
    let mut person_creations = 0.0;
    let mut distinct_id_assignments = 0.0;
    let fresh_fraction = 1.0 - f64::from(args.stale_replay_percent) / 100.0;
    for phase in phases {
        // Catch-up mutates existing entities so its closed feeds stay memory-bounded.
        if phase.name == rates::PhaseName::CatchUp {
            continue;
        }
        let duration = phase.duration.as_secs_f64();
        let rates = adjusted_open_rates(phase, args.creation_percent)?;
        person_creations += phase.rate_for(OpClass::PersonUpsert).target.get()
            * f64::from(args.creation_percent)
            / 100.0
            * duration;
        distinct_id_assignments +=
            rates[OpClass::DistinctIdAssignment.index()].target.get() * fresh_fraction * duration;
    }
    Ok(WorldGrowth::new(
        PersonCreationCount::new(with_preflight_headroom(person_creations)),
        world::DistinctIdAssignmentCount::new(with_preflight_headroom(distinct_id_assignments)),
    ))
}

fn with_preflight_headroom(value: f64) -> u64 {
    (value * GROWTH_PREFLIGHT_HEADROOM)
        .ceil()
        .min(u64::MAX as f64) as u64
}

fn bytes_mib(bytes: u64) -> f64 {
    bytes as f64 / (1024.0 * 1024.0)
}

fn enforce_gate_result(
    profile: BenchmarkProfile,
    gates: &GateEvaluation,
    output: &Path,
) -> anyhow::Result<()> {
    if profile == BenchmarkProfile::Gate && !gates.passed {
        anyhow::bail!("benchmark gate failed; see {}", output.display());
    }
    Ok(())
}

async fn drive_open_load(
    clock: &PhaseClock,
    duration: Duration,
    schedule: &mut ArrivalSchedule,
    ingress: &mut ExecutorIngress,
    runtime: &mut ExecutorRuntime,
    workload: &mut WorkloadContext<'_>,
    metrics: &mut PhaseMetrics<'_>,
) -> anyhow::Result<()> {
    let deadline = tokio::time::Instant::now() + duration;
    let mut interval = tokio::time::interval_at(
        tokio::time::Instant::now() + Duration::from_secs(collector::DEFAULT_INTERVAL_SECS),
        Duration::from_secs(collector::DEFAULT_INTERVAL_SECS),
    );
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        let next_arrival = schedule.peek_next_at();
        tokio::select! {
            () = tokio::time::sleep_until(deadline) => break,
            completion = runtime.completion_receiver_mut().recv() => {
                let completion = completion.context("executor completion stream closed during phase")?;
                record_completion(&mut metrics.collector, workload, completion)?;
            }
            result = wait_for_arrival(clock, next_arrival) => {
                result?;
                let now = clock.now()?;
                while let Some(arrival) = schedule.pop_due(now)? {
                    let operations =
                        resolve_arrival(workload, arrival.class, arrival.scheduled_at, true)?;
                    for operation in operations {
                        dispatch_open(clock, ingress, workload, &mut metrics.collector, operation)?;
                    }
                }
            }
            _ = interval.tick() => {
                flush_interval(
                    clock.now()?.as_nanos().min(duration_as_nanos(duration)),
                    metrics,
                )?;
            }
            sample = metrics.pg_receiver.recv() => {
                let sample = sample.context("PostgreSQL sampler stopped during phase")?;
                record_pg_sample(sample, metrics)?;
            }
        }
    }
    Ok(())
}

#[derive(Debug)]
struct WriterOperationSenders {
    person: mpsc::Sender<OpDescriptor>,
    distinct_id: mpsc::Sender<OpDescriptor>,
    merge: mpsc::Sender<OpDescriptor>,
}

impl WriterOperationSenders {
    async fn send(&self, class: OpClass, operation: OpDescriptor) -> anyhow::Result<()> {
        let sender = match class {
            OpClass::PersonUpsert => &self.person,
            OpClass::DistinctIdAssignment => &self.distinct_id,
            OpClass::Merge => &self.merge,
            OpClass::CanonicalRead => anyhow::bail!("canonical reads cannot use a writer pump"),
        };
        sender
            .send(operation)
            .await
            .map_err(|_| anyhow::anyhow!("{:?} writer pump stopped", class))
    }
}

fn spawn_writer_pump(
    class: OpClass,
    dispatcher: BoundedDispatcher,
    mut operation_receiver: mpsc::Receiver<OpDescriptor>,
    request_sender: mpsc::Sender<OpClass>,
    dispatch_sender: mpsc::Sender<DispatchRecord>,
    clock: PhaseClock,
    stop: CancellationToken,
) -> JoinHandle<anyhow::Result<BoundedDispatcher>> {
    tokio::spawn(async move {
        loop {
            tokio::select! {
                biased;
                () = stop.cancelled() => break,
                result = request_sender.send(class) => {
                    if result.is_err() {
                        break;
                    }
                }
            }
            let Some(operation) = operation_receiver.recv().await else {
                break;
            };
            let dispatch = dispatcher
                .dispatch_with_backpressure(operation, &clock)
                .await?;
            if dispatch_sender.send(dispatch).await.is_err() {
                break;
            }
        }
        Ok(dispatcher)
    })
}

#[allow(clippy::too_many_arguments)]
async fn drive_catch_up_load(
    clock: &PhaseClock,
    duration: Duration,
    read_schedule: &mut ArrivalSchedule,
    read_dispatcher: &mut BoundedDispatcher,
    writer_senders: &WriterOperationSenders,
    request_receiver: &mut mpsc::Receiver<OpClass>,
    dispatch_receiver: &mut mpsc::Receiver<DispatchRecord>,
    runtime: &mut ExecutorRuntime,
    workload: &mut WorkloadContext<'_>,
    metrics: &mut PhaseMetrics<'_>,
) -> anyhow::Result<()> {
    let deadline = tokio::time::Instant::now() + duration;
    let mut interval = tokio::time::interval_at(
        tokio::time::Instant::now() + Duration::from_secs(collector::DEFAULT_INTERVAL_SECS),
        Duration::from_secs(collector::DEFAULT_INTERVAL_SECS),
    );
    interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        let next_read = read_schedule.peek_next_at();
        tokio::select! {
            () = tokio::time::sleep_until(deadline) => break,
            completion = runtime.completion_receiver_mut().recv() => {
                let completion = completion.context("executor completion stream closed during catch-up")?;
                record_completion(&mut metrics.collector, workload, completion)?;
            }
            result = wait_for_arrival(clock, next_read) => {
                result?;
                let now = clock.now()?;
                while let Some(arrival) = read_schedule.pop_due(now)? {
                    anyhow::ensure!(arrival.class == OpClass::CanonicalRead, "closed writer entered the open arrival schedule");
                    let operations =
                        resolve_arrival(workload, arrival.class, arrival.scheduled_at, false)?;
                    for operation in operations {
                        dispatch_bounded(
                            clock,
                            read_dispatcher,
                            workload,
                            &mut metrics.collector,
                            operation,
                        )?;
                    }
                }
            }
            request = request_receiver.recv() => {
                let class = request.context("all catch-up writer pumps stopped")?;
                let scheduled_at = clock.now()?;
                let operations = resolve_arrival(workload, class, scheduled_at, false)?;
                anyhow::ensure!(operations.len() == 1, "catch-up writer generated a paired operation");
                writer_senders
                    .send(
                        class,
                        operations
                            .into_iter()
                            .next()
                            .expect("one catch-up operation"),
                    )
                    .await?;
            }
            dispatch = dispatch_receiver.recv() => {
                let dispatch = dispatch.context("all catch-up dispatch streams stopped")?;
                record_dispatch(&mut metrics.collector, workload, dispatch)?;
            }
            _ = interval.tick() => {
                flush_interval(
                    clock.now()?.as_nanos().min(duration_as_nanos(duration)),
                    metrics,
                )?;
            }
            sample = metrics.pg_receiver.recv() => {
                let sample = sample.context("PostgreSQL sampler stopped during catch-up")?;
                record_pg_sample(sample, metrics)?;
            }
        }
    }
    Ok(())
}

async fn join_writer_pumps(
    person_task: JoinHandle<anyhow::Result<BoundedDispatcher>>,
    distinct_id_task: JoinHandle<anyhow::Result<BoundedDispatcher>>,
    merge_task: JoinHandle<anyhow::Result<BoundedDispatcher>>,
    dispatch_receiver: &mut mpsc::Receiver<DispatchRecord>,
    runtime: &mut ExecutorRuntime,
    collector: &mut PhaseCollector,
    workload: &mut WorkloadContext<'_>,
) -> anyhow::Result<(BoundedDispatcher, BoundedDispatcher, BoundedDispatcher)> {
    let joins = async move {
        let (person, distinct_id, merge) = tokio::join!(person_task, distinct_id_task, merge_task);
        Ok::<_, anyhow::Error>((
            person.context("join person writer pump")??,
            distinct_id.context("join distinct ID writer pump")??,
            merge.context("join merge writer pump")??,
        ))
    };
    tokio::pin!(joins);
    let mut first_error = None;
    let dispatchers = loop {
        tokio::select! {
            result = &mut joins => break result?,
            completion = runtime.completion_receiver_mut().recv() => {
                if let Some(completion) = completion {
                    if let Err(error) = record_completion(collector, workload, completion) {
                        first_error.get_or_insert(error);
                    }
                }
            }
            dispatch = dispatch_receiver.recv() => {
                if let Some(dispatch) = dispatch {
                    if let Err(error) = record_dispatch(collector, workload, dispatch) {
                        first_error.get_or_insert(error);
                    }
                }
            }
        }
    };
    while let Ok(dispatch) = dispatch_receiver.try_recv() {
        if let Err(error) = record_dispatch(collector, workload, dispatch) {
            first_error.get_or_insert(error);
        }
    }
    match first_error {
        Some(error) => Err(error),
        None => Ok(dispatchers),
    }
}

async fn wait_for_arrival(
    clock: &PhaseClock,
    next_arrival: Option<ops::NanosSincePhaseStart>,
) -> anyhow::Result<()> {
    match next_arrival {
        Some(next_arrival) => clock.wait_until(next_arrival).await.map_err(Into::into),
        None => std::future::pending().await,
    }
}

fn dispatch_open(
    clock: &PhaseClock,
    ingress: &mut ExecutorIngress,
    workload: &mut WorkloadContext<'_>,
    collector: &mut PhaseCollector,
    operation: OpDescriptor,
) -> anyhow::Result<()> {
    let class = operation.class();
    let dispatch = ingress
        .dispatcher_mut(class)
        .try_dispatch_at(operation, clock.now()?)?;
    record_dispatch(collector, workload, dispatch)
}

fn dispatch_bounded(
    clock: &PhaseClock,
    dispatcher: &mut BoundedDispatcher,
    workload: &mut WorkloadContext<'_>,
    collector: &mut PhaseCollector,
    operation: OpDescriptor,
) -> anyhow::Result<()> {
    let dispatch = dispatcher.try_dispatch_at(operation, clock.now()?)?;
    record_dispatch(collector, workload, dispatch)
}

fn record_dispatch(
    collector: &mut PhaseCollector,
    workload: &mut WorkloadContext<'_>,
    dispatch: DispatchRecord,
) -> anyhow::Result<()> {
    collector.record_dispatch(dispatch)?;
    if dispatch.outcome != DispatchOutcome::Enqueued {
        workload.tracker.record_failed_dispatch(
            workload.world,
            dispatch.operation_id,
            dispatch.outcome,
        )?;
    }
    Ok(())
}

fn resolve_arrival(
    workload: &mut WorkloadContext<'_>,
    class: OpClass,
    scheduled_at: ops::NanosSincePhaseStart,
    allow_creation: bool,
) -> anyhow::Result<ResolvedOperations> {
    let WorkloadContext {
        world,
        rng,
        growth,
        world_config,
        memory_limit,
        args,
        tracker,
    } = workload;
    let memory_limit = *memory_limit;
    let mut grew = false;
    let operations = match class {
        OpClass::PersonUpsert if allow_creation && chance(rng, args.creation_percent) => {
            let creation = world.resolve_creation(scheduled_at)?;
            tracker.register_creation(
                creation.activation,
                creation.person_upsert.operation_id,
                creation.distinct_id_assignment.operation_id,
            )?;
            growth.creation();
            grew = true;
            ResolvedOperations::Pair(creation.person_upsert, creation.distinct_id_assignment)
        }
        OpClass::PersonUpsert => {
            let replay = if chance(rng, args.stale_replay_percent) {
                ReplayMode::Stale
            } else {
                ReplayMode::Fresh
            };
            ResolvedOperations::One(world.resolve_person_upsert(scheduled_at, replay)?)
        }
        OpClass::DistinctIdAssignment => {
            let mode = if chance(rng, args.stale_replay_percent) {
                AssignmentMode::StaleReplay
            } else if allow_creation {
                AssignmentMode::New
            } else {
                AssignmentMode::FreshExisting
            };
            let assignment = world.resolve_distinct_id_assignment(scheduled_at, mode)?;
            if let Some(token) = assignment.activation {
                tracker.register_distinct_id(assignment.operation.operation_id, token)?;
                growth.distinct_id();
                grew = true;
            }
            ResolvedOperations::One(assignment.operation)
        }
        OpClass::Merge => {
            let operation = if chance(rng, args.whale_merge_percent) {
                match world.resolve_whale_merge(scheduled_at) {
                    Ok(operation) => operation,
                    Err(WorldError::NoEligiblePerson) => world.resolve_full_merge(scheduled_at)?,
                    Err(error) => return Err(error.into()),
                }
            } else {
                world.resolve_full_merge(scheduled_at)?
            };
            ResolvedOperations::One(operation)
        }
        OpClass::CanonicalRead => {
            let mode = if chance(rng, args.read_miss_percent) {
                ReadMode::Miss
            } else {
                ReadMode::Hit
            };
            ResolvedOperations::One(world.resolve_read(scheduled_at, mode)?)
        }
    };
    if grew {
        ensure_runtime_memory(world_config, growth, memory_limit)?;
    }
    Ok(operations)
}

#[derive(Debug)]
enum ResolvedOperations {
    One(OpDescriptor),
    Pair(OpDescriptor, OpDescriptor),
}

impl ResolvedOperations {
    const fn len(&self) -> usize {
        match self {
            Self::One(_) => 1,
            Self::Pair(_, _) => 2,
        }
    }
}

impl IntoIterator for ResolvedOperations {
    type Item = OpDescriptor;
    type IntoIter = std::iter::Flatten<std::array::IntoIter<Option<OpDescriptor>, 2>>;

    fn into_iter(self) -> Self::IntoIter {
        match self {
            Self::One(operation) => [Some(operation), None],
            Self::Pair(first, second) => [Some(first), Some(second)],
        }
        .into_iter()
        .flatten()
    }
}

fn chance(rng: &mut impl Rng, percent: u8) -> bool {
    rng.gen_ratio(u32::from(percent), 100)
}

fn ensure_runtime_memory(
    world_config: &WorldConfig,
    growth: &RuntimeGrowth,
    memory_limit: u64,
) -> anyhow::Result<()> {
    let estimate = WorldState::estimate_memory(world_config, growth.as_world_growth())?;
    anyhow::ensure!(
        estimate.total_bytes <= memory_limit,
        "world state reached {:.1} MiB, above the configured limit {:.1} MiB",
        bytes_mib(estimate.total_bytes),
        bytes_mib(memory_limit)
    );
    Ok(())
}

fn record_completion(
    collector: &mut PhaseCollector,
    workload: &mut WorkloadContext<'_>,
    completion: CompletionRecord,
) -> anyhow::Result<()> {
    collector.record_completion(&completion)?;
    workload
        .tracker
        .record_completion(workload.world, &completion)
}

async fn run_pre_hooks(
    store: &StoreHandles<'_>,
    phase_id: PhaseId,
    hooks: &[Hook],
    sink: &mut JsonlSink,
) -> anyhow::Result<(Duration, Vec<PgDeltaRecord>)> {
    let (database_url, pool) = (store.database_url, store.pool);
    let started = Instant::now();
    let mut records = Vec::new();
    for hook in hooks {
        match hook {
            Hook::Vacuum => {
                let sampler = PgSampler::connect(database_url, phase_id).await?;
                let before = sampler.sample().await?;
                population::vacuum_analyze_checkpoint(pool).await?;
                let after = sampler.sample().await?;
                let record = pg_sampler::delta(&before, &after)?;
                sink.write(&record)?;
                records.push(record);
                sampler.close().await;
            }
        }
    }
    Ok((started.elapsed(), records))
}

type PgSample = PgDeltaRecord;

fn spawn_pg_sampler(
    database_url: String,
    phase_id: PhaseId,
) -> (CancellationToken, mpsc::Receiver<PgSample>, JoinHandle<()>) {
    let cancellation = CancellationToken::new();
    let task_cancellation = cancellation.clone();
    let (sender, receiver) = mpsc::channel(1_024);
    let task = tokio::spawn(async move {
        let mut sampler = match PgSampler::connect(&database_url, phase_id).await {
            Ok(sampler) => sampler,
            Err(error) => {
                tracing::warn!(
                    error = %error,
                    phase_id = phase_id.get(),
                    "PostgreSQL sampler unavailable for benchmark phase"
                );
                task_cancellation.cancelled().await;
                return;
            }
        };
        if !sample_pg_delta(&mut sampler, &sender, phase_id).await {
            sampler.close().await;
            return;
        }
        let mut interval = tokio::time::interval(PG_SAMPLE_INTERVAL);
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        interval.tick().await;
        loop {
            tokio::select! {
                () = task_cancellation.cancelled() => {
                    sample_pg_delta(&mut sampler, &sender, phase_id).await;
                    break;
                }
                _ = interval.tick() => {
                    if !sample_pg_delta(&mut sampler, &sender, phase_id).await {
                        break;
                    }
                }
            }
        }
        sampler.close().await;
    });
    (cancellation, receiver, task)
}

async fn sample_pg_delta(
    sampler: &mut PgSampler,
    sender: &mpsc::Sender<PgSample>,
    phase_id: PhaseId,
) -> bool {
    match sampler.sample_delta().await {
        Ok(Some(record)) => try_send_pg_sample(sender, record, phase_id),
        Ok(None) => true,
        Err(error) => {
            tracing::warn!(
                error = %error,
                phase_id = phase_id.get(),
                "PostgreSQL benchmark sample failed"
            );
            true
        }
    }
}

fn try_send_pg_sample(
    sender: &mpsc::Sender<PgSample>,
    sample: PgSample,
    phase_id: PhaseId,
) -> bool {
    match sender.try_send(sample) {
        Ok(()) => true,
        Err(mpsc::error::TrySendError::Closed(_)) => false,
        Err(mpsc::error::TrySendError::Full(_)) => {
            tracing::warn!(
                phase_id = phase_id.get(),
                "PostgreSQL benchmark sample dropped because the channel is full"
            );
            true
        }
    }
}

fn drain_pg_samples(metrics: &mut PhaseMetrics<'_>) -> anyhow::Result<()> {
    while let Ok(sample) = metrics.pg_receiver.try_recv() {
        record_pg_sample(sample, metrics)?;
    }
    Ok(())
}

fn record_pg_sample(sample: PgSample, metrics: &mut PhaseMetrics<'_>) -> anyhow::Result<()> {
    metrics.sink.write(&sample)?;
    metrics.pg_records.push(sample);
    Ok(())
}

fn finish_phase(
    phase: &PhaseSpec,
    timings: PhaseTimings,
    clock: PhaseClock,
    mut metrics: PhaseMetrics<'_>,
) -> anyhow::Result<PhaseResult> {
    let ended_at = clock.now()?.as_nanos();
    flush_interval(ended_at, &mut metrics)?;
    let duration_nanos = duration_as_nanos(phase.duration);
    let post_deadline_duration_nanos = ended_at.saturating_sub(duration_nanos);
    let summary = metrics.collector.finish_phase(
        duration_nanos,
        duration_as_nanos(timings.drain),
        post_deadline_duration_nanos,
    );
    metrics.sink.write(&summary)?;
    Ok(PhaseResult {
        name: phase.name,
        duration: phase.duration,
        pre_hook_duration: timings.pre_hook,
        targets: phase.rates,
        summary,
        intervals: metrics.intervals,
        pg: metrics.pg_records,
    })
}

fn flush_interval(ended_at_nanos: u64, metrics: &mut PhaseMetrics<'_>) -> anyhow::Result<()> {
    let last_interval_end = metrics
        .intervals
        .last()
        .map_or(0, |interval| interval.ended_at_nanos);
    if ended_at_nanos <= last_interval_end {
        return Ok(());
    }
    let interval = metrics.collector.finish_interval(ended_at_nanos);
    metrics.sink.write(&interval)?;
    metrics.intervals.push(interval);
    Ok(())
}

fn duration_as_nanos(duration: Duration) -> u64 {
    u64::try_from(duration.as_nanos()).unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::benchmark::ops::{CompletionTimestamps, NanosSincePhaseStart};

    fn success(operation_id: OperationId, class: OpClass) -> CompletionRecord {
        let at = NanosSincePhaseStart::from_nanos(PhaseId::new(1), 0);
        CompletionRecord {
            operation_id,
            class,
            timestamps: CompletionTimestamps::try_new(at, at, at, at).expect("ordered timestamps"),
            outcome: CompletionOutcome::Success,
            retry_affected: false,
            deadlock_affected: false,
            retry_attempts: 0,
            deadlock_attempts: 0,
        }
    }

    #[test]
    fn paired_creation_rate_preserves_the_total_distinct_id_target() {
        let phase = standard_phases(BenchmarkProfile::Gate, None)
            .into_iter()
            .find(|phase| phase.name == rates::PhaseName::PeakMix)
            .expect("peak phase");
        let adjusted = adjusted_open_rates(&phase, 5).expect("valid paired rate");
        let paired_rate = phase.rate_for(OpClass::PersonUpsert).target.get() * 0.05;

        assert_eq!(
            adjusted[OpClass::DistinctIdAssignment.index()].target.get() + paired_rate,
            phase.rate_for(OpClass::DistinctIdAssignment).target.get()
        );
    }

    #[test]
    fn creation_tracker_activates_only_after_both_successes() {
        let mut world = WorldState::new(WorldConfig {
            team_count: 1,
            initial_person_count: 2,
            ..WorldConfig::default()
        })
        .expect("world");
        let before = world.live_person_count();
        let scheduled_at = NanosSincePhaseStart::from_nanos(PhaseId::new(1), 0);
        let creation = world.resolve_creation(scheduled_at).expect("creation");
        let person_id = creation.person_upsert.operation_id;
        let distinct_id = creation.distinct_id_assignment.operation_id;
        let mut tracker = ActivationTracker::default();
        tracker
            .register_creation(creation.activation, person_id, distinct_id)
            .expect("pending creation");

        tracker
            .record_completion(&mut world, &success(person_id, OpClass::PersonUpsert))
            .expect("first half");
        assert_eq!(world.live_person_count(), before);

        tracker
            .record_completion(
                &mut world,
                &success(distinct_id, OpClass::DistinctIdAssignment),
            )
            .expect("second half");
        assert_eq!(world.live_person_count(), before + 1);
        tracker.ensure_empty().expect("all activations resolved");
    }

    #[test]
    fn smoke_reports_failed_gates_but_gate_profile_returns_an_error() {
        let evaluation = GateEvaluation {
            passed: false,
            harness_limited: true,
            checks: Vec::new(),
            unverified_qualifications: Vec::new(),
        };
        let output = Path::new("tmp/result.jsonl");

        enforce_gate_result(BenchmarkProfile::Smoke, &evaluation, output)
            .expect("smoke remains diagnostic");
        assert!(enforce_gate_result(BenchmarkProfile::Gate, &evaluation, output).is_err());
    }
}
