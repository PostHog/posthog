use std::collections::HashSet;
use std::sync::OnceLock;

use super::compile::{compile_metric_rules, CompiledMetricRule, MetricRuleRow, MetricRuleSource};
use super::tally::SPAN_VALUE_DURATION_MS;
use crate::js::{json_parse, JsString, JsValue};

const SPAN_KIND_INTERNAL: &str = "1";

fn default_rows() -> Vec<MetricRuleRow> {
    let filter = format!(
        r#"{{"type":"AND","values":[{{"type":"AND","values":[{{"key":"kind","operator":"is_not","value":"{SPAN_KIND_INTERNAL}","type":"span_attribute"}}]}}]}}"#
    );
    let strings = |keys: &[&str]| JsValue::Array(keys.iter().map(|k| JsValue::string(k)).collect());
    vec![
        // INTERNAL spans are the most numerous, and their names most often carry ids.
        MetricRuleRow {
            id: "default:spans:duration".to_string(),
            metric_name: JsValue::string("posthog.span.duration"),
            source: JsValue::string("spans"),
            filter_group: json_parse(&filter).expect("default filter group is valid JSON"),
            value_attribute: JsValue::string(SPAN_VALUE_DURATION_MS),
            group_by: strings(&["service_name", "kind", "name", "status_code"]),
        },
        MetricRuleRow {
            id: "default:logs:records".to_string(),
            metric_name: JsValue::string("posthog.log.records"),
            source: JsValue::string("logs"),
            filter_group: JsValue::Null,
            value_attribute: JsValue::Null,
            group_by: strings(&["service_name", "severity_text"]),
        },
    ]
}

pub fn default_metric_rules(source: MetricRuleSource) -> &'static [CompiledMetricRule] {
    static COMPILED: OnceLock<(Vec<CompiledMetricRule>, Vec<CompiledMetricRule>)> = OnceLock::new();
    let (logs, spans) = COMPILED.get_or_init(|| {
        let compiled =
            compile_metric_rules(&default_rows()).expect("default rules compile without a throw");
        let (logs, spans): (Vec<_>, Vec<_>) = compiled
            .into_iter()
            .partition(|r| r.source == MetricRuleSource::Logs);
        (logs, spans)
    });
    match source {
        MetricRuleSource::Logs => logs,
        MetricRuleSource::Spans => spans,
    }
}

pub fn with_default_metric_rules(
    team_rules: Vec<CompiledMetricRule>,
    source: MetricRuleSource,
) -> Vec<CompiledMetricRule> {
    let team_names: HashSet<JsString> = team_rules.iter().map(|r| r.metric_name.clone()).collect();
    let mut out = team_rules;
    out.extend(
        default_metric_rules(source)
            .iter()
            .filter(|r| !team_names.contains(&r.metric_name))
            .cloned(),
    );
    out
}
