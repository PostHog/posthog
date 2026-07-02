# hogql_parser_rs

Hand-rolled Rust HogQL parser. Pratt + recursive descent. Same JSON AST
shape as the [C++ ANTLR parser](../../../common/hogql_parser/) so the
two can be cross-validated query-by-query. Ships as a Python extension
via `maturin` and is selected as the `rust-json` backend in
[`posthog/hogql/parser.py`](../../../posthog/hogql/parser.py).

About **15× faster than the C++ parser on `parse_expr`** and **50–55×
on `parse_select`**, against the same input, on the same machine. The
numbers come from `posthog/hogql/scripts/parser_bench.py`; re-run
locally before and after any non-trivial change.

## The C++ parser is the source of truth

When grammar, AST shape, or any visible behaviour disagrees between
the two, the C++ ANTLR parser is right and this one is wrong. The C++
parser is generated from
[`posthog/hogql/grammar/HogQLLexer.*.g4`](../../../posthog/hogql/grammar/HogQLParser.g4)

+ `HogQLParser.g4` via ANTLR4. The Rust parser does not consume those
grammar files; it hand-implements the same recognition behaviour.

This means any grammar change is a **two-step** change:

1. **Update the ANTLR grammar and rebuild the C++ parser.** Get the
    new shape working end-to-end on `cpp-json`. Pin the new behaviour
    with regression tests (see "Tools" below).

2. **Bring the Rust parser to parity.** Run the diagnostics, find the
    new divergences, fix them. This is the part an LLM agent can drive
    in a long-running loop.

Skipping step 1 produces a Rust parser that "works" but on a shape
the C++ parser rejects, which means Cloud's printer / planner will
reject too, because they're built on top of `cpp-json`'s output. Get
the oracle right first, then the candidate.

## What's in this crate

| Path                                            | What it does                                                                                                                                                                                                                                                                                                                                  |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`src/lib.rs`](src/lib.rs)                      | PyO3 entry points (`parse_expr_json`, `parse_select_json`, `parse_program_json`, `parse_order_expr_json`, `parse_full_template_string_json`). Each returns a JSON string; on error the JSON is an `{"error": true, ...}` envelope `posthog/hogql/json_ast.py` decodes into `HogQLSyntaxError` / `ExposedHogQLError`.                           |
| [`src/lex.rs`](src/lex.rs)                      | Lexer. Hand-rolled state machine matching the ANTLR-generated C++ lexer's tokens + mode stack (default / template-string / HogQLX-tag / HogQLX-text). When you add a new keyword to the grammar, add it here too.                                                                                                                             |
| [`src/parse.rs`](src/parse.rs)                  | Parser core: `Parser` struct, public entry points, the Pratt expression parser (`parse_expr_bp`), positions (`pos_obj`, `wrap_pos`, `wrap_pos_to`), char-offset / line-col tables, `checkpoint` / `restore` for speculative branches.                                                                                                         |
| `src/parse/{expr,select,program,join,cte,hogqlx,template}.rs` | Per-rule parsing. Most grammar changes land in one of these.                                                                                                                                                                                                                                                                                  |
| [`src/parse/bp.rs`](src/parse/bp.rs)            | Binding-power table + `build_infix` / `merge_and_or` / `merge_concat`. The precedence ladder lives here; new operators usually need an entry in `infix_bp` and a `build_infix` arm.                                                                                                                                                            |
| [`src/emit.rs`](src/emit.rs)                    | AST-node builders + position helpers (`with_pos` is idempotent, `replace_pos` overrides, `no_pos` reserves null keys to opt out of the wrap). When you add a new AST node, add a helper here so callers don't hand-build the JSON object.                                                                                                     |
| [`src/error.rs`](src/error.rs)                  | `ParseError` + the JSON error envelope.                                                                                                                                                                                                                                                                                                       |

## Building locally

```bash
# One-time: install the rust toolchain via flox / rustup (the workspace
# Cargo.toml is at `rust/Cargo.toml`).

# Build + install the wheel into the venv (editable). Re-run after each
# rust source change.
uv pip install -e rust/hogql/parser

# Or via maturin directly (faster incremental):
maturin develop --release --manifest-path rust/hogql/parser/Cargo.toml

# Sanity check
python -c "import hogql_parser_rs; print(hogql_parser_rs.parse_expr_json('1 + 2'))"
```

`maturin` builds a single `cp312-abi3` wheel that works on Python
3.12+. CI builds wheels for Linux x86_64/aarch64 (manylinux 2_28 +
musllinux 1_2) and macOS arm64/x86_64; see
[`.github/workflows/build-hogql-parser-rs.yml`](../../../.github/workflows/build-hogql-parser-rs.yml).

## Coverage-instrumented build (for the parser-parity PBT)

A second build path exists for fuzz-driven parser-parity work: build the crate
with `--features coverage` and SanitizerCoverage's `trace-pc-guard` pass, and
the resulting wheel exposes two PyO3 functions (`cov_snapshot()`, `cov_reset()`)
that the pytest PBT
([`posthog/hogql/test/test_parser_pbt.py`](../../../posthog/hogql/test/test_parser_pbt.py))
uses to feed a per-example `rust_edges` novelty count into Hypothesis `target()`
on top of the existing `ast_depth` / `novel_kpaths` signals. See
[`src/cov.rs`](src/cov.rs) for the callback + bitmap implementation. The
production wheel is unchanged: without the feature, neither `cov.rs` nor the
sancov pass are compiled, and the PBT detects the absence via
`hasattr(hogql_parser_rs, "cov_snapshot")` and silently skips the third
steering label.

Cargo applies `RUSTFLAGS` globally to every crate it compiles, including
dependency proc macros and build scripts, and those don't have our
`__sanitizer_cov_trace_pc_guard*` callbacks linked in, so a naive
`RUSTFLAGS=… maturin build --features coverage` segfaults the host build
scripts on macOS (and fails to link on Linux). The fix is a small per-crate
rustc wrapper that strips the sancov flags from every invocation except the
one for `hogql_parser_rs`. That wrapper lives at
[`scripts/cov-rustc-wrapper.py`](scripts/cov-rustc-wrapper.py):

```bash
WRAPPER=$PWD/rust/hogql/parser/scripts/cov-rustc-wrapper.py

# Build the instrumented wheel into a temp dir.
RUSTC_WRAPPER="$WRAPPER" \
RUSTFLAGS="-C passes=sancov-module \
           -C llvm-args=-sanitizer-coverage-level=3 \
           -C llvm-args=-sanitizer-coverage-trace-pc-guard" \
maturin build --release --manifest-path rust/hogql/parser/Cargo.toml \
              --features coverage --out /tmp/cov-wheel

# Install it into the active venv (in the same shell session — the shared
# flox venv prunes manually-installed wheels otherwise).
VIRTUAL_ENV=$PWD/.flox/cache/venv uv pip install --reinstall --no-deps \
    /tmp/cov-wheel/hogql_parser_rs-*.whl

# Verify the instrumented wheel is loaded.
python -c "import hogql_parser_rs; print(hasattr(hogql_parser_rs, 'cov_snapshot'))"

# Run the parity PBT; the rust_edges target appears in --hypothesis-show-statistics.
RUN_PBT=1 hogli test posthog/hogql/test/test_parser_pbt.py::TestParserBackendEquivalence \
    --hypothesis-show-statistics
```

`rust_edges` will show up in Hypothesis's per-test target stats alongside
`ast_depth`. The wrapper has been verified to work locally on macOS aarch64. On
a normal install (no coverage build) the PBT just doesn't emit the third label;
nothing else changes.

If you want a production CI job to produce this wheel as a sidecar, mirror the
above invocation in a separate workflow file and publish it under a separate
package name (e.g. `hogql_parser_rs_cov`) so production deploys can't
accidentally pull the instrumented wheel.

## Publishing

The crate is pinned via the `hogql-parser-rs==X.Y.Z` line in the
repo-root [`pyproject.toml`](../../../pyproject.toml). Bump the
version in **both**:

+ [`Cargo.toml`](Cargo.toml)
+ [`pyproject.toml`](pyproject.toml)

(They must match. The PR check at
[`.github/workflows/build-hogql-parser-rs.yml`](../../../.github/workflows/build-hogql-parser-rs.yml)
enforces this.)

Version is intentionally locked in step with
[`common/hogql_parser`](../../../common/hogql_parser) (the C++ parser
PyPI package) so a bump signals "both parsers move together." The
publish workflow builds wheels, pushes to PyPI via trusted publishing,
then opens a follow-up PR that updates the repo-root pin.

## Adding a new grammar feature

Steps 1–4 are the one-time grammar-update process — done once,
human-driven. Step 5 (running the parity loop below) is the
long-running, agent-friendly part.

1. **Update [`HogQLLexer.*.g4`](../../../posthog/hogql/grammar/) and
    [`HogQLParser.g4`](../../../posthog/hogql/grammar/HogQLParser.g4).**
    Run `pnpm grammar:build` to regenerate the C++ ANTLR
    artefacts:

    ```bash
    pnpm grammar:build
    ```

    That step requires the `antlr` 4.13.2 binary on `PATH`;
    instructions in
    [`posthog/hogql/grammar/README.md`](../../../posthog/hogql/grammar/README.md).
    The script rewrites `common/hogql_parser/HogQL{Lexer,Parser}.{cpp,h,interp,tokens}`.
    The C++ parser now recognises the new shape (the Rust parser is
    hand-written, so update it to match in the steps below).

2. **Pick the AST emission.** Decide what JSON the cpp visitor should
    return for the new shape. Either reuse an existing AST node or add
    a new one in `posthog/hogql/ast.py`. The Python AST is shared
    between backends, so any new node has to land there first, otherwise
    `posthog/hogql/json_ast.py::deserialize_ast` will crash on it.

3. **Update the cpp visitor.** Add the `VISIT(YourNewRule)` arm in
    [`common/hogql_parser/parser_json.cpp`](../../../common/hogql_parser/parser_json.cpp).
    Mirror cpp's conventions: call `addPositionInfo(json, ctx)` per
    rule unless you specifically want a position-less node (see
    "Position parity" below). Rebuild the cpp wheel
    (`pip install ./common/hogql_parser`).

4. **Pin the new behaviour with a regression test.** Add a test (and a
    rust-rejects-it negative test if the grammar tightens) into the
    `parser_test_factory` suite in
    [`posthog/hogql/test/_test_parser.py`](../../../posthog/hogql/test/_test_parser.py).
    The factory runs every test against `cpp-json`, `rust-json`, and
    `rust-py`; on a fresh grammar change the test passes on cpp and
    fails on rust. That fail is the starting state for the parity
    loop.

5. **Run the parity loop.** See the next section.

## The parity loop

The agent loop that brings rust to behavioural parity with cpp. Long-running;
the diagnostics produce concrete diffs the agent attacks one at a time.

**Before each iteration, rebuild both parser wheels from local source.**
`uv pip install` / `pip install` will happily resolve to the published
PyPI wheel and ignore the working tree, so a fresh `maturin develop`
and a fresh `pip install ./common/hogql_parser` are non-negotiable —
the diagnostics test what's installed, not what's on disk.

```bash
maturin develop --release --manifest-path rust/hogql/parser/Cargo.toml
pip install --force-reinstall --no-deps ./common/hogql_parser
```

`maturin develop` writes the wheel into the active venv as editable;
`--force-reinstall --no-deps` for the cpp wheel sidesteps pip's
"already-satisfied" short-circuit when the in-tree version matches
the PyPI pin. Skip these and the loop will silently chase divergences
that have already been fixed in the working tree.

1. **Generate a new divergence.** In priority order:
    + existing failing regression tests (highest signal);
    + real production queries via `log_corpus_diagnostic.py` /
      `hog_corpus_diagnostic.py` (the hog corpus has been at 100% for
      a while — usually skip);
    + PBT (`pbt_diagnostic.py --rule expr|select|program`);
    + thinking hard about edge cases the grammar surface invites —
      pipe each candidate through `shrink_query.py` to confirm it
      diverges and get the minimal form.

    For everything other than regression tests, start with a small
    budget (lower `--n`, less thinking time) and increase until at
    least one divergence surfaces.
2. **Reduce + pin.** Shrink each divergence to its minimal form via
   shrinkray — pipe one query through `shrink_query.py`, or use
   `--shrink-failures` on the corpus runners — and add it as a
   regression test in `_test_parser.py`'s factory so it runs on all
   three backends.
3. **Read before fixing.** Read the grammar AND the cpp visitor for
   the rule. 100% identical behaviour means knowing exactly what cpp
   does — guessing leads to fixes that resurface on a deeper PBT
   run.
4. **Fix the rust parser.** Prefer general fixes that won't break on
   deeper nesting; a depth-0-only special case is a smell. Print a
   one-paragraph report for the human operator so progress is
   visible while the loop runs autonomously.
5. **Re-run the regression suite.** Anything below the previous
   baseline goes back to step 1.

Generating divergences is the slow step. Run discovery in parallel
in the background:

+ `pbt_diagnostic.py --rule select`
+ `pbt_diagnostic.py --rule expr`
+ `pbt_diagnostic.py --rule program`
+ `log_corpus_diagnostic.py` (real query corpus)
+ a research subagent grepping for cpp-vs-rust visitor differences
+ a research subagent brainstorming adversarial edge cases, each
  confirmed + minimised through `shrink_query.py`

Most of these can stream divergences as they're found. Once at least
one known divergence is in hand, start fixing it while the parallel
runs keep mining the long tail.

## Tools for parity work

Every script below has the same `--oracle` / `--candidate` flag pair
and defaults to `cpp-json` vs `rust-json`. The diagnostics include
per-node `start` / `end` positions in the comparison by default; set
`CLEAR_LOCATIONS=1` to strip positions when you want a structural-only
read.

### Regression tests in `posthog/hogql/test/`

```bash
hogli test posthog/hogql/test/test_parser_cpp_json.py
hogli test posthog/hogql/test/test_parser_rust_json.py
hogli test posthog/hogql/test/test_parser_rust_py.py
```

The behaviour suite + regression pins live in
[`_test_parser.py`](../../../posthog/hogql/test/_test_parser.py)'s
`parser_test_factory`. The three files above are thin subclasses that
spawn one runnable test entry per (backend, case) combination. When
you find a new divergence, add a reduced regression to the factory —
it picks up all three backends automatically.

### Property-based testing via `posthog/hogql/scripts/pbt_diagnostic.py`

```bash
PYTHONPATH=. python posthog/hogql/scripts/pbt_diagnostic.py \
    --n 5000 --rule program

# Per rule:
--rule expr     # standalone column expressions
--rule select   # SELECT / SELECT-set statements
--rule program  # full Hog programs (declarations + statements + exprs)
```

Generates ~5 000 random grammar surface examples per rule, parses with
oracle and candidate, buckets divergences by AST shape, and prints
reproducers. Use `--shrink-failures` to reduce each divergence to a
minimal example via shrinkray (needs the optional `hogql-parser-parity`
group — `uv sync --group hogql-parser-parity`).

### Real-query corpora via `log_corpus_diagnostic.py` / `hog_corpus_diagnostic.py`

```bash
# SELECT queries from the last 7 days of production traffic
# (redacted, AI-data-processing-approved teams only):
PYTHONPATH=. python posthog/hogql/scripts/log_corpus_diagnostic.py

# Hog programs from production (transformations, destinations, …):
PYTHONPATH=. python posthog/hogql/scripts/hog_corpus_diagnostic.py
```

Both auto-download via `hogli metabase:query` and cache locally under
`posthog/hogql/scripts/.local/`. Pass `--skip-download` to reuse the
existing dump while iterating. Failures are written one block per
divergence to a `.sql` / `.hog` file the agent can chew through. Add
`--shrink-failures` to reduce each failing query to a minimal repro via
shrinkray before it's written.

### Shrink one query via `shrink_query.py`

```bash
# Pipe in a query that diverges (or that you think might); get the
# minimal repro back on stdout:
echo '<query>' | PYTHONPATH=. python posthog/hogql/scripts/shrink_query.py --rule select
```

The "think hard about edge cases" arm of the loop, and the reducer for
any single divergence. Reads one query on stdin, writes the smallest
variant that still triggers the same divergence to stdout (chatter goes
to stderr, so stdout is exactly the repro). Doubles as a divergence
check: a query the backends agree on exits non-zero with the reason on
stderr. An agent brainstorming edge cases pipes each candidate through
it and keeps the ones that come back shrunk.

### The diagnostics need the optional parity group

Shrinking is powered by [shrinkray](https://github.com/DRMacIver/shrinkray),
which lives in the `hogql-parser-parity` group rather than the default dev
install (its transitive deps — textual, libcst, black — are heavy). The
parity scripts in `posthog/hogql/scripts/` import it at module level, so
they require that group:

```bash
uv sync --group hogql-parser-parity
```

Without it they fail fast at startup with a `ModuleNotFoundError` — these
are parity-work-only tools, so they just require the parity dependency
rather than degrading to a no-shrink mode.

### Perf bench via `posthog/hogql/scripts/parser_bench.py`

```bash
CANDIDATE_BACKEND=rust-json PYTHONPATH=. \
    python posthog/hogql/scripts/parser_bench.py
```

Runs both parsers against a fixed corpus of representative queries
(small / medium / nested / pathological) and prints an
`oracle / candidate` ratio per row. **Re-run before and after any
non-trivial change.** If `parse_select` mean drops noticeably (the
parse_select speedup is the headline number), find out why before
landing.

### Shadow compare in TEST via `cpp-with-rust-shadow`

In `TEST` mode the default backend is `cpp-with-rust-shadow`: both
backends parse, ASTs are compared **including per-node `start` / `end`
positions** (matching the diagnostics' default), mismatches **raise**
so the failing test points right at the offending query. In production
this same mode runs at a 1% sample and only logs — a mismatch there is
tagged `hogql_parser_position_only_mismatch` so position-only
divergences are triaged apart from structural ones. Useful when a
regression slips past the PBT but shows up in the suite.

```python
from posthog.hogql.constants import HogQLParserBackend
parse_expr(src, backend=HogQLParserBackend.CPP_WITH_RUST_SHADOW)
```

## Rules of thumb for the parity loop

These aren't always obvious from the diagnostics alone:

+ **Prefer the generalising fix.** When two implementations both pass
  the failing cases, pick the one that doesn't depend on the input
  shape. A `wrap_pos` call at a single emit site beats a depth-aware
  conditional. A change to the binding-power table beats an
  ad-hoc check in the consumer.

+ **Position bugs hide behind structural bugs.** Always run the PBT
  with positions on (the default); `CLEAR_LOCATIONS=1` is for
  diagnosing structural regressions only. A 99% structural match can
  mask a 50% position-aware match.

+ **Look at the cpp visitor before guessing.** Every per-node
  position decision in this parser has a cpp counterpart in
  [`common/hogql_parser/parser_json.cpp`](../../../common/hogql_parser/parser_json.cpp).
  If the cpp visitor calls `addPositionInfo(json, ctx)` you need a
  wrap on the rust side; if it doesn't, you need `emit::no_pos` (or
  the helper for that node already does it).

+ **Watch the perf bench.** Position emission isn't free. Cache O(N)
  computations on `Parser` rather than recomputing per emit; the
  `is_ascii_src` field is the canonical example.

+ **Don't fix one rule at a time at the expense of others.** A
  one-line wrap in `parse/expr.rs` can move three PBT rules at once.
  Run all three PBTs after each change, not just the one you started
  with.

## Position parity (the non-obvious part)

The C++ visitor decides per-node whether to emit positions via
`addPositionInfo(json, ctx)`. Some nodes are deliberately
position-less (`NamedArgument`, `ColumnsExpr` in qualified-asterisk
column slots, etc.) so the rust parser has to match that exactly.

Three position helpers in `emit.rs` cover the three cases:

| Helper           | When to use                                                                                                                                                                                                  |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `with_pos`       | Default. Adds `start` / `end` if not already set. Used by `Parser::wrap_pos` and `wrap_pos_to`. Idempotent so the outer pratt-loop wrap doesn't trample inner spans.                                          |
| `replace_pos`    | Override existing `start` / `end`. Used by the bare-paren grammar alts (`(*  REPLACE(...))`) where the inner wrap captured only the inner content but cpp's grammar ctx includes the outer parens.           |
| `no_pos`        | Pre-insert `start: null`, `end: null` so the outer wrap leaves the node bare. Used for nodes cpp explicitly doesn't position (`NamedArgument`, `ColumnExprNamedArg`).                                         |

Two more things to keep in mind:

+ **Offsets are character indices, not byte indices.** cpp's
  `getStartIndex()` is char-based; rust's source slices are byte-based.
  `Parser::pos_obj` converts via `byte_to_char_index` for non-ASCII
  sources, short-circuits for ASCII. If you bypass `pos_obj` (e.g.
  hand-building a position object for a node-builder you control),
  you have to do the conversion yourself.

+ **Column is character-position-in-line, not byte-position.** Same
  reason. The ASCII fast path in `pos_obj` handles this for free; the
  slow path counts chars between line-start and offset.

## Known long-tail divergences

The PBT for `expr` and `select` exposes adversarial grammar surface
that the production corpora never see: deep nested
`BETWEEN low AND high` chains with embedded aliases and ternaries,
extreme `WITHIN GROUP (ORDER BY …)` shapes, multi-token-`AND`-merged
operands. These take focused per-shape investigation; the
[PR description](https://github.com/PostHog/posthog/pull/58949) has
the current numbers.

The production corpora (`log_corpus_diagnostic`,
`hog_corpus_diagnostic`) stay above 90%, so anything the PBT surfaces
that doesn't appear there is technically grammar-parity work but not
user-visible.

## Selecting from Python

```python
from posthog.hogql.parser import parse_expr, parse_select, parse_program

ast = parse_expr("1 + event.properties.$browser", backend="rust-json")
```

Backends live in `posthog/hogql/constants.HogQLParserBackend`:

| Backend                   | Use case                                                                       |
| ------------------------- | ------------------------------------------------------------------------------ |
| `cpp-json`                | Production default. ANTLR-based, oracle for everything below.                  |
| `rust-json`               | This crate. ~15× / ~50× faster, behaviour identical (modulo the long tail).    |
| `rust-py`                 | This crate, returning `posthog.hogql.ast` dataclasses directly via PyO3 (no JSON round-trip). Production primary. |
| `cpp-with-rust-shadow`    | Parses with cpp, shadow-parses with rust, raises  on mismatch (TEST) / logs at 1% sample (prod). |
