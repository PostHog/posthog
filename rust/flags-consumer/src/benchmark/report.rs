use super::metrics::compute_delta;
use super::workloads::{PhaseResult, QueryPlanInfo};
use super::BenchmarkArgs;

fn fmt_duration_ms(d: std::time::Duration) -> String {
    let ms = d.as_secs_f64() * 1000.0;
    if ms < 1.0 {
        format!("{:.2}ms", ms)
    } else if ms < 100.0 {
        format!("{:.1}ms", ms)
    } else {
        format!("{:.0}ms", ms)
    }
}

fn fmt_bytes_mib(bytes: i64) -> String {
    let mib = bytes as f64 / (1024.0 * 1024.0);
    format!("{:.1}", mib)
}

fn print_phase_row(result: &PhaseResult, show_pg_metrics: bool) {
    let delta = compute_delta(&result.before, &result.after);

    let wal_mib = match result.wal_bytes {
        Some(b) => fmt_bytes_mib(b),
        None => "N/A".into(),
    };

    if show_pg_metrics {
        println!(
            " {:<24} | {:>6} | {:>7} | {:>7} | {:>7} | {:>7} | {:>6} | {:>6.1}% | {:>11} | {:>9} | {:>9} | {:>7}",
            result.name,
            result.latency.count,
            fmt_duration_ms(result.latency.p50),
            fmt_duration_ms(result.latency.p95),
            fmt_duration_ms(result.latency.p99),
            fmt_duration_ms(result.latency.max),
            result.errors,
            delta.hot_pct,
            delta.dead_tuples,
            fmt_bytes_mib(result.after.table_bytes),
            fmt_bytes_mib(result.after.index_bytes),
            wal_mib,
        );
    } else {
        println!(
            " {:<24} | {:>6} | {:>7} | {:>7} | {:>7} | {:>7} | {:>6} | {:>7} | {:>11} | {:>9} | {:>9} | {:>7}",
            result.name,
            result.latency.count,
            fmt_duration_ms(result.latency.p50),
            fmt_duration_ms(result.latency.p95),
            fmt_duration_ms(result.latency.p99),
            fmt_duration_ms(result.latency.max),
            result.errors,
            "",
            "",
            "",
            "",
            "",
        );
    }
}

pub fn print_report(args: &BenchmarkArgs, results: &[PhaseResult], query_plan: &QueryPlanInfo) {
    println!();
    println!("=== GIN Index Benchmark Report ===");
    println!(
        "Scale: {} rows | Teams: {} | Concurrency: {} | Burst: {}x | Duration: {}s/phase",
        args.scale, args.teams, args.concurrency, args.burst_factor, args.duration_secs
    );
    println!(
        "GIN index used for reads: {}",
        if query_plan.gin_index_used {
            "yes"
        } else {
            "NO (planner chose sequential scan)"
        }
    );
    println!();

    let header = format!(
        " {:<24} | {:>6} | {:>7} | {:>7} | {:>7} | {:>7} | {:>6} | {:>7} | {:>11} | {:>9} | {:>9} | {:>7}",
        "Phase", "Ops", "p50", "p95", "p99", "max", "Errors", "HOT%", "Dead Tuples", "Table MiB", "Index MiB", "WAL MiB"
    );
    let separator = "-".repeat(header.len());

    println!("{header}");
    println!("{separator}");

    for result in results {
        let is_read = result.name.contains("reads");
        print_phase_row(result, !is_read);
    }

    println!();
}
