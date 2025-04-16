use std::collections::HashMap;

use crate::{
    error::VmError,
    memory::VmHeap,
    values::{HogLiteral, HogValue, Num},
    vm::HogVM,
};

pub const TO_STRING_RECURSION_LIMIT: usize = 32;

// A "native function" is a function that can be called from within the VM. It takes a list
// of arguments, and returns either a value, or null. It's pure (cannot modify the VM state).
pub type NativeFunction = fn(&HogVM, Vec<HogValue>) -> Result<HogValue, VmError>;

pub fn stl_map() -> HashMap<String, NativeFunction> {
    stl().iter().map(|(a, b)| (a.to_string(), *b)).collect()
}

pub const fn stl() -> &'static [(&'static str, NativeFunction)] {
    &[
        ("toString", |vm, args| {
            // Can't just use a ToString trait implementation, because ToString requires heap access to chase
            // references in arrays and dicts
            assert_argc(&args, 1, "toString")?;
            to_string(&vm.heap, &args[0], 0).map(|s| HogLiteral::String(s).into())
        }),
        ("typeof", |vm, args| {
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
                HogLiteral::Callable(_) => Ok(HogLiteral::String("function".to_string()).into()),
                HogLiteral::Closure(_) => Ok(HogLiteral::String("function".to_string()).into()),
                HogLiteral::Null => Ok(HogLiteral::String("null".to_string()).into()),
            }
        }),
        ("values", |vm, args| {
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
        ("length", |vm, args| {
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
        ("arrayPushBack", |vm, args| {
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
        ("arrayPushFront", |vm, args| {
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
        ("arrayPopBack", |vm, args| {
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
        ("arrayPopFront", |vm, args| {
            assert_argc(&args, 1, "arrayPopFront")?;
            let array = args[0].deref(&vm.heap)?;
            match array {
                HogLiteral::Array(arr) => {
                    let mut arr = arr.clone();
                    // TODO - lol, lmao. This is silly, google the right function to actually use
                    arr.reverse();
                    arr.pop();
                    arr.reverse();
                    Ok(HogLiteral::Array(arr).into())
                }
                _ => Err(VmError::NativeCallFailed(
                    "arrayPopFront() only supports arrays".to_string(),
                )),
            }
        }),
        ("arraySort", |vm, args| {
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
                        Ok(HogLiteral::Array(vals.into_iter().map(|v| v.into()).collect()).into())
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
        ("arrayReverse", |vm, args| {
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
        ("arrayReverseSort", |vm, args| {
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
                        Ok(HogLiteral::Array(vals.into_iter().map(|v| v.into()).collect()).into())
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
        ("arrayStringConcat", |vm, args| {
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
        ("has", |vm, args| {
            assert_argc(&args, 2, "has")?;
            let haystack = &args[0];
            let needle = &args[1];
            haystack.contains(needle, &vm.heap).map(|res| res.into())
        }),
        ("indexOf", |vm, args| {
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
    ]
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
