use std::num::NonZeroU32;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use clap::Parser;
use governor::clock::DefaultClock;
use governor::state::{InMemoryState, NotKeyed};
use governor::{Quota, RateLimiter};
use hdrhistogram::Histogram;
use rand::rngs::StdRng;
use rand::SeedableRng;
use tokio::sync::Notify;

use capture_load_gen::client::CaptureClient;
use capture_load_gen::event::{BatchPayload, EventFactory, TrafficMix};
use capture_load_gen::stats::{self, Counters};
use capture_load_gen::{reset, verify};

type Limiter = RateLimiter<NotKeyed, InMemoryState, DefaultClock>;

/// High-throughput load generator for the PostHog capture `/batch` endpoint.
///
/// Two modes: rate (`--rate` + `--duration`) fires at a target events/s for a
/// fixed time; count (`--count`) sends a fixed number of events then stops.
/// When sharded across pods, the rate/count is divided so the cluster total
/// matches the value you asked for.
#[derive(Parser, Debug)]
#[command(version, about)]
struct Cli {
    /// Capture base URL. The `/batch` path is appended automatically.
    #[arg(
        long,
        env = "CAPTURE_ENDPOINT",
        default_value = "http://localhost:8000"
    )]
    endpoint: String,

    /// PostHog project API token, sent as `api_key` on the batch.
    #[arg(long, env = "CAPTURE_TOKEN")]
    token: String,

    /// Target events per second (rate mode). Requires `--duration`.
    #[arg(long)]
    rate: Option<u32>,

    /// How long to run in rate mode, e.g. "3m", "90s".
    #[arg(long, value_parser = humantime::parse_duration)]
    duration: Option<Duration>,

    /// Total events to send then stop (count mode). Conflicts with `--rate`.
    #[arg(long, conflicts_with = "rate")]
    count: Option<u64>,

    /// Events per `/batch` request.
    #[arg(long, default_value_t = 100)]
    batch_size: usize,

    /// Number of concurrent in-flight requests.
    #[arg(long, default_value_t = 32)]
    concurrency: usize,

    /// Disable gzip of the request body.
    #[arg(long)]
    no_gzip: bool,

    /// Distinct-id cardinality (number of synthetic users).
    #[arg(long, default_value_t = 10_000)]
    distinct_ids: u64,

    /// Event names to pick from (repeatable).
    #[arg(
        long = "event-name",
        default_values_t = ["$pageview".to_string(), "$autocapture".to_string(), "custom_event".to_string()],
    )]
    event_names: Vec<String>,

    /// Approximate filler bytes added to each event's properties.
    #[arg(long, default_value_t = 256)]
    prop_bytes: usize,

    /// Percentage of events that are person updates (carry a `$set` payload).
    /// The `--percent-*` flags together must not exceed 100.
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u8).range(0..=100))]
    percent_person_updates: u8,

    /// Percentage of events that are attaches: an `$identify` claiming a fresh
    /// anonymous distinct id, which has no person, so it joins the pool user's.
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u8).range(0..=100))]
    percent_attaches: u8,

    /// Percentage of events spent on person merges. Each takes two events: a
    /// fresh anonymous id sends one of its own, then an `$identify` claims it,
    /// so the merge folds one person into another. Ids still unclaimed when the
    /// load ends are claimed then, on top of `--count` and after `--duration`.
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u8).range(0..=100))]
    percent_person_merges: u8,

    /// How long a seeded anonymous id waits for its `$identify`, so ingestion
    /// has usually created its person first, e.g. "10s".
    #[arg(long, value_parser = humantime::parse_duration, default_value = "10s")]
    person_merge_delay: Duration,

    /// Percentage of events that are `$merge_dangerously` between a pool user
    /// and its fixed partner; a pair already merged is a no-op.
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u8).range(0..=100))]
    percent_dangerous_merges: u8,

    /// Per-request HTTP timeout in seconds.
    #[arg(long, default_value_t = 30)]
    timeout_secs: u64,

    /// This shard's index (0-based). Defaults to $JOB_COMPLETION_INDEX, else 0.
    #[arg(long)]
    shard_index: Option<u64>,

    /// Total number of shards. Defaults to $SHARD_TOTAL, else 1.
    #[arg(long)]
    shard_total: Option<u64>,

    /// Print one sample batch as JSON and exit without sending anything.
    #[arg(long)]
    dry_run: bool,

    /// After the load, poll until the Postgres and personhog graphs agree on
    /// the team's person graph, exiting nonzero on a mismatch that outlasts the
    /// deadline. Only shard 0 verifies; --count 0 verifies without load.
    #[arg(long)]
    verify: bool,

    /// Delete the team's person rows from both graphs and exit, so a run
    /// starts clean. Requires --team-id and --database-url.
    #[arg(long)]
    reset_team: bool,

    /// Persons database URL, required by --verify and --reset-team.
    #[arg(long, env = "DATABASE_URL")]
    database_url: Option<String>,

    /// How long the graphs get to agree.
    #[arg(long, value_parser = humantime::parse_duration, default_value = "5m")]
    verify_timeout: Duration,

    /// The personhog writer's person table.
    #[arg(long, default_value = "personhog_person_tmp")]
    tmp_person_table: String,

    /// The personhog writer's distinct-id table.
    #[arg(long, default_value = "personhog_persondistinctid_tmp")]
    tmp_pdi_table: String,

    /// The team whose person graph verify compares. Its rows are the run's
    /// cohort; the workflow wipes them before the load.
    #[arg(long)]
    team_id: Option<i64>,

    /// Port serving /metrics and /_liveness while verifying.
    #[arg(long, default_value_t = 9090)]
    metrics_port: u16,
}

/// Arcs shared by every worker.
#[derive(Clone)]
struct Shared {
    client: Arc<CaptureClient>,
    factory: Arc<EventFactory>,
    counters: Arc<Counters>,
}

enum Mode {
    Rate {
        limiter: Arc<Limiter>,
        batch_n: NonZeroU32,
        deadline: tokio::time::Instant,
        batch_size: usize,
    },
    Count {
        remaining: Arc<AtomicU64>,
        batch_size: usize,
    },
}

/// Split `total` across `shards`, handing the remainder to the lowest indices
/// so the per-shard values sum back to `total`.
fn split(total: u64, shards: u64, index: u64) -> u64 {
    let base = total / shards;
    let rem = total % shards;
    base + u64::from(index < rem)
}

fn resolve_shard(cli: &Cli) -> Result<(u64, u64)> {
    let total = match cli.shard_total {
        Some(t) => t,
        None => std::env::var("SHARD_TOTAL")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(1),
    }
    .max(1);

    let index = match cli.shard_index {
        Some(i) => i,
        None => std::env::var("JOB_COMPLETION_INDEX")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(0),
    };

    if index >= total {
        bail!("shard index {index} must be < shard total {total}");
    }
    Ok((index, total))
}

/// (sends load, verifies) for this shard. A zero-share shard still verifies
/// when it is shard 0, so `--count 0 --verify` checks without sending.
fn shard_plan(
    rate_share: Option<u64>,
    count_share: Option<u64>,
    verify: bool,
    index: u64,
) -> (bool, bool) {
    let has_load = rate_share.or(count_share).unwrap_or(0) > 0;
    (has_load, verify && index == 0)
}

/// Claim up to `batch` events from the shared remaining counter (count mode).
fn claim(remaining: &AtomicU64, batch: usize) -> u64 {
    let mut cur = remaining.load(Ordering::Relaxed);
    loop {
        if cur == 0 {
            return 0;
        }
        let take = cur.min(batch as u64);
        match remaining.compare_exchange_weak(cur, cur - take, Ordering::AcqRel, Ordering::Relaxed)
        {
            Ok(_) => return take,
            Err(actual) => cur = actual,
        }
    }
}

/// Claims the anonymous ids still seeded when the load ends, so no person merge is left half done.
async fn drain_person_merges(shared: &Shared, batch_size: usize, hist: &mut Histogram<u64>) {
    let mut rng = StdRng::from_entropy();
    let (claims, wait) = shared.factory.drain_person_merges(&mut rng);
    if claims.is_empty() {
        return;
    }
    println!(
        "[load] claiming {} seeded anonymous ids in {:.1}s",
        claims.len(),
        wait.as_secs_f64()
    );
    tokio::time::sleep(wait).await;
    for batch in claims.chunks(batch_size) {
        let body = match shared.client.encode(batch) {
            Ok(body) => body,
            Err(e) => {
                tracing::warn!("encode error: {e:#}");
                shared.counters.record(false, 0);
                continue;
            }
        };
        let result = shared.client.send(body).await;
        hist.saturating_record(result.latency.as_micros() as u64);
        shared.counters.record(result.ok, batch.len() as u64);
    }
}

async fn run_worker(shared: Shared, mode: Mode) -> Histogram<u64> {
    let mut hist = stats::new_histogram();
    let mut rng = StdRng::from_entropy();

    loop {
        let take = match &mode {
            Mode::Rate {
                limiter,
                batch_n,
                deadline,
                batch_size,
            } => {
                tokio::select! {
                    biased;
                    _ = tokio::time::sleep_until(*deadline) => break,
                    res = limiter.until_n_ready(*batch_n) => {
                        if res.is_err() {
                            break;
                        }
                    }
                }
                *batch_size as u64
            }
            Mode::Count {
                remaining,
                batch_size,
            } => {
                let take = claim(remaining, *batch_size);
                if take == 0 {
                    break;
                }
                take
            }
        };

        let events = shared.factory.batch(take as usize, &mut rng);
        let body = match shared.client.encode(&events) {
            Ok(body) => body,
            Err(e) => {
                tracing::warn!("encode error: {e:#}");
                shared.counters.record(false, 0);
                continue;
            }
        };

        let result = shared.client.send(body).await;
        hist.saturating_record(result.latency.as_micros() as u64);
        shared.counters.record(result.ok, take);
    }

    hist
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    if cli.reset_team {
        return reset::reset_team(&reset_config(&cli)?).await;
    }

    if cli.batch_size == 0 {
        bail!("--batch-size must be > 0");
    }
    if cli.concurrency == 0 {
        bail!("--concurrency must be > 0");
    }
    let mix = TrafficMix {
        person_updates: cli.percent_person_updates,
        attaches: cli.percent_attaches,
        person_merges: cli.percent_person_merges,
        dangerous_merges: cli.percent_dangerous_merges,
    };
    if mix.total() > 100 {
        bail!(
            "the --percent-* flags sum to {} and must not exceed 100",
            mix.total()
        );
    }

    let factory = Arc::new(EventFactory::new(
        cli.distinct_ids,
        cli.event_names.clone(),
        cli.prop_bytes,
        mix,
        cli.person_merge_delay,
    ));

    if cli.dry_run {
        let mut rng = StdRng::from_entropy();
        let events = factory.batch(cli.batch_size, &mut rng);
        let payload = BatchPayload {
            api_key: &cli.token,
            batch: &events,
        };
        println!("{}", serde_json::to_string_pretty(&payload)?);
        return Ok(());
    }

    let (index, total) = resolve_shard(&cli)?;

    // Validate mode selection up front.
    let duration = match (cli.rate, cli.count) {
        (Some(_), Some(_)) => bail!("--rate and --count are mutually exclusive"),
        (Some(_), None) => match cli.duration {
            Some(d) => Some(d),
            None => bail!("--rate requires --duration"),
        },
        (None, Some(_)) => None,
        (None, None) => bail!("specify either --rate (+ --duration) or --count"),
    };

    let rate_share = cli.rate.map(|rate| split(u64::from(rate), total, index));
    let count_share = cli.count.map(|count| split(count, total, index));
    let (has_load, should_verify) = shard_plan(rate_share, count_share, cli.verify, index);

    // A missing verify prerequisite must fail here, not after the load.
    let verify_cfg = if should_verify {
        Some(verify_config(&cli, duration)?)
    } else {
        None
    };

    if has_load {
        let batch_n = NonZeroU32::new(cli.batch_size as u32).context("batch size too large")?;
        let client = Arc::new(CaptureClient::new(
            &cli.endpoint,
            cli.token.clone(),
            !cli.no_gzip,
            Duration::from_secs(cli.timeout_secs),
        )?);
        let counters = Arc::new(Counters::default());
        let shared = Shared {
            client,
            factory,
            counters: counters.clone(),
        };

        let limiter: Option<Arc<Limiter>> = rate_share.map(|share| {
            let local_rate = share as u32;
            let burst = local_rate.max(cli.batch_size as u32);
            let quota = Quota::per_second(NonZeroU32::new(local_rate).unwrap())
                .allow_burst(NonZeroU32::new(burst).unwrap());
            Arc::new(RateLimiter::direct(quota))
        });
        let remaining: Option<Arc<AtomicU64>> =
            count_share.map(|share| Arc::new(AtomicU64::new(share)));

        let stop = Arc::new(Notify::new());
        let reporter = tokio::spawn(stats::report_loop(counters.clone(), stop.clone()));

        let started = Instant::now();
        let deadline = duration.map(|d| tokio::time::Instant::now() + d);

        let mut handles = Vec::with_capacity(cli.concurrency);
        for _ in 0..cli.concurrency {
            let mode = match (&limiter, &remaining) {
                (Some(limiter), _) => Mode::Rate {
                    limiter: limiter.clone(),
                    batch_n,
                    deadline: deadline.expect("rate mode has deadline"),
                    batch_size: cli.batch_size,
                },
                (None, Some(remaining)) => Mode::Count {
                    remaining: remaining.clone(),
                    batch_size: cli.batch_size,
                },
                (None, None) => unreachable!("mode validated above"),
            };
            handles.push(tokio::spawn(run_worker(shared.clone(), mode)));
        }

        let mut merged = stats::new_histogram();
        for handle in handles {
            if let Ok(hist) = handle.await {
                merged.add(&hist).ok();
            }
        }
        drain_person_merges(&shared, cli.batch_size, &mut merged).await;

        stop.notify_one();
        reporter.await.ok();

        stats::print_summary(&counters, &merged, started.elapsed());
    } else {
        println!("[load] shard {index}/{total} has no work");
    }

    if let Some(cfg) = verify_cfg {
        spawn_metrics_server(cli.metrics_port);
        let verifier = verify::Verifier::connect(&cfg).await?;
        if !verifier.run(&cfg).await? {
            bail!("shadow parity verification failed");
        }
    }
    Ok(())
}

/// Serve /metrics and /_liveness so the verify gauges can be scraped.
fn spawn_metrics_server(port: u16) {
    let router = axum::Router::new().route("/_liveness", axum::routing::get(|| async { "ok" }));
    let router = common_metrics::setup_metrics_routes(router);
    let bind = format!("0.0.0.0:{port}");
    tokio::spawn(async move {
        if let Err(error) = common_metrics::serve(router, &bind).await {
            tracing::error!(%error, "metrics server failed; verification continues without gauges");
        }
    });
}

/// The verify flags as a config, failing on the one without a default. A
/// rate run's deadline is at least its own length plus the merge delay,
/// so a long run is not cut off while its last claims still land.
fn verify_config(cli: &Cli, duration: Option<Duration>) -> Result<verify::VerifyConfig> {
    let database_url = cli
        .database_url
        .clone()
        .context("--verify requires --database-url or DATABASE_URL")?;
    let team_id = cli.team_id.context("--verify requires --team-id")?;
    Ok(verify::VerifyConfig {
        database_url,
        team_id,
        tmp_person_table: cli.tmp_person_table.clone(),
        tmp_pdi_table: cli.tmp_pdi_table.clone(),
        deadline: duration.map_or(cli.verify_timeout, |run| {
            cli.verify_timeout.max(run + cli.person_merge_delay)
        }),
    })
}

fn reset_config(cli: &Cli) -> Result<reset::ResetConfig> {
    let database_url = cli
        .database_url
        .clone()
        .context("--reset-team requires --database-url or DATABASE_URL")?;
    let team_id = cli.team_id.context("--reset-team requires --team-id")?;
    Ok(reset::ResetConfig {
        database_url,
        team_id,
        tmp_person_table: cli.tmp_person_table.clone(),
        tmp_pdi_table: cli.tmp_pdi_table.clone(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn split_divides_evenly() {
        let parts: Vec<u64> = (0..10).map(|i| split(1000, 10, i)).collect();
        assert!(parts.iter().all(|&p| p == 100));
        assert_eq!(parts.iter().sum::<u64>(), 1000);
    }

    #[test]
    fn split_gives_remainder_to_low_indices() {
        let parts: Vec<u64> = (0..10).map(|i| split(1003, 10, i)).collect();
        assert_eq!(
            parts,
            vec![101, 101, 101, 100, 100, 100, 100, 100, 100, 100]
        );
        assert_eq!(parts.iter().sum::<u64>(), 1003);
    }

    #[test]
    fn split_handles_more_shards_than_work() {
        let parts: Vec<u64> = (0..10).map(|i| split(5, 10, i)).collect();
        assert_eq!(parts.iter().sum::<u64>(), 5);
        assert_eq!(parts.iter().filter(|&&p| p == 0).count(), 5);
    }

    #[test]
    fn verify_deadline_outlasts_a_long_run() {
        let cli = Cli::parse_from([
            "loadgen",
            "--token",
            "t",
            "--database-url",
            "d",
            "--team-id",
            "1",
            "--rate",
            "1",
            "--duration",
            "20m",
            "--verify-timeout",
            "5m",
            "--person-merge-delay",
            "10s",
        ]);
        let long_run = verify_config(&cli, Some(Duration::from_secs(20 * 60))).unwrap();
        assert_eq!(long_run.deadline, Duration::from_secs(20 * 60 + 10));
        let short_run = verify_config(&cli, Some(Duration::from_secs(60))).unwrap();
        assert_eq!(short_run.deadline, Duration::from_secs(5 * 60));
    }

    #[test]
    fn verify_config_requires_a_team_id() {
        let cli = Cli::parse_from([
            "loadgen",
            "--token",
            "t",
            "--database-url",
            "d",
            "--count",
            "0",
        ]);
        assert!(verify_config(&cli, None).is_err());
    }

    #[test]
    fn reset_config_requires_a_team_id() {
        let cli = Cli::parse_from([
            "loadgen",
            "--token",
            "t",
            "--database-url",
            "d",
            "--reset-team",
        ]);
        assert!(reset_config(&cli).is_err());
    }

    #[test]
    fn zero_share_shard_zero_still_verifies() {
        assert_eq!(shard_plan(None, Some(0), true, 0), (false, true));
        assert_eq!(shard_plan(Some(0), None, true, 0), (false, true));
    }

    #[test]
    fn only_shard_zero_verifies() {
        assert_eq!(shard_plan(None, Some(10), true, 3), (true, false));
        assert_eq!(shard_plan(None, Some(10), false, 0), (true, false));
    }

    #[test]
    fn claim_drains_the_counter_exactly() {
        let remaining = AtomicU64::new(250);
        let mut taken = Vec::new();
        loop {
            let n = claim(&remaining, 100);
            if n == 0 {
                break;
            }
            taken.push(n);
        }
        assert_eq!(taken, vec![100, 100, 50]);
        assert_eq!(remaining.load(Ordering::Relaxed), 0);
    }
}
