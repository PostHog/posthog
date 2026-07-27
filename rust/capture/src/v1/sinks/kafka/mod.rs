//! Per-sink Kafka configuration for the v1 ingress. The transport itself is
//! the shared outputs machinery ([`crate::outputs::kafka::KafkaOutputs`]);
//! only the `CAPTURE_V1_SINK_*` env config surface lives here.

pub mod config;
