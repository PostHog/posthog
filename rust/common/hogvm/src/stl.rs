use core::str;
use std::collections::HashMap;
use std::sync::Arc;

use base64::Engine as _;
use chrono::{DateTime, Datelike, LocalResult, NaiveDate, NaiveDateTime, TimeZone, Timelike};
use hmac::{Hmac, Mac};
use indexmap::IndexMap;
use md5::Md5;
use once_cell::sync::Lazy;
use rand::Rng;
use serde::de::{MapAccess, SeqAccess, Visitor};
use serde_json::{json, Value as JsonValue};
use sha2::{Digest, Sha256};

use crate::{
    construct_free_standing,
    error::VmError,
    memory::{HeapReference, VmHeap},
    print_hog_string_output,
    program::Module,
    util::{get_json_nested, regex_extract, regex_match},
    values::{compare_values, HogLiteral, HogValue, Num, NumOp},
    vm::{HogVM, MAX_JSON_SERDE_DEPTH},
    ExportedFunction,
};

// A "native function" is a function that can be called from within the VM. It takes a list
// of arguments, and returns either a value, or null. It's pure (cannot modify the VM state).
// `Arc` (not `Box`) so the static registry below can be cloned cheaply per execution context.
pub type NativeFunction =
    Arc<dyn Fn(&HogVM, Vec<HogValue>) -> Result<HogValue, VmError> + Send + Sync>;

// The native and hog STL registries are process-constant: build them once and hand out cheap clones
// instead of reconstructing (and, for the hog STL, re-parsing its bytecode) on every context.
static STL_NATIVE_FNS: Lazy<HashMap<String, NativeFunction>> =
    Lazy::new(|| stl().into_iter().collect());
static HOG_STL_MODULES: Lazy<HashMap<String, Module>> =
    Lazy::new(|| HashMap::from([("stl".to_string(), hog_stl())]));

pub fn stl_map() -> HashMap<String, NativeFunction> {
    STL_NATIVE_FNS.clone()
}

pub fn hog_stl_map() -> HashMap<String, Module> {
    HOG_STL_MODULES.clone()
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
                let t = match arg {
                    // The reference distinguishes integer/float, not a single "number".
                    HogLiteral::Number(n) => {
                        if n.is_float() {
                            "float"
                        } else {
                            "integer"
                        }
                    }
                    HogLiteral::Boolean(_) => "boolean",
                    HogLiteral::String(_) => "string",
                    HogLiteral::Array(_) => "array",
                    HogLiteral::Tuple(_) => "tuple",
                    // Datetimes, dates, and errors are duck-typed objects distinguished by markers.
                    HogLiteral::Object(obj) => {
                        if obj_marker(&vm.heap, obj, "__hogDateTime__")? {
                            "datetime"
                        } else if obj_marker(&vm.heap, obj, "__hogDate__")? {
                            "date"
                        } else if obj_marker(&vm.heap, obj, "__hogError__")? {
                            "error"
                        } else {
                            "object"
                        }
                    }
                    HogLiteral::Callable(_) | HogLiteral::Closure(_) => "function",
                    HogLiteral::Null => "null",
                };
                Ok(HogLiteral::String(t.to_string()).into())
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
                    // Arrays and tuples both yield a plain array of their elements (reference: [...obj]).
                    HogLiteral::Array(a) | HogLiteral::Tuple(a) => {
                        Ok(HogLiteral::Array(a.clone()).into())
                    }
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
            "tuple",
            // `tuple(a, b, c)` constructs a tuple from its arguments (reference: args.slice() tagged
            // __isHogTuple). Any arity is allowed, including zero.
            native_func(|_vm, args| Ok(HogLiteral::Tuple(args).into())),
        ),
        (
            "length",
            native_func(|vm, args| {
                assert_argc(&args, 1, "length")?;
                let arg = args[0].deref(&vm.heap)?;
                match arg {
                    HogLiteral::Array(arr) | HogLiteral::Tuple(arr) => {
                        Ok(HogLiteral::Number(arr.len().into()).into())
                    }
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
                // Unlike the `in` opcode, the reference `has` STL is array-only: a non-array
                // haystack (string, object, null, …) is never a member, yielding false.
                assert_argc(&args, 2, "has")?;
                let needle = &args[1];
                match args[0].deref(&vm.heap)? {
                    HogLiteral::Array(vals) => {
                        for val in vals.iter() {
                            if *needle.equals(val, &vm.heap)?.try_as()? {
                                return Ok(HogLiteral::Boolean(true).into());
                            }
                        }
                        Ok(HogLiteral::Boolean(false).into())
                    }
                    _ => Ok(HogLiteral::Boolean(false).into()),
                }
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
                        // The reference returns 0 (arr.indexOf(elem) + 1) when not found.
                        Ok(HogLiteral::Number(Num::Integer(0)).into())
                    }
                    // Non-array arguments yield 0, matching the reference.
                    _ => Ok(HogLiteral::Number(Num::Integer(0)).into()),
                }
            }),
        ),
        (
            "notEmpty",
            native_func(|vm, args| {
                assert_argc(&args, 1, "notEmpty")?;
                // The reference defines notEmpty as the exact negation of empty.
                Ok(HogLiteral::Boolean(!is_hog_empty(args[0].deref(&vm.heap)?)).into())
            }),
        ),
        (
            "match",
            native_func(|vm, args| {
                assert_argc(&args, 2, "match")?;
                let value = args[0].deref(&vm.heap)?;
                let regex = args[1].deref(&vm.heap)?;
                // The reference returns false when either arg is falsy (null/empty) rather than matching.
                if !value.truthy() || !regex.truthy() {
                    return Ok(HogLiteral::Boolean(false).into());
                }
                Ok(HogLiteral::Boolean(regex_match(value.try_as::<str>()?, regex.try_as::<str>()?, true)?).into())
            }),
        ),
        (
            "like",
            native_func(|vm, args| like_impl(vm, &args, "like", false, false)),
        ),
        (
            "ilike",
            native_func(|vm, args| like_impl(vm, &args, "ilike", true, false)),
        ),
        (
            "notLike",
            native_func(|vm, args| like_impl(vm, &args, "notLike", false, true)),
        ),
        (
            "notILike",
            native_func(|vm, args| like_impl(vm, &args, "notILike", true, true)),
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
                // `res` borrows into the local `json`; clone the extracted subtree for the owned
                // value `construct_free_standing` needs.
                construct_free_standing(res.clone(), 0)
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
                    // Datetimes floor to whole seconds; dates to whole days since the epoch.
                    HogLiteral::Object(obj) if obj_marker(&vm.heap, obj, "__hogDateTime__")? => {
                        Some(obj_number(&vm.heap, obj, "dt")?.unwrap_or(0.0).floor() as i64)
                    }
                    HogLiteral::Object(obj) if obj_marker(&vm.heap, obj, "__hogDate__")? => {
                        Some(hog_date_epoch_days(&vm.heap, obj)?)
                    }
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
                    HogLiteral::Object(obj) if obj_marker(&vm.heap, obj, "__hogDateTime__")? => {
                        Some(obj_number(&vm.heap, obj, "dt")?.unwrap_or(0.0))
                    }
                    HogLiteral::Object(obj) if obj_marker(&vm.heap, obj, "__hogDate__")? => {
                        Some(hog_date_epoch_days(&vm.heap, obj)? as f64)
                    }
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
                Ok(HogLiteral::Boolean(is_hog_empty(args[0].deref(&vm.heap)?)).into())
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
                    HogLiteral::Array(a) | HogLiteral::Tuple(a) => Ok(HogLiteral::Array(
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
        (
            "JSONHas",
            native_func(|vm, args| {
                assert(!args.is_empty(), "JSONHas requires at least one argument")?;
                Ok(HogLiteral::Boolean(json_path_value(vm, &args)?.is_some()).into())
            }),
        ),
        (
            "JSONLength",
            native_func(|vm, args| {
                assert(!args.is_empty(), "JSONLength requires at least one argument")?;
                let len = match json_path_value(vm, &args)? {
                    Some(JsonValue::Array(a)) => a.len() as i64,
                    Some(JsonValue::Object(o)) => o.len() as i64,
                    _ => 0,
                };
                Ok(HogLiteral::Number(Num::Integer(len)).into())
            }),
        ),
        (
            "JSONExtractString",
            native_func(|vm, args| {
                assert(!args.is_empty(), "JSONExtractString requires at least one argument")?;
                let res = match json_path_value(vm, &args)? {
                    None | Some(JsonValue::Null) => HogLiteral::Null,
                    Some(JsonValue::String(s)) => HogLiteral::String(s),
                    Some(JsonValue::Bool(b)) => {
                        HogLiteral::String(if b { "True" } else { "False" }.to_string())
                    }
                    Some(JsonValue::Number(n)) => HogLiteral::String(n.to_string()),
                    Some(other) => HogLiteral::String(other.to_string()),
                };
                Ok(res.into())
            }),
        ),
        (
            "JSONExtractInt",
            native_func(|vm, args| {
                assert(!args.is_empty(), "JSONExtractInt requires at least one argument")?;
                let res = match json_path_value(vm, &args)? {
                    Some(JsonValue::Number(n)) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
                    Some(JsonValue::String(s)) => s.trim().parse::<i64>().ok(),
                    _ => None,
                };
                Ok(res
                    .map(|i| HogLiteral::Number(Num::Integer(i)))
                    .unwrap_or(HogLiteral::Null)
                    .into())
            }),
        ),
        (
            "JSONExtractFloat",
            native_func(|vm, args| {
                assert(!args.is_empty(), "JSONExtractFloat requires at least one argument")?;
                let res = match json_path_value(vm, &args)? {
                    Some(JsonValue::Number(n)) => n.as_f64(),
                    Some(JsonValue::String(s)) => s.trim().parse::<f64>().ok(),
                    _ => None,
                };
                Ok(res
                    .map(|f| HogLiteral::Number(Num::Float(f)))
                    .unwrap_or(HogLiteral::Null)
                    .into())
            }),
        ),
        (
            "JSONExtractBool",
            native_func(|vm, args| {
                assert(!args.is_empty(), "JSONExtractBool requires at least one argument")?;
                let b = matches!(json_path_value(vm, &args)?, Some(JsonValue::Bool(true)));
                Ok(HogLiteral::Boolean(b).into())
            }),
        ),
        (
            "JSONExtractArrayRaw",
            native_func(|vm, args| {
                assert(!args.is_empty(), "JSONExtractArrayRaw requires at least one argument")?;
                match json_path_value(vm, &args)? {
                    Some(arr @ JsonValue::Array(_)) => construct_free_standing(arr, 0),
                    _ => Ok(HogLiteral::Null.into()),
                }
            }),
        ),
        (
            "fromUnixTimestamp",
            native_func(|vm, args| {
                assert_argc(&args, 1, "fromUnixTimestamp")?;
                let ts = args[0].deref(&vm.heap)?.try_as::<Num>()?.to_float();
                make_hog_datetime(ts, "UTC")
            }),
        ),
        (
            "fromUnixTimestampMilli",
            native_func(|vm, args| {
                assert_argc(&args, 1, "fromUnixTimestampMilli")?;
                let ms = args[0].deref(&vm.heap)?.try_as::<Num>()?.to_float();
                make_hog_datetime(ms / 1000.0, "UTC")
            }),
        ),
        (
            "toUnixTimestamp",
            native_func(|vm, args| {
                assert(!args.is_empty(), "toUnixTimestamp requires at least one argument")?;
                let secs = match unix_timestamp_seconds(vm, &args, "toUnixTimestamp")? {
                    Some(secs) => secs,
                    None => return Ok(HogLiteral::Null.into()),
                };
                Ok(HogLiteral::Number(Num::Float(secs)).into())
            }),
        ),
        (
            "toUnixTimestampMilli",
            native_func(|vm, args| {
                assert(!args.is_empty(), "toUnixTimestampMilli requires at least one argument")?;
                let secs = match unix_timestamp_seconds(vm, &args, "toUnixTimestampMilli")? {
                    Some(secs) => secs,
                    None => return Ok(HogLiteral::Null.into()),
                };
                Ok(HogLiteral::Number(Num::Integer((secs * 1000.0) as i64)).into())
            }),
        ),
        (
            "toTimeZone",
            native_func(|vm, args| {
                assert_argc(&args, 2, "toTimeZone")?;
                let secs = temporal_seconds(vm, &args[0], "toTimeZone")?;
                let zone: String = args[1].deref(&vm.heap)?.try_as::<str>()?.to_string();
                make_hog_datetime(secs, &zone)
            }),
        ),
        (
            "toYear",
            native_func(|vm, args| {
                assert_argc(&args, 1, "toYear")?;
                Ok(HogLiteral::Number(Num::Integer(extract_utc_field(vm, &args[0], "year", "toYear")?))
                    .into())
            }),
        ),
        (
            "toMonth",
            native_func(|vm, args| {
                assert_argc(&args, 1, "toMonth")?;
                Ok(
                    HogLiteral::Number(Num::Integer(extract_utc_field(vm, &args[0], "month", "toMonth")?))
                        .into(),
                )
            }),
        ),
        (
            "toYYYYMM",
            native_func(|vm, args| {
                assert_argc(&args, 1, "toYYYYMM")?;
                let y = extract_utc_field(vm, &args[0], "year", "toYYYYMM")?;
                let m = extract_utc_field(vm, &args[0], "month", "toYYYYMM")?;
                Ok(HogLiteral::Number(Num::Integer(y * 100 + m)).into())
            }),
        ),
        (
            "dateTrunc",
            native_func(|vm, args| {
                assert_argc(&args, 2, "dateTrunc")?;
                let unit: String = args[0].deref(&vm.heap)?.try_as::<str>()?.to_string();
                date_trunc_impl(vm, &unit, &args[1])
            }),
        ),
        (
            "toStartOfDay",
            native_func(|vm, args| {
                assert_argc(&args, 1, "toStartOfDay")?;
                date_trunc_impl(vm, "day", &args[0])
            }),
        ),
        (
            "toStartOfHour",
            native_func(|vm, args| {
                assert_argc(&args, 1, "toStartOfHour")?;
                date_trunc_impl(vm, "hour", &args[0])
            }),
        ),
        (
            "toStartOfMonth",
            native_func(|vm, args| {
                assert_argc(&args, 1, "toStartOfMonth")?;
                date_trunc_impl(vm, "month", &args[0])
            }),
        ),
        (
            "toStartOfWeek",
            native_func(|vm, args| {
                assert_argc(&args, 1, "toStartOfWeek")?;
                let (secs, zone) = hog_datetime_parts(vm, &args[0], "toStartOfWeek")?;
                let utc = DateTime::from_timestamp(secs.floor() as i64, 0).ok_or_else(|| {
                    VmError::NativeCallFailed("toStartOfWeek: timestamp out of range".to_string())
                })?;
                let n = utc.naive_utc();
                let weekday = n.weekday().number_from_monday() as i64; // Mon=1..Sun=7
                let start = (n.date() - chrono::Duration::days(weekday - 1))
                    .and_hms_opt(0, 0, 0)
                    .ok_or_else(|| VmError::NativeCallFailed("toStartOfWeek: bad date".to_string()))?;
                make_hog_datetime(zone_local_timestamp(&zone, &start)?, &zone)
            }),
        ),
        (
            "toIntervalDay",
            native_func(|vm, args| make_hog_interval(vm, &args, "day")),
        ),
        (
            "toIntervalHour",
            native_func(|vm, args| make_hog_interval(vm, &args, "hour")),
        ),
        (
            "toIntervalMinute",
            native_func(|vm, args| make_hog_interval(vm, &args, "minute")),
        ),
        (
            "toIntervalMonth",
            native_func(|vm, args| make_hog_interval(vm, &args, "month")),
        ),
        (
            "dateAdd",
            native_func(|vm, args| {
                assert_argc(&args, 3, "dateAdd")?;
                let unit: String = args[0].deref(&vm.heap)?.try_as::<str>()?.to_string();
                let amount = args[1].deref(&vm.heap)?.try_as::<Num>()?.to_integer();
                date_add_impl(vm, &unit, amount, &args[2])
            }),
        ),
        (
            "addDays",
            native_func(|vm, args| {
                assert_argc(&args, 2, "addDays")?;
                let n = args[1].deref(&vm.heap)?.try_as::<Num>()?.to_integer();
                apply_interval(vm, &args[0], "day", n)
            }),
        ),
        (
            "dateDiff",
            native_func(|vm, args| {
                assert_argc(&args, 3, "dateDiff")?;
                let unit: String = args[0].deref(&vm.heap)?.try_as::<str>()?.to_string();
                date_diff_impl(vm, &unit, &args[1], &args[2])
            }),
        ),
        (
            "formatDateTime",
            native_func(|vm, args| {
                if args.len() < 2 || args.len() > 3 {
                    return Err(VmError::NativeCallFailed(
                        "formatDateTime takes 2 or 3 arguments".to_string(),
                    ));
                }
                format_datetime_impl(vm, &args)
            }),
        ),
        (
            "isIPAddressInRange",
            native_func(|vm, args| {
                assert_argc(&args, 2, "isIPAddressInRange")?;
                // Reference: `!address || !prefix => false`, so non-string (incl. null) args are false.
                let (HogLiteral::String(address), HogLiteral::String(prefix)) =
                    (args[0].deref(&vm.heap)?, args[1].deref(&vm.heap)?)
                else {
                    return Ok(HogLiteral::Boolean(false).into());
                };
                Ok(HogLiteral::Boolean(is_ip_address_in_range(address, prefix)).into())
            }),
        ),
        (
            "md5Hex",
            native_func(|vm, args| {
                assert_argc(&args, 1, "md5Hex")?;
                hash_with_encoding(vm, &args, |data| Md5::digest(data).to_vec(), "hex")
            }),
        ),
        (
            "md5",
            native_func(|vm, args| {
                hash_optional_encoding(vm, &args, "md5", |data| Md5::digest(data).to_vec())
            }),
        ),
        (
            "sha256Hex",
            native_func(|vm, args| {
                assert_argc(&args, 1, "sha256Hex")?;
                hash_with_encoding(vm, &args, |data| Sha256::digest(data).to_vec(), "hex")
            }),
        ),
        (
            "sha256",
            native_func(|vm, args| {
                hash_optional_encoding(vm, &args, "sha256", |data| Sha256::digest(data).to_vec())
            }),
        ),
        (
            "sha256HmacChainHex",
            native_func(|vm, args| {
                assert_argc(&args, 1, "sha256HmacChainHex")?;
                let digest = sha256_hmac_chain(vm, &args[0])?;
                Ok(HogLiteral::String(to_hex(&digest)).into())
            }),
        ),
        (
            "sha256HmacChain",
            native_func(|vm, args| {
                if args.is_empty() || args.len() > 2 {
                    return Err(VmError::NativeCallFailed(
                        "sha256HmacChain takes 1 or 2 arguments".to_string(),
                    ));
                }
                let digest = sha256_hmac_chain(vm, &args[0])?;
                let encoding = encoding_arg(vm, &args, 1)?;
                Ok(HogLiteral::String(encode_digest(&digest, &encoding)?).into())
            }),
        ),
        (
            "base64Encode",
            native_func(|vm, args| {
                assert_argc(&args, 1, "base64Encode")?;
                let s: &str = args[0].deref(&vm.heap)?.try_as()?;
                let out = base64::engine::general_purpose::STANDARD.encode(s.as_bytes());
                Ok(HogLiteral::String(out).into())
            }),
        ),
        (
            "base64Decode",
            native_func(|vm, args| {
                assert_argc(&args, 1, "base64Decode")?;
                let s: &str = args[0].deref(&vm.heap)?.try_as()?;
                Ok(HogLiteral::String(base64_decode_to_string(s)?).into())
            }),
        ),
        (
            "tryBase64Decode",
            native_func(|vm, args| {
                assert_argc(&args, 1, "tryBase64Decode")?;
                let s: &str = args[0].deref(&vm.heap)?.try_as()?;
                // Reference returns "" on failure (Buffer.from never throws, but mirror the intent).
                Ok(HogLiteral::String(base64_decode_to_string(s).unwrap_or_default()).into())
            }),
        ),
        (
            "encodeURLComponent",
            native_func(|vm, args| {
                assert_argc(&args, 1, "encodeURLComponent")?;
                let s: &str = args[0].deref(&vm.heap)?.try_as()?;
                Ok(HogLiteral::String(encode_uri_component(s)).into())
            }),
        ),
        (
            "decodeURLComponent",
            native_func(|vm, args| {
                assert_argc(&args, 1, "decodeURLComponent")?;
                let s: &str = args[0].deref(&vm.heap)?.try_as()?;
                decode_uri_component(s).map(|d| HogLiteral::String(d).into())
            }),
        ),
        (
            "tryDecodeURLComponent",
            native_func(|vm, args| {
                assert_argc(&args, 1, "tryDecodeURLComponent")?;
                let s: &str = args[0].deref(&vm.heap)?.try_as()?;
                // Reference returns null on malformed input rather than erroring.
                Ok(match decode_uri_component(s) {
                    Ok(d) => HogLiteral::String(d).into(),
                    Err(_) => HogLiteral::Null.into(),
                })
            }),
        ),
        (
            "toUUID",
            native_func(|vm, args| {
                // Reference `toUUID` is just `toString`.
                assert_argc(&args, 1, "toUUID")?;
                to_string(&vm.heap, &args[0], 0).map(|s| HogLiteral::String(s).into())
            }),
        ),
        (
            "generateUUIDv4",
            native_func(|_vm, args| {
                assert_argc(&args, 0, "generateUUIDv4")?;
                Ok(HogLiteral::String(generate_uuid_v4()).into())
            }),
        ),
        (
            "now",
            native_func(|vm, args| {
                // Optional timezone arg; the value is non-deterministic (smoke-tested only).
                if args.len() > 1 {
                    return Err(VmError::NativeCallFailed(
                        "now takes 0 or 1 arguments".to_string(),
                    ));
                }
                let zone = match args.first() {
                    Some(v) => match v.deref(&vm.heap)? {
                        HogLiteral::String(s) => s.clone(),
                        _ => "UTC".to_string(),
                    },
                    None => "UTC".to_string(),
                };
                let now = chrono::Utc::now();
                let secs = now.timestamp() as f64 + f64::from(now.timestamp_subsec_nanos()) / 1e9;
                make_hog_datetime(secs, &zone)
            }),
        ),
        (
            "today",
            native_func(|_vm, args| {
                assert_argc(&args, 0, "today")?;
                let now = chrono::Utc::now();
                construct_free_standing(
                    json!({ "__hogDate__": true, "year": now.year(), "month": now.month(), "day": now.day() }),
                    0,
                )
            }),
        ),
        (
            "HogError",
            native_func(|vm, args| {
                if args.len() > 3 {
                    return Err(VmError::NativeCallFailed(
                        "HogError takes 1 to 3 arguments".to_string(),
                    ));
                }
                let type_str = arg_string_or(vm, &args, 0, "Error")?;
                let message = arg_string_or(vm, &args, 1, "An error occurred")?;
                new_hog_error(vm, type_str, message, args.get(2))
            }),
        ),
        (
            "Error",
            native_func(|vm, args| error_constructor(vm, &args, "Error")),
        ),
        (
            "RetryError",
            native_func(|vm, args| error_constructor(vm, &args, "RetryError")),
        ),
        (
            "NotImplementedError",
            native_func(|vm, args| error_constructor(vm, &args, "NotImplementedError")),
        ),
        // Operator-alias functions: the function forms of Hog operators. Note these are the *function*
        // semantics, which differ slightly from the opcodes — e.g. `equals` is strict (no string
        // coercion) whereas the `==` opcode coerces via unifyComparisonTypes.
        (
            "equals",
            native_func(|vm, args| {
                assert_argc(&args, 2, "equals")?;
                Ok(HogLiteral::Boolean(strict_equals(vm, &args[0], &args[1])?).into())
            }),
        ),
        (
            "notEquals",
            native_func(|vm, args| {
                assert_argc(&args, 2, "notEquals")?;
                Ok(HogLiteral::Boolean(!strict_equals(vm, &args[0], &args[1])?).into())
            }),
        ),
        (
            "greater",
            native_func(|vm, args| compare_fn(vm, &args, NumOp::Gt, "greater")),
        ),
        (
            "greaterOrEquals",
            native_func(|vm, args| compare_fn(vm, &args, NumOp::Gte, "greaterOrEquals")),
        ),
        (
            "less",
            native_func(|vm, args| compare_fn(vm, &args, NumOp::Lt, "less")),
        ),
        (
            "lessOrEquals",
            native_func(|vm, args| compare_fn(vm, &args, NumOp::Lte, "lessOrEquals")),
        ),
        (
            "plus",
            native_func(|vm, args| arith_fn(vm, &args, NumOp::Add, "plus")),
        ),
        (
            "minus",
            native_func(|vm, args| arith_fn(vm, &args, NumOp::Sub, "minus")),
        ),
        (
            "and",
            native_func(|vm, args| {
                // `args.every(Boolean)` — all operands truthy.
                for arg in &args {
                    if !arg.deref(&vm.heap)?.truthy() {
                        return Ok(HogLiteral::Boolean(false).into());
                    }
                }
                Ok(HogLiteral::Boolean(true).into())
            }),
        ),
        (
            "or",
            native_func(|vm, args| {
                // `args.some(Boolean)` — any operand truthy.
                for arg in &args {
                    if arg.deref(&vm.heap)?.truthy() {
                        return Ok(HogLiteral::Boolean(true).into());
                    }
                }
                Ok(HogLiteral::Boolean(false).into())
            }),
        ),
        (
            "not",
            native_func(|vm, args| {
                assert_argc(&args, 1, "not")?;
                Ok(HogLiteral::Boolean(!args[0].deref(&vm.heap)?.truthy()).into())
            }),
        ),
        (
            "if",
            native_func(|vm, args| {
                assert_argc(&args, 3, "if")?;
                if args[0].deref(&vm.heap)?.truthy() {
                    Ok(args[1].clone())
                } else {
                    Ok(args[2].clone())
                }
            }),
        ),
        (
            "multiIf",
            native_func(|vm, args| {
                // multiIf(cond1, val1, cond2, val2, ..., default).
                if args.is_empty() {
                    return Err(VmError::NativeCallFailed(
                        "multiIf requires at least one argument".to_string(),
                    ));
                }
                let default = args.last().unwrap();
                let pairs = &args[..args.len() - 1];
                let mut i = 0;
                while i + 1 < pairs.len() {
                    if pairs[i].deref(&vm.heap)?.truthy() {
                        return Ok(pairs[i + 1].clone());
                    }
                    i += 2;
                }
                Ok(default.clone())
            }),
        ),
        (
            "in",
            native_func(|vm, args| {
                // `in(val, arr)` — array/tuple membership only (the function form, like `has`).
                assert_argc(&args, 2, "in")?;
                let needle = &args[0];
                match args[1].deref(&vm.heap)? {
                    HogLiteral::Array(vals) | HogLiteral::Tuple(vals) => {
                        for val in vals.iter() {
                            if *needle.equals(val, &vm.heap)?.try_as()? {
                                return Ok(HogLiteral::Boolean(true).into());
                            }
                        }
                        Ok(HogLiteral::Boolean(false).into())
                    }
                    _ => Ok(HogLiteral::Boolean(false).into()),
                }
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
// `toString` semantics (reference `STLToString`): a top-level Hog date renders as `YYYY-MM-DD` and a
// top-level Hog datetime as an ISO 8601 string; every other value (including nested temporals inside
// containers) goes through the canonical printer, which raw-prints a top-level string but quotes
// strings nested in arrays/objects. The `depth` arg is retained for call-site compatibility.
fn to_string(heap: &VmHeap, val: &HogValue, _depth: usize) -> Result<String, VmError> {
    if let HogLiteral::Object(obj) = val.deref(heap)? {
        if obj_marker(heap, obj, "__hogDate__")? {
            let year = obj_number(heap, obj, "year")?.unwrap_or(0.0) as i64;
            let month = obj_number(heap, obj, "month")?.unwrap_or(0.0) as i64;
            let day = obj_number(heap, obj, "day")?.unwrap_or(0.0) as i64;
            return Ok(format!("{year}-{month:02}-{day:02}"));
        }
        if obj_marker(heap, obj, "__hogDateTime__")? {
            return hog_datetime_to_iso(heap, obj);
        }
    }
    print_hog_string_output(heap, val)
}

// Render a Hog datetime as Luxon's `DateTime.fromSeconds(dt, {zone}).toISO()` does: millisecond
// precision, `Z` for UTC and a `+HH:MM` offset otherwise.
fn hog_datetime_to_iso(heap: &VmHeap, obj: &IndexMap<String, HogValue>) -> Result<String, VmError> {
    let dt = obj_number(heap, obj, "dt")?.unwrap_or(0.0);
    let zone = obj_string(heap, obj, "zone")?.unwrap_or_else(|| "UTC".to_string());
    // Luxon keeps millisecond precision; round to whole millis first to avoid float drift turning
    // e.g. .123 into .122 when splitting seconds and sub-second nanos.
    let total_millis = (dt * 1000.0).round() as i64;
    let secs = total_millis.div_euclid(1000);
    let nanos = (total_millis.rem_euclid(1000) * 1_000_000) as u32;
    let utc = DateTime::from_timestamp(secs, nanos).ok_or_else(|| {
        VmError::NativeCallFailed(format!("toString: datetime {dt} out of range"))
    })?;
    let formatted = if zone == "UTC" {
        utc.format("%Y-%m-%dT%H:%M:%S%.3fZ").to_string()
    } else {
        let tz: chrono_tz::Tz = zone
            .parse()
            .map_err(|_| VmError::NativeCallFailed(format!("unknown timezone {zone}")))?;
        utc.with_timezone(&tz)
            .format("%Y-%m-%dT%H:%M:%S%.3f%:z")
            .to_string()
    };
    Ok(formatted)
}

fn obj_marker(heap: &VmHeap, obj: &IndexMap<String, HogValue>, key: &str) -> Result<bool, VmError> {
    match obj.get(key) {
        Some(v) => Ok(matches!(v.deref(heap)?, HogLiteral::Boolean(true))),
        None => Ok(false),
    }
}

fn obj_number(
    heap: &VmHeap,
    obj: &IndexMap<String, HogValue>,
    key: &str,
) -> Result<Option<f64>, VmError> {
    match obj.get(key) {
        Some(v) => Ok(match v.deref(heap)? {
            HogLiteral::Number(n) => Some(n.to_float()),
            _ => None,
        }),
        None => Ok(None),
    }
}

fn obj_string(
    heap: &VmHeap,
    obj: &IndexMap<String, HogValue>,
    key: &str,
) -> Result<Option<String>, VmError> {
    match obj.get(key) {
        Some(v) => Ok(match v.deref(heap)? {
            HogLiteral::String(s) => Some(s.clone()),
            _ => None,
        }),
        None => Ok(None),
    }
}

// Whole days from the Unix epoch to a Hog date (reference: `day.diff(epoch, 'days').days` floored).
fn hog_date_epoch_days(heap: &VmHeap, obj: &IndexMap<String, HogValue>) -> Result<i64, VmError> {
    let year = obj_number(heap, obj, "year")?.unwrap_or(0.0) as i32;
    let month = obj_number(heap, obj, "month")?.unwrap_or(0.0) as u32;
    let day = obj_number(heap, obj, "day")?.unwrap_or(0.0) as u32;
    let date = NaiveDate::from_ymd_opt(year, month, day)
        .ok_or_else(|| VmError::NativeCallFailed(format!("invalid date {year}-{month}-{day}")))?;
    let epoch = NaiveDate::from_ymd_opt(1970, 1, 1).expect("epoch is valid");
    Ok(date.signed_duration_since(epoch).num_days())
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
        // Tuples serialize as JSON arrays, same as arrays.
        HogLiteral::Array(arr) | HogLiteral::Tuple(arr) => {
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
        HogLiteral::Callable(_) | HogLiteral::Closure(_) => {
            escape(&print_hog_string_output(heap, value)?)
        }
    })();

    if container_ptr.is_some() {
        marked.pop();
    }
    result
}

// Shared by the JSON-extract family: parse args[0] (a JSON string, or convert a Hog value) and
// navigate args[1..] as a path. A parse error or a bad path is nullish (None), matching the
// reference's JSONDecodeError / nullish get_nested_value handling.
fn json_path_value(vm: &HogVM, args: &[HogValue]) -> Result<Option<JsonValue>, VmError> {
    let json = match args[0].deref(&vm.heap)? {
        HogLiteral::String(s) => match serde_json::from_str::<JsonValue>(s) {
            Ok(j) => j,
            Err(_) => return Ok(None),
        },
        _ => vm.hog_to_json(&args[0])?,
    };
    let path = &args[1..];
    if path.is_empty() {
        return Ok(Some(json));
    }
    Ok(get_json_nested(&json, path, vm).unwrap_or(None).cloned())
}

// position(haystack, needle): 1-based char index of str(needle) in haystack, or 0 if absent (or
// haystack isn't a string). The case-insensitive variant lowercases both first.
// SQL LIKE matching (like/ilike/notLike/notILike). The reference escapes regex specials in the
// pattern, maps `%`→`.*` and `_`→`.`, then does an *unanchored* match (`.test()`), so a pattern
// without wildcards matches as a substring.
fn like_impl(
    vm: &HogVM,
    args: &[HogValue],
    name: &str,
    case_insensitive: bool,
    negate: bool,
) -> Result<HogValue, VmError> {
    assert_argc(args, 2, name)?;
    let string: &str = args[0].deref(&vm.heap)?.try_as()?;
    let pattern: &str = args[1].deref(&vm.heap)?.try_as()?;
    let regex = like_to_regex(pattern);
    let matched = regex_match(string, &regex, !case_insensitive)?;
    Ok(HogLiteral::Boolean(matched ^ negate).into())
}

fn like_to_regex(pattern: &str) -> String {
    let mut out = String::with_capacity(pattern.len() * 2);
    for c in pattern.chars() {
        match c {
            '-' | '/' | '\\' | '^' | '$' | '*' | '+' | '?' | '.' | '(' | ')' | '|' | '[' | ']'
            | '{' | '}' => {
                out.push('\\');
                out.push(c);
            }
            '%' => out.push_str(".*"),
            '_' => out.push('.'),
            other => out.push(other),
        }
    }
    out
}

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

fn make_hog_datetime(dt: f64, zone: &str) -> Result<HogValue, VmError> {
    construct_free_standing(
        json!({ "__hogDateTime__": true, "dt": dt, "zone": zone }),
        0,
    )
}

// Epoch seconds of a Hog Date/DateTime value (the `dt` field, or UTC midnight for a Date).
// toUnixTimestamp/toUnixTimestampMilli accept Date/DateTime like every temporal fn, but the
// reference also parses ISO strings (honoring the optional zone arg) and yields NaN — observably
// null once serialized — for unparseable ones, so a string that fails to parse maps to None.
fn unix_timestamp_seconds(
    vm: &HogVM,
    args: &[HogValue],
    name: &str,
) -> Result<Option<f64>, VmError> {
    if let HogLiteral::String(s) = args[0].deref(&vm.heap)? {
        // The reference does `zone || 'UTC'`, so a null zone (an absent event
        // property) silently falls back to UTC; any other non-string zone is an
        // invalid luxon zone there, yielding NaN — observably null.
        let zone = match args.get(1) {
            Some(arg) => match arg.deref(&vm.heap)? {
                HogLiteral::String(z) => Some(z.clone()),
                HogLiteral::Null => None,
                _ => return Ok(None),
            },
            None => None,
        };
        return Ok(parse_datetime_to_seconds(s, zone.as_deref()).ok());
    }
    temporal_seconds(vm, &args[0], name).map(Some)
}

fn temporal_seconds(vm: &HogVM, value: &HogValue, name: &str) -> Result<f64, VmError> {
    value
        .deref(&vm.heap)?
        .as_temporal_seconds(&vm.heap)
        .ok_or_else(|| VmError::NativeCallFailed(format!("{name} expects a Date or DateTime")))
}

// (epoch seconds, zone string) of a Hog DateTime; zone defaults to UTC (Hog Dates carry no zone).
fn hog_datetime_parts(vm: &HogVM, value: &HogValue, name: &str) -> Result<(f64, String), VmError> {
    let lit = value.deref(&vm.heap)?;
    let secs = lit
        .as_temporal_seconds(&vm.heap)
        .ok_or_else(|| VmError::NativeCallFailed(format!("{name} expects a DateTime")))?;
    let zone = match lit {
        HogLiteral::Object(map) => match map.get("zone").map(|z| z.deref(&vm.heap)) {
            Some(Ok(HogLiteral::String(s))) => s.clone(),
            _ => "UTC".to_string(),
        },
        _ => "UTC".to_string(),
    };
    Ok((secs, zone))
}

// The reference reads the UTC wall-clock of `dt` (its localize is a no-op re-label), so year/month
// are the UTC fields of the instant.
fn extract_utc_field(
    vm: &HogVM,
    value: &HogValue,
    field: &str,
    name: &str,
) -> Result<i64, VmError> {
    let secs = temporal_seconds(vm, value, name)?;
    let utc = DateTime::from_timestamp(secs.floor() as i64, 0)
        .ok_or_else(|| VmError::NativeCallFailed(format!("{name}: timestamp out of range")))?;
    Ok(match field {
        "year" => utc.year() as i64,
        "month" => utc.month() as i64,
        "day" => utc.day() as i64,
        "hour" => utc.hour() as i64,
        "minute" => utc.minute() as i64,
        "second" => utc.second() as i64,
        _ => 0,
    })
}

// dateTrunc: truncate the UTC wall-clock to the unit, then re-interpret in the value's zone.
fn date_trunc_impl(vm: &HogVM, unit: &str, value: &HogValue) -> Result<HogValue, VmError> {
    let (secs, zone) = hog_datetime_parts(vm, value, "dateTrunc")?;
    let utc = DateTime::from_timestamp(secs.floor() as i64, 0).ok_or_else(|| {
        VmError::NativeCallFailed("dateTrunc: timestamp out of range".to_string())
    })?;
    let n = utc.naive_utc();
    let truncated = match unit {
        "year" => NaiveDate::from_ymd_opt(n.year(), 1, 1).and_then(|d| d.and_hms_opt(0, 0, 0)),
        "month" => {
            NaiveDate::from_ymd_opt(n.year(), n.month(), 1).and_then(|d| d.and_hms_opt(0, 0, 0))
        }
        "day" => n.date().and_hms_opt(0, 0, 0),
        "hour" => n.date().and_hms_opt(n.hour(), 0, 0),
        "minute" => n.date().and_hms_opt(n.hour(), n.minute(), 0),
        _ => {
            return Err(VmError::NativeCallFailed(format!(
                "Unsupported unit for dateTrunc: {unit}"
            )))
        }
    }
    .ok_or_else(|| VmError::NativeCallFailed("dateTrunc: invalid date".to_string()))?;

    let tz: chrono_tz::Tz = zone
        .parse()
        .map_err(|_| VmError::NativeCallFailed(format!("dateTrunc: unknown timezone {zone}")))?;
    let new_secs = match tz.from_local_datetime(&truncated) {
        LocalResult::Single(dt) | LocalResult::Ambiguous(dt, _) => dt.timestamp() as f64,
        LocalResult::None => {
            return Err(VmError::NativeCallFailed(
                "dateTrunc: local time does not exist".to_string(),
            ))
        }
    };
    make_hog_datetime(new_secs, &zone)
}

// Epoch seconds of a naive wall-clock interpreted in `zone`.
fn zone_local_timestamp(zone: &str, naive: &NaiveDateTime) -> Result<f64, VmError> {
    let tz: chrono_tz::Tz = zone
        .parse()
        .map_err(|_| VmError::NativeCallFailed(format!("unknown timezone {zone}")))?;
    match tz.from_local_datetime(naive) {
        LocalResult::Single(dt) | LocalResult::Ambiguous(dt, _) => Ok(dt.timestamp() as f64),
        LocalResult::None => Err(VmError::NativeCallFailed(
            "local time does not exist".to_string(),
        )),
    }
}

// {__hogInterval__: true, value, unit} built directly so keys stay in insertion order when printed.
fn make_hog_interval(vm: &HogVM, args: &[HogValue], unit: &str) -> Result<HogValue, VmError> {
    assert_argc(args, 1, "toInterval")?;
    let n = args[0].deref(&vm.heap)?.try_as::<Num>()?.clone();
    let mut map = IndexMap::new();
    map.insert(
        "__hogInterval__".to_string(),
        HogLiteral::Boolean(true).into(),
    );
    map.insert("value".to_string(), HogLiteral::Number(n).into());
    map.insert(
        "unit".to_string(),
        HogLiteral::String(unit.to_string()).into(),
    );
    Ok(HogLiteral::Object(map).into())
}

// Add an interval to a DateTime. day/hour/minute/second are absolute durations; month is wall-clock
// field math (clamping the day) re-interpreted in the value's zone.
fn apply_interval(
    vm: &HogVM,
    dt_value: &HogValue,
    unit: &str,
    value: i64,
) -> Result<HogValue, VmError> {
    // Adding an interval to a Date yields a Date; to a DateTime yields a DateTime (reference
    // applyIntervalToDateTime). We do the arithmetic in epoch seconds either way, then re-wrap.
    let is_date = match dt_value.deref(&vm.heap)? {
        HogLiteral::Object(obj) => obj_marker(&vm.heap, obj, "__hogDate__")?,
        _ => false,
    };
    let (secs, zone) = hog_datetime_parts(vm, dt_value, "dateAdd")?;
    let new_secs = match unit {
        "day" => secs + (value as f64) * 86400.0,
        "hour" => secs + (value as f64) * 3600.0,
        "minute" => secs + (value as f64) * 60.0,
        "second" => secs + value as f64,
        "month" => {
            let utc = DateTime::from_timestamp(secs.floor() as i64, 0).ok_or_else(|| {
                VmError::NativeCallFailed("dateAdd: timestamp out of range".to_string())
            })?;
            let n = utc.naive_utc();
            let total = (n.year() as i64) * 12 + (n.month() as i64 - 1) + value;
            let new_year = total.div_euclid(12) as i32;
            let new_month = (total.rem_euclid(12) + 1) as u32;
            let mut day = n.day();
            let truncated = loop {
                if let Some(d) = NaiveDate::from_ymd_opt(new_year, new_month, day)
                    .and_then(|d| d.and_hms_opt(n.hour(), n.minute(), n.second()))
                {
                    break d;
                }
                if day <= 1 {
                    return Err(VmError::NativeCallFailed(
                        "dateAdd: invalid date".to_string(),
                    ));
                }
                day -= 1;
            };
            zone_local_timestamp(&zone, &truncated)?
        }
        _ => {
            return Err(VmError::NativeCallFailed(format!(
                "Unknown interval unit {unit}"
            )))
        }
    };
    if is_date {
        let utc = DateTime::from_timestamp(new_secs.floor() as i64, 0).ok_or_else(|| {
            VmError::NativeCallFailed("dateAdd: timestamp out of range".to_string())
        })?;
        return construct_free_standing(
            json!({ "__hogDate__": true, "year": utc.year(), "month": utc.month(), "day": utc.day() }),
            0,
        );
    }
    make_hog_datetime(new_secs, &zone)
}

fn date_add_impl(
    vm: &HogVM,
    unit: &str,
    amount: i64,
    dt_value: &HogValue,
) -> Result<HogValue, VmError> {
    let (unit, amount) = match unit {
        "day" | "hour" | "minute" | "second" | "month" => (unit, amount),
        "week" => ("day", amount * 7),
        "year" => ("month", amount * 12),
        _ => {
            return Err(VmError::NativeCallFailed(format!(
                "Unsupported interval unit: {unit}"
            )))
        }
    };
    apply_interval(vm, dt_value, unit, amount)
}

fn date_diff_impl(
    vm: &HogVM,
    unit: &str,
    start_v: &HogValue,
    end_v: &HogValue,
) -> Result<HogValue, VmError> {
    let start = temporal_seconds(vm, start_v, "dateDiff")?;
    let end = temporal_seconds(vm, end_v, "dateDiff")?;
    let diff = end - start;
    let utc_year_month = |secs: f64| -> Result<(i64, i64), VmError> {
        let dt = DateTime::from_timestamp(secs.floor() as i64, 0).ok_or_else(|| {
            VmError::NativeCallFailed("dateDiff: timestamp out of range".to_string())
        })?;
        Ok((dt.year() as i64, dt.month() as i64))
    };
    let result = match unit {
        "day" => (diff / 86400.0).floor() as i64,
        "hour" => (diff / 3600.0).floor() as i64,
        "minute" => (diff / 60.0).floor() as i64,
        "second" => diff as i64,
        "week" => ((diff / 86400.0).floor() as i64) / 7,
        "month" => {
            let (sy, sm) = utc_year_month(start)?;
            let (ey, em) = utc_year_month(end)?;
            (ey * 12 + em) - (sy * 12 + sm)
        }
        "year" => utc_year_month(end)?.0 - utc_year_month(start)?.0,
        _ => {
            return Err(VmError::NativeCallFailed(format!(
                "Unsupported unit for dateDiff: {unit}"
            )))
        }
    };
    Ok(HogLiteral::Number(Num::Integer(result)).into())
}

fn format_datetime_impl(vm: &HogVM, args: &[HogValue]) -> Result<HogValue, VmError> {
    let (secs, dt_zone) = hog_datetime_parts(vm, &args[0], "formatDateTime")?;
    let format: String = args[1].deref(&vm.heap)?.try_as::<str>()?.to_string();
    let zone = if args.len() > 2 {
        args[2].deref(&vm.heap)?.try_as::<str>()?.to_string()
    } else {
        dt_zone
    };
    let translated = translate_clickhouse_format(&format);
    let tz: chrono_tz::Tz = zone.parse().map_err(|_| {
        VmError::NativeCallFailed(format!("formatDateTime: unknown timezone {zone}"))
    })?;
    let dt = match tz.timestamp_opt(secs.floor() as i64, 0) {
        LocalResult::Single(dt) | LocalResult::Ambiguous(dt, _) => dt,
        LocalResult::None => {
            return Err(VmError::NativeCallFailed(
                "formatDateTime: invalid timestamp".to_string(),
            ))
        }
    };
    Ok(HogLiteral::String(dt.format(&translated).to_string()).into())
}

// Translate the reference's ClickHouse-style format tokens (% + token) to chrono strftime codes.
fn translate_clickhouse_format(format: &str) -> String {
    let chars: Vec<char> = format.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i] == '%' && i + 1 < chars.len() {
            i += 1;
            out.push_str(translate_format_token(chars[i]));
        } else {
            out.push(chars[i]);
        }
        i += 1;
    }
    out
}

fn translate_format_token(c: char) -> &'static str {
    match c {
        'a' => "%a",
        'b' => "%b",
        'c' => "%m",
        'C' => "%y",
        'd' => "%d",
        'D' => "%m/%d/%y",
        'e' => "%d",
        'f' => "%f",
        'F' => "%Y-%m-%d",
        'g' => "%y",
        'G' => "%Y",
        'h' => "%I",
        'H' => "%H",
        'i' => "%M",
        'I' => "%I",
        'j' => "%j",
        'k' => "%H",
        'l' => "%I",
        'm' => "%m",
        'M' => "%B",
        'n' => "\n",
        'p' => "%p",
        'r' => "%I:%M %p",
        'R' => "%H:%M",
        's' => "%S",
        'S' => "%S",
        't' => "\t",
        'T' => "%H:%M:%S",
        'u' => "%u",
        'V' => "%V",
        'w' => "%w",
        'W' => "%A",
        'y' => "%y",
        'Y' => "%Y",
        'z' => "%z",
        '%' => "%%",
        _ => "",
    }
}

// Port of the reference `isIPAddressInRange` (common/hogvm/typescript/src/stl/ip.ts): is `address`
// inside the CIDR `prefix`? Any malformed input returns false rather than erroring, matching the
// reference's try/catch. We reimplement parsing instead of leaning on std::net so the strict
// validation (no leading zeros, exact segment counts, single `::`) matches byte-for-byte.
fn is_ip_address_in_range(address: &str, prefix: &str) -> bool {
    if address.is_empty() || prefix.is_empty() {
        return false;
    }
    let Some((net, mask)) = prefix.split_once('/') else {
        return false;
    };
    if net.is_empty() || mask.is_empty() {
        return false;
    }
    let Ok(cidr) = mask.parse::<i64>() else {
        return false;
    };
    if cidr < 0 {
        return false;
    }
    let v4 = address.contains('.') && net.contains('.');
    let v6 = !v4 && address.contains(':') && net.contains(':');
    if !v4 && !v6 {
        return false;
    }
    if (v4 && cidr > 32) || (v6 && cidr > 128) {
        return false;
    }
    let (Some(a_bytes), Some(n_bytes)) = (ip_to_bytes(address, v4), ip_to_bytes(net, v4)) else {
        return false;
    };
    let cidr = cidr as usize;
    let full_bytes = cidr >> 3;
    for i in 0..full_bytes {
        if a_bytes[i] != n_bytes[i] {
            return false;
        }
    }
    let bits = cidr & 7;
    if bits != 0 && full_bytes < a_bytes.len() {
        let m = 0xffu16 << (8 - bits);
        if (u16::from(a_bytes[full_bytes]) & m) != (u16::from(n_bytes[full_bytes]) & m) {
            return false;
        }
    }
    true
}

fn ip_to_bytes(ip: &str, is_v4: bool) -> Option<Vec<u8>> {
    if is_v4 {
        let parts: Vec<&str> = ip.split('.').collect();
        if parts.len() != 4 {
            return None;
        }
        let mut bytes = Vec::with_capacity(4);
        for part in parts {
            let n: u32 = part.parse().ok()?;
            // Reject n > 255 and non-canonical forms like "01" (parse() already rejects "+1"/" 1").
            if n > 255 || part != n.to_string() {
                return None;
            }
            bytes.push(n as u8);
        }
        return Some(bytes);
    }

    let segments: Vec<String> = if ip.contains("::") {
        if ip.matches("::").count() > 1 {
            return None;
        }
        let (pre, post) = ip.split_once("::")?;
        let pre_seg: Vec<&str> = if pre.is_empty() {
            vec![]
        } else {
            pre.split(':').collect()
        };
        let post_seg: Vec<&str> = if post.is_empty() {
            vec![]
        } else {
            post.split(':').collect()
        };
        if pre_seg.len() + post_seg.len() > 7 {
            return None;
        }
        let fill = 8 - pre_seg.len() - post_seg.len();
        pre_seg
            .iter()
            .map(|s| s.to_string())
            .chain((0..fill).map(|_| "0".to_string()))
            .chain(post_seg.iter().map(|s| s.to_string()))
            .collect()
    } else {
        let segs: Vec<&str> = ip.split(':').collect();
        if segs.len() != 8 {
            return None;
        }
        segs.iter().map(|s| s.to_string()).collect()
    };

    let mut bytes = vec![0u8; 16];
    for (i, seg) in segments.iter().enumerate() {
        if seg.is_empty() {
            return None;
        }
        let v = u16::from_str_radix(seg, 16).ok()?;
        bytes[i * 2] = (v >> 8) as u8;
        bytes[i * 2 + 1] = (v & 0xff) as u8;
    }
    Some(bytes)
}

type HmacSha256 = Hmac<Sha256>;

// Hash `data` with the supplied digest fn, then encode. Used by md5Hex/sha256Hex (fixed "hex").
// `null` data returns `null`, matching the reference.
fn hash_with_encoding(
    vm: &HogVM,
    args: &[HogValue],
    hasher: impl Fn(&[u8]) -> Vec<u8>,
    encoding: &str,
) -> Result<HogValue, VmError> {
    match args[0].deref(&vm.heap)? {
        HogLiteral::Null => Ok(HogLiteral::Null.into()),
        lit => {
            let data: &str = lit.try_as()?;
            Ok(HogLiteral::String(encode_digest(&hasher(data.as_bytes()), encoding)?).into())
        }
    }
}

// md5/sha256 take an optional 2nd encoding arg (default "hex").
fn hash_optional_encoding(
    vm: &HogVM,
    args: &[HogValue],
    name: &str,
    hasher: impl Fn(&[u8]) -> Vec<u8>,
) -> Result<HogValue, VmError> {
    if args.is_empty() || args.len() > 2 {
        return Err(VmError::NativeCallFailed(format!(
            "{name} takes 1 or 2 arguments"
        )));
    }
    let encoding = encoding_arg(vm, args, 1)?;
    hash_with_encoding(vm, args, hasher, &encoding)
}

// sha256HmacChain: HMAC-SHA256 chained across an array of strings, re-keying each step with the
// previous raw digest. Mirrors common/hogvm/typescript/src/stl/crypto.ts.
fn sha256_hmac_chain(vm: &HogVM, arg: &HogValue) -> Result<Vec<u8>, VmError> {
    let arr = match arg.deref(&vm.heap)? {
        HogLiteral::Array(a) => a.clone(),
        _ => {
            return Err(VmError::NativeCallFailed(
                "sha256HmacChain expects an array".to_string(),
            ))
        }
    };
    if arr.len() < 2 {
        return Err(VmError::NativeCallFailed(
            "Data array must contain at least two elements.".to_string(),
        ));
    }
    let key0: &str = arr[0].deref(&vm.heap)?.try_as()?;
    let mut mac = HmacSha256::new_from_slice(key0.as_bytes())
        .map_err(|e| VmError::NativeCallFailed(e.to_string()))?;
    let msg1: &str = arr[1].deref(&vm.heap)?.try_as()?;
    mac.update(msg1.as_bytes());
    let mut digest = mac.finalize().into_bytes().to_vec();
    for elem in &arr[2..] {
        let mut next = HmacSha256::new_from_slice(&digest)
            .map_err(|e| VmError::NativeCallFailed(e.to_string()))?;
        let msg: &str = elem.deref(&vm.heap)?.try_as()?;
        next.update(msg.as_bytes());
        digest = next.finalize().into_bytes().to_vec();
    }
    Ok(digest)
}

// Encode raw digest bytes the way Node's `hash.digest(encoding)` does.
fn encode_digest(digest: &[u8], encoding: &str) -> Result<String, VmError> {
    match encoding {
        "hex" => Ok(to_hex(digest)),
        "base64" => Ok(base64::engine::general_purpose::STANDARD.encode(digest)),
        "base64url" => Ok(base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(digest)),
        // Node's "binary"/"latin1" maps each byte to the code point equal to its value.
        "binary" => Ok(digest.iter().map(|&b| b as char).collect()),
        other => Err(VmError::NativeCallFailed(format!(
            "Unsupported encoding: {other}"
        ))),
    }
}

// Read an optional encoding arg, defaulting to "hex" when absent or null.
fn encoding_arg(vm: &HogVM, args: &[HogValue], idx: usize) -> Result<String, VmError> {
    match args.get(idx) {
        Some(v) => match v.deref(&vm.heap)? {
            HogLiteral::String(s) => Ok(s.clone()),
            _ => Ok("hex".to_string()),
        },
        None => Ok("hex".to_string()),
    }
}

fn to_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0xf) as usize] as char);
    }
    out
}

// Node's `Buffer.from(s, 'base64').toString()` — lenient about padding, UTF-8 decode lossily.
fn base64_decode_to_string(s: &str) -> Result<String, VmError> {
    let engine = base64::engine::GeneralPurpose::new(
        &base64::alphabet::STANDARD,
        base64::engine::GeneralPurposeConfig::new()
            .with_decode_padding_mode(base64::engine::DecodePaddingMode::Indifferent)
            .with_decode_allow_trailing_bits(true),
    );
    let bytes = engine
        .decode(s.trim())
        .map_err(|e| VmError::NativeCallFailed(format!("base64 decode failed: {e}")))?;
    Ok(String::from_utf8_lossy(&bytes).into_owned())
}

// JS `encodeURIComponent`: keep the unreserved set, percent-encode every other UTF-8 byte.
fn encode_uri_component(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for &b in s.as_bytes() {
        let keep = b.is_ascii_alphanumeric()
            || matches!(
                b,
                b'-' | b'_' | b'.' | b'!' | b'~' | b'*' | b'\'' | b'(' | b')'
            );
        if keep {
            out.push(b as char);
        } else {
            out.push('%');
            out.push((b"0123456789ABCDEF"[(b >> 4) as usize]) as char);
            out.push((b"0123456789ABCDEF"[(b & 0xf) as usize]) as char);
        }
    }
    out
}

// JS `decodeURIComponent`: decode %XX into bytes and require the result be valid UTF-8, erroring
// (like JS's URIError) on a malformed escape or invalid UTF-8 — callers map that to null/"".
fn decode_uri_component(s: &str) -> Result<String, VmError> {
    let bytes = s.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            if i + 2 >= bytes.len() {
                return Err(VmError::NativeCallFailed("URI malformed".to_string()));
            }
            let hi = hex_val(bytes[i + 1]);
            let lo = hex_val(bytes[i + 2]);
            match (hi, lo) {
                (Some(h), Some(l)) => out.push((h << 4) | l),
                _ => return Err(VmError::NativeCallFailed("URI malformed".to_string())),
            }
            i += 3;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    String::from_utf8(out).map_err(|_| VmError::NativeCallFailed("URI malformed".to_string()))
}

fn hex_val(b: u8) -> Option<u8> {
    match b {
        b'0'..=b'9' => Some(b - b'0'),
        b'a'..=b'f' => Some(b - b'a' + 10),
        b'A'..=b'F' => Some(b - b'A' + 10),
        _ => None,
    }
}

// Mirror the reference UUID v4 template fill: random hex for `x`, `(r & 0x3) | 0x8` for `y`.
fn generate_uuid_v4() -> String {
    let mut rng = rand::thread_rng();
    let mut out = String::with_capacity(36);
    for c in "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".chars() {
        match c {
            'x' => {
                let r: u8 = rng.gen_range(0..16);
                out.push(char::from_digit(u32::from(r), 16).unwrap());
            }
            'y' => {
                let r: u8 = rng.gen_range(0..16);
                let v = (r & 0x3) | 0x8;
                out.push(char::from_digit(u32::from(v), 16).unwrap());
            }
            other => out.push(other),
        }
    }
    out
}

// Error/RetryError/NotImplementedError share one body: the function name is the error type, the
// first arg is the message, the second is the optional payload (mirrors the reference's `name` arg).
fn error_constructor(vm: &HogVM, args: &[HogValue], type_str: &str) -> Result<HogValue, VmError> {
    if args.len() > 2 {
        return Err(VmError::NativeCallFailed(format!(
            "{type_str} takes 0 to 2 arguments"
        )));
    }
    let message = arg_string_or(vm, args, 0, "An error occurred")?;
    new_hog_error(vm, type_str.to_string(), message, args.get(1))
}

// Build the Hog error duck-type `{ __hogError__, type, message, payload? }`. Payload is included
// only when present and non-null, matching the reference printer's `obj.payload ? …` guard.
fn new_hog_error(
    vm: &HogVM,
    type_str: String,
    message: String,
    payload: Option<&HogValue>,
) -> Result<HogValue, VmError> {
    let mut map = IndexMap::new();
    map.insert("__hogError__".to_string(), HogLiteral::Boolean(true).into());
    map.insert("type".to_string(), HogLiteral::String(type_str).into());
    map.insert("message".to_string(), HogLiteral::String(message).into());
    if let Some(p) = payload {
        if !matches!(p.deref(&vm.heap)?, HogLiteral::Null) {
            map.insert("payload".to_string(), p.clone());
        }
    }
    Ok(HogLiteral::Object(map).into())
}

// Resolve a string arg with the reference's `value || default` falsiness: missing, null, or empty
// string fall back to `default`; other values stringify.
fn arg_string_or(
    vm: &HogVM,
    args: &[HogValue],
    idx: usize,
    default: &str,
) -> Result<String, VmError> {
    match args.get(idx) {
        None => Ok(default.to_string()),
        Some(v) => match v.deref(&vm.heap)? {
            HogLiteral::String(s) if s.is_empty() => Ok(default.to_string()),
            HogLiteral::String(s) => Ok(s.clone()),
            HogLiteral::Null => Ok(default.to_string()),
            _ => to_string(&vm.heap, v, 0),
        },
    }
}

// `empty` semantics (and `notEmpty` is its negation): numbers/booleans are never empty; null and
// empty "" / [] / () / {} are empty. Matches the reference STL.empty.
fn is_hog_empty(lit: &HogLiteral) -> bool {
    match lit {
        HogLiteral::Number(_) | HogLiteral::Boolean(_) => false,
        HogLiteral::Null => true,
        HogLiteral::String(s) => s.is_empty(),
        HogLiteral::Array(a) | HogLiteral::Tuple(a) => a.is_empty(),
        HogLiteral::Object(o) => o.is_empty(),
        _ => false,
    }
}

// `equals`/`notEquals` use strict equality (reference `a === b`): no cross-type coercion, so a
// number and a numeric string are never equal. Differs from the coercing `==`/`!=` opcodes.
fn strict_equals(vm: &HogVM, a: &HogValue, b: &HogValue) -> Result<bool, VmError> {
    Ok(a.deref(&vm.heap)? == b.deref(&vm.heap)?)
}

// greater/less/greaterOrEquals/lessOrEquals as functions — reuse the VM's comparison semantics.
fn compare_fn(vm: &HogVM, args: &[HogValue], op: NumOp, name: &str) -> Result<HogValue, VmError> {
    assert_argc(args, 2, name)?;
    let a = args[0].deref(&vm.heap)?;
    let b = args[1].deref(&vm.heap)?;
    Ok(compare_values(op, a, b, &vm.heap)?.into())
}

// plus/minus as functions — numeric arithmetic over the two operands.
fn arith_fn(vm: &HogVM, args: &[HogValue], op: NumOp, name: &str) -> Result<HogValue, VmError> {
    assert_argc(args, 2, name)?;
    let a = args[0].deref(&vm.heap)?.try_as::<Num>()?.clone();
    let b = args[1].deref(&vm.heap)?.try_as::<Num>()?.clone();
    Ok(Num::binary_op(op, &a, &b)?.into())
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
    F: Fn(&HogVM, Vec<HogValue>) -> Result<HogValue, VmError> + Send + Sync + 'static,
{
    Arc::new(func)
}
