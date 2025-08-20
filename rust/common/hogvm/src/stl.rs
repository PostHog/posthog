use core::str;
use std::collections::HashMap;

use serde_json::{json, Value as JsonValue};

use crate::{
    construct_free_standing,
    error::VmError,
    memory::VmHeap,
    program::Module,
    util::{get_json_nested, regex_match},
    values::{HogLiteral, HogValue, Num},
    vm::HogVM,
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
                    HogLiteral::Number(_) => Ok(HogLiteral::String("number".to_string()).into()),
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
                        let (vals, errs): (Vec<_>, Vec<_>) = arr
                            .iter()
                            .map(|v| v.deref(&vm.heap).and_then(|v| v.try_as::<Num>()).cloned())
                            .partition(Result::is_ok);
                        if errs.is_empty() {
                            let mut vals = vals.into_iter().map(|v| v.unwrap()).collect::<Vec<_>>();
                            vals.sort_unstable_by(|a, b| a.compare(b));
                            Ok(
                                HogLiteral::Array(vals.into_iter().map(|v| v.into()).collect())
                                    .into(),
                            )
                        } else {
                            Err(VmError::NativeCallFailed(
                                "arraySort() only supports arrays of numbers".to_string(),
                            ))
                        }
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
                        let (vals, errs): (Vec<_>, Vec<_>) = arr
                            .iter()
                            .map(|v| v.deref(&vm.heap).and_then(|v| v.try_as::<Num>()).cloned())
                            .partition(Result::is_ok);
                        if errs.is_empty() {
                            let mut vals = vals.into_iter().map(|v| v.unwrap()).collect::<Vec<_>>();
                            vals.sort_unstable_by(|a, b| a.compare(b));
                            vals.reverse();
                            Ok(
                                HogLiteral::Array(vals.into_iter().map(|v| v.into()).collect())
                                    .into(),
                            )
                        } else {
                            Err(VmError::NativeCallFailed(
                                "arrayReverseSort() only supports arrays of numbers".to_string(),
                            ))
                        }
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
