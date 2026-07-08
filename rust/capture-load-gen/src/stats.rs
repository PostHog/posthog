use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use hdrhistogram::Histogram;
use tokio::sync::Notify;

/// Shared, lock-free counters updated on the request hot path.
#[derive(Default)]
pub struct Counters {
    pub requests_ok: AtomicU64,
    pub requests_err: AtomicU64,
    pub events_ok: AtomicU64,
}

impl Counters {
    pub fn record(&self, ok: bool, events: u64) {
        if ok {
            self.requests_ok.fetch_add(1, Ordering::Relaxed);
            self.events_ok.fetch_add(events, Ordering::Relaxed);
        } else {
            self.requests_err.fetch_add(1, Ordering::Relaxed);
        }
    }
}

/// A per-worker latency histogram. Each worker owns one so recording never
/// contends; they are merged once at the end.
pub fn new_histogram() -> Histogram<u64> {
    // 1µs .. 60s range, 3 significant figures. Auto-resizes if exceeded.
    Histogram::new_with_bounds(1, 60_000_000, 3).expect("valid histogram bounds")
}

/// Prints a throughput line once per second until `stop` is notified.
pub async fn report_loop(counters: Arc<Counters>, stop: Arc<Notify>) {
    let mut ticker = tokio::time::interval(Duration::from_secs(1));
    ticker.tick().await; // consume the immediate first tick so we don't print 0 req/s
    let mut prev_ok = 0u64;
    let mut prev_err = 0u64;
    let mut prev_events = 0u64;

    loop {
        tokio::select! {
            _ = stop.notified() => break,
            _ = ticker.tick() => {
                let ok = counters.requests_ok.load(Ordering::Relaxed);
                let err = counters.requests_err.load(Ordering::Relaxed);
                let events = counters.events_ok.load(Ordering::Relaxed);

                println!(
                    "[load] {:>8} req/s | {:>10} events/s | ok {ok} err {err}",
                    ok + err - prev_ok - prev_err,
                    events - prev_events,
                );

                prev_ok = ok;
                prev_err = err;
                prev_events = events;
            }
        }
    }
}

/// Prints the final summary once all workers have stopped.
pub fn print_summary(counters: &Counters, latency: &Histogram<u64>, elapsed: Duration) {
    let ok = counters.requests_ok.load(Ordering::Relaxed);
    let err = counters.requests_err.load(Ordering::Relaxed);
    let events = counters.events_ok.load(Ordering::Relaxed);
    let secs = elapsed.as_secs_f64().max(f64::MIN_POSITIVE);

    println!("\n=== capture-load-gen summary ===");
    println!("duration:        {:.1}s", elapsed.as_secs_f64());
    println!("requests ok:     {ok}");
    println!("requests err:    {err}");
    println!("events ok:       {events}");
    println!("avg req/s:       {:.0}", (ok + err) as f64 / secs);
    println!("avg events/s:    {:.0}", events as f64 / secs);
    if !latency.is_empty() {
        println!(
            "latency p50:     {} ms",
            latency.value_at_quantile(0.50) / 1000
        );
        println!(
            "latency p95:     {} ms",
            latency.value_at_quantile(0.95) / 1000
        );
        println!(
            "latency p99:     {} ms",
            latency.value_at_quantile(0.99) / 1000
        );
        println!("latency max:     {} ms", latency.max() / 1000);
    }
}
