//! `HogFunctionType` as the logs transformer reads it, and the `HogFunctionManagerService` contract.

use std::cmp::Ordering;
use std::sync::Arc;

use async_trait::async_trait;
use hogvm::Program;

use crate::js::{json_stringify, JsObject, JsValue};

pub const TRANSFORMATION_LOG_TYPE: &str = "transformation_log";

/// One input after `{ ...inputs, ...encrypted_inputs }` and the sort by `order`.
#[derive(Clone)]
pub struct HogFunctionInput {
    pub key: String,
    /// `input?.value`, or `None` for `undefined`.
    pub value: Option<JsValue>,
    /// Set when `input.bytecode` is truthy and `templating` is `hog`. `Err` holds why the bytecode does not load.
    pub template: Option<Result<Program, String>>,
}

#[derive(Clone)]
pub struct HogFunction {
    pub id: String,
    pub team_id: i64,
    pub name: String,
    pub function_type: String,
    pub execution_order: Option<f64>,
    pub created_at: String,
    pub bytecode: Result<Program, String>,
    pub inputs: Vec<HogFunctionInput>,
    /// `JSON.stringify({ ...inputs, ...encrypted_inputs }).includes('record')`.
    pub inputs_reference_record: bool,
    /// The string leaves of every encrypted input value, in the order `collectStringLeaves` finds them.
    pub sensitive_values: Vec<String>,
}

/// Bytecode stays a `serde_json` value, so integral numbers must become integers for the VM's token decode.
pub fn js_to_serde(value: &JsValue) -> serde_json::Value {
    match value {
        JsValue::Null => serde_json::Value::Null,
        JsValue::Bool(b) => serde_json::Value::Bool(*b),
        JsValue::Number(n) => {
            if n.fract() == 0.0 && n.abs() < 9.2e18 {
                serde_json::Value::from(*n as i64)
            } else {
                serde_json::Number::from_f64(*n)
                    .map(serde_json::Value::Number)
                    .unwrap_or(serde_json::Value::Null)
            }
        }
        JsValue::String(s) => serde_json::Value::String(s.to_utf8_lossy().into_owned()),
        JsValue::Array(items) => serde_json::Value::Array(items.iter().map(js_to_serde).collect()),
        JsValue::Object(o) => serde_json::Value::Object(
            o.iter()
                .map(|(k, v)| (k.to_utf8_lossy().into_owned(), js_to_serde(v)))
                .collect(),
        ),
    }
}

pub fn load_program(bytecode: &JsValue) -> Result<Program, String> {
    match js_to_serde(bytecode) {
        serde_json::Value::Array(tokens) => Program::new(tokens).map_err(|e| e.to_string()),
        other => Err(format!("Invalid bytecode: {other}")),
    }
}

fn truthy(value: &JsValue) -> bool {
    match value {
        JsValue::Null => false,
        JsValue::Bool(b) => *b,
        JsValue::Number(n) => *n != 0.0 && !n.is_nan(),
        JsValue::String(s) => !s.is_empty(),
        JsValue::Array(_) | JsValue::Object(_) => true,
    }
}

fn field<'a>(value: &'a JsValue, key: &str) -> Option<&'a JsValue> {
    match value {
        JsValue::Object(o) => o.get(key),
        _ => None,
    }
}

/// `collectStringLeaves`: a stack, so siblings come out last first.
fn collect_string_leaves(root: &JsValue, out: &mut Vec<String>) {
    let mut stack: Vec<&JsValue> = vec![root];
    while let Some(value) = stack.pop() {
        match value {
            JsValue::String(s) if !s.is_empty() => out.push(s.to_utf8_lossy().into_owned()),
            JsValue::Array(items) => stack.extend(items.iter()),
            JsValue::Object(o) => stack.extend(o.iter().map(|(_, v)| v)),
            _ => {}
        }
    }
}

/// The parts of a `posthog_hogfunction` row that the transformer reads.
#[derive(Debug, Clone)]
pub struct HogFunctionRow {
    pub id: String,
    pub team_id: i64,
    pub name: String,
    pub function_type: String,
    pub execution_order: Option<f64>,
    pub created_at: String,
    pub bytecode: JsValue,
    pub inputs: JsValue,
    /// Already decrypted. `None` when the column is null or did not decrypt.
    pub encrypted_inputs: Option<JsValue>,
}

impl HogFunction {
    pub fn from_row(row: HogFunctionRow) -> Self {
        let mut merged = JsObject::new();
        for source in [Some(&row.inputs), row.encrypted_inputs.as_ref()]
            .into_iter()
            .flatten()
        {
            if let JsValue::Object(o) = source {
                for (k, v) in o.iter() {
                    merged.insert(k, v.clone());
                }
            }
        }
        let inputs_reference_record =
            json_stringify(&JsValue::Object(merged.clone())).contains("record");
        let order = |input: &JsValue| match field(input, "order") {
            Some(JsValue::Number(n)) => *n,
            _ => -1.0,
        };
        let mut entries: Vec<(String, JsValue)> = merged
            .iter()
            .map(|(k, v)| (k.to_utf8_lossy().into_owned(), v.clone()))
            .collect();
        // `Array#sort` is stable, and a NaN difference counts as equal.
        entries.sort_by(|(_, a), (_, b)| {
            (order(a) - order(b))
                .partial_cmp(&0.0)
                .unwrap_or(Ordering::Equal)
        });
        let inputs = entries
            .into_iter()
            .map(|(key, input)| {
                let bytecode = field(&input, "bytecode").filter(|b| truthy(b));
                let hog_templating = match field(&input, "templating") {
                    None | Some(JsValue::Null) => true,
                    Some(JsValue::String(s)) => s.as_str() == Some("hog"),
                    Some(_) => false,
                };
                HogFunctionInput {
                    key,
                    value: field(&input, "value").cloned(),
                    template: bytecode.filter(|_| hog_templating).map(load_program),
                }
            })
            .collect();
        let mut sensitive_values = Vec::new();
        if let Some(JsValue::Object(encrypted)) = &row.encrypted_inputs {
            for (_, input) in encrypted.iter() {
                if let Some(value) = field(input, "value") {
                    collect_string_leaves(value, &mut sensitive_values);
                }
            }
        }
        HogFunction {
            bytecode: load_program(&row.bytecode),
            id: row.id,
            team_id: row.team_id,
            name: row.name,
            function_type: row.function_type,
            execution_order: row.execution_order,
            created_at: row.created_at,
            inputs,
            inputs_reference_record,
            sensitive_values,
        }
    }
}

/// `sortHogFunctions`: by `execution_order` with nulls last, then by `created_at`.
pub fn sort_hog_functions(functions: &mut [Arc<HogFunction>]) {
    functions.sort_by(|a, b| match (a.execution_order, b.execution_order) {
        (None, None) => a.created_at.cmp(&b.created_at),
        (None, Some(_)) => Ordering::Greater,
        (Some(_), None) => Ordering::Less,
        (Some(x), Some(y)) if x != y => x.partial_cmp(&y).unwrap_or(Ordering::Equal),
        _ => a.created_at.cmp(&b.created_at),
    });
}

/// `HogFunctionManagerService` narrowed to one team and the `transformation_log` type.
#[async_trait]
pub trait HogFunctionSource: Send + Sync {
    /// `getHogFunctionIdsForTeams`: the cheap lookup that answers whether a team has any.
    async fn transformation_ids(&self, team_id: i64) -> anyhow::Result<Vec<String>>;
    /// `getHogFunctionsForTeams`, sorted by `sort_hog_functions`.
    async fn transformations(&self, team_id: i64) -> anyhow::Result<Vec<Arc<HogFunction>>>;
}

/// A fixed set of functions, for the parity scenarios and tests.
pub struct StaticHogFunctions(pub Vec<Arc<HogFunction>>);

#[async_trait]
impl HogFunctionSource for StaticHogFunctions {
    async fn transformation_ids(&self, team_id: i64) -> anyhow::Result<Vec<String>> {
        Ok(self
            .0
            .iter()
            .filter(|f| f.team_id == team_id && f.function_type == TRANSFORMATION_LOG_TYPE)
            .map(|f| f.id.clone())
            .collect())
    }

    async fn transformations(&self, team_id: i64) -> anyhow::Result<Vec<Arc<HogFunction>>> {
        let mut out: Vec<Arc<HogFunction>> = self
            .0
            .iter()
            .filter(|f| f.team_id == team_id && f.function_type == TRANSFORMATION_LOG_TYPE)
            .cloned()
            .collect();
        sort_hog_functions(&mut out);
        Ok(out)
    }
}

/// A row as the parity fixtures and the Postgres `::text` columns give it.
pub fn row_from_js(value: &JsValue) -> HogFunctionRow {
    let s = |key: &str| match field(value, key) {
        Some(JsValue::String(s)) => s.to_utf8_lossy().into_owned(),
        _ => String::new(),
    };
    HogFunctionRow {
        id: s("id"),
        team_id: match field(value, "team_id") {
            Some(JsValue::Number(n)) => *n as i64,
            _ => 0,
        },
        name: s("name"),
        function_type: s("type"),
        execution_order: match field(value, "execution_order") {
            Some(JsValue::Number(n)) => Some(*n),
            _ => None,
        },
        created_at: s("created_at"),
        bytecode: field(value, "bytecode").cloned().unwrap_or(JsValue::Null),
        inputs: field(value, "inputs").cloned().unwrap_or(JsValue::Null),
        encrypted_inputs: field(value, "encrypted_inputs")
            .filter(|v| matches!(v, JsValue::Object(_)))
            .cloned(),
    }
}
