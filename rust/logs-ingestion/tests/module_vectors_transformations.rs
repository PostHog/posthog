//! Replays the `hog_transform` and `hog_inputs` vectors that Node recorded (see `logs-module-parity.test.ts`).

mod common;

use common::{array, cases, get, record_from_js, record_to_js, string};
use hogvm::{Num, OrderedJson};
use logs_ingestion::js::{json_stringify, JsObject, JsString, JsValue};
use logs_ingestion::transformations::exec::{
    build_record_globals, execute_log_transformation, globals, js_to_ordered, project_globals,
    resolve_inputs, TransformStatus,
};
use logs_ingestion::transformations::functions::{HogFunction, HogFunctionRow};

const SITE_URL: &str = "http://localhost:8010";
const TEAM_ID: i64 = 7;

fn function(bytecode: &JsValue, inputs: &JsValue) -> HogFunction {
    HogFunction::from_row(HogFunctionRow {
        id: "00000000-0000-0000-0000-000000000001".into(),
        team_id: TEAM_ID,
        name: "vector".into(),
        function_type: "transformation_log".into(),
        execution_order: None,
        created_at: String::new(),
        bytecode: bytecode.clone(),
        inputs: inputs.clone(),
        encrypted_inputs: None,
    })
}

fn ordered_to_js(value: &OrderedJson) -> JsValue {
    match value {
        OrderedJson::Null => JsValue::Null,
        OrderedJson::Bool(b) => JsValue::Bool(*b),
        OrderedJson::Number(Num::Integer(i)) => JsValue::Number(*i as f64),
        OrderedJson::Number(Num::Float(f)) => JsValue::Number(*f),
        OrderedJson::String(s) => JsValue::string(s),
        OrderedJson::Array(items) => JsValue::Array(items.iter().map(ordered_to_js).collect()),
        OrderedJson::Object(entries) => {
            let mut o = JsObject::new();
            for (k, v) in entries {
                o.insert(JsString::from(k.as_str()), ordered_to_js(v));
            }
            JsValue::Object(o)
        }
    }
}

#[test]
fn hog_transformations_match_node() {
    let cases = cases("hog_transform");
    assert!(cases.len() > 30);
    let project = project_globals(TEAM_ID, SITE_URL);
    for (input, output) in cases {
        let hog = string(get(&input, "hog"));
        let mut record = record_from_js(get(&input, "record"));
        let sensitive: Vec<String> = array(get(&input, "sensitive")).iter().map(string).collect();
        let f = function(get(&input, "bytecode"), &JsValue::Null);
        let root = globals(
            &project,
            &build_record_globals(&record),
            js_to_ordered(get(&input, "inputs")),
        );
        // A timeout far past any case, so the vectors never depend on the machine.
        let outcome = execute_log_transformation(&f, &mut record, root, 5_000.0, &sensitive);
        let status = match &outcome.status {
            TransformStatus::Mutated => "mutated",
            TransformStatus::Dropped => "dropped",
            TransformStatus::Failed(_) => "failed",
        };
        assert_eq!(
            status,
            string(get(&output, "status")),
            "{hog}\n{:?}",
            outcome.status
        );
        // A thrown Hog error and the result-shape error print the same. Other VM error texts differ between the VMs.
        if let JsValue::String(error) = get(&output, "error") {
            let error = error.to_string();
            if !error.starts_with("HogVMException") {
                assert_eq!(outcome.status, TransformStatus::Failed(error), "{hog}");
            }
        }
        let logs: Vec<String> = array(get(&output, "logs")).iter().map(string).collect();
        assert_eq!(outcome.logs, logs, "{hog}");
        assert_eq!(
            json_stringify(&record_to_js(&record)),
            json_stringify(get(&output, "record")),
            "{hog}"
        );
    }
}

#[test]
fn hog_input_templates_match_node() {
    let cases = cases("hog_inputs");
    assert!(!cases.is_empty());
    let project = project_globals(TEAM_ID, SITE_URL);
    for (input, output) in cases {
        let name = string(get(&input, "name"));
        let record = record_from_js(get(&input, "record"));
        let f = function(&JsValue::Array(vec![]), get(&input, "inputs"));
        let resolved = resolve_inputs(&f, &project, &build_record_globals(&record), 5_000.0);
        match (resolved, common::try_get(&output, "inputs")) {
            (Ok((inputs, _)), Some(expected)) => assert_eq!(
                json_stringify(&ordered_to_js(&inputs)),
                json_stringify(expected),
                "{name}"
            ),
            (Err(error), None) => assert_eq!(error, string(get(&output, "error")), "{name}"),
            (actual, _) => panic!("{name}: {:?} against {output:?}", actual.map(|(i, _)| i)),
        }
    }
}
