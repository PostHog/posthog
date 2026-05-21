//! `PyEmitter` — `Emitter` impl that constructs `posthog.hogql.ast`
//! dataclass instances directly during parsing, bypassing the
//! `serde_json::Value` intermediate tree.
//!
//! Used by the `parse_*_py` PyO3 entry points in [`crate::lib`]. The
//! `parse_*_json` entry points stay on `JsonEmitter` for the future
//! WASM build (no CPython link) and for tests that compare on JSON
//! shape.
//!
//! Construction strategy:
//!  - All `posthog.hogql.ast` classes are looked up *once* at
//!    [`PyEmitter::new`] and stored as `Bound<'py, PyAny>` references.
//!    A `getattr(ast_module, "Constant")` per node would dominate
//!    runtime over the json round-trip we're trying to beat.
//!  - Each emitter method builds a `PyDict` of kwargs and calls
//!    `class.call((), Some(&kwargs))`. The constructed object is
//!    wrapped in [`PyAst`] (which also tracks the `positions_locked`
//!    flag for idempotent `with_pos` / `no_pos` semantics).
//!
//! Position handling:
//!  - The trait's `position()` returns a `Self::Value`. For PyEmitter
//!    it's just a plain `PyInt` (the offset). Lines/columns aren't
//!    used by the Python side — only `offset` ends up on the dataclass.
//!  - `with_pos` / `no_pos` / `replace_pos` mirror cpp's idempotent
//!    semantics:
//!    * `with_pos(v, start, end)`: set `v.start = start, v.end = end`
//!      only if `v.start` is currently `None` AND `positions_locked`
//!      isn't set.
//!    * `no_pos(v)`: marks the wrapper with `positions_locked = true`.
//!      The underlying object's `start` / `end` stay at their dataclass
//!      defaults (`None`).
//!    * `replace_pos(v, start, end)`: unconditionally writes (subject
//!      to `positions_locked`). Used for outer-span overrides.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};
use std::borrow::Cow;

use crate::emit::Emitter;

// ============================================================================
// PyAst — AST value wrapper.
// ============================================================================

/// Wrapper around a Python AST object plus the out-of-band
/// `positions_locked` flag. The underlying `posthog.hogql.ast.*`
/// dataclasses use `slots=True` so they can't carry an arbitrary
/// "positions locked" attribute; the wrapper carries it instead.
///
/// `obj` is unbound (`Py<PyAny>`, no GIL lifetime) so the wrapper can
/// live alongside `Parser` without dragging a 'py through the parser's
/// type signatures everywhere. Re-attach to the GIL via `obj.bind(py)`
/// inside emitter methods where `py: Python<'_>` is available.
pub struct PyAst {
    pub obj: Py<PyAny>,
    pub positions_locked: bool,
}

impl Clone for PyAst {
    fn clone(&self) -> Self {
        // `Py<T>::clone_ref` needs the GIL; the parse loop always holds
        // it (we're called from a PyO3 #[pyfunction]), so `with_gil` is a
        // free re-borrow of the already-acquired GIL token.
        Python::with_gil(|py| Self {
            obj: self.obj.clone_ref(py),
            positions_locked: self.positions_locked,
        })
    }
}

// ============================================================================
// PyEmitter — caches AST class references and constructs nodes via
// class.call.
// ============================================================================

/// Constructs `posthog.hogql.ast` instances directly. Holds the GIL
/// token + cached class references for the full duration of one parse.
pub struct PyEmitter<'py> {
    py: Python<'py>,
    // ===== Expression node classes =====
    constant: Bound<'py, PyAny>,
    field: Bound<'py, PyAny>,
    arith_op: Bound<'py, PyAny>,
    compare_op: Bound<'py, PyAny>,
    is_distinct_from: Bound<'py, PyAny>,
    between_expr: Bound<'py, PyAny>,
    not_: Bound<'py, PyAny>,
    and_: Bound<'py, PyAny>,
    or_: Bound<'py, PyAny>,
    tuple_: Bound<'py, PyAny>,
    array_: Bound<'py, PyAny>,
    array_access: Bound<'py, PyAny>,
    tuple_access: Bound<'py, PyAny>,
    alias: Bound<'py, PyAny>,
    call: Bound<'py, PyAny>,
    expr_call: Bound<'py, PyAny>,
    lambda_: Bound<'py, PyAny>,
    type_cast: Bound<'py, PyAny>,
    try_cast: Bound<'py, PyAny>,
    array_slice: Bound<'py, PyAny>,
    dict_: Bound<'py, PyAny>,
    placeholder: Bound<'py, PyAny>,
    named_argument: Bound<'py, PyAny>,
    order_expr: Bound<'py, PyAny>,
    columns_expr: Bound<'py, PyAny>,
    spread_expr: Bound<'py, PyAny>,
    // ===== Op enums (StrEnum lookup via cls[name]) =====
    arith_op_enum: Bound<'py, PyAny>,
    compare_op_enum: Bound<'py, PyAny>,
    // ===== Module handle so we can `getattr` for less-common classes
    // (program statements, select sub-structures, hogqlx, etc.) on
    // demand. The parser cascade may add typed methods for these
    // later; for now we'll do a getattr per call. =====
    pub ast_module: Bound<'py, PyModule>,
}

impl<'py> PyEmitter<'py> {
    pub fn new(py: Python<'py>) -> PyResult<Self> {
        let ast_module = py.import_bound("posthog.hogql.ast")?;
        Ok(Self {
            constant: ast_module.getattr("Constant")?,
            field: ast_module.getattr("Field")?,
            arith_op: ast_module.getattr("ArithmeticOperation")?,
            compare_op: ast_module.getattr("CompareOperation")?,
            is_distinct_from: ast_module.getattr("IsDistinctFrom")?,
            between_expr: ast_module.getattr("BetweenExpr")?,
            not_: ast_module.getattr("Not")?,
            and_: ast_module.getattr("And")?,
            or_: ast_module.getattr("Or")?,
            tuple_: ast_module.getattr("Tuple")?,
            array_: ast_module.getattr("Array")?,
            array_access: ast_module.getattr("ArrayAccess")?,
            tuple_access: ast_module.getattr("TupleAccess")?,
            alias: ast_module.getattr("Alias")?,
            call: ast_module.getattr("Call")?,
            expr_call: ast_module.getattr("ExprCall")?,
            lambda_: ast_module.getattr("Lambda")?,
            type_cast: ast_module.getattr("TypeCast")?,
            try_cast: ast_module.getattr("TryCast")?,
            array_slice: ast_module.getattr("ArraySlice")?,
            dict_: ast_module.getattr("Dict")?,
            placeholder: ast_module.getattr("Placeholder")?,
            named_argument: ast_module.getattr("NamedArgument")?,
            order_expr: ast_module.getattr("OrderExpr")?,
            columns_expr: ast_module.getattr("ColumnsExpr")?,
            spread_expr: ast_module.getattr("SpreadExpr")?,
            arith_op_enum: ast_module.getattr("ArithmeticOperationOp")?,
            compare_op_enum: ast_module.getattr("CompareOperationOp")?,
            ast_module,
            py,
        })
    }

    /// Construct a node by invoking `class(**kwargs)`. Wraps the result
    /// in [`PyAst`] with `positions_locked = false` (caller can mark it
    /// locked via [`Emitter::no_pos`]).
    fn build(
        &self,
        class: &Bound<'py, PyAny>,
        kwargs: &Bound<'py, PyDict>,
    ) -> PyAst {
        let obj = class
            .call(PyTuple::empty_bound(self.py), Some(kwargs))
            .expect("ast class construction failed (validate kwargs / class shape)")
            .unbind();
        PyAst {
            obj,
            positions_locked: false,
        }
    }

    /// Helper: wrap a non-AST primitive (None, bool, int, str, list) as
    /// a PyAst so it can flow through the parser as `Self::Value`.
    fn wrap_prim(&self, obj: PyObject) -> PyAst {
        PyAst {
            obj,
            positions_locked: false,
        }
    }

    /// Bind the inner `Py<PyAny>` to the GIL we already hold.
    #[inline]
    fn bind<'a>(&'a self, v: &'a PyAst) -> Bound<'py, PyAny>
    where
        'a: 'py,
    {
        v.obj.bind(self.py).clone()
    }

    /// Look up a class on the cached `ast` module — fallback for
    /// less-common node types not held as a typed field.
    fn ast_class(&self, name: &str) -> Bound<'py, PyAny> {
        self.ast_module
            .getattr(name)
            .unwrap_or_else(|_| panic!("posthog.hogql.ast has no class `{name}`"))
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

    // ===== AST node constructors =====

    fn constant(&self, value: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("value", value.obj.bind(self.py)).unwrap();
        self.build(&self.constant, &kw)
    }
    fn constant_special_number(&self, name: &'static str) -> PyAst {
        // cpp's `Infinity` / `-Infinity` / `NaN` shipped as a string in
        // the JSON form. The Python deserialiser (and our PyEmitter)
        // unwrap to the f64 value here, so the resulting Constant has
        // `value: float('inf')` etc.
        let f = match name {
            "Infinity" => f64::INFINITY,
            "-Infinity" => f64::NEG_INFINITY,
            "NaN" => f64::NAN,
            _ => panic!("unknown special number name `{name}`"),
        };
        let kw = PyDict::new_bound(self.py);
        kw.set_item("value", f).unwrap();
        self.build(&self.constant, &kw)
    }
    fn constant_number_string(&self, text: String) -> PyAst {
        // Lossless big int: hand the digit string to Python `int(text, base)`.
        // Mirrors `pyobject::parse_large_int_literal`.
        let body = text.strip_prefix('-').unwrap_or(&text);
        let is_hex = body.starts_with("0x") || body.starts_with("0X");
        let base = if is_hex { 16 } else { 10 };
        let int_cls = self.py.eval_bound("int", None, None).unwrap();
        let args = PyTuple::new_bound(self.py, [text.into_py(self.py), base.into_py(self.py)]);
        let int_obj = int_cls.call(&args, None).unwrap();
        let kw = PyDict::new_bound(self.py);
        kw.set_item("value", &int_obj).unwrap();
        self.build(&self.constant, &kw)
    }
    fn field(&self, chain: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("chain", build_list(self.py, chain)).unwrap();
        self.build(&self.field, &kw)
    }
    fn arith(&self, left: PyAst, op: &str, right: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("left", left.obj.bind(self.py)).unwrap();
        kw.set_item("right", right.obj.bind(self.py)).unwrap();
        // Coerce op-string → ArithmeticOperationOp via `cls[name]`.
        let op_member = self.arith_op_enum.get_item(op).unwrap_or_else(|_| {
            self.arith_op_enum.get_item(arith_op_name_from_symbol(op)).unwrap()
        });
        kw.set_item("op", &op_member).unwrap();
        self.build(&self.arith_op, &kw)
    }
    fn compare(&self, left: PyAst, op: &str, right: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("left", left.obj.bind(self.py)).unwrap();
        kw.set_item("right", right.obj.bind(self.py)).unwrap();
        let op_member = self.compare_op_enum.get_item(op).unwrap_or_else(|_| {
            self.compare_op_enum.get_item(compare_op_name_from_symbol(op)).unwrap()
        });
        kw.set_item("op", &op_member).unwrap();
        self.build(&self.compare_op, &kw)
    }
    fn compare_is_null(&self, left: PyAst, negated: bool) -> PyAst {
        // `expr IS NULL` / `expr IS NOT NULL` → CompareOperation(left,
        // Constant(None), == / !=, is_null_comparison_style=True).
        let kw = PyDict::new_bound(self.py);
        kw.set_item("left", left.obj.bind(self.py)).unwrap();
        let null_constant = self.constant(self.null());
        kw.set_item("right", null_constant.obj.bind(self.py)).unwrap();
        let op_name = if negated { "NotEq" } else { "Eq" };
        let op_member = self.compare_op_enum.get_item(op_name).unwrap();
        kw.set_item("op", &op_member).unwrap();
        kw.set_item("is_null_comparison_style", true).unwrap();
        self.build(&self.compare_op, &kw)
    }
    fn is_distinct_from(&self, left: PyAst, right: PyAst, negated: bool) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("left", left.obj.bind(self.py)).unwrap();
        kw.set_item("right", right.obj.bind(self.py)).unwrap();
        kw.set_item("negated", negated).unwrap();
        self.build(&self.is_distinct_from, &kw)
    }
    fn between(&self, expr: PyAst, low: PyAst, high: PyAst, negated: bool) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("low", low.obj.bind(self.py)).unwrap();
        kw.set_item("high", high.obj.bind(self.py)).unwrap();
        kw.set_item("negated", negated).unwrap();
        self.build(&self.between_expr, &kw)
    }
    fn not_(&self, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.not_, &kw)
    }
    fn and_(&self, exprs: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("exprs", build_list(self.py, exprs)).unwrap();
        self.build(&self.and_, &kw)
    }
    fn or_(&self, exprs: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("exprs", build_list(self.py, exprs)).unwrap();
        self.build(&self.or_, &kw)
    }
    fn tuple_(&self, exprs: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("exprs", build_list(self.py, exprs)).unwrap();
        self.build(&self.tuple_, &kw)
    }
    fn array_(&self, exprs: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("exprs", build_list(self.py, exprs)).unwrap();
        self.build(&self.array_, &kw)
    }
    fn array_access(&self, array: PyAst, property: PyAst, nullish: bool) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("array", array.obj.bind(self.py)).unwrap();
        kw.set_item("property", property.obj.bind(self.py)).unwrap();
        if nullish {
            kw.set_item("nullish", true).unwrap();
        }
        self.build(&self.array_access, &kw)
    }
    fn tuple_access(&self, tuple_: PyAst, index: i64, nullish: bool) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("tuple", tuple_.obj.bind(self.py)).unwrap();
        kw.set_item("index", index).unwrap();
        if nullish {
            kw.set_item("nullish", true).unwrap();
        }
        self.build(&self.tuple_access, &kw)
    }
    fn alias(&self, expr: PyAst, name: &str) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("alias", name).unwrap();
        self.build(&self.alias, &kw)
    }
    fn call(&self, name: &str, args: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("name", name).unwrap();
        kw.set_item("args", build_list(self.py, args)).unwrap();
        self.build(&self.call, &kw)
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
            kw.set_item("within_group", build_list(self.py, wg)).unwrap();
        }
        self.build(&self.call, &kw)
    }
    fn lambda(&self, args: Vec<String>, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        let args_list = PyList::empty_bound(self.py);
        for a in args {
            args_list.append(a).unwrap();
        }
        kw.set_item("args", args_list).unwrap();
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.lambda_, &kw)
    }
    fn expr_call(&self, expr: PyAst, args: Vec<PyAst>) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("args", build_list(self.py, args)).unwrap();
        self.build(&self.expr_call, &kw)
    }
    fn type_cast(&self, expr: PyAst, type_name: &str) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("type_name", type_name).unwrap();
        self.build(&self.type_cast, &kw)
    }
    fn try_cast(&self, expr: PyAst, type_name: &str) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("type_name", type_name).unwrap();
        self.build(&self.try_cast, &kw)
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
        self.build(&self.array_slice, &kw)
    }
    fn dict_(&self, items: Vec<(PyAst, PyAst)>) -> PyAst {
        // Python Dict dataclass has `items: list[tuple[Expr, Expr]]`.
        let kw = PyDict::new_bound(self.py);
        let items_list = PyList::empty_bound(self.py);
        for (k, v) in items {
            let pair = PyTuple::new_bound(self.py, [k.obj, v.obj]);
            items_list.append(pair).unwrap();
        }
        kw.set_item("items", items_list).unwrap();
        self.build(&self.dict_, &kw)
    }
    fn placeholder(&self, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.placeholder, &kw)
    }
    fn named_argument(&self, name: &str, value: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("name", name).unwrap();
        kw.set_item("value", value.obj.bind(self.py)).unwrap();
        let mut node = self.build(&self.named_argument, &kw);
        // cpp's `VISIT(NamedArgument)` emits this without
        // `addPositionInfo` — Python AST shows `start=None, end=None`.
        // Mark the wrapper position-locked so the outer `with_pos` is
        // a no-op.
        node.positions_locked = true;
        node
    }
    fn order_expr(
        &self,
        expr: PyAst,
        order: &str,
        with_fill: Option<PyAst>,
    ) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        kw.set_item("order", order).unwrap();
        if let Some(wf) = with_fill {
            kw.set_item("with_fill", wf.obj.bind(self.py)).unwrap();
        }
        self.build(&self.order_expr, &kw)
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
        self.build(&self.columns_expr, &kw)
    }
    fn spread_expr(&self, expr: PyAst) -> PyAst {
        let kw = PyDict::new_bound(self.py);
        kw.set_item("expr", expr.obj.bind(self.py)).unwrap();
        self.build(&self.spread_expr, &kw)
    }

    // ===== Position machinery =====
    fn position(&self, _line: u32, _column: u32, offset: usize) -> PyAst {
        // Python AST `start` / `end` fields are plain `Optional[int]` —
        // only the offset survives. Lines/columns are emitted by cpp
        // for JSON but the Python deserialiser drops them too (see
        // `pyobject::Converter::convert::{position envelope extraction}`).
        self.wrap_prim(offset.into_py(self.py))
    }
    fn with_pos(&self, value: PyAst, start: PyAst, end: PyAst) -> PyAst {
        if value.positions_locked {
            return value;
        }
        let bound = value.obj.bind(self.py);
        // `start` is only present on AST dataclasses (via the `AST`
        // base) — primitives like int / str / None don't have it.
        // Probe `hasattr`-style; skip silently if absent.
        if let Ok(existing) = bound.getattr("start") {
            if existing.is_none() {
                let _ = bound.setattr("start", start.obj.bind(self.py));
                let _ = bound.setattr("end", end.obj.bind(self.py));
            }
        }
        value
    }
    fn no_pos(&self, mut value: PyAst) -> PyAst {
        value.positions_locked = true;
        value
    }
    fn replace_pos(&self, value: PyAst, start: PyAst, end: PyAst) -> PyAst {
        if value.positions_locked {
            return value;
        }
        let bound = value.obj.bind(self.py);
        if bound.hasattr("start").unwrap_or(false) {
            let _ = bound.setattr("start", start.obj.bind(self.py));
            let _ = bound.setattr("end", end.obj.bind(self.py));
        }
        value
    }

    // ===== Inspection =====
    fn node_kind<'a>(&self, v: &'a PyAst) -> Option<Cow<'a, str>> {
        // Python class name: `type(v).__name__`.
        let bound = v.obj.bind(self.py);
        bound
            .get_type()
            .name()
            .ok()
            .and_then(|cow_str| {
                // PyO3's name() returns Cow<'a, str>; we want the same
                // semantics as JsonEmitter's `Cow::Borrowed`.
                let s: String = cow_str.into();
                if s == "NoneType" {
                    None
                } else {
                    Some(Cow::Owned(s))
                }
            })
    }
    fn get_field(&self, v: &PyAst, name: &str) -> Option<PyAst> {
        let bound = v.obj.bind(self.py);
        bound.getattr(name).ok().map(|got| PyAst {
            obj: got.unbind(),
            positions_locked: false,
        })
    }
    fn has_field(&self, v: &PyAst, name: &str) -> bool {
        let bound = v.obj.bind(self.py);
        bound.hasattr(name).unwrap_or(false)
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
            });
        }
        Some(out)
    }
    fn position_offset(&self, v: &PyAst) -> Option<usize> {
        let bound = v.obj.bind(self.py);
        bound.extract::<usize>().ok()
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

/// Map operator symbol ("+", "-", "*", "/", "%") to the
/// ArithmeticOperationOp member NAME — first-try `cls[symbol]` works
/// because StrEnum subscript accepts the value; fallback by member name.
fn arith_op_name_from_symbol(symbol: &str) -> &'static str {
    match symbol {
        "+" => "Add",
        "-" => "Sub",
        "*" => "Mult",
        "/" => "Div",
        "%" => "Mod",
        other => panic!("unknown arithmetic op symbol `{other}`"),
    }
}

/// Map comparison operator symbol to CompareOperationOp member name.
fn compare_op_name_from_symbol(symbol: &str) -> &'static str {
    match symbol {
        "==" => "Eq",
        "!=" => "NotEq",
        ">" => "Gt",
        ">=" => "GtEq",
        "<" => "Lt",
        "<=" => "LtEq",
        "like" => "Like",
        "ilike" => "ILike",
        "not like" => "NotLike",
        "not ilike" => "NotILike",
        "in" => "In",
        "global in" => "GlobalIn",
        "not in" => "NotIn",
        "global not in" => "GlobalNotIn",
        "in cohort" => "InCohort",
        "not in cohort" => "NotInCohort",
        "=~" => "Regex",
        "=~*" => "IRegex",
        "!~" => "NotRegex",
        "!~*" => "NotIRegex",
        other => panic!("unknown comparison op symbol `{other}`"),
    }
}
