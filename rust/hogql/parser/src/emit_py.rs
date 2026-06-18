//! `PyEmitter` — `Emitter` impl that constructs `posthog.hogql.ast` dataclasses directly during parsing, bypassing the `serde_json::Value` intermediate tree.
//!
//! Used by the `parse_*_py` PyO3 entry points in [`crate::lib`]. The `parse_*_json` entry points stay on `JsonEmitter` for the future WASM build (no CPython link) and for tests that compare on JSON shape.
//!
//! Construction strategy:
//!  - All `posthog.hogql.ast` classes are looked up *once* at [`PyEmitter::new`] and stored as `Bound<'py, PyAny>` references — a `getattr(ast_module, "Constant")` per node would dominate runtime over the json round-trip we're trying to beat.
//!  - Each emitter method builds a `PyDict` of kwargs and calls `class.call((), Some(&kwargs))`. The constructed object is wrapped in [`PyAst`] (which also tracks `positions_locked` for idempotent `with_pos` / `no_pos` semantics).
//!
//! Position handling:
//!  - `position()` returns a plain `PyInt` (the offset). Lines/columns aren't used by the Python side — `AST.start` / `AST.end` are `Optional[int]`. Mirrors the post-walk extraction done by `pyobject::Converter` on the `*_json` path.
//!  - `with_pos` / `no_pos` / `replace_pos` mirror cpp's idempotent semantics:
//!    * `with_pos(v, start, end)`: set `v.start = start, v.end = end` only if `v.start` is currently `None` AND `positions_locked` isn't set.
//!    * `no_pos(v)`: marks the wrapper with `positions_locked = true`. The underlying object's `start` / `end` stay at dataclass defaults (`None`).
//!    * `replace_pos(v, start, end)`: unconditionally writes (subject to `positions_locked`). Used for outer-span overrides.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};
use std::borrow::Cow;
use std::collections::HashMap;

use crate::emit::Emitter;

// ============================================================================
// PyAst — AST value wrapper.
// ============================================================================

/// Wrapper around a Python AST object plus the out-of-band `positions_locked` flag. The underlying `posthog.hogql.ast.*` dataclasses use `slots=True` so they can't carry an arbitrary "positions locked" attribute; the wrapper carries it instead.
///
/// `obj` is unbound (`Py<PyAny>`, no GIL lifetime) so the wrapper can live alongside `Parser` without dragging a 'py through the parser's type signatures. Re-attach via `obj.bind(py)` inside emitter methods where `py: Python<'_>` is available.
pub struct PyAst {
    pub obj: Py<PyAny>,
    pub positions_locked: bool,
    /// Side-channel for parser-internal `__rust_*` sentinel keys — the JSON path stores these on the underlying `Value::Object` Map, but slots=True dataclasses reject setattr for unknown attrs, so PyEmitter routes them here.
    /// `Option<Box<HashMap>>` over inline HashMap keeps PyAst at 24 bytes instead of ~64 (HashMap is ~48 bytes inline) — >99% of nodes never carry a sentinel, so the Box is null. Clippy's `box_collection` lint flags this as wasteful (HashMap is already heap-allocated) but it doesn't account for the niche-optimized `Option<Box>` size advantage at the PyAst struct level, where we allocate millions per parse. Lazy-init via `sentinels_mut()`.
    #[allow(clippy::box_collection)]
    pub rust_sentinels: Option<Box<HashMap<String, Py<PyAny>>>>,
}

impl PyAst {
    /// Lazy accessor for the sentinel map — allocates the inner box on first access. Used by the rare `set_field` site routing a `__rust_*` sentinel.
    fn sentinels_mut(&mut self) -> &mut HashMap<String, Py<PyAny>> {
        self.rust_sentinels
            .get_or_insert_with(|| Box::new(HashMap::new()))
    }
}

impl Clone for PyAst {
    fn clone(&self) -> Self {
        // `Py<T>::clone_ref` needs the GIL; the parse loop always holds it via the outer #[pyfunction], so `with_gil` is a free re-borrow of the already-acquired token.
        Python::with_gil(|py| Self {
            obj: self.obj.clone_ref(py),
            positions_locked: self.positions_locked,
            // Skip the allocation entirely when the source had no sentinels (the common case).
            rust_sentinels: self.rust_sentinels.as_ref().map(|m| {
                Box::new(
                    m.iter()
                        .map(|(k, v)| (k.clone(), v.clone_ref(py)))
                        .collect(),
                )
            }),
        })
    }
}

// ============================================================================
// PyEmitter — caches AST class references and constructs nodes via class.call.
// ============================================================================

/// Constructs `posthog.hogql.ast` instances directly. Holds the GIL token + cached class references for the full duration of one parse.
///
/// `Clone` is required by the Emitter trait bound — the parser clones the emitter into a sub-`Parser` for `f'{…}'` template blocks. Each `Bound<'py, _>` clone is just a refcount bump, so cloning the whole struct is ~60 refcount bumps — cheap compared to a parse round.
#[derive(Clone)]
pub struct PyEmitter<'py> {
    py: Python<'py>,
    // ===== Expression node classes (28) =====
    cls_constant: Bound<'py, PyAny>,
    cls_field: Bound<'py, PyAny>,
    cls_arith_op: Bound<'py, PyAny>,
    cls_compare_op: Bound<'py, PyAny>,
    cls_is_distinct_from: Bound<'py, PyAny>,
    cls_between_expr: Bound<'py, PyAny>,
    cls_not: Bound<'py, PyAny>,
    cls_and: Bound<'py, PyAny>,
    cls_or: Bound<'py, PyAny>,
    cls_tuple: Bound<'py, PyAny>,
    cls_array: Bound<'py, PyAny>,
    cls_array_access: Bound<'py, PyAny>,
    cls_tuple_access: Bound<'py, PyAny>,
    cls_alias: Bound<'py, PyAny>,
    cls_call: Bound<'py, PyAny>,
    cls_expr_call: Bound<'py, PyAny>,
    cls_lambda: Bound<'py, PyAny>,
    cls_type_cast: Bound<'py, PyAny>,
    cls_try_cast: Bound<'py, PyAny>,
    cls_array_slice: Bound<'py, PyAny>,
    cls_dict: Bound<'py, PyAny>,
    cls_placeholder: Bound<'py, PyAny>,
    cls_named_argument: Bound<'py, PyAny>,
    cls_order_expr: Bound<'py, PyAny>,
    cls_columns_expr: Bound<'py, PyAny>,
    cls_spread_expr: Bound<'py, PyAny>,
    cls_positional_ref: Bound<'py, PyAny>,
    // ===== Statement / program classes (13) =====
    cls_program: Bound<'py, PyAny>,
    cls_block: Bound<'py, PyAny>,
    cls_expr_statement: Bound<'py, PyAny>,
    cls_if_statement: Bound<'py, PyAny>,
    cls_while_statement: Bound<'py, PyAny>,
    cls_for_in_statement: Bound<'py, PyAny>,
    cls_for_statement: Bound<'py, PyAny>,
    cls_function: Bound<'py, PyAny>,
    cls_variable_assignment: Bound<'py, PyAny>,
    cls_return_statement: Bound<'py, PyAny>,
    cls_try_catch_statement: Bound<'py, PyAny>,
    cls_throw_statement: Bound<'py, PyAny>,
    cls_variable_declaration: Bound<'py, PyAny>,
    // ===== Query / clause classes =====
    cls_cte: Bound<'py, PyAny>,
    cls_join_constraint: Bound<'py, PyAny>,
    cls_values_query: Bound<'py, PyAny>,
    cls_pivot_column: Bound<'py, PyAny>,
    cls_unpivot_column: Bound<'py, PyAny>,
    cls_grouping_set: Bound<'py, PyAny>,
    cls_hogqlx_tag: Bound<'py, PyAny>,
    cls_hogqlx_attribute: Bound<'py, PyAny>,
    cls_window_frame_expr: Bound<'py, PyAny>,
    cls_select_set_query: Bound<'py, PyAny>,
    cls_select_query: Bound<'py, PyAny>,
    cls_select_set_node: Bound<'py, PyAny>,
    cls_sample_expr: Bound<'py, PyAny>,
    cls_ratio_expr: Bound<'py, PyAny>,
    cls_pivot_expr: Bound<'py, PyAny>,
    cls_unpivot_expr: Bound<'py, PyAny>,
    cls_join_expr: Bound<'py, PyAny>,
    cls_window_function: Bound<'py, PyAny>,
    cls_with_fill_expr: Bound<'py, PyAny>,
    cls_window_expr: Bound<'py, PyAny>,
    cls_interpolate_expr: Bound<'py, PyAny>,
    cls_limit_by_expr: Bound<'py, PyAny>,
    /// Python builtin `int` class — used by `constant_number_string` for arbitrary-precision integer literals (i64-wider hex/decimal). Cached once instead of `py.eval_bound("int", ...)` per call.
    cls_int: Bound<'py, PyAny>,
    // ===== Op enum members (pre-resolved at construction) =====
    // Previous impl did `cls.get_item(op)` per arith/compare call — a PyDict lookup against the StrEnum class. Caching saves millions of lookups across the factory suite; each entry is one refcount-bumped `Bound`.
    arith_op_add: Bound<'py, PyAny>,
    arith_op_sub: Bound<'py, PyAny>,
    arith_op_mult: Bound<'py, PyAny>,
    arith_op_div: Bound<'py, PyAny>,
    arith_op_mod: Bound<'py, PyAny>,
    compare_op_eq: Bound<'py, PyAny>,
    compare_op_not_eq: Bound<'py, PyAny>,
    compare_op_gt: Bound<'py, PyAny>,
    compare_op_gt_eq: Bound<'py, PyAny>,
    compare_op_lt: Bound<'py, PyAny>,
    compare_op_lt_eq: Bound<'py, PyAny>,
    compare_op_like: Bound<'py, PyAny>,
    compare_op_ilike: Bound<'py, PyAny>,
    compare_op_not_like: Bound<'py, PyAny>,
    compare_op_not_ilike: Bound<'py, PyAny>,
    compare_op_in: Bound<'py, PyAny>,
    compare_op_global_in: Bound<'py, PyAny>,
    compare_op_not_in: Bound<'py, PyAny>,
    compare_op_global_not_in: Bound<'py, PyAny>,
    compare_op_in_cohort: Bound<'py, PyAny>,
    compare_op_not_in_cohort: Bound<'py, PyAny>,
    compare_op_regex: Bound<'py, PyAny>,
    compare_op_iregex: Bound<'py, PyAny>,
    compare_op_not_regex: Bound<'py, PyAny>,
    compare_op_not_iregex: Bound<'py, PyAny>,
}

impl<'py> PyEmitter<'py> {
    pub fn new(py: Python<'py>) -> PyResult<Self> {
        let ast_module = py.import_bound("posthog.hogql.ast")?;
        // Bind the StrEnum classes once for readability — not stored on the struct since the enum classes themselves are never read again after member extraction.
        let arith_enum = ast_module.getattr("ArithmeticOperationOp")?;
        let compare_enum = ast_module.getattr("CompareOperationOp")?;
        Ok(Self {
            cls_constant: ast_module.getattr("Constant")?,
            cls_field: ast_module.getattr("Field")?,
            cls_arith_op: ast_module.getattr("ArithmeticOperation")?,
            cls_compare_op: ast_module.getattr("CompareOperation")?,
            cls_is_distinct_from: ast_module.getattr("IsDistinctFrom")?,
            cls_between_expr: ast_module.getattr("BetweenExpr")?,
            cls_not: ast_module.getattr("Not")?,
            cls_and: ast_module.getattr("And")?,
            cls_or: ast_module.getattr("Or")?,
            cls_tuple: ast_module.getattr("Tuple")?,
            cls_array: ast_module.getattr("Array")?,
            cls_array_access: ast_module.getattr("ArrayAccess")?,
            cls_tuple_access: ast_module.getattr("TupleAccess")?,
            cls_alias: ast_module.getattr("Alias")?,
            cls_call: ast_module.getattr("Call")?,
            cls_expr_call: ast_module.getattr("ExprCall")?,
            cls_lambda: ast_module.getattr("Lambda")?,
            cls_type_cast: ast_module.getattr("TypeCast")?,
            cls_try_cast: ast_module.getattr("TryCast")?,
            cls_array_slice: ast_module.getattr("ArraySlice")?,
            cls_dict: ast_module.getattr("Dict")?,
            cls_placeholder: ast_module.getattr("Placeholder")?,
            cls_named_argument: ast_module.getattr("NamedArgument")?,
            cls_order_expr: ast_module.getattr("OrderExpr")?,
            cls_columns_expr: ast_module.getattr("ColumnsExpr")?,
            cls_spread_expr: ast_module.getattr("SpreadExpr")?,
            cls_positional_ref: ast_module.getattr("PositionalRef")?,
            cls_program: ast_module.getattr("Program")?,
            cls_block: ast_module.getattr("Block")?,
            cls_expr_statement: ast_module.getattr("ExprStatement")?,
            cls_if_statement: ast_module.getattr("IfStatement")?,
            cls_while_statement: ast_module.getattr("WhileStatement")?,
            cls_for_in_statement: ast_module.getattr("ForInStatement")?,
            cls_for_statement: ast_module.getattr("ForStatement")?,
            cls_function: ast_module.getattr("Function")?,
            cls_variable_assignment: ast_module.getattr("VariableAssignment")?,
            cls_return_statement: ast_module.getattr("ReturnStatement")?,
            cls_try_catch_statement: ast_module.getattr("TryCatchStatement")?,
            cls_throw_statement: ast_module.getattr("ThrowStatement")?,
            cls_variable_declaration: ast_module.getattr("VariableDeclaration")?,
            cls_cte: ast_module.getattr("CTE")?,
            cls_join_constraint: ast_module.getattr("JoinConstraint")?,
            cls_values_query: ast_module.getattr("ValuesQuery")?,
            cls_pivot_column: ast_module.getattr("PivotColumn")?,
            cls_unpivot_column: ast_module.getattr("UnpivotColumn")?,
            cls_grouping_set: ast_module.getattr("GroupingSet")?,
            cls_hogqlx_tag: ast_module.getattr("HogQLXTag")?,
            cls_hogqlx_attribute: ast_module.getattr("HogQLXAttribute")?,
            cls_window_frame_expr: ast_module.getattr("WindowFrameExpr")?,
            cls_select_set_query: ast_module.getattr("SelectSetQuery")?,
            cls_select_query: ast_module.getattr("SelectQuery")?,
            cls_select_set_node: ast_module.getattr("SelectSetNode")?,
            cls_sample_expr: ast_module.getattr("SampleExpr")?,
            cls_ratio_expr: ast_module.getattr("RatioExpr")?,
            cls_pivot_expr: ast_module.getattr("PivotExpr")?,
            cls_unpivot_expr: ast_module.getattr("UnpivotExpr")?,
            cls_join_expr: ast_module.getattr("JoinExpr")?,
            cls_window_function: ast_module.getattr("WindowFunction")?,
            cls_with_fill_expr: ast_module.getattr("WithFillExpr")?,
            cls_window_expr: ast_module.getattr("WindowExpr")?,
            cls_interpolate_expr: ast_module.getattr("InterpolateExpr")?,
            cls_limit_by_expr: ast_module.getattr("LimitByExpr")?,
            cls_int: py.import_bound("builtins")?.getattr("int")?,
            // Pre-resolve enum members by NAME — StrEnum classes are subscriptable by member-name (`cls["Add"]`), not by value (`cls["+"]` fails).
            arith_op_add: arith_enum.get_item("Add")?,
            arith_op_sub: arith_enum.get_item("Sub")?,
            arith_op_mult: arith_enum.get_item("Mult")?,
            arith_op_div: arith_enum.get_item("Div")?,
            arith_op_mod: arith_enum.get_item("Mod")?,
            compare_op_eq: compare_enum.get_item("Eq")?,
            compare_op_not_eq: compare_enum.get_item("NotEq")?,
            compare_op_gt: compare_enum.get_item("Gt")?,
            compare_op_gt_eq: compare_enum.get_item("GtEq")?,
            compare_op_lt: compare_enum.get_item("Lt")?,
            compare_op_lt_eq: compare_enum.get_item("LtEq")?,
            compare_op_like: compare_enum.get_item("Like")?,
            compare_op_ilike: compare_enum.get_item("ILike")?,
            compare_op_not_like: compare_enum.get_item("NotLike")?,
            compare_op_not_ilike: compare_enum.get_item("NotILike")?,
            compare_op_in: compare_enum.get_item("In")?,
            compare_op_global_in: compare_enum.get_item("GlobalIn")?,
            compare_op_not_in: compare_enum.get_item("NotIn")?,
            compare_op_global_not_in: compare_enum.get_item("GlobalNotIn")?,
            compare_op_in_cohort: compare_enum.get_item("InCohort")?,
            compare_op_not_in_cohort: compare_enum.get_item("NotInCohort")?,
            compare_op_regex: compare_enum.get_item("Regex")?,
            compare_op_iregex: compare_enum.get_item("IRegex")?,
            compare_op_not_regex: compare_enum.get_item("NotRegex")?,
            compare_op_not_iregex: compare_enum.get_item("NotIRegex")?,
            py,
        })
    }

    /// Map an arithmetic op symbol to the cached `ArithmeticOperationOp` StrEnum member — compiles to a jump table (one branch + return ref).
    fn arith_op(&self, op: &str) -> &Bound<'py, PyAny> {
        match op {
            "+" => &self.arith_op_add,
            "-" => &self.arith_op_sub,
            "*" => &self.arith_op_mult,
            "/" => &self.arith_op_div,
            "%" => &self.arith_op_mod,
            other => panic!("unknown arith op symbol `{other}`"),
        }
    }

    /// Map a comparison op symbol to the cached `CompareOperationOp` StrEnum member.
    fn compare_op(&self, op: &str) -> &Bound<'py, PyAny> {
        match op {
            "==" => &self.compare_op_eq,
            "!=" => &self.compare_op_not_eq,
            ">" => &self.compare_op_gt,
            ">=" => &self.compare_op_gt_eq,
            "<" => &self.compare_op_lt,
            "<=" => &self.compare_op_lt_eq,
            "like" => &self.compare_op_like,
            "ilike" => &self.compare_op_ilike,
            "not like" => &self.compare_op_not_like,
            "not ilike" => &self.compare_op_not_ilike,
            "in" => &self.compare_op_in,
            "global in" => &self.compare_op_global_in,
            "not in" => &self.compare_op_not_in,
            "global not in" => &self.compare_op_global_not_in,
            "in cohort" => &self.compare_op_in_cohort,
            "not in cohort" => &self.compare_op_not_in_cohort,
            "=~" => &self.compare_op_regex,
            "=~*" => &self.compare_op_iregex,
            "!~" => &self.compare_op_not_regex,
            "!~*" => &self.compare_op_not_iregex,
            other => panic!("unknown compare op symbol `{other}`"),
        }
    }

    /// Construct a node by invoking `class(**kwargs)`. Wraps the result in [`PyAst`] with `positions_locked = false`.
    fn build(&self, class: &Bound<'py, PyAny>, kwargs: &Bound<'py, PyDict>) -> PyAst {
        match class.call(PyTuple::empty_bound(self.py), Some(kwargs)) {
            Ok(obj) => PyAst {
                obj: obj.unbind(),
                positions_locked: false,
                rust_sentinels: None,
            },
            // A dataclass constructor / `__post_init__` raised. Restore the original Python
            // exception so `run_py` re-raises it verbatim (the json backends surface the same
            // raw exception from `deserialize_ast`), then unwind out of the deep parse via panic.
            Err(err) => {
                err.restore(self.py);
                panic!("ast construction raised; original exception restored for run_py");
            }
        }
    }

    /// Helper: wrap a non-AST primitive (None, bool, int, str, list) in PyAst so it flows through the parser as `Self::Value`.
    fn wrap_prim(&self, obj: PyObject) -> PyAst {
        PyAst {
            obj,
            positions_locked: false,
            rust_sentinels: None,
        }
    }
}

// ============================================================================
// Emitter impl
// ============================================================================

impl<'py> Emitter for PyEmitter<'py> {
    type Value = PyAst;

    // ===== Primitive constructors =====

    fn null(&self) -> PyAst {
        self.wrap_prim(self.py.None())
    }
    fn bool(&self, v: bool) -> PyAst {
        self.wrap_prim(v.into_py(self.py))
    }
    fn int(&self, v: i64) -> PyAst {
        self.wrap_prim(v.into_py(self.py))
    }
    fn string(&self, v: &str) -> PyAst {
        self.wrap_prim(v.into_py(self.py))
    }
    fn float(&self, v: f64) -> PyAst {
        self.wrap_prim(v.into_py(self.py))
    }
    fn uint(&self, v: u64) -> PyAst {
        self.wrap_prim(v.into_py(self.py))
    }
    fn list_value(&self, items: Vec<PyAst>) -> PyAst {
        let list = PyList::empty_bound(self.py);
        for item in items {
            list.append(item.obj).unwrap();
        }
        self.wrap_prim(list.into_any().unbind())
    }
    fn string_keyed_map(&self, pairs: Vec<(String, PyAst)>) -> PyAst {
        let dict = PyDict::new_bound(self.py);
        for (k, v) in pairs {
            dict.set_item(k, v.obj.bind(self.py)).unwrap();
        }
        self.wrap_prim(dict.into_any().unbind())
    }

    // ===== AST node constructors =====

    fn constant(&self, value: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("value", value.obj.bind(self.py)).unwrap();
        self.build(&self.cls_constant, &kw)
    }
    fn constant_special_number(&self, name: &'static str) -> PyAst {
        // cpp's `Infinity` / `-Infinity` / `NaN` ship as strings in JSON; the Python side unwraps to f64, so the Constant holds `value: float('inf')` etc.
        let f = match name {
            "Infinity" => f64::INFINITY,
            "-Infinity" => f64::NEG_INFINITY,
            "NaN" => f64::NAN,
            _ => panic!("unknown special number name `{name}`"),
        };
        let kw = PyDict::new_bound(self.py);
        kw.set_item("value", f).unwrap();
        self.build(&self.cls_constant, &kw)
    }
    fn constant_number_string(&self, text: String) -> PyAst {
        // Lossless big int: hand the digit string to Python `int(text, base)`. Mirrors `pyobject::parse_large_int_literal`.
        let body = text.strip_prefix('-').unwrap_or(&text);
        let is_hex = body.starts_with("0x") || body.starts_with("0X");
        let base = if is_hex { 16 } else { 10 };
        let args = PyTuple::new_bound(self.py, [text.into_py(self.py), base.into_py(self.py)]);
        let int_obj = self.cls_int.call(&args, None).unwrap();
        let kw = PyDict::new_bound(self.py);
        kw.set_item("value", &int_obj).unwrap();
        self.build(&self.cls_constant, &kw)
    }
    fn field(&self, chain: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("chain", build_list(self.py, chain)).unwrap();
        self.build(&self.cls_field, &kw)
    }
    fn arith(&self, left: PyAst, op: &str, right: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("left", left.obj.bind(self.py)).unwrap();
        kw.set_item("right", right.obj.bind(self.py)).unwrap();
        kw.set_item("op", self.arith_op(op)).unwrap();
        self.build(&self.cls_arith_op, &kw)
    }
    fn compare(&self, left: PyAst, op: &str, right: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("left", left.obj.bind(self.py)).unwrap();
        kw.set_item("right", right.obj.bind(self.py)).unwrap();
        kw.set_item("op", self.compare_op(op)).unwrap();
        self.build(&self.cls_compare_op, &kw)
    }
    fn compare_is_null(&self, left: PyAst, negated: bool) -> PyAst {
        // `expr IS [NOT] NULL` → CompareOperation(left, Constant(None), == / !=, is_null_comparison_style=True).
        let kw = PyDict::new_bound(self.py);
        kw.set_item("left", left.obj.bind(self.py)).unwrap();
        let null_constant = self.constant(self.null());
        kw.set_item("right", null_constant.obj.bind(self.py))
            .unwrap();
        let op_member = if negated {
            &self.compare_op_not_eq
        } else {
            &self.compare_op_eq
        };
        kw.set_item("op", op_member).unwrap();
        kw.set_item("is_null_comparison_style", true).unwrap();
        self.build(&self.cls_compare_op, &kw)
    }
    fn is_distinct_from(&self, left: PyAst, right: PyAst, negated: bool) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("left", left.obj.bind(self.py)).unwrap();
        kw.set_item("right", right.obj.bind(self.py)).unwrap();
        kw.set_item("negated", negated).unwrap();
        self.build(&self.cls_is_distinct_from, &kw)
    }
    fn between(&self, expr: PyAst, low: PyAst, high: PyAst, negated: bool) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("low", low.obj.bind(self.py)).unwrap();
        kw.set_item("high", high.obj.bind(self.py)).unwrap();
        kw.set_item("negated", negated).unwrap();
        self.build(&self.cls_between_expr, &kw)
    }
    fn not_(&self, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.cls_not, &kw)
    }
    fn and_(&self, exprs: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("exprs", build_list(self.py, exprs)).unwrap();
        self.build(&self.cls_and, &kw)
    }
    fn or_(&self, exprs: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("exprs", build_list(self.py, exprs)).unwrap();
        self.build(&self.cls_or, &kw)
    }
    fn tuple_(&self, exprs: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("exprs", build_list(self.py, exprs)).unwrap();
        self.build(&self.cls_tuple, &kw)
    }
    fn array_(&self, exprs: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("exprs", build_list(self.py, exprs)).unwrap();
        self.build(&self.cls_array, &kw)
    }
    fn array_access(&self, array: PyAst, property: PyAst, nullish: bool) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("array", array.obj.bind(self.py)).unwrap();
        kw.set_item("property", property.obj.bind(self.py)).unwrap();
        if nullish {
            kw.set_item("nullish", true).unwrap();
        }
        self.build(&self.cls_array_access, &kw)
    }
    fn tuple_access(&self, tuple_: PyAst, index: i64, nullish: bool) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("tuple", tuple_.obj.bind(self.py)).unwrap();
        kw.set_item("index", index).unwrap();
        if nullish {
            kw.set_item("nullish", true).unwrap();
        }
        self.build(&self.cls_tuple_access, &kw)
    }
    fn alias(&self, expr: PyAst, name: &str) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("alias", name).unwrap();
        self.build(&self.cls_alias, &kw)
    }
    fn call(&self, name: &str, args: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("name", name).unwrap();
        kw.set_item("args", build_list(self.py, args)).unwrap();
        self.build(&self.cls_call, &kw)
    }
    fn call_full(
        &self,
        name: &str,
        params: Option<Vec<PyAst>>,
        args: Vec<PyAst>,
        distinct: bool,
        order_by: Option<Vec<PyAst>>,
        filter_expr: Option<PyAst>,
        within_group: Option<Vec<PyAst>>,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("name", name).unwrap();
        kw.set_item("args", build_list(self.py, args)).unwrap();
        if let Some(p) = params {
            kw.set_item("params", build_list(self.py, p)).unwrap();
        }
        if distinct {
            kw.set_item("distinct", true).unwrap();
        }
        if let Some(ob) = order_by {
            kw.set_item("order_by", build_list(self.py, ob)).unwrap();
        }
        if let Some(fe) = filter_expr {
            kw.set_item("filter_expr", fe.obj.bind(self.py)).unwrap();
        }
        if let Some(wg) = within_group {
            kw.set_item("within_group", build_list(self.py, wg))
                .unwrap();
        }
        self.build(&self.cls_call, &kw)
    }
    fn lambda(&self, args: Vec<String>, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        let args_list = PyList::empty_bound(self.py);
        for a in args {
            args_list.append(a).unwrap();
        }
        kw.set_item("args", args_list).unwrap();
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.cls_lambda, &kw)
    }
    fn expr_call(&self, expr: PyAst, args: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("args", build_list(self.py, args)).unwrap();
        self.build(&self.cls_expr_call, &kw)
    }
    fn type_cast(&self, expr: PyAst, type_name: &str) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("type_name", type_name).unwrap();
        self.build(&self.cls_type_cast, &kw)
    }
    fn try_cast(&self, expr: PyAst, type_name: &str) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("type_name", type_name).unwrap();
        self.build(&self.cls_try_cast, &kw)
    }
    fn array_slice(&self, array: PyAst, start: Option<PyAst>, end: Option<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("array", array.obj.bind(self.py)).unwrap();
        if let Some(s) = start {
            kw.set_item("start_expr", s.obj.bind(self.py)).unwrap();
        }
        if let Some(e) = end {
            kw.set_item("end_expr", e.obj.bind(self.py)).unwrap();
        }
        self.build(&self.cls_array_slice, &kw)
    }
    fn dict_(&self, items: Vec<(PyAst, PyAst)>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        let items_list = PyList::empty_bound(self.py);
        for (k, v) in items {
            let pair = PyTuple::new_bound(self.py, [k.obj, v.obj]);
            items_list.append(pair).unwrap();
        }
        kw.set_item("items", items_list).unwrap();
        self.build(&self.cls_dict, &kw)
    }
    fn placeholder(&self, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.cls_placeholder, &kw)
    }
    fn named_argument(&self, name: &str, value: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("name", name).unwrap();
        kw.set_item("value", value.obj.bind(self.py)).unwrap();
        let mut node = self.build(&self.cls_named_argument, &kw);
        // cpp's `VISIT(NamedArgument)` emits this without `addPositionInfo`; `positions_locked` short-circuits future `with_pos` calls.
        node.positions_locked = true;
        node
    }
    fn order_expr(&self, expr: PyAst, order: &str, with_fill: Option<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("order", order).unwrap();
        if let Some(wf) = with_fill {
            kw.set_item("with_fill", wf.obj.bind(self.py)).unwrap();
        }
        self.build(&self.cls_order_expr, &kw)
    }
    fn columns_expr(
        &self,
        regex: Option<String>,
        columns: Option<Vec<PyAst>>,
        all_columns: bool,
        exclude: Option<Vec<String>>,
        replace: Option<Vec<(String, PyAst)>>,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        if let Some(r) = regex {
            kw.set_item("regex", r).unwrap();
        }
        if let Some(c) = columns {
            kw.set_item("columns", build_list(self.py, c)).unwrap();
        }
        if all_columns {
            kw.set_item("all_columns", true).unwrap();
        }
        if let Some(ex) = exclude {
            let ex_list = PyList::empty_bound(self.py);
            for s in ex {
                ex_list.append(s).unwrap();
            }
            kw.set_item("exclude", ex_list).unwrap();
        }
        if let Some(rep) = replace {
            let rep_dict = PyDict::new_bound(self.py);
            for (k, v) in rep {
                rep_dict.set_item(k, v.obj.bind(self.py)).unwrap();
            }
            kw.set_item("replace", rep_dict).unwrap();
        }
        self.build(&self.cls_columns_expr, &kw)
    }
    fn spread_expr(&self, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.cls_spread_expr, &kw)
    }
    fn positional_ref(&self, index: i64) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("index", index).unwrap();
        self.build(&self.cls_positional_ref, &kw)
    }

    // ===== Statement / program builders =====

    fn program(&self, declarations: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("declarations", build_list(self.py, declarations))
            .unwrap();
        self.build(&self.cls_program, &kw)
    }
    fn block(&self, declarations: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("declarations", build_list(self.py, declarations))
            .unwrap();
        self.build(&self.cls_block, &kw)
    }
    fn expr_statement(&self, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.cls_expr_statement, &kw)
    }
    fn if_statement(&self, cond: PyAst, then: PyAst, else_: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", cond.obj.bind(self.py)).unwrap();
        kw.set_item("then", then.obj.bind(self.py)).unwrap();
        kw.set_item("else_", else_.obj.bind(self.py)).unwrap();
        self.build(&self.cls_if_statement, &kw)
    }
    fn while_statement(&self, cond: PyAst, body: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", cond.obj.bind(self.py)).unwrap();
        kw.set_item("body", body.obj.bind(self.py)).unwrap();
        self.build(&self.cls_while_statement, &kw)
    }
    fn for_in_statement(
        &self,
        key_var: PyAst,
        value_var: PyAst,
        expr: PyAst,
        body: PyAst,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("keyVar", key_var.obj.bind(self.py)).unwrap();
        kw.set_item("valueVar", value_var.obj.bind(self.py))
            .unwrap();
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("body", body.obj.bind(self.py)).unwrap();
        self.build(&self.cls_for_in_statement, &kw)
    }
    fn for_statement(
        &self,
        initializer: PyAst,
        condition: PyAst,
        increment: PyAst,
        body: PyAst,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("initializer", initializer.obj.bind(self.py))
            .unwrap();
        kw.set_item("condition", condition.obj.bind(self.py))
            .unwrap();
        kw.set_item("increment", increment.obj.bind(self.py))
            .unwrap();
        kw.set_item("body", body.obj.bind(self.py)).unwrap();
        self.build(&self.cls_for_statement, &kw)
    }
    fn function_(&self, name: &str, params: Vec<PyAst>, body: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("name", name).unwrap();
        kw.set_item("params", build_list(self.py, params)).unwrap();
        kw.set_item("body", body.obj.bind(self.py)).unwrap();
        self.build(&self.cls_function, &kw)
    }
    fn variable_assignment(&self, left: PyAst, right: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("left", left.obj.bind(self.py)).unwrap();
        kw.set_item("right", right.obj.bind(self.py)).unwrap();
        self.build(&self.cls_variable_assignment, &kw)
    }
    fn return_statement(&self, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.cls_return_statement, &kw)
    }
    fn try_catch_statement(
        &self,
        try_stmt: PyAst,
        catches: Vec<PyAst>,
        finally_stmt: PyAst,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("try_stmt", try_stmt.obj.bind(self.py)).unwrap();
        kw.set_item("catches", build_list(self.py, catches))
            .unwrap();
        kw.set_item("finally_stmt", finally_stmt.obj.bind(self.py))
            .unwrap();
        self.build(&self.cls_try_catch_statement, &kw)
    }
    fn throw_statement(&self, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.cls_throw_statement, &kw)
    }
    fn variable_declaration(&self, name: &str, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("name", name).unwrap();
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.cls_variable_declaration, &kw)
    }
    fn catch_clause(&self, var: PyAst, ty: PyAst, body: PyAst) -> PyAst {
        // cpp emits this as a `[var, type, body]` JSON array; the Python AST types
        // `TryCatchStatement.catches` as `list[tuple[Optional[str], Optional[str], Statement]]`
        // (matching what `CloningVisitor.visit_try_catch_statement` builds and what
        // `json_ast._TUPLE_INNER_FIELDS` now deserialises cpp/rust-json arrays into).
        // Build a tuple here so `rust-py` produces the canonical shape directly.
        let pair = PyTuple::new_bound(self.py, [var.obj, ty.obj, body.obj]);
        self.wrap_prim(pair.into_any().unbind())
    }

    // ===== Query / clause builders =====

    fn cte(&self, name: &str, expr: PyAst, cte_type: &str) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("name", name).unwrap();
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("cte_type", cte_type).unwrap();
        self.build(&self.cls_cte, &kw)
    }
    fn cte_subquery(
        &self,
        name: &str,
        expr: PyAst,
        columns: Option<Vec<String>>,
        using_key: Option<Vec<String>>,
        materialized: Option<bool>,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("name", name).unwrap();
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("cte_type", "subquery").unwrap();
        if let Some(c) = columns {
            let l = PyList::empty_bound(self.py);
            for s in c {
                l.append(s).unwrap();
            }
            kw.set_item("columns", l).unwrap();
        }
        if let Some(uk) = using_key {
            let l = PyList::empty_bound(self.py);
            for s in uk {
                l.append(s).unwrap();
            }
            kw.set_item("using_key", l).unwrap();
        }
        if let Some(m) = materialized {
            kw.set_item("materialized", m).unwrap();
        }
        self.build(&self.cls_cte, &kw)
    }
    fn join_constraint(&self, expr: PyAst, constraint_type: &str) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("constraint_type", constraint_type).unwrap();
        self.build(&self.cls_join_constraint, &kw)
    }
    fn values_query(&self, rows: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("rows", build_list(self.py, rows)).unwrap();
        self.build(&self.cls_values_query, &kw)
    }
    fn pivot_column(&self, column: PyAst, values: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("column", column.obj.bind(self.py)).unwrap();
        kw.set_item("values", build_list(self.py, values)).unwrap();
        self.build(&self.cls_pivot_column, &kw)
    }
    fn unpivot_column(
        &self,
        value_columns: PyAst,
        name_columns: PyAst,
        unpivot_values: Vec<PyAst>,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("value_columns", value_columns.obj.bind(self.py))
            .unwrap();
        kw.set_item("name_columns", name_columns.obj.bind(self.py))
            .unwrap();
        kw.set_item("unpivot_values", build_list(self.py, unpivot_values))
            .unwrap();
        self.build(&self.cls_unpivot_column, &kw)
    }
    fn grouping_set(&self, exprs: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("exprs", build_list(self.py, exprs)).unwrap();
        self.build(&self.cls_grouping_set, &kw)
    }
    fn hogqlx_tag(&self, kind: &str, attributes: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("kind", kind).unwrap();
        kw.set_item("attributes", build_list(self.py, attributes))
            .unwrap();
        self.build(&self.cls_hogqlx_tag, &kw)
    }
    fn hogqlx_attribute(&self, name: &str, value: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("name", name).unwrap();
        kw.set_item("value", value.obj.bind(self.py)).unwrap();
        self.build(&self.cls_hogqlx_attribute, &kw)
    }
    fn select_set_query(&self, initial: PyAst, subsequent: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("initial_select_query", initial.obj.bind(self.py))
            .unwrap();
        kw.set_item("subsequent_select_queries", build_list(self.py, subsequent))
            .unwrap();
        self.build(&self.cls_select_set_query, &kw)
    }
    fn window_expr_empty(&self) -> PyAst {
        // `WindowExpr()` with all-defaults.
        self.build(&self.cls_window_expr, &PyDict::new_bound(self.py))
    }
    fn window_frame_bound(&self, frame_type: &str, frame_value: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("frame_type", frame_type).unwrap();
        kw.set_item("frame_value", frame_value.obj.bind(self.py))
            .unwrap();
        self.build(&self.cls_window_frame_expr, &kw)
    }
    fn interpolate_expr(&self, expr: PyAst, value: Option<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        if let Some(v) = value {
            kw.set_item("value", v.obj.bind(self.py)).unwrap();
        }
        self.build(&self.cls_interpolate_expr, &kw)
    }
    fn limit_by_expr(&self, n: PyAst, exprs: Vec<PyAst>, offset_value: Option<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("n", n.obj.bind(self.py)).unwrap();
        kw.set_item("exprs", build_list(self.py, exprs)).unwrap();
        if let Some(o) = offset_value {
            kw.set_item("offset_value", o.obj.bind(self.py)).unwrap();
        }
        self.build(&self.cls_limit_by_expr, &kw)
    }
    fn select_query_empty(&self) -> PyAst {
        // `SelectQuery.select: list[Expr]` is required (no default) — passing nothing trips dataclass `__init__` validation. The parser fills the real value via `set_field("select", ...)` before the node leaves, so an empty list is a safe placeholder. Same idea for the other `_empty()` shell sites.
        let kw = PyDict::new_bound(self.py);
        kw.set_item("select", PyList::empty_bound(self.py)).unwrap();
        self.build(&self.cls_select_query, &kw)
    }
    fn select_set_node(&self, select_query: PyAst, set_operator: Option<&str>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("select_query", select_query.obj.bind(self.py))
            .unwrap();
        if let Some(op) = set_operator {
            kw.set_item("set_operator", op).unwrap();
        }
        self.build(&self.cls_select_set_node, &kw)
    }
    fn sample_expr(&self, sample_value: PyAst, offset_value: Option<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("sample_value", sample_value.obj.bind(self.py))
            .unwrap();
        if let Some(o) = offset_value {
            kw.set_item("offset_value", o.obj.bind(self.py)).unwrap();
        }
        self.build(&self.cls_sample_expr, &kw)
    }
    fn ratio_expr(&self, left: PyAst, right: Option<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("left", left.obj.bind(self.py)).unwrap();
        if let Some(r) = right {
            kw.set_item("right", r.obj.bind(self.py)).unwrap();
        }
        self.build(&self.cls_ratio_expr, &kw)
    }
    fn pivot_expr(
        &self,
        table: PyAst,
        aggregates: Vec<PyAst>,
        columns: Vec<PyAst>,
        group_by: Option<Vec<PyAst>>,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("table", table.obj.bind(self.py)).unwrap();
        kw.set_item("aggregates", build_list(self.py, aggregates))
            .unwrap();
        kw.set_item("columns", build_list(self.py, columns))
            .unwrap();
        if let Some(g) = group_by {
            kw.set_item("group_by", build_list(self.py, g)).unwrap();
        }
        self.build(&self.cls_pivot_expr, &kw)
    }
    fn unpivot_expr(&self, table: PyAst, columns: Vec<PyAst>, include_nulls: bool) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("table", table.obj.bind(self.py)).unwrap();
        kw.set_item("columns", build_list(self.py, columns))
            .unwrap();
        kw.set_item("include_nulls", include_nulls).unwrap();
        self.build(&self.cls_unpivot_expr, &kw)
    }
    fn join_expr(
        &self,
        table: PyAst,
        alias: Option<String>,
        table_args: Option<PyAst>,
        column_aliases: Option<Vec<String>>,
        table_final: bool,
        sample: Option<PyAst>,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("table", table.obj.bind(self.py)).unwrap();
        if let Some(ta) = table_args {
            kw.set_item("table_args", ta.obj.bind(self.py)).unwrap();
        }
        if let Some(a) = alias {
            kw.set_item("alias", a).unwrap();
        }
        if table_final {
            kw.set_item("table_final", true).unwrap();
        }
        if let Some(s) = sample {
            kw.set_item("sample", s.obj.bind(self.py)).unwrap();
        }
        if let Some(ca) = column_aliases {
            let l = PyList::empty_bound(self.py);
            for s in ca {
                l.append(s).unwrap();
            }
            kw.set_item("column_aliases", l).unwrap();
        }
        self.build(&self.cls_join_expr, &kw)
    }
    fn window_function(
        &self,
        name: &str,
        exprs: Vec<PyAst>,
        args: Vec<PyAst>,
        over_expr: Option<PyAst>,
        over_identifier: Option<String>,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("name", name).unwrap();
        kw.set_item("exprs", build_list(self.py, exprs)).unwrap();
        kw.set_item("args", build_list(self.py, args)).unwrap();
        if let Some(we) = over_expr {
            kw.set_item("over_expr", we.obj.bind(self.py)).unwrap();
        }
        if let Some(id) = over_identifier {
            kw.set_item("over_identifier", id).unwrap();
        }
        self.build(&self.cls_window_function, &kw)
    }
    fn with_fill_expr(
        &self,
        from_value: Option<PyAst>,
        to_value: Option<PyAst>,
        step_value: Option<PyAst>,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        if let Some(v) = from_value {
            kw.set_item("from_value", v.obj.bind(self.py)).unwrap();
        }
        if let Some(v) = to_value {
            kw.set_item("to_value", v.obj.bind(self.py)).unwrap();
        }
        if let Some(v) = step_value {
            kw.set_item("step_value", v.obj.bind(self.py)).unwrap();
        }
        self.build(&self.cls_with_fill_expr, &kw)
    }

    // ===== Position machinery =====
    fn position(&self, _line: u32, _column: u32, offset: usize) -> PyAst {
        // Python AST `start` / `end` are `Optional[int]` — only the offset survives; lines/columns aren't carried on the dataclass. Pre-allocating the `Py<int>` here lets `with_pos` / `replace_pos` setattr via a `Bound` (fast IntoPy, no per-setattr int alloc).
        self.wrap_prim(offset.into_py(self.py))
    }
    fn with_pos(&self, value: PyAst, start: PyAst, end: PyAst) -> PyAst {
        if value.positions_locked {
            return value;
        }
        let bound = value.obj.bind(self.py);
        // `start` is only on AST dataclasses (via `AST` base); primitives (int / str / None) don't have it.
        if let Ok(existing) = bound.getattr("start") {
            if existing.is_none() {
                bound.setattr("start", start.obj.bind(self.py)).unwrap();
                bound.setattr("end", end.obj.bind(self.py)).unwrap();
            }
        }
        value
    }
    fn no_pos(&self, mut value: PyAst) -> PyAst {
        // `positions_locked` only blocks `with_pos` / `replace_pos` on AST dataclasses; primitives skip those paths already, so calling `no_pos` on one is a silent no-op. Debug-assert the precondition so a wrapper-less caller fails loud.
        debug_assert!(
            self.node_kind(&value).is_some(),
            "no_pos called on a non-AST primitive — position suppression would be a no-op"
        );
        value.positions_locked = true;
        value
    }
    fn replace_pos(&self, value: PyAst, start: PyAst, end: PyAst) -> PyAst {
        if value.positions_locked {
            return value;
        }
        let bound = value.obj.bind(self.py);
        if bound.hasattr("start").unwrap_or(false) {
            bound.setattr("start", start.obj.bind(self.py)).unwrap();
            bound.setattr("end", end.obj.bind(self.py)).unwrap();
        }
        value
    }

    // ===== Inspection =====
    fn node_kind<'a>(&self, v: &'a PyAst) -> Option<Cow<'a, str>> {
        let bound = v.obj.bind(self.py);
        // Plain primitives (int / str / None / list / dict / bool) aren't AST nodes — return None to match JsonEmitter. Probe `_visit_method_name` (every AST dataclass has it via `__init_subclass__`) — fast attr probe, no string parsing.
        if !bound.hasattr("_visit_method_name").unwrap_or(false) {
            return None;
        }
        let type_name = bound.get_type().qualname().ok()?;
        Some(Cow::Owned(type_name.to_string()))
    }
    fn get_field(&self, v: &PyAst, name: &str) -> Option<PyAst> {
        // Sentinel fields (`__rust_*`) live in the side-channel map — see `rust_sentinels` on `PyAst`.
        if let Some(stored) = v.rust_sentinels.as_ref().and_then(|m| m.get(name)) {
            return Some(PyAst {
                obj: stored.clone_ref(self.py),
                positions_locked: false,
                rust_sentinels: None,
            });
        }
        let bound = v.obj.bind(self.py);
        let got = bound.getattr(name).ok()?;
        // `ctes` is eagerly folded list->dict on write (see `set_field`); un-fold dict->list of values here so `inject_ctes_into_select`'s read-modify-write through `as_list` round-trips and the second `set_field` re-folds with all members. Mirrors JsonEmitter where ctes stays list-shaped during parsing.
        if name == "ctes" {
            if let Ok(dict) = got.downcast::<PyDict>() {
                let list = PyList::empty_bound(self.py);
                for (_, val) in dict.iter() {
                    list.append(val).unwrap();
                }
                return Some(PyAst {
                    obj: list.into_any().unbind(),
                    positions_locked: false,
                    rust_sentinels: None,
                });
            }
        }
        Some(PyAst {
            obj: got.unbind(),
            positions_locked: false,
            rust_sentinels: None,
        })
    }
    fn has_field(&self, v: &PyAst, name: &str) -> bool {
        // JsonEmitter returns true iff the JSON Map has the key — only set when the parser emitted a non-default value.
        // Python equivalent is "attribute exists AND is not None": slots=True dataclasses always declare every field as an attribute (even when default is None), so plain `hasattr` returns true for unset fields. The `not None` semantic matches JSON's "key exists" check for the parser's gating sites (wrap_pivot_chain's decoration check, the array-join FROM check).
        if v.rust_sentinels
            .as_ref()
            .is_some_and(|m| m.contains_key(name))
        {
            return true;
        }
        let bound = v.obj.bind(self.py);
        match bound.getattr(name) {
            Ok(value) => !value.is_none(),
            Err(_) => false,
        }
    }
    fn is_null(&self, v: &PyAst) -> bool {
        v.obj.is_none(self.py)
    }
    fn as_str<'a>(&self, v: &'a PyAst) -> Option<Cow<'a, str>> {
        let bound = v.obj.bind(self.py);
        bound.extract::<String>().ok().map(Cow::Owned)
    }
    fn as_list(&self, v: &PyAst) -> Option<Vec<PyAst>> {
        let bound = v.obj.bind(self.py);
        let list = bound.downcast::<PyList>().ok()?;
        let mut out = Vec::with_capacity(list.len());
        for item in list.iter() {
            out.push(PyAst {
                obj: item.unbind(),
                positions_locked: false,
                rust_sentinels: None,
            });
        }
        Some(out)
    }
    fn as_bool(&self, v: &PyAst) -> Option<bool> {
        // Match JsonEmitter's `Value::Bool` strictness; PyO3's `extract::<bool>` would accept ints (0 / 1) without the type gate.
        let bound = v.obj.bind(self.py);
        if bound.is_instance_of::<pyo3::types::PyBool>() {
            bound.extract::<bool>().ok()
        } else {
            None
        }
    }
    fn as_i64(&self, v: &PyAst) -> Option<i64> {
        // Match JsonEmitter's `Value::Number` (booleans excluded); PyO3's `extract::<i64>` would coerce `True` to 1.
        let bound = v.obj.bind(self.py);
        if bound.is_instance_of::<pyo3::types::PyBool>() {
            return None;
        }
        bound.extract::<i64>().ok()
    }

    // ===== Mutation =====
    fn remove_field(&self, v: &mut PyAst, name: &str) -> Option<PyAst> {
        // Sentinel fields live in the side-channel.
        if let Some(prev) = v.rust_sentinels.as_mut().and_then(|m| m.remove(name)) {
            return Some(PyAst {
                obj: prev,
                positions_locked: false,
                rust_sentinels: None,
            });
        }
        let bound = v.obj.bind(self.py);
        let prev = bound.getattr(name).ok()?;
        if prev.is_none() {
            // Field already unset (slots=True keeps the attr bound but None) — treat as absent to match JSON's `as_object_mut().remove` returning None for missing keys.
            return None;
        }
        // Replace with `None` so the field still exists (slots=True keeps it bound) but reads as missing semantically.
        bound.setattr(name, self.py.None()).unwrap();
        Some(PyAst {
            obj: prev.unbind(),
            positions_locked: false,
            rust_sentinels: None,
        })
    }
    fn set_field(&self, v: &mut PyAst, name: &str, value: PyAst) {
        // Parser-internal sentinel fields (`__rust_*`) aren't on the dataclass; slots=True rejects setattr — route to the side-channel HashMap.
        if name.starts_with("__rust_") {
            v.sentinels_mut().insert(name.to_string(), value.obj);
            return;
        }
        let bound = v.obj.bind(self.py);
        // Dict-shaped AST fields (`_DICT_FIELDS` in `json_ast.py`): `ctes`, `replace`, `window_exprs`. The parser builds `ctes` as a list (see `inject_ctes_into_select`) and the JSON path folds list→dict in `json_ast.py::_deserialize_node`. PyEmitter has no post-walk, so we fold here using each item's `name` attribute (it's a `CTE`) as the dict key.
        if name == "ctes" {
            let val_bound = value.obj.bind(self.py);
            if let Ok(list) = val_bound.downcast::<PyList>() {
                let dict = PyDict::new_bound(self.py);
                for item in list.iter() {
                    let cte_name = item
                        .getattr("name")
                        .expect("ctes list item missing `name` attribute");
                    dict.set_item(cte_name, &item).unwrap();
                }
                bound.setattr(name, dict).unwrap();
                return;
            }
        }
        bound.setattr(name, value.obj.bind(self.py)).unwrap();
        // Re-fire `__post_init__` when writing a field whose validation lives there. The printer interpolates `join_type` / `order` / `constraint_type` / `set_operator` verbatim into emitted SQL and trusts the dataclass allow-list; the JSON path runs the check via `cls(**kwargs)`, but rust-py builds the node first and writes some of these fields post-construction (notably `join_type` via `chain_join`), so the check has to be re-driven here.
        if matches!(
            name,
            "join_type" | "order" | "constraint_type" | "set_operator"
        ) {
            if let Ok(post_init) = bound.getattr("__post_init__") {
                if let Err(py_err) = post_init.call0() {
                    // Restore the original exception so `run_py` re-raises it verbatim — rust-py then
                    // surfaces the same exception the json backends do (which run this `__post_init__`
                    // check inside `cls(**kwargs)`), instead of a wrapped `not_implemented` envelope.
                    py_err.restore(self.py);
                    panic!(
                        "dataclass __post_init__ raised; original exception restored for run_py"
                    );
                }
            }
        }
    }
}

// ============================================================================
// Helpers
// ============================================================================

fn build_list(py: Python<'_>, items: Vec<PyAst>) -> Bound<'_, PyList> {
    let list = PyList::empty_bound(py);
    for item in items {
        list.append(item.obj).unwrap();
    }
    list
}
