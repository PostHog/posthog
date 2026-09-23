//! librdkafka's statistics from the fenced changelog producers, exported
//! as metrics so a slow produce can be split between the socket, the
//! broker, and the client's own queues.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use metrics::{counter, histogram};
use rdkafka::client::ClientContext;
use rdkafka::statistics::{Broker, Statistics, Window};

const WINDOW_MS: &str = "personhog_leader_fenced_producer_window_ms";
const REQUESTS_TOTAL: &str = "personhog_leader_fenced_producer_requests_total";
const BROKER_EVENTS_TOTAL: &str = "personhog_leader_fenced_producer_broker_events_total";

/// Consumes the statistics callbacks of one fenced producer. The counters
/// in a callback are cumulative for the client's lifetime, so the context
/// keeps the last values and reports the deltas.
#[derive(Default)]
pub struct FencedProducerContext {
    last: Mutex<HashMap<String, i64>>,
}

impl ClientContext for FencedProducerContext {
    fn stats(&self, stats: Statistics) {
        let mut last = self.last.lock().unwrap_or_else(|e| e.into_inner());
        for broker in stats.brokers.values() {
            let node: Arc<str> = Arc::from(broker_label(broker));
            record_window(&node, "rtt", broker.rtt.as_ref(), 1000.0);
            record_window(&node, "throttle", broker.throttle.as_ref(), 1.0);
            record_window(&node, "int_latency", broker.int_latency.as_ref(), 1000.0);
            record_window(
                &node,
                "outbuf_latency",
                broker.outbuf_latency.as_ref(),
                1000.0,
            );
            for (request, delta) in request_deltas(&mut last, broker) {
                counter!(REQUESTS_TOTAL, "broker" => node.clone(), "type" => request)
                    .increment(delta);
            }
            for (event, delta) in event_deltas(&mut last, broker) {
                counter!(BROKER_EVENTS_TOTAL, "broker" => node.clone(), "event" => event)
                    .increment(delta);
            }
        }
    }
}

/// The node id of a real broker, the logical name of a coordinator
/// connection, which is where the transaction requests are counted, or
/// one bucket for the bootstrap addresses.
fn broker_label(broker: &Broker) -> String {
    if broker.nodeid >= 0 {
        broker.nodeid.to_string()
    } else if matches!(broker.name.as_str(), "GroupCoordinator" | "TxnCoordinator") {
        broker.name.clone()
    } else {
        "bootstrap".to_string()
    }
}

/// One window's average and maximum, in milliseconds. librdkafka reports
/// latencies in microseconds and throttling in milliseconds.
fn record_window(node: &Arc<str>, window: &'static str, stats: Option<&Window>, per_ms: f64) {
    let Some(stats) = stats else {
        return;
    };
    if stats.cnt == 0 {
        return;
    }
    for (agg, value) in [("avg", stats.avg), ("max", stats.max)] {
        histogram!(WINDOW_MS, "broker" => node.clone(), "window" => window, "agg" => agg)
            .record(value as f64 / per_ms);
    }
}

/// Requests sent to the broker since the last callback, by request type.
fn request_deltas(last: &mut HashMap<String, i64>, broker: &Broker) -> Vec<(Arc<str>, u64)> {
    let mut deltas: Vec<(Arc<str>, u64)> = broker
        .req
        .iter()
        .filter_map(|(request, &count)| {
            let delta = advance(last, format!("{}/req/{request}", broker.name), count);
            (delta > 0).then(|| (Arc::from(request.as_str()), delta))
        })
        .collect();
    deltas.sort();
    deltas
}

/// Retries, timeouts, errors, and disconnects since the last callback.
fn event_deltas(last: &mut HashMap<String, i64>, broker: &Broker) -> Vec<(&'static str, u64)> {
    [
        ("tx_retry", broker.txretries as i64),
        ("req_timeout", broker.req_timeouts as i64),
        ("tx_error", broker.txerrs as i64),
        ("rx_error", broker.rxerrs as i64),
        ("disconnect", broker.disconnects.unwrap_or(0)),
    ]
    .into_iter()
    .filter_map(|(event, count)| {
        let delta = advance(last, format!("{}/event/{event}", broker.name), count);
        (delta > 0).then_some((event, delta))
    })
    .collect()
}

/// The increase of a cumulative counter since its last value.
fn advance(last: &mut HashMap<String, i64>, key: String, current: i64) -> u64 {
    let previous = last.insert(key, current).unwrap_or(0);
    current.saturating_sub(previous).max(0) as u64
}

#[cfg(test)]
mod tests {
    use super::*;

    fn broker(nodeid: i32, produce: i64, retries: u64) -> Broker {
        Broker {
            name: format!("broker-{nodeid}"),
            nodeid,
            req: HashMap::from([("Produce".to_string(), produce)]),
            txretries: retries,
            ..Broker::default()
        }
    }

    #[test]
    fn deltas_report_only_the_increase_since_the_last_callback() {
        let mut last = HashMap::new();
        assert_eq!(
            request_deltas(&mut last, &broker(1, 10, 2)),
            vec![(Arc::from("Produce"), 10)]
        );
        assert_eq!(
            event_deltas(&mut last, &broker(1, 10, 2)),
            vec![("tx_retry", 2)]
        );
        assert_eq!(
            request_deltas(&mut last, &broker(1, 13, 2)),
            vec![(Arc::from("Produce"), 3)]
        );
        assert!(event_deltas(&mut last, &broker(1, 13, 2)).is_empty());
    }

    #[test]
    fn coordinator_connections_are_labeled_by_name() {
        assert_eq!(broker_label(&broker(2, 0, 0)), "2");
        let coordinator = Broker {
            name: "TxnCoordinator".to_string(),
            nodeid: -1,
            ..Broker::default()
        };
        assert_eq!(broker_label(&coordinator), "TxnCoordinator");
        for name in [
            "ssl://broker.example:9096/bootstrap",
            "ssl://TxnCoordinator.example:9096/bootstrap",
        ] {
            let bootstrap = Broker {
                name: name.to_string(),
                nodeid: -1,
                ..Broker::default()
            };
            assert_eq!(broker_label(&bootstrap), "bootstrap", "{name}");
        }
    }

    #[test]
    fn brokers_keep_separate_counters() {
        let mut last = HashMap::new();
        request_deltas(&mut last, &broker(1, 10, 0));
        assert_eq!(
            request_deltas(&mut last, &broker(2, 4, 0)),
            vec![(Arc::from("Produce"), 4)]
        );
    }
}
