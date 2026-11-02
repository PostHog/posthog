//! Port of `nodejs/src/logs/metrics-rules/`: log-generated metrics.
//!
//! - `compile`: `compile-metric-rules.ts` (`compileMetricRules`, row validation).
//! - `defaults`: `default-metric-rules.ts` (`withDefaultMetricRules`).
//! - `tally`: `tally.ts` (`tallyRecords`, `createBatchTallies`, `idToHex`).
//! - `admission`: `MetricSeriesAdmission` from `tally.ts`.
//! - `otlp_payload`: `otlp-payload.ts` (`buildMetricRulesOtlpPayload`).
//! - `emitter`: `metrics-emitter.ts` (`LogsMetricsEmitter`), over a transport trait.
//! - `source`: the interface of `metric-rules-cache.ts`. The Postgres cache is not ported.
//!
//! The filter-group parser and matcher belong to `crate::sampling` and `crate::filter_group`.
//! This module reaches them only through `FilterGroupMatcher` and `FilterGroupParser`.
//! A JavaScript throw is `crate::property_filter::coerce::JsTypeError`.

mod admission;
mod compile;
mod defaults;
mod emitter;
mod filter;
mod ordered;
mod otlp_payload;
mod parse_float;
mod source;
mod tally;

pub use admission::{
    MetricSeriesAdmission, MAX_ADMITTED_LABEL_SETS, MAX_ADMITTED_LABEL_SETS_PER_TEAM,
};
pub use compile::{
    compile_metric_rules, compile_metric_rules_with, CompiledMetricRule, MetricRuleRow,
    MetricRuleSource, LOG_GROUP_BY_TOP_LEVEL_KEYS, MAX_GROUP_BY_KEYS, SPAN_GROUP_BY_TOP_LEVEL_KEYS,
};
pub use defaults::{default_metric_rules, with_default_metric_rules};
pub use emitter::{LogsMetricsEmitter, MetricsEmitter, OtlpTransport, EXPORT_FAILED_COUNTER};
pub use filter::{parse_filter_group, FilterGroupMatcher, FilterGroupParser};
pub use ordered::InsertionMap;
pub use otlp_payload::build_metric_rules_otlp_payload;
pub use parse_float::js_parse_float;
pub use source::MetricRulesSource;
pub use tally::{
    id_to_hex, resolve_label_value, tally_records, AdmitLabelSet, BatchTallies, LabelValue,
    MetricTallyEntry, DEFAULT_HISTOGRAM_BOUNDS, MAX_LABEL_SETS_PER_RULE, MAX_LABEL_VALUE_LENGTH,
    MAX_RECORD_AGE_MS, OVERFLOW_LABEL_KEY, SPAN_VALUE_DURATION_MS,
};
