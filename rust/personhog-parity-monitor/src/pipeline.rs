//! Owns the join and turns its reports into metrics, which carry outcome
//! labels only, never a team or an id.

use std::collections::HashMap;
use std::time::{Duration, Instant};

use health::HealthHandle;
use personhog_common::cdc_parity::Side;
use tokio::sync::mpsc;
use tokio::time::MissedTickBehavior;

use crate::feed::now_ms;
use crate::join::{side_index, Event, Join, Kind, ObserveReport, SweepReport, Topic};

pub async fn run(
    mut join: Join,
    mut events: mpsc::Receiver<Event>,
    sweep_interval: Duration,
    health: HealthHandle,
) {
    let mut ticker = tokio::time::interval(sweep_interval);
    ticker.set_missed_tick_behavior(MissedTickBehavior::Delay);
    let mut partition_counts: HashMap<Topic, u32> = HashMap::new();
    loop {
        tokio::select! {
            event = events.recv() => {
                let Some(event) = event else {
                    return;
                };
                if let Event::Assigned { topic, partitions } = &event {
                    partition_counts.insert(*topic, *partitions);
                    record_partition_gauges(&partition_counts);
                }
                let topic = event.topic();
                let report = join.observe(event, Instant::now());
                record_observation(topic, &report);
            }
            _ = ticker.tick() => {
                let report = join.settle(Instant::now());
                record_sweep(&report);
                health.report_healthy().await;
            }
        }
    }
}

fn record_partition_gauges(counts: &HashMap<Topic, u32>) {
    for (topic, count) in counts {
        metrics::gauge!(
            "personhog_parity_topic_partitions",
            "feed" => topic.side.label(),
            "topic" => topic.kind.label()
        )
        .set(*count as f64);
    }
    for kind in [Kind::DistinctIds, Kind::MergeEvents, Kind::Persons] {
        let pair = [Side::Node, Side::Personhog].map(|side| counts.get(&Topic { side, kind }));
        if let [Some(node), Some(personhog)] = pair {
            metrics::gauge!(
                "personhog_parity_topic_pair_partitions_equal",
                "topic" => kind.label()
            )
            .set(if node == personhog { 1.0 } else { 0.0 });
        }
    }
}

fn record_observation(topic: Topic, report: &ObserveReport) {
    let feed = topic.side.label();
    if report.filtered {
        metrics::counter!("personhog_parity_filtered_total", "feed" => feed, "topic" => topic.kind.label())
            .increment(1);
    }
    if report.sampled_out {
        metrics::counter!("personhog_parity_sampled_out_total", "feed" => feed, "topic" => topic.kind.label())
            .increment(1);
    }
    if let Some(side) = report.version_tie {
        metrics::counter!("personhog_parity_version_ties_total", "feed" => side.label())
            .increment(1);
    }
    if let Some(side) = report.merge_conflict {
        metrics::counter!("personhog_parity_merge_conflicts_total", "feed" => side.label())
            .increment(1);
    }
    if let Some((side, expected)) = report.placement {
        metrics::counter!(
            "personhog_parity_merge_placement_total",
            "feed" => side.label(),
            "outcome" => if expected { "expected" } else { "unexpected" }
        )
        .increment(1);
    }
}

fn record_sweep(report: &SweepReport) {
    for (outcome, count) in &report.mapping_outcomes {
        metrics::counter!("personhog_parity_settled_mappings_total", "outcome" => outcome.label())
            .increment(*count);
    }
    for (outcome, count) in &report.merge_outcomes {
        metrics::counter!("personhog_parity_settled_merges_total", "outcome" => outcome.label())
            .increment(*count);
    }
    for (outcome, count) in &report.person_outcomes {
        metrics::counter!("personhog_parity_settled_persons_total", "outcome" => outcome.label())
            .increment(*count);
    }
    for (agreement, count) in &report.merge_partitions {
        metrics::counter!("personhog_parity_merge_partition_total", "outcome" => agreement.label())
            .increment(*count);
    }
    if report.overflow_evictions > 0 {
        metrics::counter!("personhog_parity_overflow_evictions_total")
            .increment(report.overflow_evictions);
    }
    if report.warmup_evictions > 0 {
        metrics::counter!("personhog_parity_warmup_evictions_total")
            .increment(report.warmup_evictions);
    }
    metrics::gauge!("personhog_parity_pending_entries", "kind" => "mappings")
        .set(report.pending_mappings as f64);
    metrics::gauge!("personhog_parity_pending_entries", "kind" => "merges")
        .set(report.pending_merges as f64);
    metrics::gauge!("personhog_parity_pending_entries", "kind" => "persons")
        .set(report.pending_persons as f64);
    let now = now_ms();
    for side in [Side::Node, Side::Personhog] {
        if let Some(watermark) = report.feed_watermarks_ms[side_index(side)] {
            metrics::gauge!("personhog_parity_watermark_age_seconds", "feed" => side.label())
                .set((now - watermark).max(0) as f64 / 1000.0);
        }
        if let Some(watermark) = report.person_watermarks_ms[side_index(side)] {
            metrics::gauge!("personhog_parity_person_watermark_age_seconds", "feed" => side.label())
                .set((now - watermark).max(0) as f64 / 1000.0);
        }
    }
}
