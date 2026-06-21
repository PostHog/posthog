//! Deterministic throughput + deduplication benchmark for the propdefs ingest pipeline.
//!
//! This is the optimization target for the propdefs performance loop. It measures the
//! two things we care about, on a realistic, seeded, fully in-memory workload (no Kafka,
//! Postgres, or personhog required):
//!
//!   1. THROUGHPUT  — how fast we turn raw Kafka JSON events into `Update`s
//!                    (deserialize + `Event::into_updates`), reported as events/sec.
//!   2. DEDUP       — how few DB writes we generate per event after the producer-side
//!                    compaction + shared `Cache` filter, i.e. how good we are at not
//!                    issuing "not useful" requests. Reported as the dedup ratio and as
//!                    writes-per-1k-events, split by record type.
//!
//! It also isolates the `last_seen_at`-in-key churn on event definitions (the "weird
//! timestamp entries that add little value") by replaying the stream across simulated
//! hours and comparing the real key against a `(team, name)`-only counterfactual.
//!
//! Run:   cargo bench -p property-defs-rs --bench pipeline
//! Tune:  PROPDEFS_BENCH_EVENTS, PROPDEFS_BENCH_TEAMS, PROPDEFS_BENCH_SEED,
//!        PROPDEFS_BENCH_HOURS, PROPDEFS_BENCH_CACHE_CAP, PROPDEFS_BENCH_JSON=1
//!
//! The numbers are deterministic for a fixed (events, teams, seed, cache_cap): two runs
//! on the same code produce identical dedup counts, so the loop can diff them directly.

use std::time::Instant;

use ahash::AHashSet;
use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use serde_json::{json, Map, Value};

use property_defs_rs::types::{Event, Update};
use property_defs_rs::update_cache::Cache;

// ---------------------------------------------------------------------------
// Tunables (env-overridable so the loop can sweep without recompiling)
// ---------------------------------------------------------------------------

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_flag(key: &str) -> bool {
    std::env::var(key).map(|v| v == "1" || v == "true").unwrap_or(false)
}

struct BenchConfig {
    num_events: usize,
    num_teams: usize,
    seed: u64,
    hours: usize,
    cache_cap: usize,
    emit_json: bool,
}

impl BenchConfig {
    fn from_env() -> Self {
        Self {
            num_events: env_usize("PROPDEFS_BENCH_EVENTS", 300_000),
            num_teams: env_usize("PROPDEFS_BENCH_TEAMS", 50),
            seed: env_usize("PROPDEFS_BENCH_SEED", 42) as u64,
            hours: env_usize("PROPDEFS_BENCH_HOURS", 6),
            cache_cap: env_usize("PROPDEFS_BENCH_CACHE_CAP", 1_000_000),
            emit_json: env_flag("PROPDEFS_BENCH_JSON"),
        }
    }
}

// ---------------------------------------------------------------------------
// Realistic workload model
//
// Real propdefs traffic is dominated by a handful of high-volume events whose
// property *keys* are stable across occurrences (so after the first sighting,
// almost every generated Update is a duplicate), with a long tail of custom
// events and rare genuinely-new keys ("schema drift"). We model exactly that:
//   - teams have Zipfian volume (a few big teams dominate)
//   - per (team, event) we draw a stable property-key schema once
//   - each event reuses its schema, occasionally inventing one new key
// ---------------------------------------------------------------------------

const COMMON_EVENTS: [&str; 5] = [
    "$pageview",
    "$autocapture",
    "$pageleave",
    "$identify",
    "$groupidentify",
];

// Property keys that show up on almost every web event. Mix of types so property-type
// detection (utm_/$feature/ special-casing, datetime sniffing) is exercised.
const COMMON_PROP_KEYS: [&str; 12] = [
    "$current_url",
    "$browser",
    "$os",
    "$device_type",
    "$screen_height",
    "utm_source",
    "utm_campaign",
    "$feature/new-onboarding",
    "$referrer",
    "$session_id",
    "timestamp",
    "$lib_version",
];

struct EventSchema {
    event_name: String,
    prop_keys: Vec<String>,
}

struct TeamModel {
    team_id: i32,
    project_id: i64,
    // weight ~ relative volume share (Zipfian)
    weight: f64,
    schemas: Vec<EventSchema>,
}

fn build_team_models(cfg: &BenchConfig, rng: &mut StdRng) -> Vec<TeamModel> {
    let mut teams = Vec::with_capacity(cfg.num_teams);
    for t in 0..cfg.num_teams {
        let team_id = (t as i32) + 1;
        // Zipfian-ish: team rank 1 gets the most traffic.
        let weight = 1.0 / ((t + 1) as f64);

        // Each team: the 5 common events + a handful of custom events.
        let num_custom = rng.gen_range(3..=12);
        let mut schemas = Vec::new();

        for ev in COMMON_EVENTS.iter() {
            schemas.push(make_schema(ev.to_string(), rng, true));
        }
        for c in 0..num_custom {
            schemas.push(make_schema(format!("custom_event_{team_id}_{c}"), rng, false));
        }

        teams.push(TeamModel {
            team_id,
            project_id: team_id as i64,
            weight,
            schemas,
        });
    }
    teams
}

fn make_schema(event_name: String, rng: &mut StdRng, common: bool) -> EventSchema {
    let mut prop_keys: Vec<String> = Vec::new();

    // Common events carry the shared web-event keys.
    if common {
        let n = rng.gen_range(6..=COMMON_PROP_KEYS.len());
        for k in COMMON_PROP_KEYS.iter().take(n) {
            prop_keys.push((*k).to_string());
        }
    }

    // Plus some event-specific custom keys.
    let num_custom = rng.gen_range(4..=25);
    for c in 0..num_custom {
        prop_keys.push(format!("prop_{c}"));
    }
    EventSchema {
        event_name,
        prop_keys,
    }
}

fn pick_weighted_team<'a>(teams: &'a [TeamModel], total_weight: f64, rng: &mut StdRng) -> &'a TeamModel {
    let mut r = rng.gen_range(0.0..total_weight);
    for tm in teams {
        if r < tm.weight {
            return tm;
        }
        r -= tm.weight;
    }
    teams.last().unwrap()
}

/// Build a property value for a key, picking a type that exercises detection paths.
fn value_for_key(key: &str, rng: &mut StdRng) -> Value {
    if key.starts_with("$feature/") {
        return json!(rng.gen_bool(0.5));
    }
    if key.starts_with("utm_") {
        return json!("google");
    }
    if key == "timestamp" {
        return json!("2026-06-21T12:00:00Z");
    }
    match rng.gen_range(0..4) {
        0 => json!(format!("val_{}", rng.gen_range(0..1000))),
        1 => json!(rng.gen_range(0..100000)),
        2 => json!(rng.gen_bool(0.5)),
        _ => json!(format!("{}", rng.gen_range(0..50))),
    }
}

/// Generate the raw Kafka-style JSON payloads up front (so the timed phases measure
/// processing, not generation). Returns the JSON strings plus the total distinct
/// (team, event) pairs actually emitted (useful context for the report).
fn generate_workload(cfg: &BenchConfig, teams: &[TeamModel], rng: &mut StdRng) -> Vec<String> {
    let total_weight: f64 = teams.iter().map(|t| t.weight).sum();
    let mut out = Vec::with_capacity(cfg.num_events);

    for _ in 0..cfg.num_events {
        let tm = pick_weighted_team(teams, total_weight, rng);
        // Bias toward common (high-volume) events: ~70% of traffic.
        let schema = if rng.gen_bool(0.7) {
            &tm.schemas[rng.gen_range(0..COMMON_EVENTS.len())]
        } else {
            &tm.schemas[rng.gen_range(0..tm.schemas.len())]
        };

        let mut props = Map::new();
        let is_group = schema.event_name == "$groupidentify";

        if is_group {
            // groupidentify only bubbles up $group_set; model that shape.
            let mut group_set = Map::new();
            for key in &schema.prop_keys {
                group_set.insert(key.clone(), value_for_key(key, rng));
            }
            props.insert("$group_type".to_string(), json!("organization"));
            props.insert("$group_set".to_string(), Value::Object(group_set));
        } else {
            for key in &schema.prop_keys {
                props.insert(key.clone(), value_for_key(key, rng));
            }
            // Rare schema drift: invent a brand-new key ~0.5% of the time. These are
            // the genuinely-new property defs that *should* survive dedup.
            if rng.gen_bool(0.005) {
                let novel = format!("novel_{}", rng.gen_range(0..1_000_000));
                props.insert(novel, json!(rng.gen_range(0..1000)));
            }
            // A subset of events carry person properties via $set.
            if rng.gen_bool(0.2) {
                let mut set = Map::new();
                set.insert("email".to_string(), json!("a@b.com"));
                set.insert("plan".to_string(), json!("pro"));
                props.insert("$set".to_string(), Value::Object(set));
            }
        }

        let payload = json!({
            "team_id": tm.team_id,
            "project_id": tm.project_id,
            "event": schema.event_name,
            "properties": Value::Object(props).to_string(),
        });
        out.push(payload.to_string());
    }
    out
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

#[derive(Default)]
struct DedupStats {
    updates_seen: u64,
    passed_event_defs: u64,
    passed_event_props: u64,
    passed_prop_defs: u64,
}

impl DedupStats {
    fn passed_total(&self) -> u64 {
        self.passed_event_defs + self.passed_event_props + self.passed_prop_defs
    }
}

/// Mirrors the per-update filtering in `update_producer_loop`: a per-worker AHashSet
/// compaction window followed by the shared `Cache` membership filter. Kept tiny and
/// obviously equivalent; the metric depends only on `into_updates` + `Cache`, both real.
fn run_dedup(updates: &[Update], cache: &Cache, compaction: &mut AHashSet<Update>, stats: &mut DedupStats) {
    for u in updates {
        stats.updates_seen += 1;
        // producer-local compaction window
        if !compaction.insert(u.clone()) {
            continue;
        }
        // shared cross-worker cache filter
        if cache.contains_key(u) {
            continue;
        }
        cache.insert(u.clone());
        match u {
            Update::Event(_) => stats.passed_event_defs += 1,
            Update::EventProperty(_) => stats.passed_event_props += 1,
            Update::Property(_) => stats.passed_prop_defs += 1,
        }
    }
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

fn main() {
    let cfg = BenchConfig::from_env();
    let mut rng = StdRng::seed_from_u64(cfg.seed);

    eprintln!(
        "building workload: {} events, {} teams, seed {}, cache_cap {} ...",
        cfg.num_events, cfg.num_teams, cfg.seed, cfg.cache_cap
    );
    let teams = build_team_models(&cfg, &mut rng);
    let payloads = generate_workload(&cfg, &teams, &mut rng);

    // ---- Phase A: parse + decompose throughput (deserialize + into_updates) ----
    // This is exactly the per-event CPU work each producer does before dedup.
    let start = Instant::now();
    let mut total_updates: u64 = 0;
    let mut all_updates: Vec<Vec<Update>> = Vec::with_capacity(payloads.len());
    for p in &payloads {
        let event: Event = serde_json::from_str(p).expect("valid event json");
        let updates = event.into_updates(10_000);
        total_updates += updates.len() as u64;
        all_updates.push(updates);
    }
    let parse_elapsed = start.elapsed();
    let events_per_sec = cfg.num_events as f64 / parse_elapsed.as_secs_f64();
    let updates_per_sec = total_updates as f64 / parse_elapsed.as_secs_f64();

    // ---- Phase B: dedup effectiveness through the real Cache ----
    let cache = Cache::new(cfg.cache_cap, cfg.cache_cap, cfg.cache_cap);
    let mut compaction: AHashSet<Update> = AHashSet::with_capacity(1 << 20);
    let mut stats = DedupStats::default();
    let dedup_start = Instant::now();
    for updates in &all_updates {
        run_dedup(updates, &cache, &mut compaction, &mut stats);
    }
    let dedup_elapsed = dedup_start.elapsed();

    let passed = stats.passed_total();
    let dedup_ratio = 1.0 - (passed as f64 / stats.updates_seen as f64);
    let writes_per_1k = passed as f64 / (cfg.num_events as f64 / 1000.0);

    // ---- Phase C: last_seen_at churn across simulated hours ----
    // Real key: EventDefinition hashes on (team, name, last_seen_at@hour). Each new hour
    // re-issues a write for every active (team, name). Counterfactual: dedup on (team,
    // name) only. The delta is the "wasted timestamp write" volume the year-old
    // "remove last_seen_at" suggestion targets.
    // Floor period under test: 3600 reproduces the historical hourly cadence (baseline),
    // 86400 is the new daily default. Uses the SAME production flooring fn so the benchmark
    // tracks production behavior exactly.
    let floor_secs = env_usize("PROPDEFS_BENCH_FLOOR_SECS", 3600) as i64;
    let mut real_key_cache: AHashSet<Update> = AHashSet::new();
    let mut team_name_only: AHashSet<(i32, String)> = AHashSet::new();
    let mut real_eventdef_writes: u64 = 0;
    let mut counterfactual_eventdef_writes: u64 = 0;
    // Simulate one arrival per hour over the window; each arrival's last_seen_at is floored
    // by the production fn, so coarser periods collapse multiple hours into one cache key.
    let start = property_defs_rs::types::floor_last_seen(chrono::Utc::now(), 3600);
    for h in 0..cfg.hours.max(1) {
        let arrival = start + chrono::Duration::hours(h as i64);
        let last_seen = property_defs_rs::types::floor_last_seen(arrival, floor_secs);
        for updates in &all_updates {
            for u in updates {
                let Update::Event(ed) = u else { continue };
                // real: key includes the period-floored last_seen_at
                let mut keyed = ed.clone();
                keyed.last_seen_at = last_seen;
                if real_key_cache.insert(Update::Event(keyed)) {
                    real_eventdef_writes += 1;
                }
                // counterfactual: key on (team, name) only
                if team_name_only.insert((ed.team_id, ed.name.clone())) {
                    counterfactual_eventdef_writes += 1;
                }
            }
        }
    }
    let wasted_eventdef_writes = real_eventdef_writes.saturating_sub(counterfactual_eventdef_writes);

    // ---- Report ----
    println!("\n=== propdefs pipeline benchmark ===");
    println!(
        "workload         : {} events, {} teams, seed {}, cache_cap {}",
        cfg.num_events, cfg.num_teams, cfg.seed, cfg.cache_cap
    );
    println!("\n-- throughput (Phase A: deserialize + into_updates) --");
    println!("events/sec       : {events_per_sec:>14.0}");
    println!("updates/sec      : {updates_per_sec:>14.0}");
    println!("updates_seen     : {total_updates:>14}");
    println!("parse_elapsed_ms : {:>14.1}", parse_elapsed.as_secs_f64() * 1000.0);

    println!("\n-- dedup (Phase B: producer compaction + shared Cache) --");
    println!("dedup_ratio      : {dedup_ratio:>14.5}   (higher = fewer DB writes)");
    println!("writes_per_1k_evt: {writes_per_1k:>14.2}");
    println!("passed_total     : {passed:>14}");
    println!("  event_defs     : {:>14}", stats.passed_event_defs);
    println!("  event_props    : {:>14}", stats.passed_event_props);
    println!("  prop_defs      : {:>14}", stats.passed_prop_defs);
    println!("dedup_elapsed_ms : {:>14.1}", dedup_elapsed.as_secs_f64() * 1000.0);

    println!(
        "\n-- last_seen_at churn (Phase C: {} simulated hours, floor={}s) --",
        cfg.hours.max(1),
        floor_secs
    );
    println!("real_eventdef_writes          : {real_eventdef_writes:>10}");
    println!("counterfactual (team,name)    : {counterfactual_eventdef_writes:>10}");
    println!("wasted_timestamp_writes       : {wasted_eventdef_writes:>10}");

    if cfg.emit_json {
        // Single machine-readable line for the loop driver to capture + diff.
        println!(
            "BENCH_JSON {{\"events_per_sec\":{:.0},\"updates_per_sec\":{:.0},\"dedup_ratio\":{:.6},\"writes_per_1k_evt\":{:.4},\"passed_total\":{},\"passed_event_defs\":{},\"passed_event_props\":{},\"passed_prop_defs\":{},\"real_eventdef_writes\":{},\"counterfactual_eventdef_writes\":{},\"wasted_timestamp_writes\":{}}}",
            events_per_sec,
            updates_per_sec,
            dedup_ratio,
            writes_per_1k,
            passed,
            stats.passed_event_defs,
            stats.passed_event_props,
            stats.passed_prop_defs,
            real_eventdef_writes,
            counterfactual_eventdef_writes,
            wasted_eventdef_writes,
        );
    }
}
