mod client;
mod event;
mod stats;

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

use crate::client::CaptureClient;
use crate::event::{BatchPayload, EventFactory};
use crate::stats::Counters;

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

    if cli.batch_size == 0 {
        bail!("--batch-size must be > 0");
    }
    if cli.concurrency == 0 {
        bail!("--concurrency must be > 0");
    }

    let factory = Arc::new(EventFactory::new(
        cli.distinct_ids,
        cli.event_names.clone(),
        cli.prop_bytes,
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

    // Shared mode state.
    let limiter: Option<Arc<Limiter>> = cli.rate.map(|rate| {
        let local_rate = split(u64::from(rate), total, index).max(1) as u32;
        let burst = local_rate.max(cli.batch_size as u32);
        let quota = Quota::per_second(NonZeroU32::new(local_rate).unwrap())
            .allow_burst(NonZeroU32::new(burst).unwrap());
        Arc::new(RateLimiter::direct(quota))
    });
    let remaining: Option<Arc<AtomicU64>> = cli
        .count
        .map(|count| Arc::new(AtomicU64::new(split(count, total, index))));

    // Nothing to do for this shard (e.g. rate < shard count).
    if cli.rate.is_some() && split(u64::from(cli.rate.unwrap()), total, index) == 0 {
        println!("[load] shard {index}/{total} has no work (rate too low to split)");
        return Ok(());
    }
    if let Some(rem) = &remaining {
        if rem.load(Ordering::Relaxed) == 0 {
            println!("[load] shard {index}/{total} has no work (count too low to split)");
            return Ok(());
        }
    }

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

    stop.notify_one();
    reporter.await.ok();

    stats::print_summary(&counters, &merged, started.elapsed());
    Ok(())
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
