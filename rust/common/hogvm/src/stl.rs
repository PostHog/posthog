use core::str;
use std::collections::HashMap;

use chrono::{DateTime, Datelike, LocalResult, NaiveDate, NaiveDateTime, TimeZone};
use indexmap::IndexMap;
use rand::Rng;
use serde::de::{MapAccess, SeqAccess, Visitor};
use serde_json::{json, Value as JsonValue};

use crate::{
    construct_free_standing,
    error::VmError,
    memory::{HeapReference, VmHeap},
    print_hog_string_output,
    program::Module,
    util::{get_json_nested, regex_extract, regex_match},
    values::{HogLiteral, HogValue, Num},
    vm::{HogVM, MAX_JSON_SERDE_DEPTH},
    ExportedFunction,
};

pub const TO_STRING_RECURSION_LIMIT: usize = 32;

// A "native function" is a function that can be called from within the VM. It takes a list
// of arguments, and returns either a value, or null. It's pure (cannot modify the VM state).
pub type NativeFunction = Box<dyn Fn(&HogVM, Vec<HogValue>) -> Result<HogValue, VmError>>;

pub fn stl_map() -> HashMap<String, NativeFunction> {
    stl().into_iter().collect()
}

pub fn hog_stl_map() -> HashMap<String, Module> {
    let mut res = HashMap::new();
    res.insert("stl".to_string(), hog_stl());
    res
}

// NOTE - if you make changes to this, be sure to re-run `bin/dump_hogvmrs_stl`
pub fn stl() -> Vec<(String, NativeFunction)> {
    [
        (
            "toString",
            native_func(|vm, args| {
                // Can't just use a ToString trait implementation, because ToString requires heap access to chase
                // references in arrays and dicts
                assert_argc(&args, 1, "toString")?;
                to_string(&vm.heap, &args[0], 0).map(|s| HogLiteral::String(s).into())
            }),
        ),
        (
            "typeof",
            native_func(|vm, args| {
                assert_argc(&args, 1, "typeof")?;
                let arg = args[0].deref(&vm.heap)?;
                // TODO - tuples, dates, datetimes, errors are all just duck-typed "objects" or "arrays", but we should
                // still support them I guess
                match arg {
                    // The reference distinguishes integer/float, not a single "number".
                    HogLiteral::Number(n) => {
                        let t = if n.is_float() { "float" } else { "integer" };
                        Ok(HogLiteral::String(t.to_string()).into())
                    }
                    HogLiteral::Boolean(_) => Ok(HogLiteral::String("boolean".to_string()).into()),
                    HogLiteral::String(_) => Ok(HogLiteral::String("string".to_string()).into()),
                    HogLiteral::Array(_) => Ok(HogLiteral::String("array".to_string()).into()),
                    HogLiteral::Object(_) => Ok(HogLiteral::String("object".to_string()).into()),
                    HogLiteral::Callable(_) => {
                        Ok(HogLiteral::String("function".to_string()).into())
                    }
                    HogLiteral::Closure(_) => Ok(HogLiteral::String("function".to_string()).into()),
                    HogLiteral::Null => Ok(HogLiteral::String("null".to_string()).into()),
                }
            }),
        ),
        (
            // Emitted by the `null_safe_comparisons=True` wrapper to guard missing-property leaves.
            "isNull",
            native_func(|vm, args| {
                assert_argc(&args, 1, "isNull")?;
                Ok(
                    HogLiteral::Boolean(matches!(args[0].deref(&vm.heap)?, HogLiteral::Null))
                        .into(),
                )
            }),
        ),
        (
            "values",
            native_func(|vm, args| {
                assert_argc(&args, 1, "values")?;
                let arg = args[0].deref(&vm.heap)?;
                match arg {
                    HogLiteral::Array(_) => Ok(arg.clone().into()),
                    HogLiteral::Object(obj) => {
                        Ok(HogLiteral::Array(obj.values().cloned().collect()).into())
                    }
                    _ => Err(VmError::NativeCallFailed(
                        "values() only supports arrays and objects".to_string(),
                    )),
                }
            }),
        ),
        (
            "length",
            native_func(|vm, args| {
                assert_argc(&args, 1, "length")?;
                let arg = args[0].deref(&vm.heap)?;
                match arg {
                    HogLiteral::Array(arr) => Ok(HogLiteral::Number(arr.len().into()).into()),
                    HogLiteral::Object(obj) => Ok(HogLiteral::Number(obj.len().into()).into()),
                    HogLiteral::String(str) => Ok(HogLiteral::Number(str.len().into()).into()),
                    _ => Err(VmError::NativeCallFailed(
                        "length() only supports arrays, objects and strings".to_string(),
                    )),
                }
            }),
        ),
        (
            "arrayPushBack",
            native_func(|vm, args| {
                // notably, due to all native functions being pure, we don't mutate these arrays in place
                assert_argc(&args, 2, "arrayPushBack")?;
                let array = args[0].deref(&vm.heap)?;
                let value = args[1].clone();
                match array {
                    HogLiteral::Array(arr) => {
                        let mut arr = arr.clone();
                        arr.push(value);
                        Ok(HogLiteral::Array(arr).into())
                    }
                    _ => Err(VmError::NativeCallFailed(
                        "arrayPushBack() only supports arrays".to_string(),
                    )),
                }
            }),
        ),
        (
            "arrayPushFront",
            native_func(|vm, args| {
                assert_argc(&args, 2, "arrayPushFront")?;
                let array = args[0].deref(&vm.heap)?;
                let value = args[1].clone();
                match array {
                    HogLiteral::Array(arr) => {
                        let mut arr = arr.clone();
                        arr.insert(0, value);
                        Ok(HogLiteral::Array(arr).into())
                    }
                    _ => Err(VmError::NativeCallFailed(
                        "arrayPushFront() only supports arrays".to_string(),
                    )),
                }
            }),
        ),
        (
            "arrayPopBack",
            native_func(|vm, args| {
                assert_argc(&args, 1, "arrayPopBack")?;
                let array = args[0].deref(&vm.heap)?;
                match array {
                    HogLiteral::Array(arr) => {
                        let mut arr = arr.clone();
                        arr.pop();
                        Ok(HogLiteral::Array(arr).into())
                    }
                    _ => Err(VmError::NativeCallFailed(
                        "arrayPopBack() only supports arrays".to_string(),
                    )),
                }
            }),
        ),
        (
            "arrayPopFront",
            native_func(|vm, args| {
                assert_argc(&args, 1, "arrayPopFront")?;
                let array = args[0].deref(&vm.heap)?;
                match array {
                    HogLiteral::Array(arr) => {
                        let mut arr = arr.clone();
                        if !arr.is_empty() {
                            arr.remove(0);
                        }
                        Ok(HogLiteral::Array(arr).into())
                    }
                    _ => Err(VmError::NativeCallFailed(
                        "arrayPopFront() only supports arrays".to_string(),
                    )),
                }
            }),
        ),
        (
            "arraySort",
            native_func(|vm, args| {
                assert_argc(&args, 1, "arraySort")?;
                let array = args[0].deref(&vm.heap)?;
                match array {
                    HogLiteral::Array(arr) => {
                        let nums = collect_sorted_nums(&vm.heap, arr, "arraySort")?;
                        Ok(HogLiteral::Array(nums.into_iter().map(|n| n.into()).collect()).into())
                    }
                    _ => Err(VmError::NativeCallFailed(
                        "arraySort() only supports arrays".to_string(),
                    )),
                }
            }),
        ),
        (
            "arrayReverse",
            native_func(|vm, args| {
                assert_argc(&args, 1, "arrayReverse")?;
                let array = args[0].deref(&vm.heap)?;
                match array {
                    HogLiteral::Array(arr) => {
                        let mut arr = arr.clone();
                        arr.reverse();
                        Ok(HogLiteral::Array(arr).into())
                    }
                    _ => Err(VmError::NativeCallFailed(
                        "arrayReverse() only supports arrays".to_string(),
                    )),
                }
            }),
        ),
        (
            "arrayReverseSort",
            native_func(|vm, args| {
                assert_argc(&args, 1, "arrayReverseSort")?;
                let array = args[0].deref(&vm.heap)?;
                match array {
                    HogLiteral::Array(arr) => {
                        let mut nums = collect_sorted_nums(&vm.heap, arr, "arrayReverseSort")?;
                        nums.reverse();
                        Ok(HogLiteral::Array(nums.into_iter().map(|n| n.into()).collect()).into())
                    }
                    _ => Err(VmError::NativeCallFailed(
                        "arrayReverseSort() only supports arrays".to_string(),
                    )),
                }
            }),
        ),
        (
            "arrayStringConcat",
            native_func(|vm, args| {
                assert_argc(&args, 2, "arrayStringConcat")?;
                let vals = args[0].deref(&vm.heap)?;
                let sep = args[1].deref(&vm.heap)?.try_as::<str>()?;
                let HogLiteral::Array(vals) = vals else {
                    return Err(VmError::NativeCallFailed(
                        "arrayStringConcat() only supports arrays".to_string(),
                    ));
                };
                let mut parts = Vec::with_capacity(vals.len());
                for val in vals.iter() {
                    parts.push(to_string(&vm.heap, val, 0)?);
                }
                Ok(HogLiteral::String(parts.join(sep)).into())
            }),
        ),
        (
            "has",
            native_func(|vm, args| {
                assert_argc(&args, 2, "has")?;
                let haystack = &args[0];
                let needle = &args[1];
                haystack.contains(needle, &vm.heap).map(|res| res.into())
            }),
        ),
        (
            "indexOf",
            native_func(|vm, args| {
                assert_argc(&args, 2, "indexOf")?;
                let haystack = &args[0].deref(&vm.heap)?;
                let needle = &args[1];
                match haystack {
                    HogLiteral::Array(vals) => {
                        for (i, val) in vals.iter().enumerate() {
                            if *needle.equals(val, &vm.heap)?.try_as()? {
                                return Ok((i as i64).saturating_add(1).into());
                            }
                        }
                        Ok(HogLiteral::Null.into())
                    }
                    _ => Err(VmError::NativeCallFailed(
                        "indexOf() only supports arrays".to_string(),
                    )),
                }
            }),
        ),
        (
            "notEmpty",
            native_func(|vm, args| {
                assert_argc(&args, 1, "notEmpty")?;
                let val = &args[0];
                match val.deref(&vm.heap)? {
                    HogLiteral::Array(a) => Ok(HogLiteral::Boolean(!a.is_empty()).into()),
                    HogLiteral::String(s) => Ok(HogLiteral::Boolean(!s.is_empty()).into()),
                    HogLiteral::Object(o) => Ok(HogLiteral::Boolean(!o.is_empty()).into()),
                    _ => Err(VmError::NativeCallFailed(format!(
                        "{} not supported by notEmpty",
                        val.type_name()
                    ))),
                }
            }),
        ),
        (
            "match",
            native_func(|vm, args| {
                assert_argc(&args, 2, "match")?;
                let value = args[0].deref(&vm.heap)?.try_as::<str>()?;
                let regex = args[1].deref(&vm.heap)?.try_as::<str>()?;
                Ok(HogLiteral::Boolean(regex_match(value, regex, true)?).into())
            }),
        ),
        (
            "extractRegex",
            native_func(err_to_null(|vm, args| {
                // Hog: extractRegex(haystack, pattern)
                assert_argc(&args, 2, "extractRegex")?;
                if matches!(args[0].deref(&vm.heap)?, HogLiteral::Null)
                    || matches!(args[1].deref(&vm.heap)?, HogLiteral::Null)
                {
                    return Ok(HogLiteral::String(String::new()).into());
                }
                let haystack = args[0].deref(&vm.heap)?.try_as::<str>()?;
                let pattern = args[1].deref(&vm.heap)?.try_as::<str>()?;
                Ok(HogLiteral::String(regex_extract(haystack, pattern)?).into())
            })),
        ),
        (
            "JSONExtract",
            native_func(err_to_null(|vm, args| {
                assert(
                    args.len() > 1,
                    "JSONExtract requires at least two arguments",
                )?;
                let val = args[0].deref(&vm.heap)?;
                let json = match val {
                    // Parse strings as json, if a string was passed
                    HogLiteral::String(s) => serde_json::from_str(s)
                        .map_err(|e| VmError::NativeCallFailed(e.to_string()))?,
                    // Otherwise just convert the hog to a json object
                    _ => vm.hog_to_json(&args[0])?,
                };
                // JSONExtract must be provided a return type as the final argument (as per the clickhouse implementation). We
                // ignore this return type, and treat any arguments between the first and last as path components
                let path = if args.len() > 2 {
                    &args[1..args.len() - 1]
                } else {
                    &[]
                };
                let res = get_json_nested(&json, path, vm)?;
                let Some(res) = res else {
                    return Ok(HogLiteral::Null.into());
                };
                construct_free_standing(res, 0)
            })),
        ),
        // Wrapped in `err_to_null` so an unparseable input becomes `Null`, letting a leaf's
        // `if(isNull(...), false, …)` guard yield `false` rather than erroring.
        ("toDateTime", native_func(err_to_null(to_datetime))),
        ("toDate", native_func(err_to_null(to_date))),
        (
            "multiSearchAnyCaseInsensitive",
            native_func(|vm, args| {
                if args.len() != 2 {
                    return Err(VmError::NativeCallFailed(
                        "multiSearchAnyCaseInsensitive takes exactly 2 arguments".to_string(),
                    ));
                }

                // Coerce the haystack to a string (to align with TS/Python and ClickHouse behavior)
                let haystack_str = to_string(&vm.heap, &args[0], 0)?.to_lowercase();

                // The second argument must be an array of needles; otherwise, treat as no match (0)
                let needles = args[1].deref(&vm.heap)?;
                let needles_array = match needles {
                    HogLiteral::Array(arr) => arr,
                    _ => return Ok(HogLiteral::Number(0i64.into()).into()),
                };

                for needle_value in needles_array {
                    // Coerce each needle to a string, regardless of its underlying literal type
                    let needle_str = to_string(&vm.heap, needle_value, 0)?.to_lowercase();
                    if haystack_str.contains(&needle_str) {
                        // Return 1 (numeric) to match ClickHouse-style predicate semantics
                        return Ok(HogLiteral::Number(1i64.into()).into());
                    }
                }
                // No needles matched: return 0 (numeric)
                Ok(HogLiteral::Number(0i64.into()).into())
            }),
        ),
        (
            "randomFloat",
            native_func(|_vm, args| {
                assert_argc(&args, 0, "randomFloat")?;
                let value: f64 = rand::thread_rng().gen_range(0.0..1.0);
                Ok(HogLiteral::Number(Num::Float(value)).into())
            }),
        ),
        (
            "concat",
            native_func(|vm, args| {
                // Stringify each arg via the canonical print-string formatting; nulls become "".
                let mut out = String::new();
                for arg in &args {
                    if !matches!(arg.deref(&vm.heap)?, HogLiteral::Null) {
                        out.push_str(&print_hog_string_output(&vm.heap, arg)?);
                    }
                }
                Ok(HogLiteral::String(out).into())
            }),
        ),
        (
            "lower",
            native_func(|vm, args| {
                assert_argc(&args, 1, "lower")?;
                match args[0].deref(&vm.heap)? {
                    HogLiteral::Null => Ok(HogLiteral::Null.into()),
                    HogLiteral::String(s) => Ok(HogLiteral::String(s.to_lowercase()).into()),
                    other => Err(VmError::NativeCallFailed(format!(
                        "lower() expects a string, got {}",
                        other.type_name()
                    ))),
                }
            }),
        ),
        (
            "upper",
            native_func(|vm, args| {
                assert_argc(&args, 1, "upper")?;
                let s: &str = args[0].deref(&vm.heap)?.try_as()?;
                Ok(HogLiteral::String(s.to_uppercase()).into())
            }),
        ),
        (
            "reverse",
            native_func(|vm, args| {
                assert_argc(&args, 1, "reverse")?;
                match args[0].deref(&vm.heap)? {
                    HogLiteral::String(s) => {
                        Ok(HogLiteral::String(s.chars().rev().collect()).into())
                    }
                    HogLiteral::Array(arr) => {
                        let mut a = arr.clone();
                        a.reverse();
                        Ok(HogLiteral::Array(a).into())
                    }
                    other => Err(VmError::NativeCallFailed(format!(
                        "reverse() expects a string or array, got {}",
                        other.type_name()
                    ))),
                }
            }),
        ),
        ("trim", native_func(|vm, args| trim_impl(vm, args, TrimSide::Both))),
        ("trimLeft", native_func(|vm, args| trim_impl(vm, args, TrimSide::Left))),
        ("trimRight", native_func(|vm, args| trim_impl(vm, args, TrimSide::Right))),
        (
            "isNotNull",
            native_func(|vm, args| {
                assert_argc(&args, 1, "isNotNull")?;
                Ok(
                    HogLiteral::Boolean(!matches!(args[0].deref(&vm.heap)?, HogLiteral::Null))
                        .into(),
                )
            }),
        ),
        (
            "jsonParse",
            native_func(|vm, args| {
                assert_argc(&args, 1, "jsonParse")?;
                let s: &str = args[0].deref(&vm.heap)?.try_as()?;
                // Deserialize straight to a HogValue (not serde_json::Value, which sorts object keys
                // without the preserve_order feature) to keep document order.
                let parsed: HogJson = serde_json::from_str(s)
                    .map_err(|e| VmError::NativeCallFailed(format!("jsonParse: {e}")))?;
                Ok(parsed.0)
            }),
        ),
        (
            "jsonStringify",
            native_func(|vm, args| {
                // The optional 2nd "indent" arg (pretty-print) isn't used by the corpus; we emit the
                // compact-with-spaces form (Python json.dumps default) the single-arg callers expect.
                assert(
                    !args.is_empty(),
                    "jsonStringify requires at least one argument",
                )?;
                let s = json_stringify(&vm.heap, &args[0], &mut Vec::new(), 0)?;
                Ok(HogLiteral::String(s).into())
            }),
        ),
        (
            "isValidJSON",
            native_func(|vm, args| {
                assert_argc(&args, 1, "isValidJSON")?;
                let valid = match args[0].deref(&vm.heap)? {
                    HogLiteral::String(s) => serde_json::from_str::<JsonValue>(s).is_ok(),
                    _ => false,
                };
                Ok(HogLiteral::Boolean(valid).into())
            }),
        ),
        (
            "toInt",
            native_func(|vm, args| {
                assert_argc(&args, 1, "toInt")?;
                let res = match args[0].deref(&vm.heap)? {
                    HogLiteral::Number(n) => Some(if n.is_float() {
                        n.to_float() as i64
                    } else {
                        n.to_integer()
                    }),
                    HogLiteral::Boolean(b) => Some(*b as i64),
                    HogLiteral::String(s) => s.trim().parse::<i64>().ok(),
                    _ => None,
                };
                // ValueError -> null in the reference.
                Ok(res
                    .map(|i| HogLiteral::Number(Num::Integer(i)))
                    .unwrap_or(HogLiteral::Null)
                    .into())
            }),
        ),
        (
            "toFloat",
            native_func(|vm, args| {
                assert_argc(&args, 1, "toFloat")?;
                let res = match args[0].deref(&vm.heap)? {
                    HogLiteral::Number(n) => Some(n.to_float()),
                    HogLiteral::String(s) => s.trim().parse::<f64>().ok(),
                    _ => None,
                };
                Ok(res
                    .map(|f| HogLiteral::Number(Num::Float(f)))
                    .unwrap_or(HogLiteral::Null)
                    .into())
            }),
        ),
        (
            "ifNull",
            native_func(|vm, args| {
                assert_argc(&args, 2, "ifNull")?;
                if matches!(args[0].deref(&vm.heap)?, HogLiteral::Null) {
                    Ok(args[1].clone())
                } else {
                    Ok(args[0].clone())
                }
            }),
        ),
        (
            "coalesce",
            native_func(|vm, args| {
                for arg in &args {
                    if !matches!(arg.deref(&vm.heap)?, HogLiteral::Null) {
                        return Ok(arg.clone());
                    }
                }
                Ok(HogLiteral::Null.into())
            }),
        ),
        (
            "assumeNotNull",
            native_func(|vm, args| {
                assert_argc(&args, 1, "assumeNotNull")?;
                if matches!(args[0].deref(&vm.heap)?, HogLiteral::Null) {
                    Err(VmError::NativeCallFailed(
                        "Value is null in assumeNotNull".to_string(),
                    ))
                } else {
                    Ok(args[0].clone())
                }
            }),
        ),
        (
            "empty",
            native_func(|vm, args| {
                assert_argc(&args, 1, "empty")?;
                // Numbers and booleans are never "empty" (matching the reference); otherwise empty
                // means falsy: "" / [] / {} / null.
                let result = match args[0].deref(&vm.heap)? {
                    HogLiteral::Number(_) | HogLiteral::Boolean(_) => false,
                    HogLiteral::Null => true,
                    HogLiteral::String(s) => s.is_empty(),
                    HogLiteral::Array(a) => a.is_empty(),
                    HogLiteral::Object(o) => o.is_empty(),
                    _ => false,
                };
                Ok(HogLiteral::Boolean(result).into())
            }),
        ),
        (
            "keys",
            native_func(|vm, args| {
                assert_argc(&args, 1, "keys")?;
                match args[0].deref(&vm.heap)? {
                    HogLiteral::Object(o) => Ok(HogLiteral::Array(
                        o.keys().map(|k| HogLiteral::String(k.clone()).into()).collect(),
                    )
                    .into()),
                    // Arrays/tuples -> 0-based index list, matching the reference.
                    HogLiteral::Array(a) => Ok(HogLiteral::Array(
                        (0..a.len())
                            .map(|i| HogLiteral::Number(Num::Integer(i as i64)).into())
                            .collect(),
                    )
                    .into()),
                    _ => Ok(HogLiteral::Array(vec![]).into()),
                }
            }),
        ),
        (
            "round",
            native_func(|vm, args| {
                assert_argc(&args, 1, "round")?;
                let n: &Num = args[0].deref(&vm.heap)?.try_as()?;
                // Python round() is round-half-to-even and returns an int.
                Ok(HogLiteral::Number(Num::Integer(n.to_float().round_ties_even() as i64)).into())
            }),
        ),
        (
            "floor",
            native_func(|vm, args| {
                assert_argc(&args, 1, "floor")?;
                let n: &Num = args[0].deref(&vm.heap)?.try_as()?;
                Ok(HogLiteral::Number(Num::Integer(n.to_float().floor() as i64)).into())
            }),
        ),
        (
            "min2",
            native_func(|vm, args| {
                assert_argc(&args, 2, "min2")?;
                let less = {
                    let a: &Num = args[0].deref(&vm.heap)?.try_as()?;
                    let b: &Num = args[1].deref(&vm.heap)?.try_as()?;
                    a.compare(b) == std::cmp::Ordering::Less
                };
                Ok(if less { args[0].clone() } else { args[1].clone() })
            }),
        ),
        (
            "max2",
            native_func(|vm, args| {
                assert_argc(&args, 2, "max2")?;
                let greater = {
                    let a: &Num = args[0].deref(&vm.heap)?.try_as()?;
                    let b: &Num = args[1].deref(&vm.heap)?.try_as()?;
                    a.compare(b) == std::cmp::Ordering::Greater
                };
                Ok(if greater { args[0].clone() } else { args[1].clone() })
            }),
        ),
        (
            "range",
            native_func(|vm, args| {
                if args.is_empty() || args.len() > 2 {
                    return Err(VmError::NativeCallFailed(
                        "range supports 1 or 2 arguments".to_string(),
                    ));
                }
                let (start, end) = if args.len() == 1 {
                    (0, args[0].deref(&vm.heap)?.try_as::<Num>()?.to_integer())
                } else {
                    (
                        args[0].deref(&vm.heap)?.try_as::<Num>()?.to_integer(),
                        args[1].deref(&vm.heap)?.try_as::<Num>()?.to_integer(),
                    )
                };
                let arr = (start..end)
                    .map(|i| HogLiteral::Number(Num::Integer(i)).into())
                    .collect();
                Ok(HogLiteral::Array(arr).into())
            }),
        ),
        (
            "substring",
            native_func(|vm, args| {
                if args.len() < 2 || args.len() > 3 {
                    return Err(VmError::NativeCallFailed(
                        "substring takes 2 or 3 arguments".to_string(),
                    ));
                }
                let chars: Vec<char> = match args[0].deref(&vm.heap)? {
                    HogLiteral::String(s) => s.chars().collect(),
                    _ => return Ok(HogLiteral::String(String::new()).into()),
                };
                // start is 1-based.
                let start_idx = args[1].deref(&vm.heap)?.try_as::<Num>()?.to_integer() - 1;
                let length = if args.len() > 2 {
                    args[2].deref(&vm.heap)?.try_as::<Num>()?.to_integer()
                } else {
                    chars.len() as i64 - start_idx
                };
                if start_idx < 0 || length < 0 || start_idx >= chars.len() as i64 {
                    return Ok(HogLiteral::String(String::new()).into());
                }
                let s_u = start_idx as usize;
                let e_u = ((start_idx + length) as usize).min(chars.len());
                Ok(HogLiteral::String(chars[s_u..e_u].iter().collect()).into())
            }),
        ),
        (
            "replaceOne",
            native_func(|vm, args| {
                assert_argc(&args, 3, "replaceOne")?;
                let s: &str = args[0].deref(&vm.heap)?.try_as()?;
                let from: &str = args[1].deref(&vm.heap)?.try_as()?;
                let to: &str = args[2].deref(&vm.heap)?.try_as()?;
                Ok(HogLiteral::String(s.replacen(from, to, 1)).into())
            }),
        ),
        (
            "replaceAll",
            native_func(|vm, args| {
                assert_argc(&args, 3, "replaceAll")?;
                let s: &str = args[0].deref(&vm.heap)?.try_as()?;
                let from: &str = args[1].deref(&vm.heap)?.try_as()?;
                let to: &str = args[2].deref(&vm.heap)?.try_as()?;
                Ok(HogLiteral::String(s.replace(from, to)).into())
            }),
        ),
        (
            "splitByString",
            native_func(|vm, args| {
                if args.len() < 2 || args.len() > 3 {
                    return Err(VmError::NativeCallFailed(
                        "splitByString takes 2 or 3 arguments".to_string(),
                    ));
                }
                // splitByString(separator, string[, max])
                let sep: &str = args[0].deref(&vm.heap)?.try_as()?;
                let s: &str = args[1].deref(&vm.heap)?.try_as()?;
                let parts: Vec<HogValue> = if args.len() > 2 {
                    let max = args[2].deref(&vm.heap)?.try_as::<Num>()?.to_integer();
                    let max = if max < 0 { 0 } else { max as usize };
                    s.split(sep)
                        .take(max)
                        .map(|p| HogLiteral::String(p.to_string()).into())
                        .collect()
                } else {
                    s.split(sep)
                        .map(|p| HogLiteral::String(p.to_string()).into())
                        .collect()
                };
                Ok(HogLiteral::Array(parts).into())
            }),
        ),
        (
            "startsWith",
            native_func(|vm, args| {
                assert_argc(&args, 2, "startsWith")?;
                let result = matches!(
                    (args[0].deref(&vm.heap)?, args[1].deref(&vm.heap)?),
                    (HogLiteral::String(s), HogLiteral::String(p)) if s.starts_with(p.as_str())
                );
                Ok(HogLiteral::Boolean(result).into())
            }),
        ),
        (
            "position",
            native_func(|vm, args| {
                assert_argc(&args, 2, "position")?;
                Ok(HogLiteral::Number(Num::Integer(position_impl(vm, &args[0], &args[1], false)?))
                    .into())
            }),
        ),
        (
            "positionCaseInsensitive",
            native_func(|vm, args| {
                assert_argc(&args, 2, "positionCaseInsensitive")?;
                Ok(HogLiteral::Number(Num::Integer(position_impl(vm, &args[0], &args[1], true)?))
                    .into())
            }),
        ),
    ]
    .into_iter()
    .map(|(name, func)| (name.to_string(), func))
    .collect()
}

pub fn hog_stl() -> Module {
    let funcs = json!({
      "arrayCount": [2, [33, 0, 36, 1, 36, 3, 2, "values", 1, 33, 1, 36, 4, 2, "length", 1, 31, 36, 6, 36, 5, 16, 40, 31, 36, 4, 36, 5, 45, 37, 7, 36, 7, 36, 0, 54, 1, 40, 7, 33, 1, 36, 2, 6, 37, 2, 36, 5, 33, 1, 6, 37, 5, 39, -38, 35, 35, 35, 35, 35, 36, 2, 38, 35]],
      "arrayExists": [2, [36, 1, 36, 2, 2, "values", 1, 33, 1, 36, 3, 2, "length", 1, 31, 36, 5, 36, 4, 16, 40, 26, 36, 3, 36, 4, 45, 37, 6, 36, 6, 36, 0, 54, 1, 40, 2, 29, 38, 36, 4, 33, 1, 6, 37, 4, 39, -33, 35, 35, 35, 35, 35, 30, 38]],
      "arrayFilter": [2, [43, 0, 36, 1, 36, 3, 2, "values", 1, 33, 1, 36, 4, 2, "length", 1, 31, 36, 6, 36, 5, 16, 40, 33, 36, 4, 36, 5, 45, 37, 7, 36, 7, 36, 0, 54, 1, 40, 9, 36, 2, 36, 7, 2, "arrayPushBack", 2, 37, 2, 36, 5, 33, 1, 6, 37, 5, 39, -40, 35, 35, 35, 35, 35, 36, 2, 38, 35]],
      "arrayMap": [2, [43, 0, 36, 1, 36, 3, 2, "values", 1, 33, 1, 36, 4, 2, "length", 1, 31, 36, 6, 36, 5, 16, 40, 29, 36, 4, 36, 5, 45, 37, 7, 36, 2, 36, 7, 36, 0, 54, 1, 2, "arrayPushBack", 2, 37, 2, 36, 5, 33, 1, 6, 37, 5, 39, -36, 35, 35, 35, 35, 35, 36, 2, 38, 35]],
      "arrayReduce": [3, [36, 2, 36, 1, 36, 4, 2, "values", 1, 33, 1, 36, 5, 2, "length", 1, 31, 36, 7, 36, 6, 16, 40, 26, 36, 5, 36, 6, 45, 37, 8, 36, 3, 36, 8, 36, 0, 54, 2, 37, 3, 36, 6, 33, 1, 6, 37, 6, 39, -33, 35, 35, 35, 35, 35, 36, 3, 38, 35]],
      "sortableSemver": [1, [31, 36, 0, 11, 40, 3, 43, 0, 38, 36, 0, 32, "(\\d+(\\.\\d+)+)", 2, "extractRegex", 2, 36, 1, 2, "empty", 1, 40, 3, 43, 0, 38, 32, ".", 36, 1, 2, "splitByString", 2, 52, "lambda", 1, 0, 11, 36, 0, 2, "toInt", 1, 47, 3, 35, 33, 0, 38, 53, 0, 36, 2, 2, "arrayMap", 2, 38, 35, 35]],
    });

    let funcs: HashMap<String, (usize, Vec<JsonValue>)> =
        serde_json::from_value(funcs).expect("All stl functions are valid");
    let mut res = Module::new();
    for (name, (arg_count, bytecode)) in funcs {
        let func = ExportedFunction::new(arg_count, bytecode);
        res.add_function(name, func);
    }
    res
}

// TODO - this is slow, because rather than using a string buffer, we're allocating a new string each time
// we recurse
fn to_string(heap: &VmHeap, val: &HogValue, depth: usize) -> Result<String, VmError> {
    if depth > TO_STRING_RECURSION_LIMIT {
        return Err(VmError::NativeCallFailed(
            "Maximum toString recursion depth exceeded".to_string(),
        ));
    }

    let val = val.deref(heap)?;
    match val {
        HogLiteral::Number(num) => {
            let val = if num.is_float() {
                num.to_float().to_string()
            } else {
                num.to_integer().to_string()
            };
            Ok(val)
        }
        HogLiteral::Boolean(bool) => Ok(bool.to_string()),
        HogLiteral::String(string) => Ok(string.clone()),
        HogLiteral::Array(hog_values) => Ok(format!(
            "[{}]",
            hog_values
                .iter()
                .map(|v| to_string(heap, v, depth + 1))
                .collect::<Result<Vec<String>, VmError>>()?
                .join(", ")
        )),
        HogLiteral::Object(hash_map) => {
            let mut entries = Vec::new();
            for (key, value) in hash_map {
                entries.push(format!("{}: {}", key, to_string(heap, value, depth + 1)?));
            }
            Ok(format!("{{{}}}", entries.join(", ")))
        }
        HogLiteral::Callable(callable) => Ok(callable.to_string()),
        HogLiteral::Closure(closure) => Ok(closure.to_string()),
        HogLiteral::Null => Ok("null".to_string()),
    }
}

/// `toDateTime(input[, zone])` → a Hog DateTime object `{ __hogDateTime__: true, dt, zone }`.
///
/// To match ClickHouse (the parity oracle), this VM orders Hog temporals by `dt` seconds
/// ([`crate::values::compare_values`]) — the reference Python/TS HogVMs cannot order them, so their
/// `is_date_before`/`is_date_after` always return `false`. Naive strings parse as UTC (or `zone` for
/// the 2-arg form), not the process-local timezone; an explicit offset/`Z` is honored as written.
fn to_datetime(vm: &HogVM, args: Vec<HogValue>) -> Result<HogValue, VmError> {
    if args.is_empty() || args.len() > 2 {
        return Err(VmError::NativeCallFailed(
            "toDateTime takes 1 or 2 arguments".to_string(),
        ));
    }
    let zone = match args.get(1) {
        Some(arg) => Some(arg.deref(&vm.heap)?.try_as::<str>()?.to_string()),
        None => None,
    };
    let zone = zone.as_deref();
    let dt_seconds = match args[0].deref(&vm.heap)? {
        HogLiteral::Number(n) => n.to_float(),
        HogLiteral::String(s) => parse_datetime_to_seconds(s, zone)?,
        other => {
            return Err(VmError::NativeCallFailed(format!(
                "toDateTime expects a number or string, got {}",
                other.type_name()
            )))
        }
    };
    construct_free_standing(
        json!({ "__hogDateTime__": true, "dt": dt_seconds, "zone": zone.unwrap_or("UTC") }),
        0,
    )
}

/// `toDate(input)` → a Hog Date object `{ __hogDate__: true, year, month, day }` in UTC.
fn to_date(vm: &HogVM, args: Vec<HogValue>) -> Result<HogValue, VmError> {
    assert_argc(&args, 1, "toDate")?;
    let seconds = match args[0].deref(&vm.heap)? {
        HogLiteral::Number(n) => n.to_float(),
        HogLiteral::String(s) => parse_datetime_to_seconds(s, None)?,
        other => {
            return Err(VmError::NativeCallFailed(format!(
                "toDate expects a number or string, got {}",
                other.type_name()
            )))
        }
    };
    let dt = DateTime::from_timestamp(seconds as i64, 0).ok_or_else(|| {
        VmError::NativeCallFailed(format!("toDate: timestamp {seconds} out of range"))
    })?;
    construct_free_standing(
        json!({ "__hogDate__": true, "year": dt.year(), "month": dt.month(), "day": dt.day() }),
        0,
    )
}

const NAIVE_DATETIME_FORMATS: [&str; 2] = ["%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%dT%H:%M:%S%.f"];

fn parse_datetime_to_seconds(input: &str, zone: Option<&str>) -> Result<f64, VmError> {
    let input = input.trim();
    // An explicit offset/`Z` pins the absolute instant regardless of `zone`.
    if let Ok(dt) = DateTime::parse_from_rfc3339(input) {
        return Ok(datetime_to_seconds(dt));
    }
    for fmt in NAIVE_DATETIME_FORMATS {
        if let Ok(naive) = NaiveDateTime::parse_from_str(input, fmt) {
            return naive_to_seconds(naive, zone);
        }
    }
    if let Some(naive) = NaiveDate::parse_from_str(input, "%Y-%m-%d")
        .ok()
        .and_then(|date| date.and_hms_opt(0, 0, 0))
    {
        return naive_to_seconds(naive, zone);
    }
    // A bare numeric string is unix seconds (e.g. an upstream `toString(<number>)`).
    if let Ok(seconds) = input.parse::<f64>() {
        return Ok(seconds);
    }
    Err(VmError::NativeCallFailed(format!(
        "toDateTime could not parse {input:?}"
    )))
}

fn naive_to_seconds(naive: NaiveDateTime, zone: Option<&str>) -> Result<f64, VmError> {
    let Some(zone) = zone else {
        return Ok(datetime_to_seconds(naive.and_utc()));
    };
    let tz: chrono_tz::Tz = zone
        .parse()
        .map_err(|_| VmError::NativeCallFailed(format!("toDateTime: unknown timezone {zone:?}")))?;
    match tz.from_local_datetime(&naive) {
        // DST fold: ClickHouse resolves to a single instant; take the earlier one.
        LocalResult::Single(dt) | LocalResult::Ambiguous(dt, _) => Ok(datetime_to_seconds(dt)),
        LocalResult::None => Err(VmError::NativeCallFailed(format!(
            "toDateTime: {naive} does not exist in {zone}"
        ))),
    }
}

/// `f64` epoch seconds with sub-second precision, matching Python's `datetime.timestamp()`.
fn datetime_to_seconds<Tz: TimeZone>(dt: DateTime<Tz>) -> f64 {
    dt.timestamp() as f64 + f64::from(dt.timestamp_subsec_nanos()) / 1_000_000_000.0
}

// Extract every element as a Num and return them sorted ascending. Single allocation + early error,
// rather than partitioning into (oks, errs) Vecs and unwrapping — the old path allocated several
// intermediate Vecs per call, which showed up under profiling for sort-heavy workloads.
fn collect_sorted_nums(heap: &VmHeap, arr: &[HogValue], name: &str) -> Result<Vec<Num>, VmError> {
    let mut nums = Vec::with_capacity(arr.len());
    for v in arr {
        let n = v.deref(heap)?.try_as::<Num>().map_err(|_| {
            VmError::NativeCallFailed(format!("{name}() only supports arrays of numbers"))
        })?;
        nums.push(n.clone());
    }
    nums.sort_unstable_by(|a, b| a.compare(b));
    Ok(nums)
}

// Order-preserving JSON -> HogValue deserialization (serde_json's Deserializer yields map entries
// in document order; collecting into IndexMap keeps it, unlike serde_json::Value's sorted BTreeMap).
struct HogJson(HogValue);

impl<'de> serde::Deserialize<'de> for HogJson {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer
            .deserialize_any(HogJsonVisitor)
            .map(|lit| HogJson(lit.into()))
    }
}

struct HogJsonVisitor;

impl<'de> Visitor<'de> for HogJsonVisitor {
    type Value = HogLiteral;

    fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        f.write_str("a JSON value")
    }

    fn visit_bool<E>(self, v: bool) -> Result<HogLiteral, E> {
        Ok(HogLiteral::Boolean(v))
    }
    fn visit_i64<E>(self, v: i64) -> Result<HogLiteral, E> {
        Ok(HogLiteral::Number(Num::Integer(v)))
    }
    fn visit_u64<E>(self, v: u64) -> Result<HogLiteral, E> {
        Ok(HogLiteral::Number(Num::Integer(v as i64)))
    }
    fn visit_f64<E>(self, v: f64) -> Result<HogLiteral, E> {
        Ok(HogLiteral::Number(Num::Float(v)))
    }
    fn visit_str<E>(self, v: &str) -> Result<HogLiteral, E> {
        Ok(HogLiteral::String(v.to_string()))
    }
    fn visit_string<E>(self, v: String) -> Result<HogLiteral, E> {
        Ok(HogLiteral::String(v))
    }
    fn visit_none<E>(self) -> Result<HogLiteral, E> {
        Ok(HogLiteral::Null)
    }
    fn visit_unit<E>(self) -> Result<HogLiteral, E> {
        Ok(HogLiteral::Null)
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<HogLiteral, A::Error> {
        let mut vals = Vec::new();
        while let Some(HogJson(v)) = seq.next_element()? {
            vals.push(v);
        }
        Ok(HogLiteral::Array(vals))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<HogLiteral, A::Error> {
        let mut obj = IndexMap::new();
        while let Some((k, HogJson(v))) = map.next_entry::<String, HogJson>()? {
            obj.insert(k, v);
        }
        Ok(HogLiteral::Object(obj))
    }
}

// Serialize a HogValue to a JSON string matching Python's `json.dumps` default: `, ` / `: `
// separators (not serde's compact form), object keys in insertion order (IndexMap), and
// self-referential containers rendered as `null` (cycle detection via `marked`).
fn json_stringify(
    heap: &VmHeap,
    value: &HogValue,
    marked: &mut Vec<HeapReference>,
    depth: usize,
) -> Result<String, VmError> {
    if depth > MAX_JSON_SERDE_DEPTH {
        return Ok("null".to_string());
    }
    let lit = value.deref(heap)?;
    let container_ptr = match value {
        HogValue::Ref(ptr) if matches!(lit, HogLiteral::Array(_) | HogLiteral::Object(_)) => {
            Some(*ptr)
        }
        _ => None,
    };
    if let Some(ptr) = container_ptr {
        if marked.contains(&ptr) {
            return Ok("null".to_string());
        }
        marked.push(ptr);
    }

    let escape = |s: &str| -> Result<String, VmError> {
        serde_json::to_string(s).map_err(|e| VmError::NativeCallFailed(e.to_string()))
    };
    let result = (|| match lit {
        HogLiteral::Null => Ok("null".to_string()),
        HogLiteral::Boolean(b) => Ok(if *b { "true" } else { "false" }.to_string()),
        HogLiteral::Number(n) => Ok(if n.is_float() {
            // Debug formatting keeps the decimal point (2.0 -> "2.0"), matching Python's repr.
            format!("{:?}", n.to_float())
        } else {
            n.to_integer().to_string()
        }),
        HogLiteral::String(s) => escape(s),
        HogLiteral::Array(arr) => {
            let mut parts = Vec::with_capacity(arr.len());
            for v in arr {
                parts.push(json_stringify(heap, v, marked, depth + 1)?);
            }
            Ok(format!("[{}]", parts.join(", ")))
        }
        HogLiteral::Object(map) => {
            let mut parts = Vec::with_capacity(map.len());
            for (k, v) in map {
                parts.push(format!(
                    "{}: {}",
                    escape(k)?,
                    json_stringify(heap, v, marked, depth + 1)?
                ));
            }
            Ok(format!("{{{}}}", parts.join(", ")))
        }
        // Callables/closures serialize as the quoted `fn<name(argCount)>` string, like the reference.
        HogLiteral::Callable(_) | HogLiteral::Closure(_) => escape(&print_hog_string_output(heap, value)?),
    })();

    if container_ptr.is_some() {
        marked.pop();
    }
    result
}

// position(haystack, needle): 1-based char index of str(needle) in haystack, or 0 if absent (or
// haystack isn't a string). The case-insensitive variant lowercases both first.
fn position_impl(
    vm: &HogVM,
    haystack: &HogValue,
    needle: &HogValue,
    ci: bool,
) -> Result<i64, VmError> {
    let s = match haystack.deref(&vm.heap)? {
        HogLiteral::String(s) => s.clone(),
        _ => return Ok(0),
    };
    let n = to_string(&vm.heap, needle, 0)?; // str(needle)
    let (s, n) = if ci {
        (s.to_lowercase(), n.to_lowercase())
    } else {
        (s, n)
    };
    match s.find(&n) {
        Some(byte_idx) => Ok(s[..byte_idx].chars().count() as i64 + 1),
        None => Ok(0),
    }
}

enum TrimSide {
    Both,
    Left,
    Right,
}

// trim/trimLeft/trimRight: 1 arg strips whitespace; 2nd arg strips a single char (a non-string
// 2nd arg defaults to space, a multi-char string yields "") — matching the reference.
fn trim_impl(vm: &HogVM, args: Vec<HogValue>, side: TrimSide) -> Result<HogValue, VmError> {
    if args.is_empty() || args.len() > 2 {
        return Err(VmError::NativeCallFailed(
            "trim takes 1 or 2 arguments".to_string(),
        ));
    }
    let s: &str = args[0].deref(&vm.heap)?.try_as()?;
    let result = if args.len() == 2 {
        let chars: Vec<char> = match args[1].deref(&vm.heap)? {
            HogLiteral::String(c) => c.chars().collect(),
            _ => vec![' '],
        };
        if chars.len() > 1 {
            String::new()
        } else {
            let pat = |x: char| chars.contains(&x);
            match side {
                TrimSide::Both => s.trim_matches(pat).to_string(),
                TrimSide::Left => s.trim_start_matches(pat).to_string(),
                TrimSide::Right => s.trim_end_matches(pat).to_string(),
            }
        }
    } else {
        match side {
            TrimSide::Both => s.trim().to_string(),
            TrimSide::Left => s.trim_start().to_string(),
            TrimSide::Right => s.trim_end().to_string(),
        }
    };
    Ok(HogLiteral::String(result).into())
}

fn assert(test: bool, msg: impl AsRef<str>) -> Result<(), VmError> {
    if test {
        Ok(())
    } else {
        Err(VmError::NativeCallFailed(format!(
            "Assert failed: {}",
            msg.as_ref()
        )))
    }
}

fn assert_argc(args: &[HogValue], count: usize, name: impl AsRef<str>) -> Result<(), VmError> {
    assert(
        args.len() == count,
        format!("{} takes exactly {} arguments", name.as_ref(), count),
    )
}

fn err_to_null(
    func: impl Fn(&HogVM, Vec<HogValue>) -> Result<HogValue, VmError>,
) -> impl Fn(&HogVM, Vec<HogValue>) -> Result<HogValue, VmError> {
    move |vm, args| func(vm, args).or(Ok(HogLiteral::Null.into()))
}

/// Helper to construct a HogVM native function from a closure.
pub fn native_func<F>(func: F) -> NativeFunction
where
    F: Fn(&HogVM, Vec<HogValue>) -> Result<HogValue, VmError> + 'static,
{
    Box::new(func)
}
