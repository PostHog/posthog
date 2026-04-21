use crate::stats::{StatsCollector, StatsSnapshot};
use comfy_table::{presets::UTF8_FULL_CONDENSED, Cell, CellAlignment, ContentArrangement, Table};
use owo_colors::OwoColorize;

fn format_us(us: u64) -> String {
    if us < 1_000 {
        format!("{us}us")
    } else if us < 1_000_000 {
        format!("{:.1}ms", us as f64 / 1_000.0)
    } else {
        format!("{:.2}s", us as f64 / 1_000_000.0)
    }
}

fn stats_row(name: &str, snap: &StatsSnapshot) -> Vec<Cell> {
    vec![
        Cell::new(name),
        Cell::new(snap.total).set_alignment(CellAlignment::Right),
        Cell::new(snap.successes).set_alignment(CellAlignment::Right),
        Cell::new(if snap.failures > 0 {
            snap.failures.to_string().red().to_string()
        } else {
            "0".to_string()
        })
        .set_alignment(CellAlignment::Right),
        Cell::new(format_us(snap.p50_us)).set_alignment(CellAlignment::Right),
        Cell::new(format_us(snap.p95_us)).set_alignment(CellAlignment::Right),
        Cell::new(format_us(snap.p99_us)).set_alignment(CellAlignment::Right),
        Cell::new(format!("{:.1}", snap.throughput_rps)).set_alignment(CellAlignment::Right),
    ]
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
    println!(
        "{}",
        format!("=== personhog-cannon {title} results ===").bold()
    );
    println!(
        "  Duration: {:.2}s | Team: {} | Persons: {}",
        elapsed.as_secs_f64(),
        team_id,
        num_persons
    );
    println!();

    let mut table = Table::new();
    table
        .load_preset(UTF8_FULL_CONDENSED)
        .set_content_arrangement(ContentArrangement::Dynamic)
        .set_header(vec![
            "Operation", "Total", "Success", "Failed", "p50", "p95", "p99", "RPS",
        ]);

    if write_snap.total > 0 {
        table.add_row(stats_row("writes", &write_snap));
    }
    if read_snap.total > 0 {
        table.add_row(stats_row("reads", &read_snap));
    }

    println!("{table}");
    println!();

    if violations.is_empty() {
        println!(
            "  {}",
            "Consistency violations: 0".green()
        );
    } else {
        println!(
            "  {}",
            format!("Consistency violations: {}", violations.len()).red().bold()
        );
        println!();
        for v in violations.iter().take(20) {
            println!(
                "    person_id={} key={:?} expected={} actual={}",
                v.person_id,
                v.key,
                v.expected.to_string().green(),
                v.actual.to_string().red(),
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
