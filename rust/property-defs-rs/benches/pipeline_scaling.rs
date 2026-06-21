//! Pipeline parallelism benchmark. The service funnels all post-decompose work (dedup, sort,
//! batch shaping) through a single consumer task, which is a prime suspect for "6 CPUs but only
//! ~1 used". This measures the alternative: deterministically route each event by hash(team,
//! event) to one of N independent workers, each with its OWN cache doing the full CPU pipeline
//! (deserialize -> into_updates -> dedup -> sort/dedup batches). It reports throughput scaling
//! vs worker count, and how much dedup the sharding costs (updates that survive each worker's
//! cache; should stay ~flat if routing keeps a key on one worker).
//!
//! Run: cargo bench -p property-defs-rs --bench pipeline_scaling
//! Tune: PROPDEFS_BENCH_EVENTS, PROPDEFS_BENCH_TEAMS, PROPDEFS_BENCH_SEED

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::hint::black_box;
use std::thread;
use std::time::Instant;

use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use serde_json::{json, Map, Value};

use property_defs_rs::types::{Event, Update};
use property_defs_rs::update_cache::Cache;

const CAP: usize = 2_000_000;

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

const COMMON_EVENTS: [&str; 4] = ["$pageview", "$autocapture", "$pageleave", "$identify"];
const COMMON_KEYS: [&str; 8] = [
    "$current_url", "$browser", "$os", "$device_type", "utm_source", "$referrer", "$session_id",
    "$lib_version",
];

// (team_id, event_name, raw_json) tuples, so we can route by (team, event) without reparsing.
fn gen_events(num_events: usize, num_teams: usize, seed: u64) -> Vec<(i32, String, String)> {
    let mut rng = StdRng::seed_from_u64(seed);

    // Per-team stable schemas: (event_name -> prop keys).
    let mut team_events: Vec<Vec<(String, Vec<String>)>> = Vec::with_capacity(num_teams);
    for t in 0..num_teams {
        let mut evs: Vec<(String, Vec<String>)> = Vec::new();
        for e in COMMON_EVENTS {
            let n = rng.gen_range(5..=COMMON_KEYS.len());
            let mut keys: Vec<String> = COMMON_KEYS.iter().take(n).map(|k| k.to_string()).collect();
            for c in 0..rng.gen_range(4..20) {
                keys.push(format!("prop_{c}"));
            }
            evs.push((e.to_string(), keys));
        }
        for c in 0..rng.gen_range(3..10) {
            let keys: Vec<String> = (0..rng.gen_range(5..25)).map(|i| format!("p{i}")).collect();
            evs.push((format!("custom_{t}_{c}"), keys));
        }
        team_events.push(evs);
    }

    let total_weight: f64 = (0..num_teams).map(|t| 1.0 / (t + 1) as f64).sum();
    let mut out = Vec::with_capacity(num_events);
    for _ in 0..num_events {
        // Zipfian team pick.
        let mut r = rng.gen_range(0.0..total_weight);
        let mut team = num_teams - 1;
        for t in 0..num_teams {
            r -= 1.0 / (t + 1) as f64;
            if r < 0.0 {
                team = t;
                break;
            }
        }
        let evs = &team_events[team];
        let (event, keys) = &evs[rng.gen_range(0..evs.len())];

        let mut props = Map::new();
        for k in keys {
            props.insert(k.clone(), json!(format!("v{}", rng.gen_range(0..50))));
        }
        let payload = json!({
            "team_id": (team as i32) + 1,
            "project_id": (team as i64) + 1,
            "event": event,
            "properties": Value::Object(props).to_string(),
        });
        out.push(((team as i32) + 1, event.clone(), payload.to_string()));
    }
    out
}

#[derive(Clone, Copy)]
enum RouteBy {
    RoundRobin, // no key affinity (current multi-pod reality): same key hits many workers
    Team,       // all of a team's updates on one worker: perfect dedup, but Zipfian imbalance
    TeamEvent,  // balanced, but splits a property's PropertyDefinition across events
}

fn route(by: RouteBy, idx: usize, team: i32, event: &str, n: usize) -> usize {
    if n == 1 {
        return 0;
    }
    match by {
        RouteBy::RoundRobin => idx % n,
        _ => {
            let mut h = DefaultHasher::new();
            team.hash(&mut h);
            if let RouteBy::TeamEvent = by {
                event.hash(&mut h);
            }
            (h.finish() as usize) % n
        }
    }
}

// One worker's full CPU pipeline over its shard. Returns updates that survived its cache.
fn process_shard(shard: &[&str]) -> u64 {
    let cache = Cache::new(CAP, CAP, CAP);
    let mut passed = 0u64;
    let mut batch: Vec<Update> = Vec::with_capacity(1000);
    for raw in shard {
        let ev: Event = serde_json::from_str(raw).expect("valid event");
        for u in ev.into_updates(10_000) {
            if !cache.contains_key(&u) {
                cache.insert(u.clone());
                batch.push(u);
                passed += 1;
            }
        }
        if batch.len() >= 1000 {
            // model the consumer's per-batch CPU work
            batch.sort_unstable();
            batch.dedup();
            black_box(&batch);
            batch.clear();
        }
    }
    batch.sort_unstable();
    batch.dedup();
    black_box(&batch);
    passed
}

// Returns (events_per_sec, total_passed_updates).
fn run(events: &[(i32, String, String)], by: RouteBy, n: usize) -> (f64, u64) {
    let mut shards: Vec<Vec<&str>> = vec![Vec::new(); n];
    for (idx, (team, event, raw)) in events.iter().enumerate() {
        shards[route(by, idx, *team, event, n)].push(raw.as_str());
    }

    let start = Instant::now();
    let passed: u64 = thread::scope(|s| {
        let handles: Vec<_> = shards
            .iter()
            .map(|shard| s.spawn(move || process_shard(shard)))
            .collect();
        handles.into_iter().map(|h| h.join().unwrap()).sum()
    });
    let elapsed = start.elapsed();
    (events.len() as f64 / elapsed.as_secs_f64(), passed)
}

fn main() {
    let cores = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1);
    let num_events = env_usize("PROPDEFS_BENCH_EVENTS", 200_000);
    let num_teams = env_usize("PROPDEFS_BENCH_TEAMS", 50);
    let seed = env_usize("PROPDEFS_BENCH_SEED", 42) as u64;

    eprintln!("generating {num_events} events, {num_teams} teams (cores={cores})...");
    let events = gen_events(num_events, num_teams, seed);

    let worker_counts: Vec<usize> = [1, 2, 4, 6, 8].into_iter().filter(|&n| n <= cores.max(1) * 2).collect();

    println!("\n=== pipeline scaling: N independent workers, each a full CPU pipeline ===");
    println!("(deserialize + into_updates + dedup + sort; full DB writes excluded)");

    for (label, by) in [
        ("round-robin (current multi-pod: NO key affinity)", RouteBy::RoundRobin),
        ("route by team (perfect dedup)", RouteBy::Team),
        ("route by (team,event)", RouteBy::TeamEvent),
    ] {
        println!("\n-- {label} --");
        println!(
            "{:<9} {:>14} {:>10} {:>14} {:>16}",
            "workers", "events/sec", "scaling", "passed(=writes)", "writes_vs_1pod"
        );
        let mut base = 0.0;
        let mut base_passed = 0u64;
        for (i, &n) in worker_counts.iter().enumerate() {
            let mut best = 0.0;
            let mut passed = 0;
            for _ in 0..3 {
                let (eps, p) = run(&events, by, n);
                if eps > best {
                    best = eps;
                }
                passed = p;
            }
            if i == 0 {
                base = best;
                base_passed = passed;
            }
            println!(
                "{:<9} {:>14.0} {:>9.2}x {:>14} {:>15.3}x",
                n,
                best,
                best / base,
                passed,
                passed as f64 / base_passed as f64
            );
        }
    }
    println!(
        "\nscaling ~Nx => CPU pipeline parallelizes. writes_vs_1pod: round-robin grows to N\n\
         (N pods with no key affinity each re-issue the same inserts => (N-1)/N are fake);\n\
         routing by team keeps it at 1.0 (team_id is in every dedup key)."
    );
}
