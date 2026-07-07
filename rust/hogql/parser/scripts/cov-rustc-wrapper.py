#!/usr/bin/env python3
"""Per-crate SanitizerCoverage flag scoping for the parser-parity grind.

Cargo applies `RUSTFLAGS` (and `CARGO_ENCODED_RUSTFLAGS`) to every rustc
invocation it makes, including dependency proc macros and build scripts.
`-C passes=sancov-module` ends up instrumenting those crates too. Their
binaries call `__sanitizer_cov_trace_pc_guard*`, which is only defined in
`hogql_parser_rs::cov` and isn't linked into anything else, so they SIGSEGV
on macOS (or fail to link on Linux).

Used as `RUSTC_WRAPPER`, cargo invokes this script as
`cov-rustc-wrapper.py rustc <args>`. We inspect the args for the
`--crate-name` cargo always passes, and if it's anything other than our
parser crate, we strip the sancov-related `-C` flags before re-execing rustc.
For our crate, everything passes through unchanged so the sancov pass runs
and our `cov.rs` callbacks get linked.

See "Coverage-instrumented build" in `rust/hogql/parser/README.md`.
"""

import os
import sys

# The single crate we actually want instrumented. Everything else (deps, proc
# macros, build scripts) gets the sancov flags stripped.
TARGET_CRATE = "hogql_parser_rs"

# `-C` flag VALUES that introduce or configure the SanitizerCoverage pass.
# These have to be stripped as `(-C, VALUE)` pairs; matched on the VALUE half.
SANCOV_PREFIXES = (
    "passes=sancov-module",
    "llvm-args=-sanitizer-coverage",
)


def main() -> None:
    args = sys.argv[1:]

    crate_name: str | None = None
    for i, a in enumerate(args):
        if a == "--crate-name" and i + 1 < len(args):
            crate_name = args[i + 1]
            break

    if crate_name == TARGET_CRATE:
        os.execvp(args[0], args)

    filtered: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-C" and i + 1 < len(args) and any(args[i + 1].startswith(p) for p in SANCOV_PREFIXES):
            i += 2
            continue
        filtered.append(a)
        i += 1
    os.execvp(filtered[0], filtered)


if __name__ == "__main__":
    main()
