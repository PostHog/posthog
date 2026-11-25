//! Pure, editable Rhai expressions and native collection/JSON/text primitives.
//! No view engine, filesystem, imports, processes or network capabilities enter
//! this runtime. Optimized ASTs and regexes are cached on each worker thread.
use rhai::{
    AST, Array, Dynamic, Engine, EvalAltResult, ImmutableString, Map, OptimizationLevel, Scope,
};
use serde_json::Value;
use std::{
    cell::{Cell, RefCell},
    collections::{HashMap, HashSet},
    rc::Rc,
    time::{Duration, Instant},
};

type Error = Box<EvalAltResult>;
type Result<T> = std::result::Result<T, Error>;
const MAX_BYTES: usize = 8 * 1024 * 1024;
const MAX_ITEMS: usize = 100_000;
const MAX_CODE: usize = 16 * 1024;
const OPERATIONS: u64 = 1_000_000;
const TIME: Duration = Duration::from_millis(500);

#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Evaluation {
    pub value: Value,
    pub elapsed_us: u64,
    pub operations: u64,
}
struct Budget {
    deadline: Cell<Option<Instant>>,
    cancelled: RefCell<Option<async_channel::Receiver<()>>>,
    operations: Cell<u64>,
}
struct Runtime {
    engine: Engine,
    cache: HashMap<String, AST>,
    budget: Rc<Budget>,
}
thread_local! {static RUNTIME:RefCell<Runtime>=RefCell::new(Runtime::new());}

fn error(text: impl Into<String>) -> Error {
    text.into().into()
}
fn data_size(value: &Dynamic) -> Result<usize> {
    fn size(v: &Dynamic, depth: usize, bytes: &mut usize, nodes: &mut usize) -> Result<()> {
        *nodes += 1;
        if depth > 64 || *nodes > 500_000 {
            return Err(error(
                "Expression JSON is too deeply nested or has too many values",
            ));
        }
        if let Some(s) = v.read_lock::<ImmutableString>() {
            *bytes = bytes.saturating_add(s.len());
        } else if let Some(a) = v.read_lock::<Array>() {
            for x in a.iter() {
                size(x, depth + 1, bytes, nodes)?;
            }
        } else if let Some(m) = v.read_lock::<Map>() {
            for (k, x) in m.iter() {
                *bytes = bytes.saturating_add(k.len());
                size(x, depth + 1, bytes, nodes)?;
            }
        } else {
            *bytes = bytes.saturating_add(8);
        }
        if *bytes > MAX_BYTES {
            return Err(error("Expression JSON exceeds 8 MB"));
        }
        Ok(())
    }
    let mut bytes = 0;
    size(value, 0, &mut bytes, &mut 0)?;
    Ok(bytes)
}
fn json(value: &Dynamic) -> Result<Value> {
    data_size(value)?;
    rhai::serde::from_dynamic(value).map_err(|e| error(e.to_string()))
}
fn dynamic(value: &Value) -> Result<Dynamic> {
    rhai::serde::to_dynamic(value).map_err(|e| error(e.to_string()))
}
fn field(value: &Dynamic, key: &str) -> Dynamic {
    if key.is_empty() {
        return value.clone();
    }
    if !key.starts_with('/') {
        return value
            .read_lock::<Map>()
            .and_then(|m| m.get(key).cloned())
            .unwrap_or_default();
    }
    let mut result = value.clone();
    for part in key[1..].split('/') {
        let key = part.replace("~1", "/").replace("~0", "~");
        result = if result.is_map() {
            result
                .cast::<Map>()
                .get(key.as_str())
                .cloned()
                .unwrap_or_default()
        } else if result.is_array() {
            key.parse::<usize>()
                .ok()
                .and_then(|i| result.cast::<Array>().get(i).cloned())
                .unwrap_or_default()
        } else {
            Dynamic::UNIT
        };
    }
    result
}
fn scalar_key(value: &Dynamic) -> Result<Option<String>> {
    if value.is_unit() {
        Ok(None)
    } else if value.is::<ImmutableString>() {
        Ok(Some(format!("s:{}", value.clone_cast::<ImmutableString>())))
    } else if value.is_int() {
        Ok(Some(format!("n:{}", value.as_int().unwrap())))
    } else if value.is_float() {
        Ok(Some(format!("n:{}", value.as_float().unwrap())))
    } else if value.is_bool() {
        Ok(Some(format!("b:{}", value.as_bool().unwrap())))
    } else {
        Err(error("Key must be a scalar"))
    }
}
impl Budget {
    fn check(&self) -> Result<()> {
        if self
            .cancelled
            .borrow()
            .as_ref()
            .is_some_and(|r| r.is_closed())
        {
            return Err(error("Workflow expression cancelled"));
        }
        if self.deadline.get().is_some_and(|d| Instant::now() >= d) {
            return Err(error("Expression exceeded 500 ms"));
        }
        Ok(())
    }
}
impl Runtime {
    fn new() -> Self {
        let mut engine = Engine::new();
        engine
            .register_custom_syntax(["null"], false, |_, _| Ok(Dynamic::UNIT))
            .expect("native null literal");
        engine
            .set_optimization_level(OptimizationLevel::Simple)
            .set_max_operations(OPERATIONS)
            .set_max_expr_depths(64, 64)
            .set_max_call_levels(32)
            .set_max_variables(512)
            .set_max_functions(128)
            .set_max_array_size(MAX_ITEMS)
            .set_max_map_size(MAX_ITEMS)
            .set_max_string_size(MAX_BYTES)
            .disable_symbol("eval");
        engine.on_print(|_| {});
        engine.on_debug(|_, _, _| {});
        let budget = Rc::new(Budget {
            deadline: Cell::new(None),
            cancelled: RefCell::default(),
            operations: Cell::new(0),
        });
        let limits = budget.clone();
        engine.on_progress(move |ops| {
            limits.operations.set(ops);
            if ops % 256 == 0 {
                limits.check().err().map(|e| Dynamic::from(e.to_string()))
            } else {
                None
            }
        });
        register(&mut engine, budget.clone());
        Self {
            engine,
            cache: HashMap::new(),
            budget,
        }
    }
    fn compile(&mut self, code: &str) -> std::result::Result<AST, String> {
        if code.trim().is_empty() || code.len() > MAX_CODE {
            return Err("Expressions need 1–16384 bytes of source".into());
        }
        if let Some(ast) = self.cache.get(code) {
            return Ok(ast.clone());
        }
        let mut constants = Scope::new();
        constants.push_constant("null", Dynamic::UNIT);
        let ast = self
            .engine
            .compile_with_scope(&constants, code)
            .map_err(|e| e.to_string())?;
        // Bound cached code/ASTs even while an editor tries many variants.
        if self.cache.len() >= 128
            || self.cache.keys().map(String::len).sum::<usize>() + code.len() > 1024 * 1024
        {
            self.cache.clear();
        }
        self.cache.insert(code.into(), ast.clone());
        Ok(ast)
    }
}
pub fn validate(code: &str) -> std::result::Result<(), String> {
    RUNTIME.with(|runtime| runtime.borrow_mut().compile(code).map(|_| ()))
}
pub fn evaluate(
    code: &str,
    input: Value,
    cancelled: Option<async_channel::Receiver<()>>,
) -> std::result::Result<Evaluation, String> {
    let started = Instant::now();
    if serde_json::to_vec(&input).map_err(|e| e.to_string())?.len() > MAX_BYTES {
        return Err("Expression input exceeds 8 MB".into());
    }
    RUNTIME.with(|runtime| {
        let mut runtime = runtime.borrow_mut();
        let ast = runtime.compile(code)?;
        let mut scope = Scope::new();
        scope.push_constant("input", dynamic(&input).map_err(|e| e.to_string())?);
        scope.push_constant("null", Dynamic::UNIT);
        runtime.budget.deadline.set(Some(Instant::now() + TIME));
        runtime.budget.operations.set(0);
        *runtime.budget.cancelled.borrow_mut() = cancelled;
        let output = runtime
            .engine
            .eval_ast_with_scope::<Dynamic>(&mut scope, &ast)
            .map_err(|e| e.to_string())
            .and_then(|v| json(&v).map_err(|e| format!("Expression must return JSON data: {e}")));
        let checked = runtime.budget.check().map_err(|e| e.to_string());
        runtime.budget.deadline.set(None);
        runtime.budget.cancelled.borrow_mut().take();
        checked?;
        let value = output?;
        if serde_json::to_vec(&value).map_err(|e| e.to_string())?.len() > MAX_BYTES {
            return Err("Expression output exceeds 8 MB".into());
        }
        Ok(Evaluation {
            value,
            elapsed_us: started.elapsed().as_micros() as u64,
            operations: runtime.budget.operations.get(),
        })
    })
}

fn register(engine: &mut Engine, budget: Rc<Budget>) {
    engine.register_fn(
        "join",
        |values: Array, separator: ImmutableString| -> Result<String> {
            let mut text = String::new();
            for (index, value) in values.into_iter().enumerate() {
                let part = if value.is_unit() {
                    String::new()
                } else {
                    value.to_string()
                };
                let gap = if index > 0 { separator.len() } else { 0 };
                if text.len().saturating_add(gap).saturating_add(part.len()) > MAX_BYTES {
                    return Err(error("Joined text exceeds 8 MB"));
                }
                if index > 0 {
                    text.push_str(&separator);
                }
                text.push_str(&part);
            }
            Ok(text)
        },
    );
    engine.register_fn("trimmed", |s: ImmutableString| s.trim().to_owned());
    engine.register_fn(
        "replace_text",
        |s: ImmutableString,
         needle: ImmutableString,
         replacement: ImmutableString|
         -> Result<String> {
            let growth = s
                .match_indices(needle.as_str())
                .count()
                .saturating_mul(replacement.len());
            if s.len().saturating_add(growth) > MAX_BYTES {
                return Err(error("Text output exceeds 8 MB"));
            }
            Ok(s.replace(needle.as_str(), replacement.as_str()))
        },
    );
    engine.register_fn("iso_date", |millis: i64| -> Result<String> {
        Ok(chrono::DateTime::from_timestamp_millis(millis)
            .ok_or_else(|| error("Invalid timestamp"))?
            .format("%Y-%m-%d")
            .to_string())
    });
    engine.register_fn("iso_time", |millis: i64| -> Result<String> {
        Ok(chrono::DateTime::from_timestamp_millis(millis)
            .ok_or_else(|| error("Invalid timestamp"))?
            .to_rfc3339_opts(chrono::SecondsFormat::Millis, true))
    });
    // Explicit UTC parsing keeps chart periods and source timestamps independent
    // of the machine's locale/time zone. Invalid input remains JSON null.
    engine.register_fn("timestamp", |text: ImmutableString| -> Dynamic {
        let parsed = chrono::DateTime::parse_from_rfc3339(&text)
            .map(|date| date.timestamp_millis())
            .ok()
            .or_else(|| {
                chrono::NaiveDate::parse_from_str(&text, "%Y-%m-%d")
                    .ok()?
                    .and_hms_opt(0, 0, 0)
                    .map(|date| date.and_utc().timestamp_millis())
            })
            .or_else(|| {
                ["%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%dT%H:%M:%S%.f"]
                    .iter()
                    .find_map(|format| chrono::NaiveDateTime::parse_from_str(&text, format).ok())
                    .map(|date| date.and_utc().timestamp_millis())
            });
        parsed.map(Dynamic::from).unwrap_or_default()
    });
    engine.register_fn(
        "get",
        |v: Dynamic, key: ImmutableString, default: Dynamic| {
            let v = field(&v, &key);
            if v.is_unit() { default } else { v }
        },
    );
    engine.register_fn(
        "coalesce",
        |value: Dynamic, default: Dynamic| if value.is_unit() { default } else { value },
    );
    engine.register_fn("truthy", |v: Dynamic| {
        if v.is_unit() {
            false
        } else if v.is_bool() {
            v.as_bool().unwrap()
        } else if v.is_int() {
            v.as_int().unwrap() != 0
        } else if v.is_float() {
            v.as_float().unwrap() != 0.
        } else if v.is_string() {
            !v.clone_cast::<ImmutableString>().is_empty()
        } else {
            true
        }
    });
    engine.register_fn("merge", |mut a: Map, b: Map| {
        a.extend(b);
        a
    });
    engine.register_fn("omit", |mut value: Map, fields: Array| {
        for field in fields {
            if let Some(k) = field.try_cast::<ImmutableString>() {
                value.remove(k.as_str());
            }
        }
        value
    });
    engine.register_fn("pick", |value: Map, fields: Array| {
        fields
            .into_iter()
            .filter_map(|f| f.try_cast::<ImmutableString>())
            .filter_map(|k| value.get(k.as_str()).map(|v| (k.into(), v.clone())))
            .collect::<Map>()
    });
    engine.register_fn("pluck", |rows: Array, key: ImmutableString| {
        rows.iter().map(|r| field(r, &key)).collect::<Array>()
    });
    engine.register_fn("flatten", |rows: Array| -> Result<Array> {
        let size = rows
            .iter()
            .filter_map(|r| r.read_lock::<Array>())
            .map(|a| a.len())
            .sum::<usize>();
        if size > MAX_ITEMS {
            return Err(error("Flatten exceeds 100000 items"));
        }
        Ok(rows
            .into_iter()
            .filter_map(|r| r.try_cast::<Array>())
            .flatten()
            .collect())
    });
    engine.register_fn("take", |mut rows: Array, count: i64| {
        rows.truncate(count.max(0) as usize);
        rows
    });
    engine.register_fn("take", |text: ImmutableString, count: i64| {
        text.chars().take(count.max(0) as usize).collect::<String>()
    });
    engine.register_fn("unique", |rows: Array| -> Result<Array> {
        let mut seen = HashSet::new();
        let mut result = Array::new();
        for row in rows {
            let k = serde_json::to_string(&json(&row)?).map_err(|e| error(e.to_string()))?;
            if seen.insert(k) {
                result.push(row);
            }
        }
        Ok(result)
    });
    engine.register_fn(
        "index_by",
        |rows: Array, key: ImmutableString| -> Result<Map> {
            let mut index = Map::new();
            for row in rows {
                let k = field(&row, &key);
                if !k.is_unit() {
                    index.insert(k.to_string().into(), row);
                }
            }
            Ok(index)
        },
    );
    engine.register_fn(
        "group_by",
        |rows: Array, key: ImmutableString| -> Result<Map> {
            let mut index = Map::new();
            for row in rows {
                let k = field(&row, &key);
                if !k.is_unit() {
                    let entry = index
                        .entry(k.to_string().into())
                        .or_insert_with(|| Dynamic::from(Array::new()));
                    entry.write_lock::<Array>().unwrap().push(row);
                }
            }
            Ok(index)
        },
    );
    engine.register_fn(
        "sort_by",
        |mut rows: Array, key: ImmutableString, descending: bool| -> Result<Array> {
            let mut keyed: Vec<_> = rows.drain(..).map(|r| (field(&r, &key), r)).collect();
            for (key, _) in &keyed {
                scalar_key(key)?;
            }
            keyed.sort_by(|(a, _), (b, _)| {
                let c = if a.is_int() && b.is_int() {
                    a.as_int().unwrap().cmp(&b.as_int().unwrap())
                } else if (a.is_int() || a.is_float()) && (b.is_int() || b.is_float()) {
                    let n =
                        |v: &Dynamic| v.as_float().unwrap_or_else(|_| v.as_int().unwrap() as f64);
                    n(a).total_cmp(&n(b))
                } else {
                    a.to_string().cmp(&b.to_string())
                };
                if descending { c.reverse() } else { c }
            });
            Ok(keyed.into_iter().map(|(_, r)| r).collect())
        },
    );
    let limits = budget.clone();
    engine.register_fn(
        "left_join",
        move |base: Array,
              rows: Array,
              left: ImmutableString,
              right: ImmutableString,
              output: ImmutableString,
              many: bool|
              -> Result<Array> {
            if ["__proto__", "constructor", "prototype"].contains(&output.as_str()) {
                return Err(error("Reserved join field"));
            }
            let mut index: HashMap<String, Array> = HashMap::new();
            let mut weights:HashMap<String,usize>=HashMap::new();
            for (i, row) in rows.into_iter().enumerate() {
                if i % 1024 == 0 {
                    limits.check()?;
                }
                if let Some(key) = scalar_key(&field(&row, &right))? {
                    *weights.entry(key.clone()).or_default()+=data_size(&row)?;
                    let matches = index.entry(key).or_default();
                    if !many && !matches.is_empty() {
                        return Err(error("Ambiguous single-match join"));
                    }
                    matches.push(row);
                }
            }
            let mut result = Array::with_capacity(base.len());
            let mut produced=0usize;let mut matches_count=0usize;
            for (i, row) in base.into_iter().enumerate() {
                if i % 1024 == 0 {
                    limits.check()?;
                }
                let key = scalar_key(&field(&row, &left))?;
                let found = key.as_ref().and_then(|k| index.get(k));
                matches_count=matches_count.saturating_add(found.map_or(0,Vec::len));
                produced=produced.saturating_add(data_size(&row)?).saturating_add(output.len()).saturating_add(key.as_ref().and_then(|k|weights.get(k)).copied().unwrap_or(0));
                if produced>MAX_BYTES || matches_count>MAX_ITEMS {return Err(error("Join output exceeds its data budget; filter the inputs or split into batches"));}
                let value = if many {
                    Dynamic::from(found.cloned().unwrap_or_default())
                } else {
                    found.and_then(|v| v.first()).cloned().unwrap_or_default()
                };
                let mut row = row
                    .try_cast::<Map>()
                    .ok_or_else(|| error("Join base rows must be objects"))?;
                row.insert(output.clone().into(), value);
                result.push(row.into());
            }
            Ok(result)
        },
    );
    engine.register_fn("parse_json", |text: ImmutableString| -> Result<Dynamic> {
        if text.len() > MAX_BYTES {
            return Err(error("JSON text exceeds 8 MB"));
        }
        let v: Value = serde_json::from_str(&text).map_err(|e| error(e.to_string()))?;
        dynamic(&v)
    });
    engine.register_fn("json", |value: Dynamic| -> Result<String> {
        let text = serde_json::to_string(&json(&value)?).map_err(|e| error(e.to_string()))?;
        if text.len() > MAX_BYTES {
            Err(error("JSON text exceeds 8 MB"))
        } else {
            Ok(text)
        }
    });
    engine.register_fn("unwrap_json", |value: Dynamic| -> Result<Dynamic> {
        let parsed = json(&value)?;
        let text = if let Some(content) = parsed["content"].as_array() {
            Some(
                content
                    .iter()
                    .map(|c| c["text"].as_str().unwrap_or(""))
                    .collect::<String>(),
            )
        } else {
            parsed.as_str().map(str::to_owned)
        };
        if let Some(text) = text {
            return dynamic(&serde_json::from_str::<Value>(&text).unwrap_or(Value::String(text)));
        }
        Ok(value)
    });
    let regexes: Rc<RefCell<HashMap<String, regex::Regex>>> = Rc::default();
    let compile = move |pattern: &str| -> Result<regex::Regex> {
        if pattern.len() > 4096 {
            return Err(error("Regex exceeds 4096 bytes"));
        }
        if let Some(re) = regexes.borrow().get(pattern) {
            return Ok(re.clone());
        }
        let re = regex::RegexBuilder::new(pattern)
            .size_limit(1024 * 1024)
            .dfa_size_limit(1024 * 1024)
            .build()
            .map_err(|e| error(e.to_string()))?;
        if regexes.borrow().len() >= 128 {
            regexes.borrow_mut().clear();
        }
        regexes.borrow_mut().insert(pattern.into(), re.clone());
        Ok(re)
    };
    let re = compile.clone();
    engine.register_fn(
        "matches",
        move |text: ImmutableString, pattern: ImmutableString| -> Result<bool> {
            Ok(re(&pattern)?.is_match(&text))
        },
    );
    let re = compile.clone();
    engine.register_fn(
        "capture",
        move |text: ImmutableString, pattern: ImmutableString| -> Result<Array> {
            Ok(re(&pattern)?
                .captures(&text)
                .map(|c| {
                    c.iter()
                        .map(|m| {
                            m.map(|m| Dynamic::from(m.as_str().to_owned()))
                                .unwrap_or_default()
                        })
                        .collect()
                })
                .unwrap_or_default())
        },
    );
    let re = compile.clone();
    let limits = budget.clone();
    engine.register_fn(
        "captures",
        move |text: ImmutableString, pattern: ImmutableString| -> Result<Array> {
            let mut out = Array::new();
            for (i, c) in re(&pattern)?.captures_iter(&text).enumerate() {
                if i % 1024 == 0 {
                    limits.check()?;
                }
                if i >= MAX_ITEMS {
                    return Err(error("Too many regex matches"));
                }
                out.push(Dynamic::from(
                    c.iter()
                        .map(|m| {
                            m.map(|m| Dynamic::from(m.as_str().to_owned()))
                                .unwrap_or_default()
                        })
                        .collect::<Array>(),
                ));
            }
            Ok(out)
        },
    );
    engine.register_fn(
        "replace_re",
        move |text: ImmutableString,
              pattern: ImmutableString,
              replacement: ImmutableString|
              -> Result<String> {
            let re = compile(&pattern)?;
            let mut out = String::new();
            let mut end = 0;
            for (i, cap) in re.captures_iter(&text).enumerate() {
                if i % 1024 == 0 {
                    budget.check()?;
                }
                let whole = cap.get(0).unwrap();
                let maximum = cap
                    .iter()
                    .flatten()
                    .map(|m| m.len())
                    .max()
                    .unwrap_or(0)
                    .max(1)
                    .saturating_mul(replacement.len());
                if maximum > MAX_BYTES || i > MAX_ITEMS {
                    return Err(error("Regex replacement exceeds its output budget"));
                }
                let mut piece = String::new();
                cap.expand(&replacement, &mut piece);
                if out.len() + whole.start() - end + piece.len() > MAX_BYTES {
                    return Err(error("Regex output exceeds 8 MB"));
                }
                out.push_str(&text[end..whole.start()]);
                out.push_str(&piece);
                end = whole.end();
            }
            if out.len() + text.len() - end > MAX_BYTES {
                return Err(error("Regex output exceeds 8 MB"));
            }
            out.push_str(&text[end..]);
            Ok(out)
        },
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn timestamps_parse_offsets_dates_and_fractional_utc_and_reject_invalid_input() {
        let value = evaluate(
            "input.map(|s|timestamp(s))",
            json!([
                "2026-11-12T08:00:00Z",
                "2026-11-12T10:00:00+02:00",
                "2026-11-12",
                "2026-11-12 08:00:00.125",
                "not a date"
            ]),
            None,
        )
        .unwrap()
        .value;
        assert_eq!(
            value,
            json!([
                1794470400000i64,
                1794470400000i64,
                1794441600000i64,
                1794470400125i64,
                null
            ])
        );
    }
    #[test]
    fn expressions_have_functions_closures_and_native_collection_operations() {
        let out=evaluate("fn key(p) { p.repo + \"#\" + p.number } let rows=input.filter(|p| p.open).map(|p| #{id:key(p),repo:p.repo}); group_by(rows, \"repo\")",json!([{"repo":"a","number":1,"open":true},{"repo":"b","number":2,"open":false}]),None).unwrap();
        assert_eq!(out.value, json!({"a":[{"id":"a#1","repo":"a"}]}));
        assert_eq!(
            evaluate(
                "let offset = input.offset; input.items.map(|n| n + offset)",
                json!({"items":[1,2],"offset":3}),
                None
            )
            .unwrap()
            .value,
            json!([4, 5])
        );
        assert_eq!(
            evaluate(
                "left_join(input.base,input.detail,\"id\",\"id\",\"detail\",false)",
                json!({"base":[{"id":1},{"id":"1"},{"id":2}],"detail":[{"id":1,"ok":true}]}),
                None
            )
            .unwrap()
            .value,
            json!([{"id":1,"detail":{"id":1,"ok":true}},{"id":"1","detail":null},{"id":2,"detail":null}])
        );
    }
    #[test]
    fn code_errors_and_resource_limits_fail_without_exposing_host_capabilities() {
        for code in [
            "loop {}",
            "fn f(){f()} f()",
            "import \"/etc/passwd\" as x; x",
            "read_file(\"/etc/passwd\")",
            "eval(\"1+1\")",
            "input.host.call()",
        ] {
            assert!(evaluate(code, Value::Null, None).is_err(), "{code}");
        }
        let (tx, rx) = async_channel::bounded::<()>(1);
        tx.close();
        assert!(
            evaluate("input", json!({}), Some(rx))
                .unwrap_err()
                .contains("cancelled")
        );
        assert_eq!(
            evaluate("input.map(|v| v*2)", json!([1, 2, 3]), None)
                .unwrap()
                .value,
            json!([2, 4, 6])
        );
    }
    #[test]
    fn json_regex_and_stable_order_helpers_are_native_and_typed() {
        assert_eq!(
            evaluate(
                "input.join(\" · \")",
                json!(["café", null, "東京", 42]),
                None
            )
            .unwrap()
            .value,
            "café ·  · 東京 · 42"
        );
        assert!(
            evaluate(
                "input.join(\"\")",
                json!(["x".repeat(5 * 1024 * 1024), "y".repeat(5 * 1024 * 1024)]),
                None
            )
            .is_err()
        );
        assert_eq!(
            evaluate("capture(input, \"#[0-9]+\")[0]", json!("PR #42"), None)
                .unwrap()
                .value,
            "#42"
        );
        assert_eq!(
            evaluate(
                "replace_re(input, \"([a-z]+):([0-9]+)\", \"$2/$1\")",
                json!("a:42"),
                None
            )
            .unwrap()
            .value,
            "42/a"
        );
        assert_eq!(
            evaluate(
                "sort_by(unique(input), \"score\", true)",
                json!([{"score":2},{"score":8},{"score":2}]),
                None
            )
            .unwrap()
            .value,
            json!([{"score":8},{"score":2}])
        );
    }
    #[test]
    fn joins_bound_repeated_match_expansion_before_allocating_the_result() {
        let input = json!({"base":[{"id":1},{"id":1},{"id":1}],"detail":[{"id":1,"text":"x".repeat(3*1024*1024)}]});
        assert!(
            evaluate(
                "left_join(input.base,input.detail,\"id\",\"id\",\"found\",true)",
                input,
                None
            )
            .unwrap_err()
            .contains("budget")
        );
    }
}
