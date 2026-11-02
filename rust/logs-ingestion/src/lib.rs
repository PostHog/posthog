//! Rust port of the Node logs ingestion consumer in `nodejs/src/logs`.
//!
//! The two implementations are kept 1:1 by the shared parity corpus in
//! `nodejs/src/logs/parity/fixtures`: the same messages in must give the same messages out.
//! `PORTING.md` maps each TypeScript file to its module and lists the JavaScript semantics
//! that the port reproduces.

pub mod attribute_value;
pub mod avro;
pub mod body_parse;
pub mod content_weights;
pub mod filter_group;
pub mod internal_logs;
pub mod js;
pub mod metric_rules;
pub mod normalize;
pub mod pattern;
pub mod pii;
pub mod pipeline;
pub mod property_filter;
pub mod rate_limiter;
pub mod record;
pub mod retention;
pub mod sampling;
