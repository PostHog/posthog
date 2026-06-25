//! Canonical Hog value formatting, matching the reference VMs' `printHogValue` /
//! `printHogStringOutput` (see `common/hogvm/typescript/src/stl/print.ts` and
//! `common/hogvm/python/stl/print.py`). This is what `print(...)` emits and is the
//! oracle the parity harness diffs against. Kept separate from `stl::to_string`
//! (which is `toString` semantics) on purpose — the two are subtly different and the
//! parity loop is what reconciles them.

use crate::{
    memory::{HeapReference, VmHeap},
    values::{Callable, HogLiteral, HogValue},
};

const PRINT_RECURSION_LIMIT: usize = 64;

/// Escape a string the way the reference VMs do: wrap in single quotes and escape the
/// clickhouse-style control characters plus the quote and backslash.
pub fn escape_string(value: &str) -> String {
    let mut out = String::with_capacity(value.len() + 2);
    out.push('\'');
    for c in value.chars() {
        match c {
            '\u{08}' => out.push_str("\\b"),
            '\u{0C}' => out.push_str("\\f"),
            '\r' => out.push_str("\\r"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\0' => out.push_str("\\0"),
            '\u{0B}' => out.push_str("\\v"),
            '\\' => out.push_str("\\\\"),
            '\'' => out.push_str("\\'"),
            other => out.push(other),
        }
    }
    out.push('\'');
    out
}

/// Format a value as `print(...)` would. Top-level strings are emitted raw; everything
/// else (including strings nested inside arrays/objects) goes through [`print_hog_value`].
pub fn print_hog_string_output(heap: &VmHeap, value: &HogValue) -> Result<String, crate::VmError> {
    match value.deref(heap)? {
        HogLiteral::String(s) => Ok(s.clone()),
        _ => print_hog_value(heap, value, &mut Vec::new(), 0),
    }
}

/// The recursive canonical printer. `marked` tracks the heap references currently being
/// printed so self-referential containers render as `null` (matching the reference VMs'
/// `marked` set), rather than recursing forever.
pub fn print_hog_value(
    heap: &VmHeap,
    value: &HogValue,
    marked: &mut Vec<HeapReference>,
    depth: usize,
) -> Result<String, crate::VmError> {
    if depth > PRINT_RECURSION_LIMIT {
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

    let result = format_literal(heap, lit, marked, depth);

    if container_ptr.is_some() {
        marked.pop();
    }

    result
}

fn format_literal(
    heap: &VmHeap,
    lit: &HogLiteral,
    marked: &mut Vec<HeapReference>,
    depth: usize,
) -> Result<String, crate::VmError> {
    match lit {
        HogLiteral::Null => Ok("null".to_string()),
        HogLiteral::Boolean(b) => Ok(if *b { "true" } else { "false" }.to_string()),
        HogLiteral::Number(n) => Ok(if n.is_float() {
            n.to_float().to_string()
        } else {
            n.to_integer().to_string()
        }),
        HogLiteral::String(s) => Ok(escape_string(s)),
        HogLiteral::Array(arr) => {
            let mut parts = Vec::with_capacity(arr.len());
            for elem in arr {
                parts.push(print_hog_value(heap, elem, marked, depth + 1)?);
            }
            Ok(format!("[{}]", parts.join(", ")))
        }
        HogLiteral::Object(obj) => {
            let mut parts = Vec::with_capacity(obj.len());
            for (key, val) in obj {
                parts.push(format!(
                    "{}: {}",
                    escape_string(key),
                    print_hog_value(heap, val, marked, depth + 1)?
                ));
            }
            Ok(format!("{{{}}}", parts.join(", ")))
        }
        // The reference VMs print both callables and closures as `fn<name(argCount)>`.
        HogLiteral::Callable(callable) => Ok(print_callable(callable)),
        HogLiteral::Closure(closure) => Ok(print_callable(&closure.callable)),
    }
}

fn print_callable(callable: &Callable) -> String {
    let Callable::Local(local) = callable;
    format!("fn<{}({})>", escape_identifier(&local.name), local.stack_arg_count)
}

/// Identifiers print raw when they look like identifiers, else backtick-escaped — matching
/// the reference `escapeIdentifier`.
fn escape_identifier(identifier: &str) -> String {
    let is_ident = {
        let mut chars = identifier.chars();
        matches!(chars.next(), Some(c) if c.is_ascii_alphabetic() || c == '_' || c == '$')
            && chars.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '$')
    };
    if is_ident && !identifier.is_empty() {
        identifier.to_string()
    } else {
        let mut out = String::with_capacity(identifier.len() + 2);
        out.push('`');
        for c in identifier.chars() {
            match c {
                '\u{08}' => out.push_str("\\b"),
                '\u{0C}' => out.push_str("\\f"),
                '\r' => out.push_str("\\r"),
                '\n' => out.push_str("\\n"),
                '\t' => out.push_str("\\t"),
                '\0' => out.push_str("\\0"),
                '\u{0B}' => out.push_str("\\v"),
                '\\' => out.push_str("\\\\"),
                '`' => out.push_str("\\`"),
                other => out.push(other),
            }
        }
        out.push('`');
        out
    }
}
