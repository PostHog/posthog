use std::sync::Arc;

use metrics::{counter, gauge};
use rdkafka::error::KafkaError;
use tracing::error;

use super::types::error_code_tag;
use crate::v1::sinks::SinkName;

const BROKER_STATE_UP: &str = "UP";

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
            "capture_v1_kafka_client_errors_total",
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
                "capture_v1_kafka_client_errors_total",
                "cluster" => sink,
                "mode" => mode,
                "error" => "all_brokers_down",
            )
            .increment(1);
        }

        // metric label key "cluster" kept for dashboard backward compatibility
        gauge!("capture_v1_kafka_producer_queue_depth",
            "cluster" => sink, "mode" => mode)
        .set(stats.msg_cnt as f64);
        gauge!("capture_v1_kafka_producer_queue_bytes",
            "cluster" => sink, "mode" => mode)
        .set(stats.msg_size as f64);
        if stats.msg_max > 0 {
            gauge!("capture_v1_kafka_producer_queue_utilization",
                "cluster" => sink, "mode" => mode)
            .set(stats.msg_cnt as f64 / stats.msg_max as f64);
        }

        for (topic, ts) in stats.topics {
            gauge!("capture_v1_kafka_batch_size_bytes_avg",
                "cluster" => sink, "mode" => mode, "topic" => topic)
            .set(ts.batchsize.avg as f64);
        }

        for bs in stats.brokers.values() {
            let id: Arc<str> = Arc::from(bs.nodeid.to_string());
            gauge!("capture_v1_kafka_broker_connected",
                "cluster" => sink, "mode" => mode, "broker" => Arc::clone(&id))
            .set(if bs.state == BROKER_STATE_UP {
                1.0
            } else {
                0.0
            });
            if let Some(rtt) = &bs.rtt {
                gauge!("capture_v1_kafka_broker_rtt_us",
                    "cluster" => sink, "mode" => mode,
                    "quantile" => "p50", "broker" => Arc::clone(&id))
                .set(rtt.p50 as f64);
                gauge!("capture_v1_kafka_broker_rtt_us",
                    "cluster" => sink, "mode" => mode,
                    "quantile" => "p99", "broker" => Arc::clone(&id))
                .set(rtt.p99 as f64);
            }
            counter!("capture_v1_kafka_broker_tx_errors_total",
                "cluster" => sink, "mode" => mode, "broker" => Arc::clone(&id))
            .absolute(bs.txerrs);
            counter!("capture_v1_kafka_broker_rx_errors_total",
                "cluster" => sink, "mode" => mode, "broker" => id)
            .absolute(bs.rxerrs);
        }
    }
}
