//! Cache contention benchmark for the propdefs shared `Cache`.
//!
//! Answers two questions empirically, on the real `Cache` (quick_cache under the hood):
//!   1. Does the producer hot path (contains_key, ~99.8% hits) contend across worker threads?
//!   2. Would giving each worker its own cache (the "spread events to workers" idea) help?
//!
//! Method: T threads hammer the cache with a realistic op mix and we report aggregate
//! throughput + scaling efficiency = ops_per_sec(T) / (T * ops_per_sec(1)). Efficiency ~1.0
//! means perfect scaling (no contention); well below 1.0 means lock contention. We compare a
//! shared cache (all threads, one Cache) against per-thread caches (partitioned), and also
//! show an insert-heavy run so you can see the harness *does* detect contention when it exists.
//!
//! Run: cargo bench -p property-defs-rs --bench cache_contention
//! Tune: PROPDEFS_BENCH_KEYS, PROPDEFS_BENCH_READ_OPS, PROPDEFS_BENCH_WRITE_OPS

use std::hint::black_box;
use std::sync::Arc;
use std::thread;
use std::time::Instant;

use property_defs_rs::types::{EventProperty, Update};
use property_defs_rs::update_cache::Cache;

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

const CAP: usize = 2_000_000;

fn make_key(i: usize) -> Update {
    Update::EventProperty(EventProperty {
        team_id: (i % 1000) as i32,
        project_id: (i % 1000) as i64,
        event: "evt".to_string(),
        property: format!("prop_{i}"),
    })
}

// Cheap deterministic index stream so the timed loop is dominated by the cache op, not RNG or
// allocation. xorshift64 + mask into [lo, lo+range) (range is a power of two).
#[inline(always)]
fn next_idx(state: &mut u64, lo: usize, range_mask: usize) -> usize {
    let mut x = *state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    *state = x;
    lo + (x as usize & range_mask)
}

#[derive(Clone, Copy)]
enum Mode {
    Shared,
    PerThread,
}

// Returns aggregate ops/sec across `threads`.
fn run_reads(mode: Mode, threads: usize, keys: &Arc<Vec<Update>>, ops: usize, partition: usize) -> f64 {
    let range_mask = partition - 1; // partition is a power of two
    // One shared cache, or one cache per thread (each pre-populated with its own partition).
    let caches: Vec<Arc<Cache>> = match mode {
        Mode::Shared => {
            let c = Arc::new(Cache::new(CAP, CAP, CAP));
            for k in keys.iter() {
                c.insert(k.clone());
            }
            (0..threads).map(|_| c.clone()).collect()
        }
        Mode::PerThread => (0..threads)
            .map(|t| {
                let c = Arc::new(Cache::new(CAP, CAP, CAP));
                for i in 0..partition {
                    c.insert(keys[t * partition + i].clone());
                }
                c
            })
            .collect(),
    };

    let start = Instant::now();
    thread::scope(|s| {
        for (t, cache_slot) in caches.iter().enumerate() {
            let cache = cache_slot.clone();
            let keys = keys.clone();
            // Shared+overlap: every thread roams the whole keyspace (worst case for sharing).
            // PerThread: thread t stays in its own partition [t*partition, ..).
            let lo = match mode {
                Mode::Shared => 0,
                Mode::PerThread => t * partition,
            };
            let mut state = 0x9e3779b97f4a7c15u64 ^ (t as u64).wrapping_mul(0x100000001b3);
            s.spawn(move || {
                let mut hits = 0u64;
                for _ in 0..ops {
                    let idx = next_idx(&mut state, lo, range_mask);
                    if cache.contains_key(&keys[idx]) {
                        hits += 1;
                    }
                }
                black_box(hits);
            });
        }
    });
    let elapsed = start.elapsed();
    (threads * ops) as f64 / elapsed.as_secs_f64()
}

fn run_inserts(mode: Mode, threads: usize, keys: &Arc<Vec<Update>>, ops: usize, partition: usize) -> f64 {
    let range_mask = partition - 1;
    let caches: Vec<Arc<Cache>> = match mode {
        Mode::Shared => {
            let c = Arc::new(Cache::new(CAP, CAP, CAP));
            (0..threads).map(|_| c.clone()).collect()
        }
        Mode::PerThread => (0..threads).map(|_| Arc::new(Cache::new(CAP, CAP, CAP))).collect(),
    };

    let start = Instant::now();
    thread::scope(|s| {
        for (t, cache_slot) in caches.iter().enumerate() {
            let cache = cache_slot.clone();
            let keys = keys.clone();
            let lo = match mode {
                Mode::Shared => 0,
                Mode::PerThread => t * partition,
            };
            let mut state = 0xd1b54a32d192ed03u64 ^ (t as u64).wrapping_mul(0x100000001b3);
            s.spawn(move || {
                for _ in 0..ops {
                    let idx = next_idx(&mut state, lo, range_mask);
                    cache.insert(keys[idx].clone());
                }
            });
        }
    });
    let elapsed = start.elapsed();
    (threads * ops) as f64 / elapsed.as_secs_f64()
}

// The real producer op mix: contains_key on (almost) every update, insert on the rare miss.
// `insert_every` = 100 models a 1% miss rate (prod steady-state is ~0.2%, so this is
// pessimistic — more write-lock pressure than reality).
fn run_mixed(
    mode: Mode,
    threads: usize,
    keys: &Arc<Vec<Update>>,
    ops: usize,
    partition: usize,
    insert_every: usize,
) -> f64 {
    let range_mask = partition - 1;
    let caches: Vec<Arc<Cache>> = match mode {
        Mode::Shared => {
            let c = Arc::new(Cache::new(CAP, CAP, CAP));
            for k in keys.iter() {
                c.insert(k.clone());
            }
            (0..threads).map(|_| c.clone()).collect()
        }
        Mode::PerThread => (0..threads)
            .map(|t| {
                let c = Arc::new(Cache::new(CAP, CAP, CAP));
                for i in 0..partition {
                    c.insert(keys[t * partition + i].clone());
                }
                c
            })
            .collect(),
    };

    let start = Instant::now();
    thread::scope(|s| {
        for (t, cache_slot) in caches.iter().enumerate() {
            let cache = cache_slot.clone();
            let keys = keys.clone();
            let lo = match mode {
                Mode::Shared => 0,
                Mode::PerThread => t * partition,
            };
            let mut state = 0x2545f4914f6cdd1du64 ^ (t as u64).wrapping_mul(0x100000001b3);
            s.spawn(move || {
                let mut acc = 0u64;
                for i in 0..ops {
                    let idx = next_idx(&mut state, lo, range_mask);
                    if i % insert_every == 0 {
                        cache.insert(keys[idx].clone());
                    } else if cache.contains_key(&keys[idx]) {
                        acc += 1;
                    }
                }
                black_box(acc);
            });
        }
    });
    let elapsed = start.elapsed();
    (threads * ops) as f64 / elapsed.as_secs_f64()
}

fn pow2_floor(n: usize) -> usize {
    let mut p = 1;
    while p * 2 <= n {
        p *= 2;
    }
    p
}

fn main() {
    let cores = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1);
    let keys_req = env_usize("PROPDEFS_BENCH_KEYS", 1 << 20); // 1,048,576
    let read_ops = env_usize("PROPDEFS_BENCH_READ_OPS", 20_000_000);
    let write_ops = env_usize("PROPDEFS_BENCH_WRITE_OPS", 3_000_000);

    let max_threads = 4usize.min(pow2_floor(cores).max(1));
    let thread_counts: Vec<usize> = [1, 2, 4].into_iter().filter(|&t| t <= max_threads).collect();
    // Partition must be a power of two and evenly divide the keyspace across max_threads.
    let partition = pow2_floor(keys_req / max_threads);
    let total_keys = partition * max_threads;

    let keys: Arc<Vec<Update>> = Arc::new((0..total_keys).map(make_key).collect());
    let shards = Cache::new(CAP, CAP, CAP).num_shards();

    eprintln!(
        "cores={cores}, shards/subcache={shards}, keys={total_keys}, partition/thread={partition}"
    );

    let report = |title: &str, runner: &dyn Fn(Mode, usize) -> f64| {
        println!("\n== {title} ==");
        println!("{:<8} {:>18} {:>18}", "threads", "shared (eff)", "per-thread (eff)");
        let base_shared = runner(Mode::Shared, 1);
        let base_pt = runner(Mode::PerThread, 1);
        for &t in &thread_counts {
            let sh = runner(Mode::Shared, t);
            let pt = runner(Mode::PerThread, t);
            let sh_eff = sh / (t as f64 * base_shared);
            let pt_eff = pt / (t as f64 * base_pt);
            println!(
                "{:<8} {:>11.1}M ({sh_eff:.2}) {:>11.1}M ({pt_eff:.2})",
                t,
                sh / 1e6,
                pt / 1e6
            );
        }
    };

    println!("\nEfficiency = ops/sec(T) / (T * ops/sec(1)); ~1.00 = perfect scaling / no contention.");

    report("producer mix (99% contains_key + 1% insert — the real hot loop)", &|mode, t| {
        run_mixed(mode, t, &keys, read_ops, partition, 100)
    });

    report("contains_key only (~99.8% hits in prod)", &|mode, t| {
        run_reads(mode, t, &keys, read_ops, partition)
    });

    report("insert-only (worst case: every op takes a write lock)", &|mode, t| {
        run_inserts(mode, t, &keys, write_ops, partition)
    });
}
