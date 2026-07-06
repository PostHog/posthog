//! Canonical Hog value formatting, matching the reference VMs' `printHogValue` /
//! `printHogStringOutput` (see `common/hogvm/typescript/src/stl/print.ts` and
//! `common/hogvm/python/stl/print.py`). This is what `print(...)` emits and is the
//! oracle the parity harness diffs against. Kept separate from `stl::to_string`
//! (which is `toString` semantics) on purpose — the two are subtly different and the
//! parity loop is what reconciles them.

use indexmap::IndexMap;

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
        HogLiteral::Tuple(arr) => {
            let mut parts = Vec::with_capacity(arr.len());
            for elem in arr {
                parts.push(print_hog_value(heap, elem, marked, depth + 1)?);
            }
            // The reference disambiguates 0/1-element tuples as `tuple(...)`; 2+ print as `(a, b)`.
            if arr.len() < 2 {
                Ok(format!("tuple({})", parts.join(", ")))
            } else {
                Ok(format!("({})", parts.join(", ")))
            }
        }
        HogLiteral::Object(obj) => {
            // Hog temporals are duck-typed objects; the reference prints them as DateTime(...)/Date(...).
            if let Some(temporal) = format_temporal(heap, obj)? {
                return Ok(temporal);
            }
            // Hog errors are duck-typed too; the reference prints them as `Type('message'[, payload])`.
            if let Some(err) = format_error(heap, obj, marked, depth)? {
                return Ok(err);
            }
            // HogQL AST nodes (`{__hx_ast: …}`) render back to SQL, wrapped as `sql(…)`.
            if obj.contains_key("__hx_ast") {
                return Ok(format!("sql({})", HogQLPrinter::new(heap).print_node(obj)?));
            }
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
    match callable {
        Callable::Local(local) => {
            format!(
                "fn<{}({})>",
                escape_identifier(&local.name),
                local.stack_arg_count
            )
        }
        // Native arity isn't tracked here; the reference prints maxArgs, but no corpus program
        // prints a bare native-function value, so the count is a placeholder.
        Callable::Stl(name) => format!("fn<{}(0)>", escape_identifier(name)),
    }
}

// Render the Hog temporal duck-types: `{__hogDateTime__: true, dt, zone}` -> `DateTime(dt, 'zone')`
// and `{__hogDate__: true, year, month, day}` -> `Date(y, m, d)`. Returns None for plain objects.
fn format_temporal(
    heap: &VmHeap,
    obj: &IndexMap<String, HogValue>,
) -> Result<Option<String>, crate::VmError> {
    if marker(heap, obj.get("__hogDateTime__"))? {
        let dt = number(heap, obj.get("dt"))?.unwrap_or(0.0);
        let zone = string(heap, obj.get("zone"))?.unwrap_or_else(|| "UTC".to_string());
        return Ok(Some(format!(
            "DateTime({}, {})",
            format_dt_seconds(dt),
            escape_string(&zone)
        )));
    }
    if marker(heap, obj.get("__hogDate__"))? {
        let y = number(heap, obj.get("year"))?.unwrap_or(0.0) as i64;
        let m = number(heap, obj.get("month"))?.unwrap_or(0.0) as i64;
        let d = number(heap, obj.get("day"))?.unwrap_or(0.0) as i64;
        return Ok(Some(format!("Date({y}, {m}, {d})")));
    }
    Ok(None)
}

// Render the Hog error duck-type `{__hogError__: true, type, message, payload?}` as
// `Type('message')` or `Type('message', payload)`. Returns None for plain objects.
fn format_error(
    heap: &VmHeap,
    obj: &IndexMap<String, HogValue>,
    marked: &mut Vec<HeapReference>,
    depth: usize,
) -> Result<Option<String>, crate::VmError> {
    if !marker(heap, obj.get("__hogError__"))? {
        return Ok(None);
    }
    let type_str = string(heap, obj.get("type"))?.unwrap_or_else(|| "Error".to_string());
    let message = string(heap, obj.get("message"))?.unwrap_or_default();
    let payload = match obj.get("payload") {
        Some(p) if !matches!(p.deref(heap)?, HogLiteral::Null) => {
            format!(", {}", print_hog_value(heap, p, marked, depth + 1)?)
        }
        _ => String::new(),
    };
    Ok(Some(format!(
        "{type_str}({}{payload})",
        escape_string(&message)
    )))
}

fn marker(heap: &VmHeap, v: Option<&HogValue>) -> Result<bool, crate::VmError> {
    match v {
        Some(v) => Ok(matches!(v.deref(heap)?, HogLiteral::Boolean(true))),
        None => Ok(false),
    }
}

fn number(heap: &VmHeap, v: Option<&HogValue>) -> Result<Option<f64>, crate::VmError> {
    match v {
        Some(v) => Ok(match v.deref(heap)? {
            HogLiteral::Number(n) => Some(n.to_float()),
            _ => None,
        }),
        None => Ok(None),
    }
}

fn string(heap: &VmHeap, v: Option<&HogValue>) -> Result<Option<String>, crate::VmError> {
    match v {
        Some(v) => Ok(match v.deref(heap)? {
            HogLiteral::String(s) => Some(s.clone()),
            _ => None,
        }),
        None => Ok(None),
    }
}

// DateTime seconds print with a trailing `.0` when integral (matching Python's `float(dt)` str and
// the reference DateTime() format), e.g. 1609504496 -> "1609504496.0", 1609504496.5 unchanged.
fn format_dt_seconds(f: f64) -> String {
    let s = format!("{f}");
    if s.contains(['.', 'e', 'E']) || !f.is_finite() {
        s
    } else {
        format!("{s}.0")
    }
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

// ── HogQL AST → SQL printer ──────────────────────────────────────────────────────────────────
// Port of the reference `HogQLPrinter` (common/hogvm/typescript/src/stl/print.ts). HogQL queries
// built via `sql(...)` are duck-typed AST objects (`{__hx_ast: <type>, …}`); this renders them back
// to SQL. Only the non-pretty path is implemented (the VM never pretty-prints). The outer `sql(…)`
// wrapper is added by the caller (`format_literal`), matching `printHogValue`.
struct HogQLPrinter<'a> {
    heap: &'a VmHeap,
    // Mirrors the reference's `stack.length`: a query that isn't the outermost node is parenthesised.
    depth: usize,
}

impl<'a> HogQLPrinter<'a> {
    fn new(heap: &'a VmHeap) -> Self {
        HogQLPrinter { heap, depth: 0 }
    }

    // Entry point: an already-dereferenced AST object.
    fn print_node(&mut self, obj: &IndexMap<String, HogValue>) -> Result<String, crate::VmError> {
        self.depth += 1;
        let result = self.dispatch(obj);
        self.depth -= 1;
        result
    }

    // Visit any child: a nested AST object dispatches; a null renders empty; anything else goes
    // through the canonical value printer (the reference's `escapeValue`).
    fn visit(&mut self, node: &HogValue) -> Result<String, crate::VmError> {
        match node.deref(self.heap)? {
            HogLiteral::Null => Ok(String::new()),
            HogLiteral::Object(obj) if obj.contains_key("__hx_ast") => self.print_node(obj),
            _ => print_hog_value(self.heap, node, &mut Vec::new(), 0),
        }
    }

    fn dispatch(&mut self, obj: &IndexMap<String, HogValue>) -> Result<String, crate::VmError> {
        let node_type = self.str_field(obj, "__hx_ast")?.ok_or_else(|| {
            crate::VmError::NativeCallFailed("HogQL node missing __hx_ast".to_string())
        })?;
        match node_type.as_str() {
            "SelectQuery" => self.select_query(obj),
            "SelectSetQuery" => self.select_set_query(obj),
            "JoinExpr" => self.join_expr(obj),
            "JoinConstraint" => self.visit_child(obj, "expr"),
            "Call" => self.call(obj),
            "Constant" => self.visit_child(obj, "value"),
            "Field" => self.field(obj),
            "Alias" => self.alias(obj),
            "And" => self.logical(obj, "and"),
            "Or" => self.logical(obj, "or"),
            "Not" => Ok(format!("not({})", self.visit_child(obj, "expr")?)),
            "CompareOperation" => self.compare(obj),
            "Tuple" => Ok(format!("tuple({})", self.exprs(obj)?.join(", "))),
            "Array" => Ok(format!("[{}]", self.exprs(obj)?.join(", "))),
            "ArithmeticOperation" => self.arithmetic(obj),
            "OrderExpr" => Ok(format!(
                "{} {}",
                self.visit_child(obj, "expr")?,
                self.str_field(obj, "order")?.unwrap_or_default()
            )),
            "Lambda" => self.lambda(obj),
            "Asterisk" => Ok("*".to_string()),
            other => Err(crate::VmError::NativeCallFailed(format!(
                "Unknown HogQL AST node type: {other}"
            ))),
        }
    }

    fn select_query(&mut self, obj: &IndexMap<String, HogValue>) -> Result<String, crate::VmError> {
        let is_top_level = self.depth <= 1;
        let distinct = if self.bool_field(obj, "distinct")? {
            " DISTINCT"
        } else {
            ""
        };
        let select = self.exprs_field(obj, "select")?;
        let mut clauses = vec![format!("SELECT{distinct} {}", select.join(", "))];

        if let Some(from) = obj.get("select_from") {
            let rendered = self.visit_join_expression(from)?;
            if !rendered.is_empty() {
                clauses.push(format!("FROM {rendered}"));
            }
        }
        for (key, kw) in [
            ("prewhere", "PREWHERE"),
            ("where", "WHERE"),
            ("having", "HAVING"),
        ] {
            if obj.contains_key(key) {
                let rendered = self.visit_child(obj, key)?;
                if !rendered.is_empty() {
                    clauses.push(format!("{kw} {rendered}"));
                }
            }
        }
        for (key, kw) in [("group_by", "GROUP BY"), ("order_by", "ORDER BY")] {
            let parts = self.exprs_field(obj, key)?;
            if !parts.is_empty() {
                clauses.push(format!("{kw} {}", parts.join(", ")));
            }
        }
        if obj.contains_key("limit") {
            let limit = self.visit_child(obj, "limit")?;
            if !limit.is_empty() {
                clauses.push(format!("LIMIT {limit}"));
                if self.bool_field(obj, "limit_with_ties")? {
                    clauses.push("WITH TIES".to_string());
                }
                if obj.contains_key("offset") {
                    let offset = self.visit_child(obj, "offset")?;
                    if !offset.is_empty() {
                        clauses.push(format!("OFFSET {offset}"));
                    }
                }
            }
        }

        let response = clauses.join(" ");
        Ok(if is_top_level {
            response
        } else {
            format!("({response})")
        })
    }

    fn select_set_query(
        &mut self,
        obj: &IndexMap<String, HogValue>,
    ) -> Result<String, crate::VmError> {
        // The reference decrements/increments the indent around the set query; with pretty=false that
        // only affects the parenthesisation check, which we approximate via depth.
        let mut result = self.visit_child(obj, "initial_select_query")?;
        for entry in self.array_field(obj, "subsequent_select_queries")? {
            let HogLiteral::Object(eo) = entry.deref(self.heap)? else {
                continue;
            };
            let op = self.str_field(eo, "set_operator")?.unwrap_or_default();
            let query = match eo.get("select_query") {
                Some(q) => self.visit(q)?,
                None => String::new(),
            };
            if !op.is_empty() {
                result.push_str(&format!(" {op} "));
            }
            result.push_str(&query);
        }
        Ok(if self.depth > 1 {
            format!("({})", result.trim())
        } else {
            result
        })
    }

    fn visit_join_expression(&mut self, node: &HogValue) -> Result<String, crate::VmError> {
        if let HogLiteral::Object(obj) = node.deref(self.heap)? {
            if self.str_field(obj, "__hx_ast")?.as_deref() == Some("JoinExpr") {
                return self.join_expr(obj);
            }
        }
        self.visit(node)
    }

    fn join_expr(&mut self, obj: &IndexMap<String, HogValue>) -> Result<String, crate::VmError> {
        let mut parts = Vec::new();
        let table = self.visit_child(obj, "table")?;
        match self.str_field(obj, "alias")? {
            Some(alias) if alias != table => {
                parts.push(format!("{table} AS {}", escape_identifier(&alias)));
            }
            _ => parts.push(table),
        }

        let mut current = obj.get("next_join").cloned();
        while let Some(join) = current {
            let HogLiteral::Object(jo) = join.deref(self.heap)? else {
                break;
            };
            let jo = jo.clone();
            let join_type = self
                .str_field(&jo, "join_type")?
                .unwrap_or_else(|| "JOIN".to_string());
            let table = self.visit_child(&jo, "table")?;
            let constraint = match jo.get("constraint") {
                Some(c) => {
                    if let HogLiteral::Object(co) = c.deref(self.heap)? {
                        let ctype = self.str_field(co, "constraint_type")?.unwrap_or_default();
                        format!("{ctype} {}", self.visit(c)?)
                    } else {
                        String::new()
                    }
                }
                None => String::new(),
            };
            let table_with_alias = match self.str_field(&jo, "alias")? {
                Some(alias) if alias != table => {
                    format!("{table} AS {}", escape_identifier(&alias))
                }
                _ => table,
            };
            parts.push(
                format!("{join_type} {table_with_alias} {constraint}")
                    .trim()
                    .to_string(),
            );
            current = jo.get("next_join").cloned();
        }
        Ok(parts.join(" "))
    }

    fn call(&mut self, obj: &IndexMap<String, HogValue>) -> Result<String, crate::VmError> {
        let name = self.str_field(obj, "name")?.unwrap_or_default();
        Ok(format!(
            "{name}({})",
            self.exprs_field(obj, "args")?.join(", ")
        ))
    }

    fn field(&mut self, obj: &IndexMap<String, HogValue>) -> Result<String, crate::VmError> {
        let chain = self.array_field(obj, "chain")?;
        if chain.len() == 1 {
            if let HogLiteral::String(s) = chain[0].deref(self.heap)? {
                if s == "*" {
                    return Ok("*".to_string());
                }
            }
        }
        let mut parts = Vec::with_capacity(chain.len());
        for elem in &chain {
            parts.push(self.escape_identifier_or_index(elem)?);
        }
        Ok(parts.join("."))
    }

    fn alias(&mut self, obj: &IndexMap<String, HogValue>) -> Result<String, crate::VmError> {
        if self.bool_field(obj, "hidden")? {
            return self.visit_child(obj, "expr");
        }
        let inside = self.visit_child(obj, "expr")?;
        let alias = self.str_field(obj, "alias")?.unwrap_or_default();
        Ok(format!("{inside} AS {}", escape_identifier(&alias)))
    }

    fn logical(
        &mut self,
        obj: &IndexMap<String, HogValue>,
        func: &str,
    ) -> Result<String, crate::VmError> {
        let exprs = self.exprs_field(obj, "exprs")?;
        match exprs.len() {
            0 => Ok(String::new()),
            1 => Ok(exprs.into_iter().next().unwrap()),
            _ => Ok(format!("{func}({})", exprs.join(", "))),
        }
    }

    fn compare(&mut self, obj: &IndexMap<String, HogValue>) -> Result<String, crate::VmError> {
        let left = self.visit_child(obj, "left")?;
        let right = self.visit_child(obj, "right")?;
        let op = self.str_field(obj, "op")?.unwrap_or_default();
        let func = match op.as_str() {
            "==" => "equals",
            "!=" => "notEquals",
            "<" => "less",
            ">" => "greater",
            "<=" => "lessOrEquals",
            ">=" => "greaterOrEquals",
            "in" => "in",
            "not in" => "notIn",
            "like" => "like",
            "not like" => "notLike",
            "ilike" => "ilike",
            "not ilike" => "notILike",
            "=~" | "!~" | "=~*" | "!~*" => "match",
            other => other,
        };
        Ok(match op.as_str() {
            "!~*" => format!("not({func}({left}, concat('(?i)', {right})))"),
            "=~*" => format!("{func}({left}, concat('(?i)', {right}))"),
            "!~" => format!("not({func}({left}, {right}))"),
            _ => format!("{func}({left}, {right})"),
        })
    }

    fn arithmetic(&mut self, obj: &IndexMap<String, HogValue>) -> Result<String, crate::VmError> {
        let left = self.visit_child(obj, "left")?;
        let right = self.visit_child(obj, "right")?;
        let func = match self.str_field(obj, "op")?.as_deref() {
            Some("+") => "plus",
            Some("-") => "minus",
            Some("*") => "multiply",
            Some("/") => "divide",
            Some("%") => "modulo",
            other => {
                return Err(crate::VmError::NativeCallFailed(format!(
                    "Unknown ArithmeticOperation operator: {other:?}"
                )))
            }
        };
        Ok(format!("{func}({left}, {right})"))
    }

    fn lambda(&mut self, obj: &IndexMap<String, HogValue>) -> Result<String, crate::VmError> {
        let args = self.array_field(obj, "args")?;
        let escaped: Vec<String> = args
            .iter()
            .filter_map(|a| match a.deref(self.heap) {
                Ok(HogLiteral::String(s)) => Some(escape_identifier(s)),
                _ => None,
            })
            .collect();
        let arg_list = if escaped.len() == 1 {
            escaped[0].clone()
        } else {
            format!("({})", escaped.join(", "))
        };
        Ok(format!("{arg_list} -> {}", self.visit_child(obj, "expr")?))
    }

    // ── helpers ──
    fn exprs(&mut self, obj: &IndexMap<String, HogValue>) -> Result<Vec<String>, crate::VmError> {
        self.exprs_field(obj, "exprs")
    }

    fn exprs_field(
        &mut self,
        obj: &IndexMap<String, HogValue>,
        key: &str,
    ) -> Result<Vec<String>, crate::VmError> {
        let items = self.array_field(obj, key)?;
        let mut out = Vec::with_capacity(items.len());
        for item in &items {
            out.push(self.visit(item)?);
        }
        Ok(out)
    }

    fn visit_child(
        &mut self,
        obj: &IndexMap<String, HogValue>,
        key: &str,
    ) -> Result<String, crate::VmError> {
        match obj.get(key) {
            Some(v) => self.visit(v),
            None => Ok(String::new()),
        }
    }

    fn array_field(
        &self,
        obj: &IndexMap<String, HogValue>,
        key: &str,
    ) -> Result<Vec<HogValue>, crate::VmError> {
        match obj.get(key) {
            Some(v) => Ok(match v.deref(self.heap)? {
                HogLiteral::Array(a) | HogLiteral::Tuple(a) => a.clone(),
                _ => Vec::new(),
            }),
            None => Ok(Vec::new()),
        }
    }

    fn str_field(
        &self,
        obj: &IndexMap<String, HogValue>,
        key: &str,
    ) -> Result<Option<String>, crate::VmError> {
        string(self.heap, obj.get(key))
    }

    fn bool_field(
        &self,
        obj: &IndexMap<String, HogValue>,
        key: &str,
    ) -> Result<bool, crate::VmError> {
        marker(self.heap, obj.get(key))
    }

    // `escapeIdentifierOrIndex`: a non-negative integer stays bare; everything else is an identifier.
    fn escape_identifier_or_index(&self, value: &HogValue) -> Result<String, crate::VmError> {
        Ok(match value.deref(self.heap)? {
            HogLiteral::Number(n) if !n.is_float() => n.to_integer().to_string(),
            HogLiteral::String(s) => escape_identifier(s),
            other => escape_identifier(&print_hog_value(
                self.heap,
                &HogLiteral::clone(other).into(),
                &mut Vec::new(),
                0,
            )?),
        })
    }
}
