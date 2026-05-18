# hogql_parser_rs

ALL(*) variant of the rust HogQL parser. Loads the same serialized ATN that
ANTLR generates for cpp and implements the runtime simulator (lexer ATN sim,
DFA cache, SLL/LL prediction, semantic predicates).

## Why a separate crate

`hogql_parser_rs` is a hand-rolled Pratt + recursive-descent parser, fast but
~99.88% cpp grammar parity (36 cpp-accept rust-reject divergences per 30 000
Hypothesis examples). `hogql_parser_backtrack_rs` is its sibling exploring
sequential backtracking on top of the same Pratt core.

This crate explores the third path: implement the same algorithm class that
cpp uses (adaptive ALL(*)). Grammar parity by construction; perf TBD vs the
Pratt parser.

See [`PARSER_BENCHMARK_BASELINE.md`](../../../PARSER_BENCHMARK_BASELINE.md)
for the perf baseline this variant will be measured against.

## Status

Scaffold only. Every entry point returns a `NotImplementedError` envelope.

Implementation roadmap:

- **M1**: ATN deserializer (parse `.interp` byte format)
- **M2**: Lexer ATN simulator + mode stack
- **M3**: Parser with SLL prediction
- **M4**: LL fallback for full-context decisions
- **M5**: Semantic predicates + HogQLX modes
- **M6**: Visitor parity (matches cpp's emit JSON shape)

## Selecting in Python

Exposed via the `rust-json` backend in
[`posthog/hogql/parser.py`](../../../posthog/hogql/parser.py).

## Building locally

```bash
maturin develop --release -m rust/hogql/parser/Cargo.toml
```

Coexists with `hogql_parser_rs` and `hogql_parser_backtrack_rs` — all three
wheels install side by side under distinct Python module names.
