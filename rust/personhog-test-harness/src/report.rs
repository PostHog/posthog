use crate::stats::{StatsCollector, StatsSnapshot};

fn format_us(us: u64) -> String {
    if us < 1_000 {
        format!("{us}us")
    } else if us < 1_000_000 {
        format!("{:.1}ms", us as f64 / 1_000.0)
    } else {
        format!("{:.2}s", us as f64 / 1_000_000.0)
    }
}

fn print_stats_row(name: &str, snap: &StatsSnapshot) {
    println!(
        "  {:<10} {:>8} {:>8} {:>7} {:>8} {:>8} {:>8} {:>9.1}",
        name,
        snap.total,
        snap.successes,
        snap.failures,
        format_us(snap.p50_us),
        format_us(snap.p95_us),
        format_us(snap.p99_us),
        snap.throughput_rps,
    );
}

pub fn print_report(
    title: &str,
    collector: &StatsCollector,
    team_id: i64,
    num_persons: usize,
    violations: &[ConsistencyViolation],
) {
    let write_snap = collector.writes.snapshot();
    let read_snap = collector.reads.snapshot();
    let elapsed = write_snap.elapsed.max(read_snap.elapsed);

    println!();
    println!("=== personhog-test-harness {title} results ===");
    println!(
        "  Duration: {:.2}s | Team: {} | Persons: {}",
        elapsed.as_secs_f64(),
        team_id,
        num_persons
    );
    println!();
    println!(
        "  {:<10} {:>8} {:>8} {:>7} {:>8} {:>8} {:>8} {:>9}",
        "Operation", "Total", "Success", "Failed", "p50", "p95", "p99", "RPS"
    );
    if write_snap.total > 0 {
        print_stats_row("writes", &write_snap);
    }
    if read_snap.total > 0 {
        print_stats_row("reads", &read_snap);
    }
    println!();

    if violations.is_empty() {
        println!("  Consistency violations: 0");
    } else {
        println!("  Consistency violations: {}", violations.len());
        println!();
        for v in violations.iter().take(20) {
            println!(
                "    person_id={} key={:?} expected={} actual={}",
                v.person_id, v.key, v.expected, v.actual,
            );
        }
        if violations.len() > 20 {
            println!("    ... and {} more", violations.len() - 20);
        }
    }
    println!();
}

pub struct ConsistencyViolation {
    pub person_id: i64,
    pub key: String,
    pub expected: serde_json::Value,
    pub actual: serde_json::Value,
}
