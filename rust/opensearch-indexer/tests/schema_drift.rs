// CI gate: locks the on-wire shape of `$ai_*` events. If an upstream change renames
// or retypes one of the props the indexer consumes, this test fails before the
// service ships a build that would silently drop or mis-extract data.

use jsonschema::JSONSchema;
use opensearch_indexer::{parser::parse, types::AiEvent};
use serde_json::Value;

const SAMPLE_AI_GENERATION: &str = include_str!("static/sample_ai_generation.json");
const AI_EVENT_SCHEMA: &str = include_str!("static/ai_event.schema.json");

#[test]
fn fixture_properties_match_schema() {
    let schema: Value = serde_json::from_str(AI_EVENT_SCHEMA).expect("schema is valid JSON");
    let compiled = JSONSchema::compile(&schema).expect("schema compiles");

    let event: Value = serde_json::from_str(SAMPLE_AI_GENERATION).expect("fixture is valid JSON");
    let props_str = event["properties"]
        .as_str()
        .expect("`properties` is a stringified JSON blob");
    let props: Value = serde_json::from_str(props_str).expect("properties parse as JSON");

    let errors: Vec<String> = compiled
        .validate(&props)
        .err()
        .map(|iter| iter.map(|e| e.to_string()).collect())
        .unwrap_or_default();
    if !errors.is_empty() {
        panic!("schema drift detected:\n  {}", errors.join("\n  "));
    }
}

#[test]
fn schema_rejects_renamed_heavy_prop() {
    // Positive control: simulate upstream renaming `$ai_input_state` to camelCase.
    // The schema must reject so the CI gate actually fires on drift.
    let schema: Value = serde_json::from_str(AI_EVENT_SCHEMA).unwrap();
    let compiled = JSONSchema::compile(&schema).unwrap();

    let drifted = serde_json::json!({
        "$ai_input": [],
        "$ai_output": "",
        "$ai_output_choices": [],
        "$ai_inputState": {},
        "$ai_output_state": {},
        "$ai_tools": [],
        "$ai_model": "gpt-4",
        "$ai_provider": "openai",
        "$ai_trace_id": "t",
        "$ai_input_tokens": 0,
        "$ai_output_tokens": 0,
        "$ai_total_cost_usd": 0.0,
        "$ai_latency": 0.0,
        "$ai_is_error": false
    });
    assert!(
        !compiled.is_valid(&drifted),
        "schema must reject renamed heavy props"
    );
}

#[test]
fn fixture_deserializes_into_ai_event() {
    let event: AiEvent =
        serde_json::from_str(SAMPLE_AI_GENERATION).expect("fixture deserializes into AiEvent");
    assert_eq!(event.event, "$ai_generation");
    assert_eq!(event.team_id, 42);
}

#[test]
fn fixture_parses_into_index_doc() {
    let event: AiEvent =
        serde_json::from_str(SAMPLE_AI_GENERATION).expect("fixture deserializes into AiEvent");
    let doc = parse(&event)
        .expect("parse succeeds")
        .expect("matched $ai_*");

    assert_eq!(
        doc.trace_id.as_deref(),
        Some("537b7988-0186-494f-a313-77a5a8f7db26")
    );
    assert_eq!(doc.team_id, 42);
    assert_eq!(doc.model.as_deref(), Some("gpt-4"));
    assert_eq!(doc.provider.as_deref(), Some("openai"));
    assert_eq!(doc.cost, Some(0.001));
    assert_eq!(doc.latency_ms, Some(500));
    assert!(!doc.is_error);
    assert_eq!(doc.tool_names, vec!["get_weather"]);
    assert_eq!(doc.timestamp, "2025-01-29T16:04:53.816000Z");
}
