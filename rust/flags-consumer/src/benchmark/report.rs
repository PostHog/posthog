use std::time::Duration;

use serde::Serialize;

use super::collector::{ClassMetrics, IntervalRecord, LatencySummary, PhaseSummaryRecord};
use super::ops::OpClass;
use super::pg_sampler::{PgDeltaRecord, TableGroup, WalDelta};
use super::rates::{FeedMode, PhaseName, RateSpec, PROD_US_RATES};

const NANOS_PER_MILLISECOND: f64 = 1_000_000.0;

#[derive(Debug, Clone, Copy, Serialize)]
pub struct GateThresholds {
    pub steady_read_p50_ms: f64,
    pub steady_read_p99_ms: f64,
    pub storm_read_p99_ms: f64,
    pub recovery_max_secs: u64,
    pub catch_up_headroom: f64,
    pub dispatch_p99_ms: f64,
    pub rate_tolerance_percent: f64,
    pub max_read_drift_ratio: f64,
    pub max_backlog_secs: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct PhaseResult {
    pub name: PhaseName,
    pub duration: Duration,
    pub pre_hook_duration: Duration,
    pub targets: [RateSpec; OpClass::COUNT],
    pub summary: PhaseSummaryRecord,
    pub intervals: Vec<IntervalRecord>,
    pub pg: Vec<PgDeltaRecord>,
}

#[derive(Debug, Clone, Serialize)]
pub struct GateCheck {
    pub name: String,
    pub passed: bool,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct GateEvaluation {
    pub passed: bool,
    pub harness_limited: bool,
    pub checks: Vec<GateCheck>,
    pub unverified_qualifications: Vec<String>,
}

pub fn evaluate_gates(phases: &[PhaseResult], thresholds: GateThresholds) -> GateEvaluation {
    let mut checks = Vec::new();
    add_phase_integrity_checks(&mut checks, phases, thresholds);

    let peak = phase(phases, PhaseName::PeakMix);
    if let Some(peak) = peak {
        let read = class_metrics(peak, OpClass::CanonicalRead);
        checks.push(max_latency_check(
            "steady read p50",
            read.schedule.count,
            read.schedule.p50_nanos,
            thresholds.steady_read_p50_ms,
        ));
        checks.push(max_latency_check(
            "steady read p99",
            read.schedule.count,
            read.schedule.p99_nanos,
            thresholds.steady_read_p99_ms,
        ));
        let interval_reads = peak
            .intervals
            .iter()
            .filter(|interval| interval.started_at_nanos < peak.summary.duration_nanos)
            .map(|interval| &interval.classes[OpClass::CanonicalRead.index()])
            .filter(|read| read.counts.scheduled > 0)
            .collect::<Vec<_>>();
        let interval_slo = !interval_reads.is_empty()
            && interval_reads.iter().all(|read| {
                nanos_millis(read.schedule.p50_nanos) <= thresholds.steady_read_p50_ms
                    && nanos_millis(read.schedule.p99_nanos) <= thresholds.steady_read_p99_ms
            });
        checks.push(GateCheck {
            name: "steady interval read SLO".to_owned(),
            passed: interval_slo,
            detail: "every non-empty 10s interval must meet read p50 and p99 limits".to_owned(),
        });
        let drift = read_drift_ratio(peak);
        checks.push(GateCheck {
            name: "steady read drift".to_owned(),
            passed: drift.is_some_and(|ratio| ratio <= thresholds.max_read_drift_ratio),
            detail: drift.map_or_else(
                || "fewer than five non-empty workload intervals".to_owned(),
                |ratio| {
                    format!(
                        "late/early median interval p99 {ratio:.2}x, limit {:.2}x",
                        thresholds.max_read_drift_ratio
                    )
                },
            ),
        });
    } else {
        checks.push(missing_phase("steady gate", PhaseName::PeakMix));
    }

    if let Some(storm) = phase(phases, PhaseName::MergeStorm) {
        let read = class_metrics(storm, OpClass::CanonicalRead);
        checks.push(max_latency_check(
            "storm read p99",
            read.schedule.count,
            read.schedule.p99_nanos,
            thresholds.storm_read_p99_ms,
        ));
    } else {
        checks.push(missing_phase("storm gate", PhaseName::MergeStorm));
    }

    if let (Some(storm), Some(recovery)) = (
        phase(phases, PhaseName::MergeStorm),
        phase(phases, PhaseName::Recovery),
    ) {
        let recovery_outcome = recovery_time(
            recovery,
            Duration::from_nanos(storm.summary.post_deadline_duration_nanos),
            thresholds,
        );
        checks.push(GateCheck {
            name: "recovery time".to_owned(),
            passed: matches!(
                recovery_outcome,
                RecoveryOutcome::Recovered(elapsed)
                    if elapsed <= Duration::from_secs(thresholds.recovery_max_secs)
            ),
            detail: match recovery_outcome {
                RecoveryOutcome::Recovered(elapsed) => {
                    format!(
                        "{:.1}s from storm end, limit {}s",
                        elapsed.as_secs_f64(),
                        thresholds.recovery_max_secs
                    )
                }
                RecoveryOutcome::NoReadTraffic => {
                    "no read traffic was observed during recovery".to_owned()
                }
                RecoveryOutcome::NotRecovered => {
                    "read SLO was not restored for the remainder of recovery".to_owned()
                }
            },
        });
        let vacuumed = [TableGroup::Person, TableGroup::DistinctIdMap]
            .into_iter()
            .all(|group| {
                recovery.pg.iter().any(|record| {
                    record
                        .tables
                        .iter()
                        .any(|table| table.group == group && table.vacuums > 0)
                })
            });
        checks.push(GateCheck {
            name: "recovery vacuum observed".to_owned(),
            passed: vacuumed,
            detail: if vacuumed {
                "manual vacuum counters advanced for both table groups".to_owned()
            } else {
                "manual vacuum counters did not advance for both table groups".to_owned()
            },
        });
    } else if phase(phases, PhaseName::Recovery).is_none() {
        checks.push(missing_phase("recovery gate", PhaseName::Recovery));
    } else {
        checks.push(missing_phase("recovery gate", PhaseName::MergeStorm));
    }

    if let Some(catch_up) = phase(phases, PhaseName::CatchUp) {
        for (class, average) in [
            (OpClass::PersonUpsert, PROD_US_RATES.person_upsert.average),
            (
                OpClass::DistinctIdAssignment,
                PROD_US_RATES.distinct_id_assignment.average,
            ),
            (OpClass::Merge, PROD_US_RATES.merge.average),
        ] {
            let headroom = achieved_rate(catch_up, class) / average.get();
            checks.push(GateCheck {
                name: catch_up_check_name(class).to_owned(),
                passed: headroom >= thresholds.catch_up_headroom,
                detail: format!(
                    "{headroom:.2}x average, required {:.2}x",
                    thresholds.catch_up_headroom
                ),
            });
        }
        let read = class_metrics(catch_up, OpClass::CanonicalRead);
        checks.push(max_latency_check(
            "catch-up read p99",
            read.schedule.count,
            read.schedule.p99_nanos,
            thresholds.steady_read_p99_ms,
        ));
        checks.push(max_latency_check(
            "catch-up read p50",
            read.schedule.count,
            read.schedule.p50_nanos,
            thresholds.steady_read_p50_ms,
        ));
    } else {
        checks.push(missing_phase("catch-up gate", PhaseName::CatchUp));
    }

    let dispatch_limit_nanos = millis_to_nanos(thresholds.dispatch_p99_ms);
    let harness_limited = phases.iter().any(|phase| {
        phase
            .intervals
            .iter()
            .filter(|interval| interval.started_at_nanos < phase.summary.duration_nanos)
            .any(|interval| {
                phase.targets.iter().any(|target| {
                    target.feed == FeedMode::Open
                        && target.target.is_active()
                        && interval.classes[target.class.index()].dispatch_lag.count > 0
                        && interval.classes[target.class.index()]
                            .dispatch_lag
                            .p99_nanos
                            > dispatch_limit_nanos
                })
            })
    });
    checks.push(GateCheck {
        name: "load generator dispatch p99".to_owned(),
        passed: !harness_limited,
        detail: if harness_limited {
            format!(
                "at least one class exceeded {:.2}ms; result is harness-limited",
                thresholds.dispatch_p99_ms
            )
        } else {
            format!(
                "all classes at or below {:.2}ms",
                thresholds.dispatch_p99_ms
            )
        },
    });
    let passed = checks.iter().all(|check| check.passed);
    GateEvaluation {
        passed,
        harness_limited,
        checks,
        unverified_qualifications: vec![
            "dead tuples and index size plateau, with autovacuum keeping up per partition"
                .to_owned(),
            "bootstrap throughput extrapolates to the accepted full-backfill window".to_owned(),
            "production-candidate instance uses a working set at least 3-5x RAM".to_owned(),
            "load generator has guaranteed CPU and is not externally throttled".to_owned(),
        ],
    }
}

fn add_phase_integrity_checks(
    checks: &mut Vec<GateCheck>,
    phases: &[PhaseResult],
    thresholds: GateThresholds,
) {
    for phase in phases {
        let shed = phase
            .summary
            .classes
            .iter()
            .map(|class| class.counts.shed.saturating_add(class.counts.closed))
            .sum::<u64>();
        checks.push(GateCheck {
            name: format!("{} zero shed", phase.name.as_str()),
            passed: shed == 0,
            detail: format!("{shed} operations shed or sent to a closed executor"),
        });

        let errors = phase
            .summary
            .classes
            .iter()
            .map(|class| class.counts.errors)
            .sum::<u64>();
        checks.push(GateCheck {
            name: format!("{} zero errors", phase.name.as_str()),
            passed: errors == 0,
            detail: format!("{errors} operation errors"),
        });

        for target in phase
            .targets
            .iter()
            .filter(|target| target.feed == FeedMode::Open && target.target.is_active())
        {
            let class = target.class;
            let target_rate = target.target.get();
            let scheduled = scheduled_rate(phase, class);
            let achieved = achieved_rate(phase, class);
            let scheduled_error = rate_error_percent(scheduled, target_rate);
            let schedule_tolerance = poisson_rate_tolerance_percent(
                target_rate,
                phase.duration,
                thresholds.rate_tolerance_percent,
            );
            let deadline_counts = phase.summary.deadline_counts[class.index()];
            let achieved_error =
                completion_shortfall_percent(deadline_counts.achieved, deadline_counts.scheduled);
            checks.push(GateCheck {
                name: format!(
                    "{} {} scheduled rate",
                    phase.name.as_str(),
                    class_name(class)
                ),
                passed: scheduled_error <= schedule_tolerance,
                detail: format!(
                    "{scheduled:.1}/s scheduled vs {target_rate:.1}/s target ({scheduled_error:.2}% error, {schedule_tolerance:.2}% Poisson limit)"
                ),
            });
            checks.push(GateCheck {
                name: format!(
                    "{} {} achieved rate",
                    phase.name.as_str(),
                    class_name(class)
                ),
                passed: achieved_error <= thresholds.rate_tolerance_percent,
                detail: format!(
                    "{achieved:.1}/s completed by deadline vs {scheduled:.1}/s scheduled ({achieved_error:.2}% shortfall, {:.2}% limit)",
                    thresholds.rate_tolerance_percent
                ),
            });

            let outstanding = outstanding_at_deadline(phase, class);
            let backlog_secs = outstanding as f64 / target_rate;
            checks.push(GateCheck {
                name: format!(
                    "{} {} deadline backlog",
                    phase.name.as_str(),
                    class_name(class)
                ),
                passed: backlog_secs <= thresholds.max_backlog_secs,
                detail: format!(
                    "{outstanding} outstanding ({backlog_secs:.3}s at target), limit {:.3}s",
                    thresholds.max_backlog_secs
                ),
            });
        }
    }
}

pub fn print_report(
    postgres_version: &str,
    settings: &[(String, String)],
    seed: u64,
    phases: &[PhaseResult],
    gates: &GateEvaluation,
) {
    println!("\n=== Read-store schema benchmark report ===");
    println!("PostgreSQL: {postgres_version}");
    println!("Seed: {seed}");
    for (name, value) in settings {
        println!("{name}: {value}");
    }

    for phase in phases {
        println!(
            "\n{} ({:.1}s workload + {:.3}s post-deadline, including {:.3}s executor drain)",
            phase.name.as_str(),
            phase.duration.as_secs_f64(),
            Duration::from_nanos(phase.summary.post_deadline_duration_nanos).as_secs_f64(),
            Duration::from_nanos(phase.summary.drain_duration_nanos).as_secs_f64(),
        );
        println!(
            " {:<23} {:>10} {:>10} {:>9} {:>11} {:>8} {:>8} {:>8} {:>8} {:>23} {:>23} {:>23} {:>23} {:>13}",
            "Class",
            "Sched/s",
            "Done/s",
            "Complete",
            "Deadline q",
            "Errors",
            "Shed",
            "Retry",
            "Deadlock",
            "Service p50/p95/p99/max",
            "Schedule p50/p95/p99/max",
            "Queue p50/p95/p99/max",
            "Dispatch p50/p95/p99/max",
            "Headroom/peak"
        );
        for class in &phase.summary.classes {
            let headroom = catch_up_headroom(phase, class.class);
            println!(
                " {:<23} {:>10.1} {:>10.1} {:>9} {:>11} {:>8} {:>8} {:>8} {:>8} {:>23} {:>23} {:>23} {:>23} {:>12}",
                class_name(class.class),
                scheduled_rate(phase, class.class),
                achieved_rate(phase, class.class),
                class.counts.completed,
                outstanding_at_deadline(phase, class.class),
                class.counts.errors,
                class.counts.shed + class.counts.closed,
                format!("{}/{}", class.counts.retry_affected, class.counts.retry_attempts),
                format!("{}/{}", class.counts.deadlock_affected, class.counts.deadlock_attempts),
                latency_set(class.service),
                latency_set(class.schedule),
                latency_set(class.queue),
                latency_set(class.dispatch_lag),
                headroom.map_or_else(|| "-".to_owned(), |value| format!("{value:.2}x")),
            );
        }
        print_pg_summary(&phase.pg);
    }

    println!(
        "\nAutomated gate result: {}",
        if gates.passed { "PASS" } else { "FAIL" }
    );
    for check in &gates.checks {
        println!(
            " {} {:<30} {}",
            if check.passed { "PASS" } else { "FAIL" },
            check.name,
            check.detail
        );
    }
    println!("Manual qualifications still required:");
    for qualification in &gates.unverified_qualifications {
        println!(" - {qualification}");
    }
}

fn phase(phases: &[PhaseResult], name: PhaseName) -> Option<&PhaseResult> {
    phases.iter().find(|phase| phase.name == name)
}

fn class_metrics(phase: &PhaseResult, class: OpClass) -> &ClassMetrics {
    &phase.summary.classes[class.index()]
}

fn achieved_rate(phase: &PhaseResult, class: OpClass) -> f64 {
    phase.summary.deadline_counts[class.index()].achieved as f64 / phase.duration.as_secs_f64()
}

fn scheduled_rate(phase: &PhaseResult, class: OpClass) -> f64 {
    phase.summary.deadline_counts[class.index()].scheduled as f64 / phase.duration.as_secs_f64()
}

fn outstanding_at_deadline(phase: &PhaseResult, class: OpClass) -> u64 {
    let counts = phase.summary.deadline_counts[class.index()];
    counts
        .scheduled
        .saturating_sub(counts.shed)
        .saturating_sub(counts.closed)
        .saturating_sub(counts.completed)
}

fn rate_error_percent(actual: f64, target: f64) -> f64 {
    ((actual - target).abs() / target) * 100.0
}

fn poisson_rate_tolerance_percent(
    target_rate: f64,
    duration: Duration,
    configured_tolerance: f64,
) -> f64 {
    let expected_count = target_rate * duration.as_secs_f64();
    configured_tolerance.max(400.0 / expected_count.sqrt())
}

fn completion_shortfall_percent(achieved: u64, scheduled: u64) -> f64 {
    if scheduled == 0 {
        return 100.0;
    }
    scheduled.saturating_sub(achieved) as f64 / scheduled as f64 * 100.0
}

fn catch_up_headroom(phase: &PhaseResult, class: OpClass) -> Option<f64> {
    if phase.name != PhaseName::CatchUp || class == OpClass::CanonicalRead {
        return None;
    }
    let peak = match class {
        OpClass::PersonUpsert => PROD_US_RATES.person_upsert.five_minute_peak,
        OpClass::DistinctIdAssignment => PROD_US_RATES.distinct_id_assignment.five_minute_peak,
        OpClass::Merge => PROD_US_RATES.merge.five_minute_peak,
        OpClass::CanonicalRead => unreachable!(),
    };
    Some(achieved_rate(phase, class) / peak.get())
}

fn read_drift_ratio(phase: &PhaseResult) -> Option<f64> {
    let values = phase
        .intervals
        .iter()
        .filter_map(|interval| {
            let read = &interval.classes[OpClass::CanonicalRead.index()];
            (interval.started_at_nanos < phase.summary.duration_nanos && read.schedule.count > 0)
                .then_some(read.schedule.p99_nanos)
        })
        .collect::<Vec<_>>();
    if values.len() < 5 {
        return None;
    }
    let settled = &values[1..];
    let middle = settled.len() / 2;
    let early = median(&settled[..middle])?;
    let late = median(&settled[middle..])?;
    Some(late as f64 / early as f64)
}

fn median(values: &[u64]) -> Option<u64> {
    let mut values = values.to_vec();
    values.sort_unstable();
    values.get(values.len() / 2).copied()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RecoveryOutcome {
    Recovered(Duration),
    NoReadTraffic,
    NotRecovered,
}

fn recovery_time(
    phase: &PhaseResult,
    storm_post_deadline: Duration,
    thresholds: GateThresholds,
) -> RecoveryOutcome {
    let active_intervals = phase
        .intervals
        .iter()
        .filter(|interval| {
            interval.started_at_nanos < phase.summary.duration_nanos
                && interval.classes[OpClass::CanonicalRead.index()]
                    .counts
                    .scheduled
                    > 0
        })
        .collect::<Vec<_>>();
    if active_intervals.is_empty() {
        return RecoveryOutcome::NoReadTraffic;
    }
    let recovered_interval = active_intervals
        .iter()
        .enumerate()
        .find_map(|(index, interval)| {
            let remains_recovered = active_intervals[index..].iter().all(|candidate| {
                let read = &candidate.classes[OpClass::CanonicalRead.index()];
                nanos_millis(read.schedule.p50_nanos) <= thresholds.steady_read_p50_ms
                    && nanos_millis(read.schedule.p99_nanos) <= thresholds.steady_read_p99_ms
            });
            remains_recovered.then_some(*interval)
        });
    let Some(recovered_interval) = recovered_interval else {
        return RecoveryOutcome::NotRecovered;
    };
    RecoveryOutcome::Recovered(
        storm_post_deadline
            + phase.pre_hook_duration
            + Duration::from_nanos(recovered_interval.ended_at_nanos),
    )
}

fn max_latency_check(
    name: impl Into<String>,
    sample_count: u64,
    actual_nanos: u64,
    limit_ms: f64,
) -> GateCheck {
    let actual_ms = nanos_millis(actual_nanos);
    GateCheck {
        name: name.into(),
        passed: sample_count > 0 && actual_ms <= limit_ms,
        detail: if sample_count == 0 {
            "no latency samples".to_owned()
        } else {
            format!("{actual_ms:.3}ms, limit {limit_ms:.3}ms ({sample_count} samples)")
        },
    }
}

fn nanos_millis(nanos: u64) -> f64 {
    nanos as f64 / NANOS_PER_MILLISECOND
}

fn missing_phase(name: &'static str, phase: PhaseName) -> GateCheck {
    GateCheck {
        name: name.to_owned(),
        passed: false,
        detail: format!("missing {} phase", phase.as_str()),
    }
}

fn millis_to_nanos(millis: f64) -> u64 {
    (millis * NANOS_PER_MILLISECOND) as u64
}

fn latency_set(summary: LatencySummary) -> String {
    format!(
        "{}/{}/{}/{}",
        latency_ms(summary.p50_nanos),
        latency_ms(summary.p95_nanos),
        latency_ms(summary.p99_nanos),
        latency_ms(summary.max_nanos)
    )
}

fn latency_ms(nanos: u64) -> String {
    format!("{:.2}", nanos as f64 / NANOS_PER_MILLISECOND)
}

fn class_name(class: OpClass) -> &'static str {
    match class {
        OpClass::PersonUpsert => "person_upsert",
        OpClass::DistinctIdAssignment => "distinct_id_assignment",
        OpClass::Merge => "merge",
        OpClass::CanonicalRead => "canonical_read",
    }
}

fn catch_up_check_name(class: OpClass) -> &'static str {
    match class {
        OpClass::PersonUpsert => "catch-up person headroom",
        OpClass::DistinctIdAssignment => "catch-up distinct ID headroom",
        OpClass::Merge => "catch-up merge headroom",
        OpClass::CanonicalRead => "catch-up read headroom",
    }
}

fn print_pg_summary(records: &[PgDeltaRecord]) {
    for group in [TableGroup::Person, TableGroup::DistinctIdMap] {
        let deltas = records
            .iter()
            .flat_map(|record| record.tables.iter())
            .filter(|table| table.group == group)
            .collect::<Vec<_>>();
        let Some(last) = deltas.last() else {
            continue;
        };
        let inserts = deltas.iter().map(|table| table.inserts).sum::<u64>();
        let updates = deltas.iter().map(|table| table.updates).sum::<u64>();
        let deletes = deltas.iter().map(|table| table.deletes).sum::<u64>();
        let hot = deltas.iter().map(|table| table.hot_updates).sum::<u64>();
        let vacuums = deltas.iter().map(|table| table.vacuums).sum::<u64>();
        let autovacuums = deltas.iter().map(|table| table.autovacuums).sum::<u64>();
        let stats_reset = deltas.iter().any(|table| table.stats_reset_detected);
        let hot_percent = if updates == 0 {
            0.0
        } else {
            hot as f64 / updates as f64 * 100.0
        };
        println!(
            " PG {:?}: ins {} | upd {} | del {} | HOT {:.1}% | dead {} | vacuum {}/{} | heap {:.1} MiB | index {:.1} MiB{}",
            group,
            inserts,
            updates,
            deletes,
            hot_percent,
            last.dead_tuples,
            vacuums,
            autovacuums,
            bytes_mib(last.heap_bytes),
            bytes_mib(last.index_bytes),
            if stats_reset { " | stats reset" } else { "" },
        );
    }
    let unavailable = records.iter().find_map(|record| match &record.wal {
        WalDelta::Unavailable { reason } => Some(reason.as_ref()),
        WalDelta::Available { .. } => None,
    });
    let wal = records
        .iter()
        .filter_map(|record| match record.wal {
            WalDelta::Available { bytes } => Some(bytes),
            WalDelta::Unavailable { .. } => None,
        })
        .sum::<u64>();
    match unavailable {
        Some(reason) => println!(" PG WAL: unavailable ({reason})"),
        None => println!(" PG WAL: {:.1} MiB", bytes_mib(wal)),
    }
}

fn bytes_mib(bytes: u64) -> f64 {
    bytes as f64 / (1024.0 * 1024.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::benchmark::collector::{LatencySummary, OperationCounts};
    use crate::benchmark::ops::PhaseId;
    use crate::benchmark::rates::{FeedMode, RatePerSecond};

    fn metrics(class: OpClass, achieved: u64, schedule_p99_ms: u64) -> ClassMetrics {
        ClassMetrics {
            class,
            counts: OperationCounts {
                scheduled: achieved,
                completed: achieved,
                achieved,
                ..OperationCounts::default()
            },
            service: LatencySummary::default(),
            schedule: LatencySummary {
                count: achieved,
                p50_nanos: 500_000,
                p99_nanos: schedule_p99_ms * 1_000_000,
                ..LatencySummary::default()
            },
            queue: LatencySummary::default(),
            dispatch_lag: LatencySummary::default(),
        }
    }

    fn result(name: PhaseName, duration_secs: u64) -> PhaseResult {
        let duration = Duration::from_secs(duration_secs);
        let rates = [
            (OpClass::PersonUpsert, 5_788.0),
            (OpClass::DistinctIdAssignment, 3_594.0),
            (OpClass::Merge, 54.6),
            (OpClass::CanonicalRead, 14_474.0),
        ];
        let classes =
            rates.map(|(class, rate)| metrics(class, (rate * duration_secs as f64) as u64, 1));
        let deadline_counts = classes.map(|class| class.counts);
        PhaseResult {
            name,
            duration,
            pre_hook_duration: Duration::from_secs(1),
            targets: rates.map(|(class, rate)| RateSpec {
                class,
                target: RatePerSecond::new(rate),
                feed: if name == PhaseName::CatchUp && class != OpClass::CanonicalRead {
                    FeedMode::Closed
                } else {
                    FeedMode::Open
                },
            }),
            summary: PhaseSummaryRecord {
                record_type: "phase_summary",
                phase_id: PhaseId::new(name as u64 + 1),
                duration_nanos: duration.as_nanos() as u64,
                drain_duration_nanos: 0,
                post_deadline_duration_nanos: 0,
                deadline_counts,
                classes,
            },
            intervals: Vec::new(),
            pg: Vec::new(),
        }
    }

    fn thresholds() -> GateThresholds {
        GateThresholds {
            steady_read_p50_ms: 1.0,
            steady_read_p99_ms: 5.0,
            storm_read_p99_ms: 10.0,
            recovery_max_secs: 900,
            catch_up_headroom: 5.0,
            dispatch_p99_ms: 5.0,
            rate_tolerance_percent: 2.0,
            max_read_drift_ratio: 1.2,
            max_backlog_secs: 1.0,
        }
    }

    #[test]
    fn gates_reject_latency_and_catch_up_capacity_regressions() {
        let mut phases = vec![
            result(PhaseName::PeakMix, 10),
            result(PhaseName::MergeStorm, 10),
            result(PhaseName::Recovery, 10),
            result(PhaseName::CatchUp, 10),
        ];
        phases[1].summary.classes[OpClass::CanonicalRead.index()]
            .schedule
            .p99_nanos = 11_000_000;
        phases[3].summary.deadline_counts[OpClass::Merge.index()].achieved = 1;
        let evaluation = evaluate_gates(&phases, thresholds());

        assert!(!evaluation.passed);
        assert!(evaluation
            .checks
            .iter()
            .any(|check| check.name == "storm read p99" && !check.passed));
        assert!(evaluation
            .checks
            .iter()
            .any(|check| check.name == "catch-up merge headroom" && !check.passed));
    }

    #[test]
    fn post_deadline_completions_do_not_satisfy_an_open_rate_gate() {
        let mut peak = result(PhaseName::PeakMix, 10);
        let read = OpClass::CanonicalRead.index();
        peak.summary.deadline_counts[read].completed = 0;
        peak.summary.deadline_counts[read].achieved = 0;

        let evaluation = evaluate_gates(&[peak], thresholds());

        assert!(evaluation.checks.iter().any(|check| {
            check.name == "peak_mix canonical_read achieved rate" && !check.passed
        }));
        assert!(evaluation.checks.iter().any(|check| {
            check.name == "peak_mix canonical_read deadline backlog" && !check.passed
        }));
    }

    #[test]
    fn closed_feed_dispatch_wait_is_not_a_harness_failure() {
        let mut catch_up = result(PhaseName::CatchUp, 10);
        let mut classes = catch_up.summary.classes;
        classes[OpClass::Merge.index()].dispatch_lag = LatencySummary {
            count: 1,
            p99_nanos: 100_000_000,
            ..LatencySummary::default()
        };
        catch_up.intervals.push(IntervalRecord {
            record_type: "interval",
            phase_id: catch_up.summary.phase_id,
            interval_index: 0,
            started_at_nanos: 0,
            ended_at_nanos: 10_000_000_000,
            classes,
        });

        let evaluation = evaluate_gates(&[catch_up], thresholds());

        assert!(!evaluation.harness_limited);
    }

    #[test]
    fn low_rate_poisson_variance_uses_a_statistical_schedule_limit() {
        let mut recovery = result(PhaseName::Recovery, 60);
        recovery.targets[OpClass::Merge.index()].target = RatePerSecond::new(17.2);
        recovery.summary.deadline_counts[OpClass::Merge.index()] = OperationCounts {
            scheduled: 966,
            completed: 966,
            achieved: 966,
            ..OperationCounts::default()
        };

        let evaluation = evaluate_gates(&[recovery], thresholds());

        assert!(evaluation
            .checks
            .iter()
            .any(|check| { check.name == "recovery merge scheduled rate" && check.passed }));
    }

    #[test]
    fn storm_post_deadline_work_is_charged_to_recovery() {
        let mut storm = result(PhaseName::MergeStorm, 60);
        storm.summary.post_deadline_duration_nanos = Duration::from_secs(901).as_nanos() as u64;
        let mut recovery = result(PhaseName::Recovery, 60);
        recovery.pre_hook_duration = Duration::ZERO;
        let mut classes = recovery.summary.classes;
        let read = &mut classes[OpClass::CanonicalRead.index()];
        read.counts.scheduled = 100;
        read.schedule = LatencySummary {
            count: 100,
            p50_nanos: 500_000,
            p99_nanos: 1_000_000,
            ..LatencySummary::default()
        };
        recovery.intervals.push(IntervalRecord {
            record_type: "interval",
            phase_id: recovery.summary.phase_id,
            interval_index: 0,
            started_at_nanos: 0,
            ended_at_nanos: 10_000_000_000,
            classes,
        });

        let evaluation = evaluate_gates(&[storm, recovery], thresholds());

        assert!(evaluation
            .checks
            .iter()
            .any(|check| check.name == "recovery time" && !check.passed));
    }

    #[test]
    fn recovery_ignores_the_pure_drain_interval() {
        let mut recovery = result(PhaseName::Recovery, 10);
        recovery.pre_hook_duration = Duration::ZERO;
        let mut workload_classes = recovery.summary.classes;
        let read = &mut workload_classes[OpClass::CanonicalRead.index()];
        read.counts.scheduled = 100;
        read.schedule = LatencySummary {
            count: 100,
            p50_nanos: 500_000,
            p99_nanos: 1_000_000,
            ..LatencySummary::default()
        };
        recovery.intervals.push(IntervalRecord {
            record_type: "interval",
            phase_id: recovery.summary.phase_id,
            interval_index: 0,
            started_at_nanos: 0,
            ended_at_nanos: 10_000_000_000,
            classes: workload_classes,
        });

        let mut drain_classes = workload_classes;
        let drain_read = &mut drain_classes[OpClass::CanonicalRead.index()];
        drain_read.counts.scheduled = 1;
        drain_read.schedule.p50_nanos = 100_000_000;
        drain_read.schedule.p99_nanos = 100_000_000;
        recovery.intervals.push(IntervalRecord {
            record_type: "interval",
            phase_id: recovery.summary.phase_id,
            interval_index: 1,
            started_at_nanos: 10_000_000_000,
            ended_at_nanos: 11_000_000_000,
            classes: drain_classes,
        });

        assert_eq!(
            recovery_time(&recovery, Duration::ZERO, thresholds()),
            RecoveryOutcome::Recovered(Duration::from_secs(10))
        );
    }

    #[test]
    fn recovery_reports_no_read_traffic_separately() {
        let recovery = result(PhaseName::Recovery, 10);

        assert_eq!(
            recovery_time(&recovery, Duration::ZERO, thresholds()),
            RecoveryOutcome::NoReadTraffic
        );
    }
}
