use bytes::Bytes;
use capture_logs::service::parse_otel_metrics_message;
use opentelemetry_proto::tonic::metrics::v1::metric::Data;

/// When an OTLP/JSON payload mixes a sum (counter) and a histogram, the
/// histogram's `Metric.data` was silently set to `None` after deserialization
/// while the counter's survived — even though parsing returned `Ok`.
/// See opentelemetry-rust#3328 for the upstream root cause.
#[test]
fn histogram_with_string_u64s_alongside_sum() {
    let json = r#"{
      "resourceMetrics":[{
        "resource":{"attributes":[{"key":"service.name","value":{"stringValue":"demo"}}]},
        "scopeMetrics":[{
          "scope":{"name":"x"},
          "metrics":[
            {"name":"demo.counter","sum":{
              "aggregationTemporality":2,
              "isMonotonic":true,
              "dataPoints":[{"timeUnixNano":"1700000000000000000","asDouble":42.0}]
            }},
            {"name":"demo.histogram","histogram":{
              "aggregationTemporality":2,
              "dataPoints":[{
                "timeUnixNano":"1700000000000000000",
                "count":"10",
                "sum":234.5,
                "bucketCounts":["3","4","2","1"],
                "explicitBounds":[10,50,100]
              }]
            }}
          ]
        }]
      }]
    }"#;

    let result = parse_otel_metrics_message(&Bytes::from(json));
    let request = match result {
        Ok(r) => r,
        Err(e) => panic!("parse_otel_metrics_message returned Err: {e}"),
    };

    let metrics = &request.resource_metrics[0].scope_metrics[0].metrics;
    assert_eq!(metrics.len(), 2, "both metrics should be present");

    let counter = &metrics[0];
    let histogram = &metrics[1];

    eprintln!("counter.data is_some = {}", counter.data.is_some());
    eprintln!("histogram.data is_some = {}", histogram.data.is_some());
    if let Some(Data::Histogram(h)) = &histogram.data {
        eprintln!("histogram.data_points.len = {}", h.data_points.len());
        if let Some(dp) = h.data_points.first() {
            eprintln!(
                "dp.count={} sum={:?} bucket_counts={:?} explicit_bounds={:?}",
                dp.count, dp.sum, dp.bucket_counts, dp.explicit_bounds
            );
        }
    }

    assert!(
        matches!(histogram.data, Some(Data::Histogram(_))),
        "histogram.data is None — silently dropped during JSON deserialization"
    );
}

/// Same payload as the bug ticket but with the histogram's u64 fields encoded
/// as JSON numbers instead of strings. If this passes, it proves the silent
/// drop is caused by string-encoded u64 fields (count, bucketCounts) lacking a
/// custom serde deserializer in upstream opentelemetry-proto.
#[test]
fn histogram_with_unquoted_u64_works() {
    let json = r#"{
      "resourceMetrics":[{
        "resource":{"attributes":[]},
        "scopeMetrics":[{
          "scope":{"name":"x"},
          "metrics":[
            {"name":"demo.histogram","histogram":{
              "aggregationTemporality":2,
              "dataPoints":[{
                "timeUnixNano":"1700000000000000000",
                "count":10,
                "sum":234.5,
                "bucketCounts":[3,4,2,1],
                "explicitBounds":[10,50,100]
              }]
            }}
          ]
        }]
      }]
    }"#;

    let request = parse_otel_metrics_message(&Bytes::from(json)).expect("parse ok");
    let histogram = &request.resource_metrics[0].scope_metrics[0].metrics[0];
    eprintln!(
        "unquoted-u64 path: histogram.data is_some = {}",
        histogram.data.is_some()
    );
    assert!(matches!(histogram.data, Some(Data::Histogram(_))));
}

#[test]
fn exponential_histogram_with_string_u64s() {
    let json = r#"{
      "resourceMetrics":[{
        "resource":{"attributes":[]},
        "scopeMetrics":[{
          "scope":{"name":"x"},
          "metrics":[
            {"name":"demo.expo","exponentialHistogram":{
              "aggregationTemporality":2,
              "dataPoints":[{
                "timeUnixNano":"1700000000000000000",
                "startTimeUnixNano":"1700000000000000000",
                "count":"5",
                "sum":11.5,
                "scale":1,
                "zeroCount":"0",
                "positive":{"offset":0,"bucketCounts":["1","2","2"]}
              }]
            }}
          ]
        }]
      }]
    }"#;

    let request = parse_otel_metrics_message(&Bytes::from(json)).expect("parse ok");
    let metric = &request.resource_metrics[0].scope_metrics[0].metrics[0];
    eprintln!("expo.data is_some = {}", metric.data.is_some());
    if let Some(Data::ExponentialHistogram(eh)) = &metric.data {
        eprintln!("expo.data_points.len = {}", eh.data_points.len());
        if let Some(dp) = eh.data_points.first() {
            eprintln!(
                "dp.count={} sum={:?} scale={} zero_count={} positive={:?}",
                dp.count, dp.sum, dp.scale, dp.zero_count, dp.positive
            );
        }
    }
    assert!(matches!(metric.data, Some(Data::ExponentialHistogram(_))));
}

#[test]
fn summary_with_string_u64s() {
    let json = r#"{
      "resourceMetrics":[{
        "resource":{"attributes":[]},
        "scopeMetrics":[{
          "scope":{"name":"x"},
          "metrics":[
            {"name":"demo.summary","summary":{
              "dataPoints":[{
                "timeUnixNano":"1700000000000000000",
                "startTimeUnixNano":"1700000000000000000",
                "count":"100",
                "sum":500.0,
                "quantileValues":[
                  {"quantile":0.5,"value":2.5},
                  {"quantile":0.99,"value":9.9}
                ]
              }]
            }}
          ]
        }]
      }]
    }"#;

    let request = parse_otel_metrics_message(&Bytes::from(json)).expect("parse ok");
    let metric = &request.resource_metrics[0].scope_metrics[0].metrics[0];
    eprintln!("summary.data is_some = {}", metric.data.is_some());
    if let Some(Data::Summary(s)) = &metric.data {
        eprintln!("summary.data_points.len = {}", s.data_points.len());
        if let Some(dp) = s.data_points.first() {
            eprintln!(
                "dp.count={} sum={} quantile_values={:?}",
                dp.count, dp.sum, dp.quantile_values
            );
        }
    }
    assert!(matches!(metric.data, Some(Data::Summary(_))));
}

/// NumberDataPoint.asInt as a JSON string (per OTLP spec) should produce a
/// NumberDataPoint with value=AsInt(42), not None / 0. See
/// opentelemetry-rust#3328 — same upstream root cause as the histogram bug.
#[test]
fn number_data_point_as_int_string() {
    let json = r#"{
      "resourceMetrics":[{
        "resource":{"attributes":[]},
        "scopeMetrics":[{
          "scope":{"name":"x"},
          "metrics":[
            {"name":"demo.counter","sum":{
              "aggregationTemporality":2,
              "isMonotonic":true,
              "dataPoints":[{"timeUnixNano":"1700000000000000000","asInt":"42"}]
            }}
          ]
        }]
      }]
    }"#;

    let request = parse_otel_metrics_message(&Bytes::from(json)).expect("parse ok");
    let counter = &request.resource_metrics[0].scope_metrics[0].metrics[0];
    let Some(Data::Sum(sum)) = &counter.data else {
        panic!(
            "counter.data not a Sum variant: {:?}",
            counter.data.is_some()
        );
    };
    let dp = &sum.data_points[0];
    eprintln!("dp.value = {:?}", dp.value);
    assert!(
        dp.value.is_some(),
        "asInt as string yields value=None instead of AsInt(42)"
    );
}

// ---------- Edge-case regression tests for patch_otel_json ----------

/// HistogramDataPoint.count is u64 and the OTLP/JSON spec allows values up to
/// u64::MAX. Our `coerce_string_to_integer` tries i64 first then u64; this test
/// confirms that values > i64::MAX still round-trip correctly via the u64 path.
#[test]
fn edge_u64_above_i64_max_round_trips() {
    let big = u64::MAX; // 18446744073709551615
    let json = format!(
        r#"{{
          "resourceMetrics":[{{
            "resource":{{"attributes":[]}},
            "scopeMetrics":[{{
              "scope":{{"name":"x"}},
              "metrics":[
                {{"name":"big.histogram","histogram":{{
                  "aggregationTemporality":2,
                  "dataPoints":[{{
                    "timeUnixNano":"1700000000000000000",
                    "count":"{big}",
                    "sum":1.0,
                    "bucketCounts":["{big}"],
                    "explicitBounds":[]
                  }}]
                }}}}
              ]
            }}]
          }}]
        }}"#
    );

    let req = parse_otel_metrics_message(&Bytes::from(json)).expect("parse ok");
    let metric = &req.resource_metrics[0].scope_metrics[0].metrics[0];
    let Some(Data::Histogram(h)) = &metric.data else {
        panic!("histogram silently dropped for u64::MAX count");
    };
    let dp = &h.data_points[0];
    assert_eq!(dp.count, u64::MAX, "count must round-trip as u64::MAX");
    assert_eq!(
        dp.bucket_counts,
        vec![u64::MAX],
        "bucket_counts must round-trip as u64::MAX"
    );
}

/// asInt at i64::MAX and i64::MIN — boundary check on the i64-first path of
/// `coerce_string_to_integer`. NumberDataPoint.value::AsInt is sfixed64 (i64),
/// so signed boundaries must round-trip exactly.
#[test]
fn edge_as_int_signed_boundaries() {
    for &value in &[i64::MAX, i64::MIN, 0_i64, -1_i64, 1_i64] {
        let json = format!(
            r#"{{
              "resourceMetrics":[{{
                "resource":{{"attributes":[]}},
                "scopeMetrics":[{{
                  "scope":{{"name":"x"}},
                  "metrics":[
                    {{"name":"as.int","sum":{{
                      "aggregationTemporality":2,
                      "isMonotonic":true,
                      "dataPoints":[{{
                        "timeUnixNano":"1700000000000000000",
                        "asInt":"{value}"
                      }}]
                    }}}}
                  ]
                }}]
              }}]
            }}"#
        );

        let req = parse_otel_metrics_message(&Bytes::from(json))
            .unwrap_or_else(|e| panic!("parse failed for asInt={value}: {e}"));
        let metric = &req.resource_metrics[0].scope_metrics[0].metrics[0];
        let Some(Data::Sum(sum)) = &metric.data else {
            panic!("counter silently dropped for asInt={value}");
        };
        use opentelemetry_proto::tonic::metrics::v1::number_data_point::Value as NdpValue;
        match sum.data_points[0].value {
            Some(NdpValue::AsInt(n)) => assert_eq!(n, value, "asInt round-trip mismatch"),
            other => panic!("expected AsInt({value}), got {other:?}"),
        }
    }
}

/// Mixed encoding: per the OTLP/JSON spec ("either numbers or strings are
/// accepted when decoding"), a payload that mixes string-encoded u64s with
/// number-encoded u64s in the same Metric must parse identically. Tests that
/// the string→number coercion doesn't break the unquoted path either.
#[test]
fn edge_mixed_string_and_number_encodings() {
    let json = r#"{
      "resourceMetrics":[{
        "resource":{"attributes":[]},
        "scopeMetrics":[{
          "scope":{"name":"x"},
          "metrics":[
            {"name":"mixed.histogram","histogram":{
              "aggregationTemporality":2,
              "dataPoints":[{
                "timeUnixNano":"1700000000000000000",
                "count":10,
                "sum":99.0,
                "bucketCounts":["3",4,"2",1],
                "explicitBounds":[10,50,100]
              }]
            }}
          ]
        }]
      }]
    }"#;

    let req = parse_otel_metrics_message(&Bytes::from(json)).expect("parse ok");
    let metric = &req.resource_metrics[0].scope_metrics[0].metrics[0];
    let Some(Data::Histogram(h)) = &metric.data else {
        panic!("mixed-encoding histogram silently dropped");
    };
    let dp = &h.data_points[0];
    assert_eq!(dp.count, 10);
    assert_eq!(dp.bucket_counts, vec![3, 4, 2, 1]);
}

/// Negative value in a u64 field is a spec violation by the client and should be
/// rejected with a parse error (translating to 400 BAD_REQUEST at the HTTP layer).
/// Currently silenced by the upstream `flatten + Option<oneof> + default` pattern;
/// un-ignore when upstream changes that.
#[test]
#[ignore = "upstream silencing pattern not yet fixed — opentelemetry-rust#3328 + missing-default follow-up"]
fn edge_negative_value_in_u64_field_should_error() {
    let json = r#"{
      "resourceMetrics":[{
        "resource":{"attributes":[]},
        "scopeMetrics":[{
          "scope":{"name":"x"},
          "metrics":[
            {"name":"bad.histogram","histogram":{
              "aggregationTemporality":2,
              "dataPoints":[{
                "timeUnixNano":"1700000000000000000",
                "count":"-1",
                "sum":1.0,
                "bucketCounts":["1"],
                "explicitBounds":[]
              }]
            }}
          ]
        }]
      }]
    }"#;

    let result = parse_otel_metrics_message(&Bytes::from(json));
    assert!(
        result.is_err(),
        "spec-violating count=\"-1\" must be rejected, not silently dropped"
    );
}

/// Non-numeric string in a u64 field — same as above. Should reject, currently
/// silenced by the upstream pattern.
#[test]
#[ignore = "upstream silencing pattern not yet fixed — opentelemetry-rust#3328 + missing-default follow-up"]
fn edge_non_numeric_string_in_u64_field_should_error() {
    let json = r#"{
      "resourceMetrics":[{
        "resource":{"attributes":[]},
        "scopeMetrics":[{
          "scope":{"name":"x"},
          "metrics":[
            {"name":"bad.histogram","histogram":{
              "aggregationTemporality":2,
              "dataPoints":[{
                "timeUnixNano":"1700000000000000000",
                "count":"not-a-number",
                "sum":1.0,
                "bucketCounts":["1"],
                "explicitBounds":[]
              }]
            }}
          ]
        }]
      }]
    }"#;

    let result = parse_otel_metrics_message(&Bytes::from(json));
    assert!(
        result.is_err(),
        "spec-violating count=\"not-a-number\" must be rejected, not silently dropped"
    );
}

/// Regression for the gap that necessitated the expanded EXPONENTIAL_HISTOGRAM
/// defaults: client sends a minimal spec-valid expo without any of the upstream-
/// undeclared-default fields. Without our defaults, this hard-errors and the
/// metric silently drops.
#[test]
fn edge_expo_with_minimal_fields_only() {
    let json = r#"{
      "resourceMetrics":[{
        "resource":{"attributes":[]},
        "scopeMetrics":[{
          "scope":{"name":"x"},
          "metrics":[
            {"name":"minimal.expo","exponentialHistogram":{
              "aggregationTemporality":2,
              "dataPoints":[{"timeUnixNano":"1700000000000000000"}]
            }}
          ]
        }]
      }]
    }"#;

    let req = parse_otel_metrics_message(&Bytes::from(json)).expect("parse ok");
    let metric = &req.resource_metrics[0].scope_metrics[0].metrics[0];
    let Some(Data::ExponentialHistogram(eh)) = &metric.data else {
        panic!("minimal expo silently dropped — defaults missing for required-by-serde field");
    };
    assert_eq!(eh.data_points.len(), 1);
}

/// Same as above for summary: required-by-serde fields (sum is non-Option!)
/// must be defaulted when the client omits them, or the metric silently drops.
#[test]
fn edge_summary_with_minimal_fields_only() {
    let json = r#"{
      "resourceMetrics":[{
        "resource":{"attributes":[]},
        "scopeMetrics":[{
          "scope":{"name":"x"},
          "metrics":[
            {"name":"minimal.summary","summary":{
              "dataPoints":[{"timeUnixNano":"1700000000000000000"}]
            }}
          ]
        }]
      }]
    }"#;

    let req = parse_otel_metrics_message(&Bytes::from(json)).expect("parse ok");
    let metric = &req.resource_metrics[0].scope_metrics[0].metrics[0];
    let Some(Data::Summary(s)) = &metric.data else {
        panic!("minimal summary silently dropped — defaults missing for required-by-serde field");
    };
    assert_eq!(s.data_points.len(), 1);
}

/// Empty `"exponentialHistogram": {}` — no dataPoints, no aggregationTemporality.
/// ExponentialHistogram itself lacks serde(default), so without our variant-level
/// defaults this would silently drop too.
#[test]
fn edge_empty_exponential_histogram_variant() {
    let json = r#"{
      "resourceMetrics":[{
        "resource":{"attributes":[]},
        "scopeMetrics":[{
          "scope":{"name":"x"},
          "metrics":[
            {"name":"empty.expo","exponentialHistogram":{}}
          ]
        }]
      }]
    }"#;

    let req = parse_otel_metrics_message(&Bytes::from(json)).expect("parse ok");
    let metric = &req.resource_metrics[0].scope_metrics[0].metrics[0];
    assert!(
        matches!(metric.data, Some(Data::ExponentialHistogram(_))),
        "empty exponentialHistogram should yield an empty-data-points variant, not silent-drop"
    );
}
