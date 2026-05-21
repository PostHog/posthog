# Phase 2 completion plan

## What's already on this branch

| Commit | What |
| --- | --- |
| `39f3af6a` | **Phase 1** — `rust-py` backend via post-parse `Value`→`PyObject` converter. ~10% perf win. All 378 factory tests pass. Branch `claude/hogql-rust-parser-phase2`. |
| `ca6f0d4a` | **Phase 2 foundation** — `Emitter` trait + `JsonEmitter` impl + compat free fns. Parser methods routed via `self.emit.xxx()`. All 1,513 tests pass across cpp-json + python + rust-json + rust-py. |

## What's left (Phase 2 main course)

Make the parser actually skip the `serde_json::Value` intermediate tree when running with a `PyEmitter` that builds Python objects directly. The trait is ready; the parser needs to be made generic over `E: Emitter` and stop using `serde_json::Value`-specific APIs.

### Scope (verified by multiple grinds)

| Item | Count | Files |
| --- | --- | --- |
| `Result<Value, …>` return types to generalize | ~50 | `parse.rs`, `parse/*.rs` |
| `Value::Variant(…)` direct constructions | ~170 | `parse/expr.rs` (heaviest), others |
| `.get("…")` / `.as_str()` / `.as_object_mut()` inspection sites | ~120 | mostly `parse/expr.rs`, some in `parse/select.rs`, `parse.rs` |
| Free helpers that need `<E: Emitter>` parameterization | ~10 | `apply_between_hoist`, `stamp_span_from_children`, `split_at_rightmost_and`, `is_paren_form_columns_replace`, `is_bare_field` (expr.rs); `emit_float_constant`, `parse_number_literal` (parse.rs); `wrap_literal_chunk`, `pos_in_source` (template.rs); `build_infix`, `merge_concat`, `merge_and_or`, `is_concat_call`, `fold_call_or_exprcall` (bp.rs) |
| `serde_json::json!({…})` manual node constructions | 5-6 | `parse/expr.rs::apply_between_hoist` (IsDistinctFrom, TypeCast, ArithmeticOperation, ArrayAccess, ExprCall), `parse/bp.rs::fold_call_or_exprcall` (ExprCall), `parse/select.rs:623` |

### Verified gotchas

1. **`Emitter: Clone` is required.** `parse_template_body` spawns a sub-`Parser` for `f'{…}'` blocks, so the parent's emitter has to be cloneable. `JsonEmitter` is Copy (free), `PyEmitter` should be `#[derive(Clone)]` (cheap `Bound::clone_ref` underneath).
2. **`E::Value: Clone` is also required.** The parser does `lhs.clone()` in spots like the BETWEEN body splitter and the modulo-extension closure. JSON: cheap struct clone, Py: refcount bump.
3. **`apply_between_hoist`'s `serde_json::json!` builds for IsDistinctFrom / TypeCast / ArithmeticOperation / ArrayAccess / ExprCall**: these need trait methods on `Emitter`. The trait already has `is_distinct_from`, `type_cast`, `arith`, `array_access`; missing only `expr_call(expr, args)` — which I added in my WIP attempt.
4. **`merge_and_or` does in-place mutation** (`obj.get_mut("exprs").extend(...)`, `obj.remove("start")`). This pattern doesn't generalize cleanly. Rewrite as: read exprs from lhs (if it's an And/Or node, extract), read exprs from rhs (same), build fresh `emit.and_(combined)` / `emit.or_(combined)`. The fresh node has no positions, which is what the original was trying to achieve via `obj.remove`.
5. **`try_limit_modulo_extension` in select.rs uses a closure `|p: &mut Self| -> Result<Option<Value>, ParseError>`** — the closure body must call `p.emit.arith(...)` (not `self.emit.arith(...)`) to avoid a borrow-checker conflict with `p.bump()?`.
6. **Free helpers can't access `self`.** Either parameterize them with `<E: Emitter>` taking `&E` (cleaner) OR keep them on the JSON path via the existing `compat::*` free fns (already in `emit.rs`).
7. **Top-level `&Parser<'_>` references** (e.g. inner closure in `parse/expr.rs:2964`) need the generic param: `&Parser<'_, E>`.
8. **`pyo3` 0.22 specifics for PyEmitter**: `Bound<'py, PyAny>` carries the GIL lifetime. The emitter can't easily own a `Bound` long-term — store `Py<PyAny>` (no lifetime) and re-attach to GIL via `bound(py)` when needed. Cache module references in `PyEmitter::new(py)` from `posthog.hogql.ast`.
9. **`no_pos` / `with_pos` idempotency on Python objects**: slot-only dataclasses (`ast.py` uses `slots=True`) can't carry an out-of-band "positions locked" marker. The `PyEmitter::Value` type needs to be a wrapper struct: `struct PyAst { obj: Py<PyAny>, positions_locked: bool }`. `with_pos` checks the flag; `no_pos` sets it; `replace_pos` ignores it.

### Suggested execution order

Do this in a fresh session (or as a series of agent tasks) to avoid context exhaustion. **Build after each step.**

1. **Make Parser generic + entry points generic + threading the emitter through `parse_template_body`.** ~50 method signatures. Build will produce many errors — that's expected; we fix them in the next steps.
2. **bp.rs free helpers** (`build_infix`, `merge_concat`, `merge_and_or`, `is_concat_call`, `fold_call_or_exprcall`): make all generic over `<E: Emitter>`, replace `Value::xxx` with trait methods. Already designed in my WIP — see git diff of `claude/hogql-rust-parser-phase2` at HEAD vs the latest unstaged WIP. Required `expr_call` trait method to be added.
3. **expr.rs free helpers** (`apply_between_hoist`, `stamp_span_from_children`, `split_at_rightmost_and`, `is_paren_form_columns_replace`, `is_bare_field`): same treatment. The `serde_json::json!` builds in `apply_between_hoist` map to trait methods (`is_distinct_from`, `type_cast`, `arith`, `array_access`, `expr_call`).
4. **expr.rs Parser methods**: replace ~140 `Value::Variant(…)` patterns. Most common: `Value::Null` → `self.emit.null()`, `Value::Bool(b)` → `self.emit.bool(b)`, `Value::String(s.into())` → `self.emit.string(&s)`, `Value::from(i64)` → `self.emit.int(i)`. Sed handles many; manual fixes for the `serde_json::json!` macros.
5. **expr.rs inspection patterns**: ~80 sites. `v.get("node").and_then(Value::as_str)` → `self.emit.node_kind(&v).as_deref()`. `v.get("foo").cloned()` → `self.emit.get_field(&v, "foo")`. `obj.contains_key("start")` → `self.emit.has_field(&v, "start")`. Add trait methods if missing (e.g. `set_field`/`extend_list_field` for mutation patterns).
6. **select.rs, join.rs, program.rs, hogqlx.rs, cte.rs, parse.rs**: same patterns, smaller volumes. Each file ~10-40 sites.
7. **template.rs**: already half-done in the foundation commit, finish by routing the emitter through `parse_template_body` and its helpers.
8. **Implement `PyEmitter`** in `rust/hogql/parser/src/emit_py.rs`:
   - `struct PyEmitter<'py> { py: Python<'py>, ast_module: Bound<'py, PyModule>, … }`
   - `type Value = PyAst { obj: Py<PyAny>, positions_locked: bool }`
   - Every trait method constructs via `ast_class.call(args, Some(&kwargs))` — same pattern as `pyobject.rs::Converter::convert`.
   - Position fields: when `with_pos`/`no_pos`/`replace_pos` runs, set `.start` and `.end` attrs on the underlying PyObject (these are `Optional[int]` fields on the dataclass).
   - Caching: cache class references (`ArithmeticOperation`, `Constant`, etc.) at construction time — `getattr(ast_module, name)` per node would dominate runtime otherwise.
9. **Wire `parse_*_py` entry points** in `lib.rs` to construct `PyEmitter::new(py)` and call `parse::parse_expr(emitter, …)` directly — bypassing the `pyobject.rs::Converter` post-parse walk.
10. **Test**: factory suite (1,513 tests) must pass via PyEmitter. Smoke-test the corpus runs.
11. **Benchmark**: `parser_bench.py` cpp-json vs rust-json vs rust-py. Phase 1 gave 1.1× over rust-json; phase 2 PyEmitter should give meaningfully more (probably 1.3-1.5×) by skipping the `Value` tree entirely.

### Things to add to the `Emitter` trait when needed

The current trait has 33 constructors + 8 inspection methods. The grind will likely surface these as missing:

- `expr_call(expr, args) -> Self::Value` — needed by `bp.rs::fold_call_or_exprcall` and `apply_between_hoist::ExprCall` arm.
- `arithmetic_with(left, op, right) -> Self::Value` — wait, `arith` already exists. The `apply_between_hoist::ArithmeticOperation` arm just needs to use `arith`. ✓
- `is_distinct_from_with(left, right, negated) -> Self::Value` — already exists as `is_distinct_from`. ✓
- `type_cast_with(...)` — already exists as `type_cast`. ✓
- `set_field(&self, v: &mut Self::Value, name: &str, value: Self::Value)` — for `select.rs:623` and the `merge_select_decorators` mutation pattern in `parse.rs`. JSON impl mutates the `Map`; Py impl calls `obj.setattr(name, value)`. **Add this.**
- `clear_positions(&self, v: &mut Self::Value)` — for the `merge_and_or` position clearing. Alternative: rebuild via fresh `emit.and_/or_` (already in the trait, no positions by default). **Use the rebuild path; no new method needed.**

### Things NOT to do

- Don't try to do all 290 sites with sed. Some are inside free helpers / closures / nested patterns where sed corrupts the code. Mix sed-amenable patterns (return types, simple `Value::Null` → `self.emit.null()`) with manual editing of complex sites.
- Don't make `bp.rs` use `crate::emit::{self, …}` import — keep just `crate::emit::Emitter`. Free fns there should be parameterized over E, not falling back to the `emit::xxx` compat layer.
- Don't bind `E::Value = serde_json::Value` anywhere — that defeats the purpose. The whole point is letting `PyEmitter::Value = PyAst` work.
- Don't commit half-broken state. The branch is currently green at HEAD; keep it that way.

### Expected outcome

After Phase 2 completion: a `rust-py` backend that constructs `posthog.hogql.ast` instances directly during parsing, with no `serde_json::Value` intermediate. Faster than the Phase 1 converter approach (probably 1.3-1.5× over `rust-json`). WASM path stays intact via `parse_*_json` + `JsonEmitter`.
