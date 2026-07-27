use std::sync::Arc;

use metrics::{counter, gauge};
use rdkafka::error::KafkaError;
use tracing::error;

use super::constants::*;
use super::types::error_code_tag;
use crate::v1::sinks::SinkName;

const BROKER_STATE_UP: &str = "UP";

/// Emit min/avg/max/stddev + p50/p90/p95/p99 gauges for an rdkafka window
/// stat, tagged by `quantile` and `broker`.
fn emit_window_stats(
    metric: &'static str,
    w: &rdkafka::statistics::Window,
    sink: &'static str,
    mode: &'static str,
    broker: &Arc<str>,
) {
    for (quantile, value) in [
        ("min", w.min),
        ("avg", w.avg),
        ("max", w.max),
        ("stddev", w.stddev),
        ("p50", w.p50),
        ("p90", w.p90),
        ("p95", w.p95),
        ("p99", w.p99),
    ] {
        gauge!(
            metric,
            "cluster" => sink,
            "mode" => mode,
            "quantile" => quantile,
            "broker" => Arc::clone(broker),
        )
        .set(value as f64);
    }
}

// ---------------------------------------------------------------------------
// KafkaContext
// ---------------------------------------------------------------------------

pub(crate) struct KafkaContext {
    handle: lifecycle::Handle,
    sink: SinkName,
    mode: &'static str,
}

impl KafkaContext {
    pub fn new(handle: lifecycle::Handle, sink: SinkName, mode: &'static str) -> Self {
        Self { handle, sink, mode }
    }
}

impl rdkafka::ClientContext for KafkaContext {
    fn error(&self, err: KafkaError, reason: &str) {
        let sink = self.sink.as_str();
        let mode = self.mode;
        let tag = err
            .rdkafka_error_code()
            .map(error_code_tag)
            .unwrap_or("unknown");
        error!(
            sink = sink,
            mode = mode,
            error = %err,
            error_tag = tag,
            reason = reason,
            "rdkafka client error"
        );
        counter!(
            KAFKA_CLIENT_ERRORS_TOTAL,
            "cluster" => sink,
            "mode" => mode,
            "error" => tag,
        )
        .increment(1);
    }

    fn stats(&self, stats: rdkafka::Statistics) {
        let sink = self.sink.as_str();
        let mode = self.mode;

        let brokers_up = stats.brokers.values().any(|b| b.state == BROKER_STATE_UP);
        if brokers_up {
            self.handle.report_healthy();
        } else if !stats.brokers.is_empty() {
            error!(
                sink = sink,
                mode = mode,
                broker_count = stats.brokers.len(),
                "all brokers DOWN for sink"
            );
            counter!(
                KAFKA_CLIENT_ERRORS_TOTAL,
                "cluster" => sink,
                "mode" => mode,
                "error" => "all_brokers_down",
            )
            .increment(1);
        }

        // metric label key "cluster" kept for dashboard backward compatibility
        gauge!(KAFKA_PRODUCER_QUEUE_DEPTH,
            "cluster" => sink, "mode" => mode)
        .set(stats.msg_cnt as f64);
        gauge!(KAFKA_PRODUCER_QUEUE_BYTES,
            "cluster" => sink, "mode" => mode)
        .set(stats.msg_size as f64);
        if stats.msg_max > 0 {
            gauge!(KAFKA_PRODUCER_QUEUE_UTILIZATION,
                "cluster" => sink, "mode" => mode)
            .set(stats.msg_cnt as f64 / stats.msg_max as f64);
        }

        for (topic, ts) in stats.topics {
            gauge!(KAFKA_BATCH_SIZE_BYTES_AVG,
                "cluster" => sink, "mode" => mode, "topic" => topic)
            .set(ts.batchsize.avg as f64);
        }

        for bs in stats.brokers.values() {
            let id: Arc<str> = Arc::from(bs.nodeid.to_string());
            gauge!(KAFKA_BROKER_CONNECTED,
                "cluster" => sink, "mode" => mode, "broker" => Arc::clone(&id))
            .set(if bs.state == BROKER_STATE_UP {
                1.0
            } else {
                0.0
            });
            // Broker round-trip latency.
            if let Some(rtt) = &bs.rtt {
                emit_window_stats(KAFKA_BROKER_RTT_US, rtt, sink, mode, &id);
            }
            // Internal queue time (linger + backlog).
            if let Some(int_latency) = &bs.int_latency {
                emit_window_stats(KAFKA_BROKER_INT_LATENCY_US, int_latency, sink, mode, &id);
            }
            // Output buffer time before wire send.
            if let Some(outbuf_latency) = &bs.outbuf_latency {
                emit_window_stats(
                    KAFKA_BROKER_OUTBUF_LATENCY_US,
                    outbuf_latency,
                    sink,
                    mode,
                    &id,
                );
            }
            counter!(KAFKA_BROKER_TX_ERRORS_TOTAL,
                "cluster" => sink, "mode" => mode, "broker" => Arc::clone(&id))
            .absolute(bs.txerrs);
            counter!(KAFKA_BROKER_RX_ERRORS_TOTAL,
                "cluster" => sink, "mode" => mode, "broker" => id)
            .absolute(bs.rxerrs);
        }
    }
}
