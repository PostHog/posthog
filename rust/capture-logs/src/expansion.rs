//! Request-wide budget for the rows a request expands into.
//!
//! A body size cap bounds the input bytes only. OTLP shares one resource and one scope between
//! many records, and every row gets its own copy of them, so a small body can still build a very
//! large set of rows. The handlers estimate the expanded size from the decoded request and reject
//! it before they build any row.

use opentelemetry_proto::tonic::collector::logs::v1::ExportLogsServiceRequest;
use opentelemetry_proto::tonic::collector::metrics::v1::ExportMetricsServiceRequest;
use opentelemetry_proto::tonic::collector::trace::v1::ExportTraceServiceRequest;
use opentelemetry_proto::tonic::common::v1::{InstrumentationScope, KeyValue};
use opentelemetry_proto::tonic::metrics::v1::metric::Data;
use opentelemetry_proto::tonic::resource::v1::Resource;
use prost::Message;

/// Fixed cost of one row: the uuid, ids, timestamps and the map and string headers that every row
/// allocates, whatever its content.
pub const ROW_OVERHEAD_BYTES: u64 = 256;

/// Fixed cost of one attribute in a row map: two string headers and the hash table slot.
pub const ATTRIBUTE_OVERHEAD_BYTES: u64 = 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ExpansionExceeded {
    pub limit: u64,
}

/// Adds row costs and fails as soon as the total goes over the limit, so a caller can stop before
/// it builds the row that does not fit.
#[derive(Debug)]
pub struct ExpansionBudget {
    limit: u64,
    used: u64,
}

impl ExpansionBudget {
    pub fn new(limit: u64) -> Self {
        Self { limit, used: 0 }
    }

    pub fn used(&self) -> u64 {
        self.used
    }

    pub fn charge(&mut self, bytes: u64) -> Result<(), ExpansionExceeded> {
        self.used = self.used.saturating_add(bytes);
        if self.used > self.limit {
            return Err(ExpansionExceeded { limit: self.limit });
        }
        Ok(())
    }

    /// Charges `count` rows of `bytes_per_row` each in one step.
    pub fn charge_rows(&mut self, count: u64, bytes_per_row: u64) -> Result<(), ExpansionExceeded> {
        self.charge(count.saturating_mul(bytes_per_row))
    }
}

fn len_u64(len: usize) -> u64 {
    u64::try_from(len).unwrap_or(u64::MAX)
}

/// The protobuf size of each attribute is a proxy for the size of its string form in the row.
pub fn attributes_cost(attributes: &[KeyValue]) -> u64 {
    attributes.iter().fold(0u64, |total, kv| {
        total
            .saturating_add(len_u64(kv.encoded_len()))
            .saturating_add(ATTRIBUTE_OVERHEAD_BYTES)
    })
}

pub fn resource_cost(resource: Option<&Resource>) -> u64 {
    resource.map_or(0, |r| attributes_cost(&r.attributes))
}

/// A row keeps only `name@version` from the scope.
pub fn scope_cost(scope: Option<&InstrumentationScope>) -> u64 {
    scope.map_or(0, |s| {
        len_u64(s.name.len())
            .saturating_add(len_u64(s.version.len()))
            .saturating_add(1)
    })
}

pub fn check_logs_request(
    request: &ExportLogsServiceRequest,
    limit: u64,
) -> Result<u64, ExpansionExceeded> {
    let mut budget = ExpansionBudget::new(limit);
    for resource_logs in &request.resource_logs {
        let resource = resource_cost(resource_logs.resource.as_ref());
        for scope_logs in &resource_logs.scope_logs {
            let shared = resource.saturating_add(scope_cost(scope_logs.scope.as_ref()));
            for record in &scope_logs.log_records {
                let own = len_u64(record.encoded_len()).saturating_add(
                    len_u64(record.attributes.len()).saturating_mul(ATTRIBUTE_OVERHEAD_BYTES),
                );
                budget.charge(
                    shared
                        .saturating_add(own)
                        .saturating_add(ROW_OVERHEAD_BYTES),
                )?;
            }
        }
    }
    Ok(budget.used())
}

pub fn check_traces_request(
    request: &ExportTraceServiceRequest,
    limit: u64,
) -> Result<u64, ExpansionExceeded> {
    let mut budget = ExpansionBudget::new(limit);
    for resource_spans in &request.resource_spans {
        let resource = resource_cost(resource_spans.resource.as_ref());
        for scope_spans in &resource_spans.scope_spans {
            let shared = resource.saturating_add(scope_cost(scope_spans.scope.as_ref()));
            for span in &scope_spans.spans {
                let own = len_u64(span.encoded_len()).saturating_add(
                    len_u64(span.attributes.len()).saturating_mul(ATTRIBUTE_OVERHEAD_BYTES),
                );
                budget.charge(
                    shared
                        .saturating_add(own)
                        .saturating_add(ROW_OVERHEAD_BYTES),
                )?;
            }
        }
    }
    Ok(budget.used())
}

/// A metric becomes one row per data point, and each row copies the resource, the scope and the
/// metric name and unit.
pub fn check_metrics_request(
    request: &ExportMetricsServiceRequest,
    limit: u64,
) -> Result<u64, ExpansionExceeded> {
    let mut budget = ExpansionBudget::new(limit);
    for resource_metrics in &request.resource_metrics {
        let resource = resource_cost(resource_metrics.resource.as_ref());
        for scope_metrics in &resource_metrics.scope_metrics {
            let scope = resource.saturating_add(scope_cost(scope_metrics.scope.as_ref()));
            for metric in &scope_metrics.metrics {
                let shared = scope
                    .saturating_add(len_u64(metric.name.len()))
                    .saturating_add(len_u64(metric.unit.len()))
                    .saturating_add(ROW_OVERHEAD_BYTES);
                let point_cost = |encoded_len: usize, attributes: &[KeyValue]| {
                    shared.saturating_add(len_u64(encoded_len)).saturating_add(
                        len_u64(attributes.len()).saturating_mul(ATTRIBUTE_OVERHEAD_BYTES),
                    )
                };
                match &metric.data {
                    Some(Data::Gauge(g)) => {
                        for dp in &g.data_points {
                            budget.charge(point_cost(dp.encoded_len(), &dp.attributes))?;
                        }
                    }
                    Some(Data::Sum(s)) => {
                        for dp in &s.data_points {
                            budget.charge(point_cost(dp.encoded_len(), &dp.attributes))?;
                        }
                    }
                    Some(Data::Histogram(h)) => {
                        for dp in &h.data_points {
                            budget.charge(point_cost(dp.encoded_len(), &dp.attributes))?;
                        }
                    }
                    Some(Data::ExponentialHistogram(h)) => {
                        for dp in &h.data_points {
                            budget.charge(point_cost(dp.encoded_len(), &dp.attributes))?;
                        }
                    }
                    Some(Data::Summary(s)) => {
                        for dp in &s.data_points {
                            budget.charge(point_cost(dp.encoded_len(), &dp.attributes))?;
                        }
                    }
                    None => {}
                }
            }
        }
    }
    Ok(budget.used())
}

#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry_proto::tonic::common::v1::{any_value, AnyValue};
    use opentelemetry_proto::tonic::logs::v1::{LogRecord, ResourceLogs, ScopeLogs};
    use opentelemetry_proto::tonic::trace::v1::{ResourceSpans, ScopeSpans, Span};

    fn resource_with_value_of(len: usize) -> Resource {
        Resource {
            attributes: vec![KeyValue {
                key: "k".to_string(),
                value: Some(AnyValue {
                    value: Some(any_value::Value::StringValue("x".repeat(len))),
                }),
            }],
            ..Default::default()
        }
    }

    fn logs_request(resource_len: usize, records: usize) -> ExportLogsServiceRequest {
        ExportLogsServiceRequest {
            resource_logs: vec![ResourceLogs {
                resource: Some(resource_with_value_of(resource_len)),
                scope_logs: vec![ScopeLogs {
                    log_records: vec![LogRecord::default(); records],
                    ..Default::default()
                }],
                ..Default::default()
            }],
        }
    }

    fn traces_request(resource_len: usize, spans: usize) -> ExportTraceServiceRequest {
        ExportTraceServiceRequest {
            resource_spans: vec![ResourceSpans {
                resource: Some(resource_with_value_of(resource_len)),
                scope_spans: vec![ScopeSpans {
                    spans: vec![Span::default(); spans],
                    ..Default::default()
                }],
                ..Default::default()
            }],
        }
    }

    #[test]
    fn budget_rejects_only_past_the_limit() {
        let mut budget = ExpansionBudget::new(100);
        assert!(budget.charge(100).is_ok());
        assert_eq!(budget.charge(1), Err(ExpansionExceeded { limit: 100 }));
    }

    #[test]
    fn budget_saturates_instead_of_wrapping() {
        let mut budget = ExpansionBudget::new(u64::MAX - 1);
        assert!(budget.charge_rows(u64::MAX, u64::MAX).is_err());
    }

    #[test]
    fn logs_charge_the_shared_resource_once_per_record() {
        let one = check_logs_request(&logs_request(10_000, 1), u64::MAX).unwrap();
        let hundred = check_logs_request(&logs_request(10_000, 100), u64::MAX).unwrap();

        assert!(one > 10_000);
        assert_eq!(hundred, one * 100);
    }

    #[test]
    fn logs_with_a_small_body_but_a_large_expansion_are_rejected() {
        let request = logs_request(64 * 1024, 2_000);
        assert!(request.encoded_len() < 128 * 1024);

        assert!(check_logs_request(&request, 64 * 1024 * 1024).is_err());
    }

    #[test]
    fn traces_with_a_small_body_but_a_large_expansion_are_rejected() {
        let request = traces_request(64 * 1024, 2_000);
        assert!(request.encoded_len() < 128 * 1024);

        assert!(check_traces_request(&request, 64 * 1024 * 1024).is_err());
    }

    #[test]
    fn metrics_charge_the_shared_resource_once_per_data_point() {
        use opentelemetry_proto::tonic::metrics::v1::{
            Gauge, Metric, NumberDataPoint, ResourceMetrics, ScopeMetrics,
        };
        let request = |points: usize| ExportMetricsServiceRequest {
            resource_metrics: vec![ResourceMetrics {
                resource: Some(resource_with_value_of(64 * 1024)),
                scope_metrics: vec![ScopeMetrics {
                    metrics: vec![Metric {
                        name: "m".to_string(),
                        data: Some(Data::Gauge(Gauge {
                            data_points: vec![NumberDataPoint::default(); points],
                        })),
                        ..Default::default()
                    }],
                    ..Default::default()
                }],
                ..Default::default()
            }],
        };

        let one = check_metrics_request(&request(1), u64::MAX).unwrap();
        assert_eq!(
            check_metrics_request(&request(10), u64::MAX).unwrap(),
            one * 10
        );
        assert!(check_metrics_request(&request(2_000), 64 * 1024 * 1024).is_err());
    }

    #[test]
    fn typical_batches_fit_the_default_limit() {
        let limit = 128 * 1024 * 1024;
        assert!(check_logs_request(&logs_request(2 * 1024, 10_000), limit).is_ok());
        assert!(check_traces_request(&traces_request(2 * 1024, 10_000), limit).is_ok());
    }
}
