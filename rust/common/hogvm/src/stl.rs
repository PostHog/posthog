use crate::{
    error::VmError,
    memory::VmHeap,
    values::{HogLiteral, HogValue},
    vm::VmState,
};

// A "native function" is a function that can be called from within the VM. It takes a list
// of arguments, and returns either a value, or null. It's pure (cannot modify the VM state).
pub type NativeFunction = fn(&VmState, Vec<HogValue>) -> Result<HogValue, VmError>;

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
            assert_argc(&args, 1, "")?;
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
            assert_argc(&args, 1, "")?;
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
    ]
}

// TODO - this is slow, because rather than using a string buffer, we're allocating a new string each time
// we recurse
fn to_string(heap: &VmHeap, val: &HogValue, depth: usize) -> Result<String, VmError> {
    if depth > 30 {
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
                .join(",")
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
