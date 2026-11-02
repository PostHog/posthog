//! Throughput benchmark of the Rust logs consumer. `run-logs-bench.sh` runs it beside the Node
//! benchmark on the same workload files and reads the result JSON from stdout.
//!
//!   logs-ingestion-bench <workload.json> <measured passes> <warmup passes>
//!
//! It uses jemalloc, as every long-lived PostHog Rust service does. A production binary of this
//! consumer must call `common_alloc::used!()` too: the consumer allocates per record, and the
//! glibc allocator costs about a quarter of its CPU time.

use std::sync::Arc;
use std::time::Instant;

use logs_ingestion::js::{json_parse, json_stringify, JsObject, JsValue};
use logs_ingestion::pipeline::scenario::{build_scenario_consumer, kafka_message};
use logs_ingestion::rate_limiter::{system_clock, RedisTokenBucket, TokenBucketRedis};

common_alloc::used!();

fn cpu_ms() -> f64 {
    let stat = std::fs::read_to_string("/proc/self/stat").unwrap_or_default();
    let after_comm = stat.rsplit_once(')').map(|(_, rest)| rest).unwrap_or("");
    let fields: Vec<&str> = after_comm.split_whitespace().collect();
    let ticks = |i: usize| {
        fields
            .get(i)
            .and_then(|f| f.parse::<f64>().ok())
            .unwrap_or(0.0)
    };
    // utime and stime are fields 14 and 15; `after_comm` starts at field 3. Linux uses 100 ticks/s.
    (ticks(11) + ticks(12)) * 10.0
}

fn peak_rss_mb() -> f64 {
    std::fs::read_to_string("/proc/self/status")
        .unwrap_or_default()
        .lines()
        .find_map(|l| l.strip_prefix("VmHWM:"))
        .and_then(|v| v.trim().trim_end_matches("kB").trim().parse::<f64>().ok())
        .unwrap_or(0.0)
        / 1024.0
}

fn percentile(sorted: &[f64], p: f64) -> f64 {
    sorted[((p / 100.0) * sorted.len() as f64)
        .floor()
        .min(sorted.len() as f64 - 1.0) as usize]
}

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let path = args
        .get(1)
        .expect("usage: logs-ingestion-bench <workload.json> [passes] [warmup]");
    let passes: usize = args.get(2).map_or(10, |p| p.parse().unwrap());
    let warmup: usize = args.get(3).map_or(2, |p| p.parse().unwrap());

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(std::thread::available_parallelism().map_or(4, |n| n.get()))
        .enable_all()
        .build()?;
    runtime.block_on(async move {
        let scenario = json_parse(&std::fs::read_to_string(path)?)?;
        let client = redis::Client::open("redis://127.0.0.1:6379")?;
        let mut conn = client.get_multiplexed_async_connection().await?;
        let _: () = redis::cmd("FLUSHDB").query_async(&mut conn).await?;
        let redis: Arc<dyn TokenBucketRedis> = Arc::new(RedisTokenBucket::new(conn));
        let harness = build_scenario_consumer(&scenario, redis, system_clock(), true);

        let batches: Vec<Vec<_>> = match scenario_field(&scenario, "batches") {
            Some(JsValue::Array(batches)) => batches
                .iter()
                .map(|b| match b {
                    JsValue::Array(ms) => ms.iter().map(kafka_message).collect(),
                    _ => Vec::new(),
                })
                .collect(),
            _ => Vec::new(),
        };
        let messages_per_pass: usize = batches.iter().map(Vec::len).sum();
        let records_per_pass: f64 = batches
            .iter()
            .flatten()
            .map(|m| {
                m.header("record_count")
                    .and_then(|v| v.parse::<f64>().ok())
                    .unwrap_or(0.0)
            })
            .sum();
        let bytes_per_pass: usize = batches
            .iter()
            .flatten()
            .map(|m| m.value.as_ref().map_or(0, |v| v.len()))
            .sum();

        let run_batch = |batch: Vec<_>| {
            let consumer = &harness.consumer;
            async move {
                let processed = consumer.process_kafka_batch(batch).await?;
                if let Some(task) = processed.background_task {
                    task.await?;
                }
                anyhow::Ok(())
            }
        };
        for _ in 0..warmup {
            for batch in &batches {
                run_batch(batch.clone()).await?;
            }
        }
        harness
            .outputs
            .produced_count
            .store(0, std::sync::atomic::Ordering::SeqCst);

        let mut batch_ms = Vec::new();
        let cpu_start = cpu_ms();
        let wall_start = Instant::now();
        for _ in 0..passes {
            for batch in &batches {
                let batch = batch.clone();
                let start = Instant::now();
                run_batch(batch).await?;
                batch_ms.push(start.elapsed().as_secs_f64() * 1000.0);
            }
        }
        let wall_ms = wall_start.elapsed().as_secs_f64() * 1000.0;
        let cpu = cpu_ms() - cpu_start;

        let mut sorted = batch_ms.clone();
        sorted.sort_by(f64::total_cmp);
        let seconds = wall_ms / 1000.0;
        let total = |n: f64| n * passes as f64;
        let mut result = JsObject::new();
        let name = match scenario_field(&scenario, "name") {
            Some(JsValue::String(s)) => s.to_utf8_lossy().into_owned(),
            _ => String::new(),
        };
        for (k, v) in [
            ("implementation", JsValue::string("rust")),
            ("workload", JsValue::string(&name)),
            ("passes", JsValue::Number(passes as f64)),
            ("batches", JsValue::Number(batch_ms.len() as f64)),
            ("messages", JsValue::Number(total(messages_per_pass as f64))),
            ("records", JsValue::Number(total(records_per_pass))),
            ("input_bytes", JsValue::Number(total(bytes_per_pass as f64))),
            (
                "produced",
                JsValue::Number(
                    harness
                        .outputs
                        .produced_count
                        .load(std::sync::atomic::Ordering::SeqCst) as f64,
                ),
            ),
            ("wall_ms", JsValue::Number(wall_ms)),
            ("cpu_ms", JsValue::Number(cpu)),
            ("peak_rss_mb", JsValue::Number(peak_rss_mb())),
            (
                "messages_per_s",
                JsValue::Number(total(messages_per_pass as f64) / seconds),
            ),
            (
                "records_per_s",
                JsValue::Number(total(records_per_pass) / seconds),
            ),
            (
                "input_mb_per_s",
                JsValue::Number(total(bytes_per_pass as f64) / 1024.0 / 1024.0 / seconds),
            ),
        ] {
            result.insert_str(k, v);
        }
        let mut stats = JsObject::new();
        stats.insert_str(
            "mean",
            JsValue::Number(batch_ms.iter().sum::<f64>() / batch_ms.len() as f64),
        );
        for (k, p) in [("p50", 50.0), ("p95", 95.0), ("p99", 99.0)] {
            stats.insert_str(k, JsValue::Number(percentile(&sorted, p)));
        }
        stats.insert_str("max", JsValue::Number(*sorted.last().unwrap_or(&0.0)));
        result.insert_str("batch_ms", JsValue::Object(stats));
        println!("{}", json_stringify(&JsValue::Object(result)));
        anyhow::Ok(())
    })
}

fn scenario_field<'a>(scenario: &'a JsValue, key: &str) -> Option<&'a JsValue> {
    match scenario {
        JsValue::Object(o) => o.get(key),
        _ => None,
    }
}
