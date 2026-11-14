use std::collections::HashSet;
use std::sync::Arc;
use std::time::{Duration, Instant};

use hogvm::{
    ExecutionContext, HeapReference, HogLiteral, HogVM, HogValue, Num, OrderedJson, Program,
    StepOutcome, VmError, MAX_JSON_SERDE_DEPTH,
};

use crate::attribute_value::{decode_log_attribute_value, encode_log_attribute_value};
use crate::avro::{AvroMap, AvroValue};
use crate::js::{json_stringify, number_to_string, utf16_len, JsObject, JsString, JsValue};
use crate::metric_rules::id_to_hex;
use crate::normalize::MAX_LOG_RECORD_BYTES;
use crate::record::LogRecord;

use super::functions::HogFunction;

pub const DEFAULT_LOG_TRANSFORMATION_TIMEOUT_MS: f64 = 10.0;
pub const LOG_TRANSFORMATION_MEMORY_LIMIT_BYTES: usize = 8 * 1024 * 1024;
pub const MAX_LOG_TRANSFORMATION_PRINT_LOGS: usize = 5;
pub const MAX_TRANSFORMED_FIELD_BYTES: usize = MAX_LOG_RECORD_BYTES;
pub const MAX_LOG_LENGTH: usize = 10_000;
const TRUNCATION_SUFFIX: &str = "... (truncated)";
const REDACTED: &str = "***REDACTED***";
/// The Node VM checks its clock every 32 ops and on every call.
const DEADLINE_CHECK_MASK: u64 = 31;
pub const INVALID_RESULT_ERROR: &str =
    "Transformation must return the record (optionally mutated) or null to drop it";

#[derive(Debug, Clone, PartialEq)]
pub enum TransformStatus {
    Mutated,
    Dropped,
    Failed(String),
}

#[derive(Debug, Clone)]
pub struct TransformOutcome {
    pub status: TransformStatus,
    pub duration_ms: f64,
    pub logs: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Applied {
    Mutated,
    Dropped,
    Invalid,
}

/// `String(error)` of what the Node VM throws: `UncaughtHogVMException` prints as `Type('message')`, any other
/// `HogVMException` as `HogVMException: message`. The message texts of other VM errors differ between the VMs.
pub fn vm_error_text(error: &VmError) -> String {
    match error {
        VmError::UncaughtException(kind, message) => {
            format!("{kind}('{}')", message.replace('\'', "\\'"))
        }
        other => format!("HogVMException: {other}"),
    }
}

fn elapsed_ms(start: Instant) -> f64 {
    start.elapsed().as_secs_f64() * 1000.0
}

/// A JavaScript number as the Rust VM holds it: integral values are integers, as a compiled `5` is.
pub fn js_number(n: f64) -> Num {
    if n.fract() == 0.0 && n.abs() <= 9_007_199_254_740_992.0 {
        Num::Integer(n as i64)
    } else {
        Num::Float(n)
    }
}

pub fn js_to_ordered(value: &JsValue) -> OrderedJson {
    match value {
        JsValue::Null => OrderedJson::Null,
        JsValue::Bool(b) => OrderedJson::Bool(*b),
        JsValue::Number(n) => OrderedJson::Number(js_number(*n)),
        JsValue::String(s) => OrderedJson::String(Arc::from(s.to_utf8_lossy().as_ref())),
        JsValue::Array(items) => OrderedJson::Array(items.iter().map(js_to_ordered).collect()),
        JsValue::Object(o) => OrderedJson::Object(
            o.iter()
                .map(|(k, v)| (k.to_utf8_lossy().into_owned(), js_to_ordered(v)))
                .collect(),
        ),
    }
}

fn ostr(value: Option<&str>) -> OrderedJson {
    value.map_or(OrderedJson::Null, |s| OrderedJson::String(Arc::from(s)))
}

fn oint(value: Option<i64>) -> OrderedJson {
    value.map_or(OrderedJson::Null, |n| OrderedJson::Number(Num::Integer(n)))
}

fn decode_attribute_map(map: Option<&AvroMap>) -> OrderedJson {
    OrderedJson::Object(
        map.into_iter()
            .flat_map(|m| m.iter_strings())
            .map(|(k, v)| {
                (
                    k.to_string(),
                    OrderedJson::String(Arc::from(
                        decode_log_attribute_value(v).to_utf8_lossy().as_ref(),
                    )),
                )
            })
            .collect(),
    )
}

pub fn build_record_globals(record: &LogRecord) -> OrderedJson {
    OrderedJson::Object(vec![
        ("body".into(), ostr(record.body())),
        (
            "attributes".into(),
            decode_attribute_map(record.attributes()),
        ),
        (
            "resource_attributes".into(),
            decode_attribute_map(record.resource_attributes()),
        ),
        ("severity_text".into(), ostr(record.severity_text())),
        ("severity_number".into(), oint(record.severity_number())),
        ("service_name".into(), ostr(record.service_name())),
        (
            "instrumentation_scope".into(),
            ostr(record.instrumentation_scope()),
        ),
        ("event_name".into(), ostr(record.event_name())),
        ("timestamp".into(), oint(record.timestamp())),
        (
            "observed_timestamp".into(),
            oint(record.observed_timestamp()),
        ),
        (
            "trace_id".into(),
            ostr(id_to_hex(record.trace_id(), 16).as_deref()),
        ),
        (
            "span_id".into(),
            ostr(id_to_hex(record.span_id(), 8).as_deref()),
        ),
    ])
}

pub fn project_globals(team_id: i64, site_url: &str) -> OrderedJson {
    OrderedJson::Object(vec![
        ("id".into(), OrderedJson::Number(Num::Integer(team_id))),
        ("name".into(), OrderedJson::String(Arc::from(""))),
        (
            "url".into(),
            OrderedJson::String(Arc::from(format!("{site_url}/project/{team_id}"))),
        ),
    ])
}

pub fn globals(project: &OrderedJson, record: &OrderedJson, inputs: OrderedJson) -> OrderedJson {
    OrderedJson::Object(vec![
        ("project".into(), project.clone()),
        ("record".into(), record.clone()),
        ("inputs".into(), inputs),
    ])
}

/// A short secret that occurs in the marker, such as `*`, multiplies the length on every later pass,
/// so `None` stops a result past the memory limit. Such a value is far over the record cap anyway.
pub fn redact_string(value: &str, sensitive: &[String]) -> Option<String> {
    let mut out = value.to_string();
    for s in sensitive.iter().filter(|s| !s.is_empty()) {
        let count = out.matches(s.as_str()).count();
        if count == 0 {
            continue;
        }
        let grown =
            (out.len() - count * s.len()).saturating_add(count.saturating_mul(REDACTED.len()));
        if grown > MAX_CONVERTED_BYTES {
            return None;
        }
        out = out.replace(s.as_str(), REDACTED);
    }
    Some(out)
}

pub fn redact_sensitive_values(message: &str, sensitive: &[String]) -> String {
    if message.is_empty() || sensitive.is_empty() {
        return message.to_string();
    }
    let mut variants: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for value in sensitive.iter().filter(|v| !v.is_empty()) {
        let escaped = json_stringify(&JsValue::string(value));
        for variant in [value.clone(), escaped[1..escaped.len() - 1].to_string()] {
            if seen.insert(variant.clone()) {
                variants.push(variant);
            }
        }
    }
    if variants.is_empty() {
        return message.to_string();
    }
    variants.sort_by_key(|v| std::cmp::Reverse(utf16_len(v)));
    let mut out = String::with_capacity(message.len());
    let mut rest = message;
    'outer: while !rest.is_empty() {
        for variant in &variants {
            if rest.starts_with(variant.as_str()) {
                out.push_str(REDACTED);
                rest = &rest[variant.len()..];
                continue 'outer;
            }
        }
        let c = rest.chars().next().unwrap();
        out.push(c);
        rest = &rest[c.len_utf8()..];
    }
    out
}

pub fn sanitize_log_message(args: &[JsValue], sensitive: &[String]) -> String {
    let joined = args
        .iter()
        .map(|a| match a {
            JsValue::String(s) => s.to_utf8_lossy().into_owned(),
            other => json_stringify(other),
        })
        .collect::<Vec<_>>()
        .join(", ");
    let message = redact_sensitive_values(&joined, sensitive);
    // Node truncates once the text is within the suffix length of the cap.
    if MAX_LOG_LENGTH < utf16_len(&message) + utf16_len(TRUNCATION_SUFFIX) {
        let mut units = 0;
        let mut end = 0;
        for (i, c) in message.char_indices() {
            if units + c.len_utf16() > MAX_LOG_LENGTH {
                break;
            }
            units += c.len_utf16();
            end = i + c.len_utf8();
        }
        return format!("{}{TRUNCATION_SUFFIX}", &message[..end]);
    }
    message
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConvertError {
    Cyclic,
    /// Shared references expand on every visit, so a small heap can describe an exponential tree.
    TooLarge,
}

/// Bounds on the memory and stack of one conversion. Node applies a result under the record cap that exceeds them.
const MAX_CONVERTED_NODES: usize = 100_000;
const MAX_CONVERTED_BYTES: usize = LOG_TRANSFORMATION_MEMORY_LIMIT_BYTES;
const MAX_CONVERTED_DEPTH: usize = MAX_JSON_SERDE_DEPTH;

struct Converter<'a> {
    vm: &'a HogVM<'a>,
    sensitive: &'a [String],
    path: Vec<HeapReference>,
    nodes: usize,
    bytes: usize,
}

impl Converter<'_> {
    fn charge(&mut self, bytes: usize) -> Result<(), ConvertError> {
        self.nodes += 1;
        self.bytes = self.bytes.saturating_add(bytes);
        if self.nodes > MAX_CONVERTED_NODES || self.bytes > MAX_CONVERTED_BYTES {
            return Err(ConvertError::TooLarge);
        }
        Ok(())
    }

    fn text(&mut self, s: &str) -> Result<JsString, ConvertError> {
        let out = if self.sensitive.is_empty() {
            s.to_string()
        } else {
            redact_string(s, self.sensitive).ok_or(ConvertError::TooLarge)?
        };
        self.charge(out.len())?;
        Ok(JsString::from(out))
    }

    fn convert(&mut self, value: &HogValue) -> Result<JsValue, ConvertError> {
        let pointer = match value {
            HogValue::Ref(ptr) => {
                if self.path.contains(ptr) {
                    return Err(ConvertError::Cyclic);
                }
                Some(*ptr)
            }
            HogValue::Lit(_) => None,
        };
        let Ok(literal) = value.deref(&self.vm.heap) else {
            return Ok(JsValue::Null);
        };
        // The recursion uses the thread's stack, and a stack overflow ends the process.
        if self.path.len() >= MAX_CONVERTED_DEPTH {
            return Err(ConvertError::TooLarge);
        }
        if let Some(ptr) = pointer {
            self.path.push(ptr);
        }
        let out = self.convert_literal(literal);
        if pointer.is_some() {
            self.path.pop();
        }
        out
    }

    fn convert_literal(&mut self, literal: &HogLiteral) -> Result<JsValue, ConvertError> {
        self.charge(0)?;
        match literal {
            HogLiteral::Null => Ok(JsValue::Null),
            HogLiteral::Boolean(b) => Ok(JsValue::Bool(*b)),
            HogLiteral::Number(n) => Ok(JsValue::Number(n.to_float())),
            HogLiteral::String(s) => Ok(JsValue::String(self.text(s)?)),
            HogLiteral::Callable(_) | HogLiteral::Closure(_) => Ok(self
                .vm
                .closure_json(literal)
                .map_or(JsValue::Null, |json| closure_object(&json))),
            HogLiteral::Array(items) | HogLiteral::Tuple(items) => items
                .iter()
                .map(|item| self.convert(item))
                .collect::<Result<Vec<_>, _>>()
                .map(JsValue::Array),
            HogLiteral::Object(map) => {
                let mut object = JsObject::new();
                for (key, item) in map.iter() {
                    // `obj['__proto__'] = v` sets the prototype, so the key never becomes an own property.
                    if key == "__proto__" {
                        continue;
                    }
                    let value = self.convert(item)?;
                    let key = self.text(key)?;
                    object.insert(key, value);
                }
                Ok(JsValue::Object(object))
            }
        }
    }
}

/// The closure object of the Node VM, in its key order, from the `serde_json` form that sorts keys.
fn closure_object(json: &serde_json::Value) -> JsValue {
    fn ordered(json: &serde_json::Value, order: &[&str]) -> JsValue {
        let mut object = JsObject::new();
        if let serde_json::Value::Object(map) = json {
            for key in order {
                if let Some(value) = map.get(*key) {
                    let value = match (*key, value) {
                        ("callable", v) => ordered(
                            v,
                            &[
                                "__hogCallable__",
                                "name",
                                "chunk",
                                "argCount",
                                "upvalueCount",
                                "ip",
                            ],
                        ),
                        (_, v) => serde_to_js(v),
                    };
                    object.insert_str(key, value);
                }
            }
        }
        JsValue::Object(object)
    }
    ordered(json, &["__hogClosure__", "callable", "upvalues"])
}

fn serde_to_js(value: &serde_json::Value) -> JsValue {
    match value {
        serde_json::Value::Null => JsValue::Null,
        serde_json::Value::Bool(b) => JsValue::Bool(*b),
        serde_json::Value::Number(n) => JsValue::Number(n.as_f64().unwrap_or(0.0)),
        serde_json::Value::String(s) => JsValue::string(s),
        serde_json::Value::Array(items) => JsValue::Array(items.iter().map(serde_to_js).collect()),
        serde_json::Value::Object(map) => {
            let mut object = JsObject::new();
            for (k, v) in map {
                object.insert_str(k, serde_to_js(v));
            }
            JsValue::Object(object)
        }
    }
}

pub fn hog_to_js(
    vm: &HogVM,
    value: &HogValue,
    sensitive: &[String],
) -> Result<JsValue, ConvertError> {
    hog_values_to_js(vm, std::slice::from_ref(value), sensitive).map(|mut values| values.remove(0))
}

/// The values share one node and byte limit, so many arguments cannot each use a full limit.
pub fn hog_values_to_js(
    vm: &HogVM,
    values: &[HogValue],
    sensitive: &[String],
) -> Result<Vec<JsValue>, ConvertError> {
    let mut converter = Converter {
        vm,
        sensitive,
        path: Vec::new(),
        nodes: 0,
        bytes: 0,
    };
    values.iter().map(|v| converter.convert(v)).collect()
}

pub type PrintHandler<'a> = dyn FnMut(&HogVM, Vec<HogValue>) -> Result<(), String> + 'a;

/// A field of a result: `None` when absent, `Some(None)` for an explicit null.
type FieldUpdate<T> = Option<Option<T>>;

pub struct VmRun<T> {
    pub result: Result<T, String>,
    pub duration_ms: f64,
}

pub fn run_program<T>(
    program: &Program,
    globals: OrderedJson,
    timeout_ms: f64,
    mut on_print: Option<&mut PrintHandler<'_>>,
    finish: impl FnOnce(&HogVM, HogValue) -> Result<T, String>,
) -> VmRun<T> {
    let start = Instant::now();
    let deadline = Duration::try_from_secs_f64(timeout_ms.max(0.0) / 1000.0)
        .ok()
        .and_then(|timeout| start.checked_add(timeout));
    let past_deadline = || deadline.is_some_and(|deadline| Instant::now() > deadline);
    let context = ExecutionContext::with_defaults(program.clone())
        .with_ordered_globals(globals)
        .with_raw_result()
        .with_max_steps(usize::MAX)
        .with_max_heap_size(LOG_TRANSFORMATION_MEMORY_LIMIT_BYTES);
    let result = (|| {
        let mut vm = context.to_vm().map_err(|e| vm_error_text(&e))?;
        let mut ops: u64 = 0;
        let timed_out = |ops: u64| {
            format!(
                "HogVMException: Execution timed out after {} seconds. Performed {ops} ops.",
                number_to_string(timeout_ms / 1000.0)
            )
        };
        // Strings on the stack are outside the heap limit, and reading an array element copies one.
        let within_memory = |vm: &HogVM| {
            let used = vm.memory_bytes();
            if used > LOG_TRANSFORMATION_MEMORY_LIMIT_BYTES {
                return Err(format!(
                    "HogVMException: Memory limit of {LOG_TRANSFORMATION_MEMORY_LIMIT_BYTES} bytes exceeded. Tried to allocate {used} bytes."
                ));
            }
            Ok(())
        };
        loop {
            match vm.step().map_err(|e| vm_error_text(&e))? {
                StepOutcome::Continue => {
                    ops += 1;
                    if ops & DEADLINE_CHECK_MASK == 0 {
                        if past_deadline() {
                            return Err(timed_out(ops));
                        }
                        within_memory(&vm)?;
                    }
                }
                StepOutcome::NativeCall(name, args) => {
                    ops += 1;
                    if past_deadline() {
                        return Err(timed_out(ops));
                    }
                    if name == "print" {
                        if let Some(print) = on_print.as_mut() {
                            print(&vm, args)?;
                        }
                        vm.push_stack(HogLiteral::Null)
                            .map_err(|e| vm_error_text(&e))?;
                    } else {
                        context
                            .execute_native_function_call(&mut vm, &name, args)
                            .map_err(|e| vm_error_text(&e))?;
                    }
                    within_memory(&vm)?;
                }
                StepOutcome::Finished(_) => {
                    let value = vm.take_result().unwrap_or(HogValue::Lit(HogLiteral::Null));
                    return finish(&vm, value);
                }
            }
        }
    })();
    VmRun {
        result,
        duration_ms: elapsed_ms(start),
    }
}

fn coerce_string_map(value: &JsValue) -> Option<Vec<(String, String)>> {
    let JsValue::Object(object) = value else {
        return None;
    };
    let mut out = Vec::with_capacity(object.len());
    for (key, entry) in object.iter() {
        let text = match entry {
            JsValue::Null => continue,
            JsValue::String(s) => s.to_utf8_lossy().into_owned(),
            other => json_stringify(other),
        };
        if text.len() > MAX_TRANSFORMED_FIELD_BYTES {
            return None;
        }
        out.push((key.to_utf8_lossy().into_owned(), text));
    }
    Some(out)
}

fn string_field(result: &JsObject, key: &str) -> Result<FieldUpdate<String>, ()> {
    match result.get(key) {
        None => Ok(None),
        Some(JsValue::Null) => Ok(Some(None)),
        Some(JsValue::String(s)) => Ok(Some(Some(s.to_utf8_lossy().into_owned()))),
        Some(_) => Err(()),
    }
}

fn map_field(result: &JsObject, key: &str) -> Result<FieldUpdate<Vec<(String, String)>>, ()> {
    match result.get(key) {
        None => Ok(None),
        Some(JsValue::Null) => Ok(Some(None)),
        Some(value) => coerce_string_map(value).map(|m| Some(Some(m))).ok_or(()),
    }
}

/// `encodeAttributeMap`: values the transformation left alone keep their exact wire form.
fn encode_attribute_map(map: Vec<(String, String)>, original: Option<&AvroMap>) -> AvroMap {
    let mut out = AvroMap::new();
    for (key, value) in map {
        let kept = original
            .and_then(|o| o.get(&key))
            .and_then(AvroValue::as_str)
            .filter(|wire| decode_log_attribute_value(wire).to_utf8_lossy() == value.as_str());
        let wire = match kept {
            Some(wire) => wire.to_string(),
            None => encode_log_attribute_value(&value),
        };
        out.assign(key, AvroValue::String(wire));
    }
    out
}

fn optional_string(value: Option<String>) -> AvroValue {
    value.map_or(AvroValue::Null, AvroValue::String)
}

pub fn apply_transform_result(record: &mut LogRecord, result: &JsValue) -> Applied {
    let result = match result {
        JsValue::Null | JsValue::Bool(false) => return Applied::Dropped,
        JsValue::Object(o) => o,
        _ => return Applied::Invalid,
    };
    let Ok(body) = string_field(result, "body") else {
        return Applied::Invalid;
    };
    let Ok(severity_text) = string_field(result, "severity_text") else {
        return Applied::Invalid;
    };
    let Ok(attributes) = map_field(result, "attributes") else {
        return Applied::Invalid;
    };
    let Ok(resource_attributes) = map_field(result, "resource_attributes") else {
        return Applied::Invalid;
    };

    let string_bytes = |new: &Option<Option<String>>, old: Option<&str>| match new {
        Some(v) => v.as_ref().map_or(0, String::len),
        None => old.map_or(0, str::len),
    };
    let map_bytes = |new: &Option<Option<Vec<(String, String)>>>, old: Option<&AvroMap>| match new {
        Some(v) => v
            .iter()
            .flatten()
            .map(|(k, v)| k.len() + v.len())
            .sum::<usize>(),
        None => old
            .into_iter()
            .flat_map(|m| m.iter_strings())
            .map(|(k, v)| k.len() + v.len())
            .sum(),
    };
    let total = string_bytes(&body, record.body())
        + string_bytes(&severity_text, record.severity_text())
        + map_bytes(&attributes, record.attributes())
        + map_bytes(&resource_attributes, record.resource_attributes());
    if total > MAX_TRANSFORMED_FIELD_BYTES {
        return Applied::Invalid;
    }

    if let Some(body) = body {
        record.set("body", optional_string(body));
    }
    if let Some(severity_text) = severity_text {
        record.set("severity_text", optional_string(severity_text));
    }
    for (name, map) in [
        ("attributes", attributes),
        ("resource_attributes", resource_attributes),
    ] {
        if let Some(map) = map {
            let value = match map {
                None => AvroValue::Null,
                Some(map) => AvroValue::Map(encode_attribute_map(map, record.get_map(name))),
            };
            record.set(name, value);
        }
    }
    Applied::Mutated
}

/// Other keys are never read, so a cycle there is harmless. Top-level keys are redacted too, as
/// `redactSensitiveStrings` rewrites every key.
fn result_fields(vm: &HogVM, value: &HogValue, sensitive: &[String]) -> JsValue {
    let invalid = JsValue::Number(0.0);
    let Ok(literal) = value.deref(&vm.heap) else {
        return JsValue::Null;
    };
    match literal {
        HogLiteral::Object(map) => {
            let mut out = JsObject::new();
            for (key, item) in map.iter() {
                let key = if sensitive.is_empty() {
                    Some(key.clone())
                } else {
                    redact_string(key, sensitive)
                };
                let Some(key) = key.filter(|k| {
                    ["body", "severity_text", "attributes", "resource_attributes"]
                        .contains(&k.as_str())
                }) else {
                    continue;
                };
                match hog_to_js(vm, item, sensitive) {
                    Ok(v) => out.insert_str(&key, v),
                    Err(_) => return invalid,
                }
            }
            JsValue::Object(out)
        }
        HogLiteral::Null => JsValue::Null,
        HogLiteral::Boolean(b) => JsValue::Bool(*b),
        // The Node VM returns a closure as an object with none of the record keys, which changes nothing.
        HogLiteral::Callable(_) | HogLiteral::Closure(_) => JsValue::Object(JsObject::new()),
        _ => invalid,
    }
}

pub fn execute_log_transformation(
    function: &HogFunction,
    record: &mut LogRecord,
    globals: OrderedJson,
    timeout_ms: f64,
    sensitive: &[String],
) -> TransformOutcome {
    let program = match &function.bytecode {
        Ok(program) => program,
        Err(error) => {
            return TransformOutcome {
                status: TransformStatus::Failed(error.clone()),
                duration_ms: 0.0,
                logs: Vec::new(),
            }
        }
    };
    let mut logs: Vec<String> = Vec::new();
    let mut print = |vm: &HogVM, args: Vec<HogValue>| -> Result<(), String> {
        if logs.len() < MAX_LOG_TRANSFORMATION_PRINT_LOGS {
            let args = hog_values_to_js(vm, &args, &[]).map_err(|e| match e {
                ConvertError::Cyclic => {
                    "TypeError: Converting circular structure to JSON".to_string()
                }
                ConvertError::TooLarge => "RangeError: Invalid string length".to_string(),
            })?;
            logs.push(sanitize_log_message(&args, sensitive));
        }
        Ok(())
    };
    let run = run_program(
        program,
        globals,
        timeout_ms,
        Some(&mut print),
        |vm, value| Ok(result_fields(vm, &value, sensitive)),
    );
    let status = match run.result {
        Err(error) => TransformStatus::Failed(error),
        Ok(result) => match apply_transform_result(record, &result) {
            Applied::Mutated => TransformStatus::Mutated,
            Applied::Dropped => TransformStatus::Dropped,
            Applied::Invalid => TransformStatus::Failed(INVALID_RESULT_ERROR.to_string()),
        },
    };
    TransformOutcome {
        status,
        duration_ms: run.duration_ms,
        logs,
    }
}

pub fn resolve_inputs(
    function: &HogFunction,
    project: &OrderedJson,
    record: &OrderedJson,
    timeout_ms: f64,
) -> Result<(OrderedJson, f64), String> {
    let mut inputs: Vec<(String, OrderedJson)> = Vec::with_capacity(function.inputs.len());
    let mut duration_ms = 0.0;
    for input in &function.inputs {
        let value = match &input.template {
            Some(template) => {
                let program = template
                    .as_ref()
                    .map_err(|e| format!("Error: Could not resolve input '{}': {e}", input.key))?;
                let run = run_program(
                    program,
                    globals(project, record, order_like_js(inputs.clone())),
                    timeout_ms,
                    None,
                    |vm, value| hog_to_js(vm, &value, &[]).map_err(|e| format!("{e:?}")),
                );
                duration_ms += run.duration_ms;
                let value = run
                    .result
                    .map_err(|e| format!("Error: Could not resolve input '{}': {e}", input.key))?;
                js_to_ordered(&value)
            }
            None => input
                .value
                .as_ref()
                .map_or(OrderedJson::Null, js_to_ordered),
        };
        match inputs.iter_mut().find(|(k, _)| *k == input.key) {
            Some(slot) => slot.1 = value,
            None => inputs.push((input.key.clone(), value)),
        }
    }
    Ok((order_like_js(inputs), duration_ms))
}

/// `inputs[key] = v` on a plain object puts array-index keys first.
fn order_like_js(entries: Vec<(String, OrderedJson)>) -> OrderedJson {
    let mut indexed: Vec<(u32, String, OrderedJson)> = Vec::new();
    let mut named = Vec::new();
    for (k, v) in entries {
        match crate::js::is_array_index(&k) {
            Some(n) => indexed.push((n, k, v)),
            None => named.push((k, v)),
        }
    }
    indexed.sort_by_key(|(n, _, _)| *n);
    OrderedJson::Object(
        indexed
            .into_iter()
            .map(|(_, k, v)| (k, v))
            .chain(named)
            .collect(),
    )
}
